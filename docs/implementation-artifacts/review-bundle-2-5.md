# Review Bundle — Story 2.5: M&A 타겟 랭킹 API (2026-07-13)

역할: 당신은 이 프로젝트 컨텍스트가 전혀 없는 시니어 파이썬/FastAPI 리뷰어다. 아래 AC·제약·코드(verbatim, 축약 없음)만 보고 실제 버그·계약 위반·SQL 방언 문제를 찾아라. 스타일 지적보다 동작 결함 우선.

## 스토리 AC 요약

1. `GET /mna/ranking` — mna_target_score **내림차순(null last)**, 요소별 분해(valuation/capacity/ownership/macro) + population_basis 포함.
2. `market`(정확일치)·`sector`(KSIC prefix 매칭)·`as_of`(date, 기본=최신) 필터 + 페이지네이션, 응답 봉투 `{items,total,page,size}`.
3. mna_target_score null = "산출 불가"(엄격 null 정책) — null 그대로 반환, 0점/최하위 강제 금지.
4. 레이어: routers→services→repositories, SQL은 repository에서만. null 정렬은 SQLite/PostgreSQL 방언 무관 명시적 키.
5. 스코어 미적재 → 빈 봉투 200. 무효 날짜(2026-02-30) → 422.
6. 기존 191 테스트 회귀 0 (현재 196 passed).

## 아키텍처 제약(위반 여부 볼 것)

- AD-2: 라우터·서비스는 SQL 실행 금지(repository만).
- AD-6: 목록 봉투 {items,total,page,size}, 에러 {detail,code}.
- AD-10: mna_score의 writer는 mna_engine뿐 — 이 스토리는 읽기 전용이어야 함.
- corp_code(8자리)가 유일 조인 키(AD-5).

## 이미 알려진 것(재보고 불필요)

- latest_as_of가 부분 실행으로 오염될 수 있는 문제 → score_run 메타데이터 별도 스토리로 defer 결정(deferred-work.md).
- 금융주 mna_target_score null(업종별 변수세트 미지원, 레벨 2 defer) — API는 정직하게 null 노출이 의도.
- count/items 비원자성(스냅샷) — 1-7부터 Low defer 계열.
- starlette TestClient deprecation 경고 — 라이브러리 몫.
- `is_(None)` 정렬·subquery COUNT는 이전 GPT 리뷰에서 PG 포함 clean 판정 이력 있음.

## 코드 (verbatim)


### `app/repositories/mna_score.py`

```python
"""mna_score 배치 입력 조회 + 멱등 upsert 저장소 (AD-2: SQL은 여기서만).

mna_engine(app/analysis/mna_engine.py)의 유일한 DB 접근 지점. 2.1(gap_engine, 종목별 단건
조회)과 달리 **cross-sectional 백분위**라 전체 모집단을 배치로 한 번에 가져온다 — 종목 루프
안에서 단건 쿼리하면 N+1이자 설계 오류(한 종목의 점수가 전체 분포에 의존).

look-ahead 부분차단은 2.1(valueup_score.py)과 동일 규칙: 같은 연도의 사업보고서(quarter=4)는
그 해 안에 공시될 수 없으므로(통상 다음해 3월) 배제 — `year<yr OR (year=yr AND quarter<4)`.
1~3분기 동일연도 시차는 공통 defer(deferred-work.md 2-1 섹션).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import Company, MacroIndicator, MnaScore, Ownership


def list_all_corp_codes(session: Session) -> list[str]:
    """전 종목 corp_code 목록(run()의 corp_codes 기본값)."""
    return list(session.scalars(select(Company.corp_code)).all())


def all_company_sectors(session: Session) -> dict[str, str | None]:
    """전 종목 corp_code → sector(DART induty_code). 2.7 버킷 택소노미 입력."""
    rows = session.execute(select(Company.corp_code, Company.sector)).all()
    return {code: sector for code, sector in rows}


def all_latest_metrics(session: Session, as_of: str) -> dict[str, dict[str, Any]]:
    """전 종목의 as_of 시점 최신 (year,quarter) valuation_metrics 행(배치).

    corp_code → {ev_ebitda, pbr, debt_ratio, net_cash, ebitda_margin}.
    look-ahead 배제 후 corp별 최신 1행을 Python에서 선택(정렬된 결과 첫 등장 유지 —
    SQLite/PostgreSQL 양쪽에서 동일 동작, 데이터 규모상 충분).
    """
    as_of_year = int(as_of[:4])
    rows = session.execute(
        text(
            "SELECT corp_code, ev_ebitda, pbr, debt_ratio, net_cash, ebitda_margin "
            "FROM valuation_metrics "
            "WHERE year < :yr OR (year = :yr AND quarter < 4) "
            "ORDER BY corp_code, year DESC, quarter DESC"
        ),
        {"yr": as_of_year},
    ).mappings().all()
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = row["corp_code"]
        if code not in latest:  # 정렬상 corp별 첫 행 = 최신
            latest[code] = {
                "ev_ebitda": row["ev_ebitda"],
                "pbr": row["pbr"],
                "debt_ratio": row["debt_ratio"],
                "net_cash": row["net_cash"],
                "ebitda_margin": row["ebitda_margin"],
            }
    return latest


def all_latest_ownership(session: Session, as_of: str) -> dict[str, dict[str, Any]]:
    """전 종목의 as_of 이전(포함) 최신 ownership 행(배치).

    corp_code → {largest_shareholder_pct, treasury_stock_pct}.
    as_of 근사치(비12월 결산 라벨오류)는 1-6 known-limitation 그대로.
    """
    stmt = (
        select(Ownership)
        .where(Ownership.as_of <= as_of)
        .order_by(Ownership.corp_code, Ownership.as_of.desc())
    )
    latest: dict[str, dict[str, Any]] = {}
    for obj in session.scalars(stmt):
        if obj.corp_code not in latest:
            latest[obj.corp_code] = {
                "largest_shareholder_pct": obj.largest_shareholder_pct,
                "treasury_stock_pct": obj.treasury_stock_pct,
            }
    return latest


def latest_macro_percentile_basis(
    session: Session, as_of: str, indicator: str = "base_rate"
) -> tuple[float | None, list[float]]:
    """(as_of 이전 최신 지표값, as_of 이전 전체 역사 시계열) — 매크로 백분위 기준.

    모집단 = as_of 이전 전체 관측값(리드 결정: 롤링 윈도우 아님, ECOS 수집 기간 길어지면
    후속 재검토). as_of 이후 관측은 look-ahead라 제외.
    """
    stmt = (
        select(MacroIndicator)
        .where(MacroIndicator.indicator == indicator, MacroIndicator.date <= as_of)
        .order_by(MacroIndicator.date.desc())
    )
    objs = list(session.scalars(stmt))
    # 현재값 = 최신 '관측 행'의 값(null이면 null 그대로 — 과거 non-null로 몰래 대체 금지,
    # 코드리뷰 2026-07-10 High: AC6 엄격 null 위반이었음). history 정제와 현재값 선택은 분리.
    current = objs[0].value if objs else None
    history = [o.value for o in objs if o.value is not None]
    return current, history


def upsert_mna_score(session: Session, rec: dict[str, Any]) -> MnaScore:
    """(corp_code, as_of) 자연키 기준 mna_score upsert.

    2.1 upsert_valueup_score와 동일 정책: 권위 있는 전체 재계산 결과이므로 null 포함 전체
    교체 + `rec[field]` 직접 인덱싱(키 누락은 프로그래밍 오류 → KeyError로 즉시 노출).
    """
    stmt = select(MnaScore).where(
        MnaScore.corp_code == rec["corp_code"], MnaScore.as_of == rec["as_of"],
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        obj = MnaScore(corp_code=rec["corp_code"], as_of=rec["as_of"])
        session.add(obj)
    for field in (
        "mna_target_score", "valuation_score", "capacity_score",
        "ownership_score", "macro_score", "population_basis",
    ):
        setattr(obj, field, rec[field])
    return obj


# ── 서빙 조회 (2.5 /mna/ranking) ─────────────────────────────────────────────
# 위쪽은 mna_engine 전용 배치 입력·upsert, 아래는 API 서빙 읽기 전용(AD-10: 쓰기는 엔진만).


def latest_as_of(session: Session) -> str | None:
    """mna_score의 최신 as_of(기본 조회 기준일). 없으면 None.

    부분 실행이 latest_as_of를 오염시키는 문제는 2.4와 공통 defer(score_run 메타데이터,
    deferred-work.md) — 여기서 해결하지 않는다.
    """
    return session.scalar(select(func.max(MnaScore.as_of)))


def list_scores(
    session: Session, filters: dict[str, Any], page: int, size: int
) -> tuple[list[dict[str, Any]], int]:
    """M&A 타겟 랭킹 서빙 조회(2.5). company 조인 + 필터 + mna_target_score 내림차순.

    2.4 list_scores와 동일 골격, 정렬 방향만 반대(인수 매력 높은 순). null 정렬은
    방언 무관 명시적 키(`IS NULL` 우선 → 값 desc → corp_code 안정 정렬)로 처리.
    sector 필터는 KSIC prefix 매칭(2.7 버킷 택소노미와 동일 단위) — 정확일치로 하면
    세분류 코드(4~5자리)를 사용자가 알 수 없어 필터가 사실상 죽는다.
    """
    conds = [MnaScore.as_of == filters["as_of"]]
    if filters.get("market"):
        conds.append(Company.market == filters["market"])
    if filters.get("sector"):
        conds.append(Company.sector.startswith(filters["sector"], autoescape=True))

    base = select(MnaScore, Company).join(
        Company, Company.corp_code == MnaScore.corp_code
    ).where(*conds)

    total = session.scalar(
        select(func.count()).select_from(base.subquery())
    ) or 0
    rows = session.execute(
        base.order_by(
            MnaScore.mna_target_score.is_(None),  # null last(명시적)
            MnaScore.mna_target_score.desc(),
            MnaScore.corp_code.asc(),
        ).limit(size).offset((page - 1) * size)
    ).all()

    items = []
    for score, company in rows:
        items.append({
            "corp_code": score.corp_code,
            "corp_name": company.corp_name,
            "market": company.market,
            "sector": company.sector,
            "as_of": score.as_of,
            "mna_target_score": score.mna_target_score,
            "valuation_score": score.valuation_score,
            "capacity_score": score.capacity_score,
            "ownership_score": score.ownership_score,
            "macro_score": score.macro_score,
            "population_basis": score.population_basis,
        })
    return items, total


def delete_mna_score(session: Session, corp_code: str, as_of: str) -> None:
    """근거(입력 데이터)를 잃은 (corp_code, as_of)의 오래된 score 정리(2.1 reconciliation
    패턴). 없으면 no-op(멱등)."""
    stmt = select(MnaScore).where(
        MnaScore.corp_code == corp_code, MnaScore.as_of == as_of,
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is not None:
        session.delete(obj)

```

### `app/schemas.py`

```python
"""API 응답 pydantic 스키마."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """목록 응답 봉투 (AD-6)."""

    items: list[T]
    total: int
    page: int
    size: int


class MetricOut(BaseModel):
    """valuation_metrics 뷰 + company 조인 결과."""

    corp_code: str
    corp_name: str | None = None
    market: str | None = None
    sector: str | None = None
    year: int
    quarter: int
    roe: float | None = None
    roa: float | None = None
    pbr: float | None = None
    per: float | None = None
    ev_ebitda: float | None = None
    debt_ratio: float | None = None
    payout_ratio: float | None = None
    net_cash: int | None = None
    ebitda_margin: float | None = None
    yoy_revenue_growth: float | None = None
    yoy_income_growth: float | None = None


class MnaRankingOut(BaseModel):
    """mna_score + company 조인 결과 (2.5 M&A 타겟 랭킹).

    mna_target_score 계약: **null=산출 불가**(요소 하나라도 입력 데이터 부족이면 총점
    null — 2.3 엄격 null 정책). UI에서 0점이나 최하위로 표시 금지, "산출 불가"로 표시.
    population_basis: 백분위 모집단 식별(sector:{KSIC2} / market_fallback / market, 2.7).
    """

    corp_code: str
    corp_name: str | None = None
    market: str | None = None
    sector: str | None = None
    as_of: str
    mna_target_score: float | None = None
    valuation_score: float | None = None
    capacity_score: float | None = None
    ownership_score: float | None = None
    macro_score: float | None = None
    population_basis: str | None = None


class GapAnalysisOut(BaseModel):
    """valueup_score + company 조인 결과 (2.4 갭분석/워싱랭킹).

    washing_flag 계약: true=워싱 의심 / false=워싱 근거 없음 / **null=판단 불가**
    (입력 데이터 부족 — UI에서 빈칸이나 '아니오'로 표시 금지, "판단 불가"로 표시할 것).
    """

    corp_code: str
    corp_name: str | None = None
    market: str | None = None
    as_of: str
    target_roe: float | None = None
    actual_roe: float | None = None
    roe_gap: float | None = None
    achievement_rate: float | None = None
    progress_rate: float | None = None
    execution_score: float | None = None
    washing_flag: bool | None = None
    buyback_status: str | None = None

```

### `app/services/mna.py`

```python
"""M&A 타겟 랭킹 유스케이스 (routers→services→repositories, AD-2)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.repositories import mna_score as repo
from app.schemas import MnaRankingOut, Page


def ranking(
    session: Session, filters: dict[str, Any], page: int, size: int
) -> Page[MnaRankingOut]:
    filters["as_of"] = filters.get("as_of") or repo.latest_as_of(session)
    if filters["as_of"] is None:  # 스코어 미적재 → 빈 봉투(500 아님)
        return Page(items=[], total=0, page=page, size=size)
    rows, total = repo.list_scores(session, filters, page, size)
    return Page(items=[MnaRankingOut(**r) for r in rows], total=total, page=page, size=size)

```

### `app/routers/mna.py`

```python
"""/mna 라우터 — M&A 타겟 랭킹 (HTTP 경계, AD-2)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import MnaRankingOut, Page
from app.services import mna as service

router = APIRouter(prefix="/mna", tags=["mna"])


@router.get(
    "/ranking",
    response_model=Page[MnaRankingOut],
    description=(
        "M&A 타겟 점수 랭킹. mna_target_score 내림차순(인수 매력 높은 순), null last. "
        "mna_target_score: null=산출 불가(요소 하나라도 입력 데이터 부족 — 엄격 null 정책) — "
        "UI에서 null을 0점이나 최하위로 표시하지 말고 '산출 불가'로 표시할 것. "
        "population_basis: 백분위 모집단(sector:{KSIC2}=업종 peer / market_fallback=peer 미달 "
        "폴백 / market=업종 정보 없음). sector 필터는 KSIC 코드 prefix 매칭(예: 64=금융지주 계열)."
    ),
)
def mna_ranking(
    market: str | None = None,
    sector: str | None = Query(None, description="KSIC 업종코드 prefix(예: 26, 64)"),
    # date 타입 = FastAPI가 달력 검증(2026-02-30/garbage → 422, 2.4 일괄리뷰 교훈)
    as_of: date | None = Query(None, description="기준일(YYYY-MM-DD), 기본=최신"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[MnaRankingOut]:
    filters = {"market": market, "sector": sector,
               "as_of": as_of.isoformat() if as_of else None}
    return service.ranking(db, filters, page, size)

```

### `app/main.py`

```python
"""FastAPI 엔트리포인트.

레이어 구조(AD-2): routers → services → repositories → models/DB.
이 스토리는 골격 + /health 만 제공한다.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app import __version__
from app.config import settings
from app.db import check_db
from app.routers import metrics as metrics_router
from app.routers import mna as mna_router
from app.routers import valueup as valueup_router

logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name, version=__version__)
app.include_router(metrics_router.router)
app.include_router(valueup_router.router)
app.include_router(mna_router.router)


@app.get("/health", tags=["system"])
def health() -> JSONResponse:
    """헬스체크: 앱 기동 + DB 왕복(SELECT 1) 확인.

    DB 정상 → 200 {status:ok, db:ok}
    DB 실패 → 503 {status:degraded, db:down} (모니터링이 상태를 읽게)
    """
    try:
        check_db()
    except Exception:
        # 원인 추적용 로깅. 시크릿(DB URL·키)은 SecretStr이라 예외 메시지에 원문 노출 안 됨.
        logger.exception("DB health check failed")
        return JSONResponse(
            status_code=503, content={"status": "degraded", "db": "down"}
        )
    return JSONResponse(status_code=200, content={"status": "ok", "db": "ok"})

```

### `tests/test_mna_api.py`

```python
"""Story 2.5 — M&A 타겟 랭킹 API 검증 (SQLite in-memory + TestClient)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Company, MnaScore


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:", future=True,
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    return eng


def _seed(s: Session) -> None:
    for code, name, market, sector in (
        ("00000001", "저평가매력", "KOSPI", "26100"),   # 반도체
        ("00000002", "보통", "KOSPI", "26200"),
        ("00000003", "산출불가금융", "KOSPI", "64110"),  # 금융(엄격 null)
        ("00000004", "코스닥유통", "KOSDAQ", "47000"),
        ("00000005", "과거스냅샷", "KOSPI", None),
    ):
        s.add(Company(corp_code=code, corp_name=name, market=market, sector=sector))
    s.add(MnaScore(
        corp_code="00000001", as_of="2026-07-13",
        mna_target_score=82.5, valuation_score=0.9, capacity_score=0.8,
        ownership_score=0.7, macro_score=0.6, population_basis="sector:26",
    ))
    s.add(MnaScore(
        corp_code="00000002", as_of="2026-07-13",
        mna_target_score=41.0, valuation_score=0.4, capacity_score=0.4,
        ownership_score=0.5, macro_score=0.6, population_basis="sector:26",
    ))
    s.add(MnaScore(  # 엄격 null(요소 산출 불가 → 총점 null)
        corp_code="00000003", as_of="2026-07-13",
        mna_target_score=None, valuation_score=None, capacity_score=None,
        ownership_score=0.9, macro_score=0.6, population_basis=None,
    ))
    s.add(MnaScore(
        corp_code="00000004", as_of="2026-07-13",
        mna_target_score=60.0, valuation_score=0.6, capacity_score=0.6,
        ownership_score=0.6, macro_score=0.6, population_basis="market_fallback",
    ))
    s.add(MnaScore(  # 다른 as_of(과거) — 최신 기본 조회에서 제외돼야
        corp_code="00000005", as_of="2025-12-31",
        mna_target_score=99.0, valuation_score=1.0, capacity_score=1.0,
        ownership_score=1.0, macro_score=1.0, population_basis="market",
    ))
    s.commit()


@pytest.fixture()
def client(engine, monkeypatch):
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    return TestClient(fastapi_app)


def test_ranking_envelope_desc_null_last(client) -> None:
    """AC1/2: 봉투 + mna_target_score 내림차순(null last) + 기본 as_of=최신 + 요소별 분해."""
    r = client.get("/mna/ranking")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "total", "page", "size"}
    assert body["total"] == 4  # 최신 as_of만, 과거(00000005) 제외
    codes = [i["corp_code"] for i in body["items"]]
    # 82.5 → 60.0 → 41.0 → null(산출 불가 마지막)
    assert codes == ["00000001", "00000004", "00000002", "00000003"]
    top = body["items"][0]
    # 요소별 분해 + population_basis 노출
    assert top["valuation_score"] == 0.9
    assert top["capacity_score"] == 0.8
    assert top["ownership_score"] == 0.7
    assert top["macro_score"] == 0.6
    assert top["population_basis"] == "sector:26"


def test_null_score_returned_as_null(client) -> None:
    """AC3: 엄격 null — 총점 null은 null 그대로(0점 강제 금지), 산출된 요소는 노출."""
    r = client.get("/mna/ranking")
    last = r.json()["items"][-1]
    assert last["corp_code"] == "00000003"
    assert last["mna_target_score"] is None
    assert last["ownership_score"] == 0.9  # 산출된 요소는 그대로


def test_filters_market_and_sector_prefix(client) -> None:
    """AC2: market 필터 + sector는 KSIC prefix 매칭."""
    r = client.get("/mna/ranking", params={"market": "KOSDAQ"})
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000004"]
    r2 = client.get("/mna/ranking", params={"sector": "26"})  # 26100·26200 모두
    assert [i["corp_code"] for i in r2.json()["items"]] == ["00000001", "00000002"]
    r3 = client.get("/mna/ranking", params={"sector": "26100"})  # 세분류 정확 매칭도 동작
    assert [i["corp_code"] for i in r3.json()["items"]] == ["00000001"]


def test_explicit_as_of_and_pagination(client) -> None:
    """AC2/5: as_of 스냅샷 + 페이지네이션 + 무효 날짜 422."""
    r = client.get("/mna/ranking", params={"as_of": "2025-12-31"})
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000005"]
    r2 = client.get("/mna/ranking", params={"page": 2, "size": 2})
    body = r2.json()
    assert body["total"] == 4 and body["page"] == 2
    assert [i["corp_code"] for i in body["items"]] == ["00000002", "00000003"]
    assert client.get("/mna/ranking", params={"as_of": "2026-02-30"}).status_code == 422
    assert client.get("/mna/ranking", params={"as_of": "garbage"}).status_code == 422


def test_empty_scores_returns_empty_envelope(engine, monkeypatch) -> None:
    """AC5: 스코어 미적재 → 빈 봉투(500 아님)."""
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    r = TestClient(fastapi_app).get("/mna/ranking")
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0, "page": 1, "size": 20}

```
