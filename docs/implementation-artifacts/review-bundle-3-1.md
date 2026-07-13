# Review Bundle — Story 3.1: 시장·매크로 통계 API (2026-07-13)

역할: 당신은 이 프로젝트 컨텍스트가 전혀 없는 시니어 파이썬/FastAPI/SQL 리뷰어다. 아래 AC·제약·코드(verbatim, 축약 없음)만 보고 실제 버그·계약 위반·SQL 방언 문제를 찾아라. 스타일 지적보다 동작 결함 우선.

## 스토리 AC 요약

1. `GET /stats/market-comparison` — 시장(KOSPI/KOSDAQ)별 n(as_of 시점 look-ahead 안전 최신 지표 보유 종목 수)·avg_roe·avg_pbr·avg_ev_ebitda(null-safe 평균)·n_judged·n_washing·washing_ratio. 데이터 없는 시장은 행 자체가 없음(all-null 행 금지).
2. `GET /stats/summary` — 시장 구분 없는 전체 KPI(n_companies·n_metrics·avg_*·n_judged·n_washing·washing_ratio) 단일 객체.
3. `GET /stats/macro` — 4개 매크로 지표(base_rate/bond_3y/usd_krw/leading_index) 각각의 as_of 이전 최신 관측. 관측 없으면 date/value null이되 지표 자리 4개는 항상 보장.
4. washing_ratio 분모 = n_judged(washing_flag IS NOT NULL), n_judged=0이면 washing_ratio는 null(0으로 나누지 않음). n(지표보유)과 n_judged(판단가능)는 서로 다른 모집단 — 섞으면 안 됨.
5. as_of(date, 422 검증) 기본값: market-comparison/summary는 valueup_score 최신 as_of, macro는 macro_indicator 자체 최신 관측일(서로 독립적 소스, 시스템 시계 미사용). valueup_score 미적재 시 market-comparison은 빈 봉투 200, summary는 404.
6. 레이어: routers→services→repositories(AD-2), SQL은 repository에서만. look-ahead 방지(같은 해 사업보고서 quarter=4 배제)는 2.1/2.3과 동일 SQL 패턴 재사용.
7. 응답 형태: market-comparison·macro는 Page[T] 봉투(AD-6)를 쓰되 page/size 쿼리 파라미터는 받지 않고 항상 page=1, size=len(items) 고정(고정 소수 카디널리티라 실제 페이지네이션 없음 — 의도된 설계). summary는 목록이 아니라 봉투 없이 단일 객체.

## 아키텍처 제약(위반 여부 볼 것)

- AD-2: 라우터·서비스는 SQL 실행 금지(repository만).
- AD-6: 에러 계약 {detail,code}(main.py 전역 RequestValidationError 핸들러가 이미 처리, 이 스토리가 새로 만들지 않음).
- AD-4/AD-7/AD-10: valueup_score·macro_indicator·mna_score는 각각 유일 writer가 있음 — 이 스토리는 셋 다 **읽기만** 해야 함.
- 1.7 known-limitation: DISTINCT ON(PostgreSQL 전용)은 SQLite 비호환이라 금지 — corp별 최신행 선택은 정렬+Python dedupe로.

## 설계상 의도된 선택(재보고 불필요)

- market-comparison·macro가 Page[T] 봉투를 쓰지만 page/size 쿼리 파라미터를 받지 않는 것은 버그가 아니라 의도(고정 소수 카디널리티, dev notes에 근거 기록).
- look-ahead 안전 SQL을 `app/repositories/mna_score.py`(2.3, Epic 2 완료 파일)에서 재사용하지 않고 `stats.py`에 독립 작성한 것은 의도(Epic 2 완료 코드의 blast radius를 0으로 유지, 3번째 소비자 생기면 공통 헬퍼 추출 검토).
- washing 카운트를 SQL GROUP BY/CASE 대신 Python 루프로 계산한 것은 의도(데이터 규모가 작고, 방언별 boolean 집계 표현 차이를 피하기 위함).
- score_run 배치 메타데이터(부분 실행이 latest_as_of를 오염시킬 수 있는 문제)는 2.4부터 이어진 별도 defer — 이 스토리도 동일 함수(`valueup_score.latest_as_of`)를 재사용하므로 같은 한계를 상속하나 이 스토리의 스코프는 아님.

## 코드 (verbatim)


### `app/repositories/stats.py`

```python
"""시장·매크로 통계 조회 저장소 (AD-2: SQL은 여기서만).

`valuation_metrics` VIEW·`valueup_score`·`macro_indicator`를 **읽기만**(각 writer는
어댑터/엔진, AD-4/AD-7/AD-10 불변). look-ahead 안전 최신 지표 조회는 2.1/2.3(gap_engine·
mna_engine)의 SQL 패턴을 재사용하되, 완료된 Epic 2 파일(`mna_score.py`)은 건드리지 않고
이 모듈에 독립 작성한다(blast radius 격리, 3번째 소비자가 생기면 공통 헬퍼로 추출 검토).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import Company, MacroIndicator, ValueupScore

# macro_indicator CHECK 제약과 동일한 고정 화이트리스트(app/models.py:MacroIndicator).
# 관측이 없어도 이 4개 자리는 항상 보장 — "지표 자체가 없음"과 "아직 값이 없음"을 구분.
MACRO_INDICATORS = ("base_rate", "bond_3y", "usd_krw", "leading_index")


def _latest_metrics_by_market(session: Session, as_of: str) -> dict[str, list[dict[str, Any]]]:
    """as_of 시점 look-ahead 안전 최신 1건/종목의 roe·pbr·ev_ebitda를 market별로 묶는다.

    2.1/2.3과 동일한 사업보고서 배제 규칙(`year<yr OR (year=yr AND quarter<4)`).
    corp별 최신행 선택은 DISTINCT ON(PostgreSQL 전용) 대신 정렬 후 Python dedupe —
    SQLite/PostgreSQL 양쪽 이식성(1.7 known-limitation 컨벤션).
    """
    as_of_year = int(as_of[:4])
    rows = session.execute(
        text(
            "SELECT vm.corp_code, c.market, vm.roe, vm.pbr, vm.ev_ebitda, vm.year, vm.quarter "
            "FROM valuation_metrics vm JOIN company c ON c.corp_code = vm.corp_code "
            "WHERE vm.year < :yr OR (vm.year = :yr AND vm.quarter < 4) "
            "ORDER BY vm.corp_code, vm.year DESC, vm.quarter DESC"
        ),
        {"yr": as_of_year},
    ).mappings().all()

    latest_per_corp: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = row["corp_code"]
        if code not in latest_per_corp:  # 정렬상 corp별 첫 행 = 최신
            latest_per_corp[code] = row

    by_market: dict[str, list[dict[str, Any]]] = {}
    for rec in latest_per_corp.values():
        by_market.setdefault(rec["market"], []).append(rec)
    return by_market


def _avg(values: list[float | None]) -> float | None:
    """null-safe 평균 — None은 제외하고 평균, 값이 하나도 없으면 None(0으로 나누지 않음)."""
    non_null = [v for v in values if v is not None]
    if not non_null:
        return None
    return sum(non_null) / len(non_null)


def _washing_counts_by_market(
    session: Session, as_of: str
) -> dict[str, tuple[int, int]]:
    """as_of 스냅샷의 시장별 (n_judged, n_washing). judged=washing_flag IS NOT NULL.

    SQL 집계(COUNT/CASE) 대신 Python에서 세는 이유: 결과 행 수가 종목 수 규모(수십~수백)에
    불과해 성능 문제가 없고, 방언별 boolean 집계 표현 차이(SQLite/PostgreSQL)를 피한다.
    """
    stmt = (
        select(Company.market, ValueupScore.washing_flag)
        .join(ValueupScore, ValueupScore.corp_code == Company.corp_code)
        .where(ValueupScore.as_of == as_of)
    )
    counts: dict[str, tuple[int, int]] = {}
    for market, washing_flag in session.execute(stmt).all():
        n_judged, n_washing = counts.get(market, (0, 0))
        if washing_flag is not None:
            n_judged += 1
            if washing_flag:
                n_washing += 1
        counts[market] = (n_judged, n_washing)
    return counts


def market_comparison(session: Session, as_of: str) -> list[dict[str, Any]]:
    """시장별(KOSPI/KOSDAQ) n·avg_roe·avg_pbr·avg_ev_ebitda·washing_ratio(2.4~2.6과 동일
    look-ahead·null 계약). 데이터 없는 시장은 행 자체를 만들지 않는다(all-null 행 금지)."""
    by_market = _latest_metrics_by_market(session, as_of)
    washing = _washing_counts_by_market(session, as_of)

    markets = sorted(set(by_market) | set(washing))
    items = []
    for market in markets:
        recs = by_market.get(market, [])
        n_judged, n_washing = washing.get(market, (0, 0))
        items.append({
            "market": market,
            "n": len(recs),
            "avg_roe": _avg([r["roe"] for r in recs]),
            "avg_pbr": _avg([r["pbr"] for r in recs]),
            "avg_ev_ebitda": _avg([r["ev_ebitda"] for r in recs]),
            "n_judged": n_judged,
            "n_washing": n_washing,
            "washing_ratio": (n_washing / n_judged) if n_judged > 0 else None,
        })
    return items


def summary(session: Session, as_of: str) -> dict[str, Any]:
    """시장 구분 없는 전체 헤드라인 KPI."""
    by_market = _latest_metrics_by_market(session, as_of)
    all_recs = [r for recs in by_market.values() for r in recs]
    washing = _washing_counts_by_market(session, as_of)
    n_judged = sum(j for j, _ in washing.values())
    n_washing = sum(w for _, w in washing.values())
    n_companies = session.scalar(select(func.count()).select_from(Company)) or 0

    return {
        "as_of": as_of,
        "n_companies": n_companies,
        "n_metrics": len(all_recs),
        "avg_roe": _avg([r["roe"] for r in all_recs]),
        "avg_pbr": _avg([r["pbr"] for r in all_recs]),
        "avg_ev_ebitda": _avg([r["ev_ebitda"] for r in all_recs]),
        "n_judged": n_judged,
        "n_washing": n_washing,
        "washing_ratio": (n_washing / n_judged) if n_judged > 0 else None,
    }


def latest_macro_as_of(session: Session) -> str | None:
    """macro_indicator 자체의 최신 관측일. market-comparison/summary의 as_of(valueup_score
    기반)와 독립 — 서로 다른 데이터 계열이라 각자의 최신값을 기본으로 삼는다(AD-8 정신:
    시스템 시계 대신 데이터 기반 기본값)."""
    return session.scalar(select(func.max(MacroIndicator.date)))


def macro_snapshot(session: Session, as_of: str) -> list[dict[str, Any]]:
    """4개 매크로 지표 각각의 as_of 이전 최신 관측. 관측이 없으면 date/value null이되
    지표 자리 자체는 항상 4개 보장(고정 화이트리스트 순회)."""
    result: dict[str, dict[str, Any]] = {
        ind: {"indicator": ind, "date": None, "value": None} for ind in MACRO_INDICATORS
    }
    stmt = (
        select(MacroIndicator)
        .where(MacroIndicator.indicator.in_(MACRO_INDICATORS), MacroIndicator.date <= as_of)
        .order_by(MacroIndicator.indicator, MacroIndicator.date.desc())
    )
    seen: set[str] = set()
    for obj in session.scalars(stmt):
        if obj.indicator in seen:
            continue
        seen.add(obj.indicator)
        result[obj.indicator] = {
            "indicator": obj.indicator, "date": obj.date, "value": obj.value,
        }
    return [result[ind] for ind in MACRO_INDICATORS]

```

### `app/services/stats.py`

```python
"""시장·매크로 통계 유스케이스 (routers→services→repositories, AD-2)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.repositories import stats as repo
from app.repositories import valueup_score
from app.schemas import MacroSnapshotOut, MarketComparisonOut, Page, StatsSummaryOut


def market_comparison(session: Session, as_of: str | None) -> Page[MarketComparisonOut]:
    resolved = as_of or valueup_score.latest_as_of(session)
    if resolved is None:  # valueup_score 미적재 → 빈 봉투(500 아님)
        return Page(items=[], total=0, page=1, size=0)
    rows = repo.market_comparison(session, resolved)
    items = [MarketComparisonOut(**r) for r in rows]
    return Page(items=items, total=len(items), page=1, size=len(items))


def summary(session: Session, as_of: str | None) -> StatsSummaryOut | None:
    resolved = as_of or valueup_score.latest_as_of(session)
    if resolved is None:  # valueup_score 미적재 → null(엔드포인트가 204/빈 필드로 처리)
        return None
    return StatsSummaryOut(**repo.summary(session, resolved))


def macro(session: Session, as_of: str | None) -> Page[MacroSnapshotOut]:
    # macro_indicator 자체의 최신 관측일이 기본값 — valueup_score와 독립(서로 다른 데이터 계열).
    # 관측이 아예 없으면(resolved=None) 시스템 시계로 대체하지 않고(AD-8 정신) 4개 지표
    # 자리를 null로 채운 빈 스냅샷을 바로 구성 — DB 재조회 불필요(어차피 빈 결과).
    resolved = as_of or repo.latest_macro_as_of(session)
    if resolved is None:
        rows = [{"indicator": ind, "date": None, "value": None} for ind in repo.MACRO_INDICATORS]
    else:
        rows = repo.macro_snapshot(session, resolved)
    items = [MacroSnapshotOut(**r) for r in rows]
    return Page(items=items, total=len(items), page=1, size=len(items))

```

### `app/routers/stats.py`

```python
"""/stats 라우터 — 시장·매크로 통계 (HTTP 경계, AD-2).

market-comparison·macro는 Page[T] 봉투(AD-6)를 쓰되 실제 페이지네이션 파라미터는 받지
않는다 — 고정 소수 카디널리티(시장 2개·매크로 지표 4개)라 페이지 개념이 없다(3.1 dev notes
근거). summary는 목록이 아니므로 봉투 없이 단일 객체(스코어 미적재 시 404).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import MacroSnapshotOut, MarketComparisonOut, Page, StatsSummaryOut
from app.services import stats as service

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get(
    "/market-comparison",
    response_model=Page[MarketComparisonOut],
    description=(
        "시장(KOSPI/KOSDAQ)별 평균지표·워싱비율. n=as_of 시점 최신 지표 보유 종목 수, "
        "washing_ratio 분모는 n_judged(washing_flag가 null 아닌 종목 — n과 다른 모집단). "
        "데이터 없는 시장은 행 자체가 없다. page/size는 항상 1/len(items) 고정(페이지네이션 없음)."
    ),
)
def market_comparison(
    as_of: date | None = Query(None, description="기준일(YYYY-MM-DD), 기본=valueup_score 최신"),
    db: Session = Depends(get_db),
) -> Page[MarketComparisonOut]:
    return service.market_comparison(db, as_of.isoformat() if as_of else None)


@router.get(
    "/summary",
    response_model=StatsSummaryOut,
    description="시장 구분 없는 전체 헤드라인 KPI. valueup_score 미적재 시 404.",
)
def summary(
    as_of: date | None = Query(None, description="기준일(YYYY-MM-DD), 기본=valueup_score 최신"),
    db: Session = Depends(get_db),
) -> StatsSummaryOut:
    result = service.summary(db, as_of.isoformat() if as_of else None)
    if result is None:
        raise HTTPException(status_code=404, detail="valueup_score 데이터가 없습니다")
    return result


@router.get(
    "/macro",
    response_model=Page[MacroSnapshotOut],
    description=(
        "매크로 지표(base_rate·bond_3y·usd_krw·leading_index) 스냅샷. "
        "date/value null=아직 관측 없음(지표 자리는 항상 4개 보장). "
        "기본 as_of=macro_indicator 자체의 최신 관측일(valueup_score와 독립)."
    ),
)
def macro(
    as_of: date | None = Query(None, description="기준일(YYYY-MM-DD), 기본=매크로 최신 관측일"),
    db: Session = Depends(get_db),
) -> Page[MacroSnapshotOut]:
    return service.macro(db, as_of.isoformat() if as_of else None)

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


class ScreeningOut(BaseModel):
    """company + valueup_score + mna_score outer join 결과 (2.6 다중조건 스크리닝).

    null 계약 승계: washing_flag null=판단 불가(빈칸/아니오 표시 금지, 2.4),
    mna_target_score null=산출 불가(0점/최하위 표시 금지, 2.5).
    has_valueup_score/has_mna_score: 엔진 실행 여부(score row 존재) — "row 없음(미실행)"과
    "row는 있으나 전부 null(엄격 게이팅 산출 불가)"은 필드값만으론 구분 불가라 명시 노출.
    """

    corp_code: str
    corp_name: str | None = None
    market: str | None = None
    sector: str | None = None
    as_of: str
    has_valueup_score: bool
    has_mna_score: bool
    execution_score: float | None = None
    washing_flag: bool | None = None
    buyback_status: str | None = None
    buyback_executed: bool | None = None
    mna_target_score: float | None = None
    population_basis: str | None = None


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


class MarketComparisonOut(BaseModel):
    """시장별(KOSPI/KOSDAQ) 헤드라인 통계 (3.1). n=as_of 시점 최신 지표 보유 종목 수,
    washing_ratio 분모는 n_judged(washing_flag가 null이 아닌 종목) — n과 다른 모집단."""

    market: str
    n: int
    avg_roe: float | None = None
    avg_pbr: float | None = None
    avg_ev_ebitda: float | None = None
    n_judged: int
    n_washing: int
    washing_ratio: float | None = None


class StatsSummaryOut(BaseModel):
    """시장 구분 없는 전체 헤드라인 KPI (3.1)."""

    as_of: str
    n_companies: int
    n_metrics: int
    avg_roe: float | None = None
    avg_pbr: float | None = None
    avg_ev_ebitda: float | None = None
    n_judged: int
    n_washing: int
    washing_ratio: float | None = None


class MacroSnapshotOut(BaseModel):
    """매크로 지표 스냅샷 (3.1). date/value null = 아직 관측 없음(지표 자리는 항상 보장)."""

    indicator: str
    date: str | None = None
    value: float | None = None


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

### `app/main.py`

```python
"""FastAPI 엔트리포인트.

레이어 구조(AD-2): routers → services → repositories → models/DB.
이 스토리는 골격 + /health 만 제공한다.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app import __version__
from app.config import settings
from app.db import check_db
from app.routers import metrics as metrics_router
from app.routers import mna as mna_router
from app.routers import screening as screening_router
from app.routers import stats as stats_router
from app.routers import valueup as valueup_router

logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name, version=__version__)
app.include_router(metrics_router.router)
app.include_router(valueup_router.router)
app.include_router(mna_router.router)
app.include_router(screening_router.router)
app.include_router(stats_router.router)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """422를 AD-6 에러 계약 {detail, code}로 변환(2-5 GPT 리뷰 Med).

    FastAPI 기본 응답은 detail만 있고 code가 없어 계약 위반 — 전 라우터 공통 적용.
    """
    # jsonable_encoder: pydantic v2 errors()의 ctx에 예외 객체 등 비직렬화 값이 섞일 수
    # 있음(FastAPI 기본 핸들러와 동일 처리) — 없으면 422 만들다 500이 됨.
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(exc.errors()), "code": "VALIDATION_ERROR"},
    )


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

### `tests/test_stats_api.py`

```python
"""Story 3.1 — 시장·매크로 통계 API 검증 (SQLite in-memory + TestClient)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Company, MacroIndicator, ValueupScore
from app.sql_views import CREATE_VALUATION_METRICS

AS_OF = "2026-07-13"


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:", future=True,
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    with eng.connect() as conn:
        conn.execute(text(CREATE_VALUATION_METRICS))
        conn.commit()
    return eng


def _seed_financials(session: Session) -> None:
    """valuation_metrics 뷰가 읽을 원천(financials·prices)을 직접 raw SQL로 시드.

    look-ahead 안전성 검증을 위해 일부는 같은 해 사업보고서(quarter=4)로 넣는다.
    """
    session.execute(text(
        "INSERT INTO financials (corp_code, year, quarter, revenue, net_income, equity, "
        "total_assets, total_liabilities, operating_income) VALUES "
        # KOSPI: 고평가 저ROE 종목(과거 3분기 실적 — as_of 시점 조회 가능)
        "('00000001', 2025, 3, 1000, 50, 1000, 3000, 1000, 60), "
        # KOSPI: 저평가 고ROE 종목
        "('00000002', 2025, 3, 1000, 200, 1000, 3000, 1000, 220), "
        # KOSPI: look-ahead 배제 대상 — 같은 해(2026) 사업보고서(quarter=4)는 제외돼야 함
        "('00000001', 2026, 4, 9999, 9999, 9999, 9999, 9999, 9999), "
        # KOSDAQ 종목
        "('00000003', 2025, 3, 500, 100, 500, 1500, 500, 110)"
    ))
    session.execute(text(
        "INSERT INTO prices (corp_code, date, close, volume, trading_value, market_cap) VALUES "
        "('00000001', '2025-12-31', 1000, 100, 100000, 5000), "
        "('00000002', '2025-12-31', 1000, 100, 100000, 1000), "
        "('00000003', '2025-12-31', 1000, 100, 100000, 1500)"
    ))
    session.commit()


def _seed(s: Session) -> None:
    for code, name, market in (
        ("00000001", "고평가워싱", "KOSPI"),
        ("00000002", "저평가양호", "KOSPI"),
        ("00000003", "코스닥종목", "KOSDAQ"),
        ("00000004", "지표없음", "KOSPI"),  # metrics 없음 — 평균에서 자연 제외
    ):
        s.add(Company(corp_code=code, corp_name=name, market=market))
    s.add(ValueupScore(corp_code="00000001", as_of=AS_OF, washing_flag=True))
    s.add(ValueupScore(corp_code="00000002", as_of=AS_OF, washing_flag=False))
    s.add(ValueupScore(corp_code="00000003", as_of=AS_OF, washing_flag=None))  # 판단 불가
    s.add(MacroIndicator(indicator="base_rate", date="2026-07-01", value=3.5))
    s.add(MacroIndicator(indicator="usd_krw", date="2026-06-01", value=1350.0))
    # bond_3y·leading_index는 의도적으로 미수집 — null 자리 검증
    s.commit()
    _seed_financials(s)


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


def test_market_comparison_avg_and_washing_ratio(client) -> None:
    """AC1/4: null-safe 평균 + washing_ratio(분모=n_judged) + look-ahead 배제."""
    r = client.get("/stats/market-comparison")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "total", "page", "size"}
    assert body["page"] == 1 and body["size"] == body["total"]
    by_market = {i["market"]: i for i in body["items"]}
    kospi = by_market["KOSPI"]
    # KOSPI: 00000001(roe=5%)·00000002(roe=20%) — 2026년 사업보고서(look-ahead)는 배제돼야 함
    assert kospi["n"] == 2
    assert kospi["avg_roe"] == pytest.approx((5.0 + 20.0) / 2)
    # washing: 00000001=True·00000002=False 둘 다 KOSPI에서 판단됨 → n_judged=2, n_washing=1
    assert kospi["n_judged"] == 2 and kospi["n_washing"] == 1
    assert kospi["washing_ratio"] == 0.5
    kosdaq = by_market["KOSDAQ"]
    assert kosdaq["n_judged"] == 0  # washing_flag=None(판단불가)만 있어 분모 0
    assert kosdaq["washing_ratio"] is None


def test_summary_headline_kpi(client) -> None:
    """AC2: 전체 헤드라인 KPI, n_companies(전체) vs n_metrics(지표보유) 분리."""
    r = client.get("/stats/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["n_companies"] == 4  # 4번 종목(지표없음)도 포함
    assert body["n_metrics"] == 3    # 지표 있는 종목만
    assert body["n_judged"] == 2 and body["n_washing"] == 1
    assert body["washing_ratio"] == 0.5


def test_summary_returns_404_when_no_scores(engine, monkeypatch) -> None:
    """AC5: valueup_score 미적재 → 404(500 아님)."""
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    r = TestClient(fastapi_app).get("/stats/summary")
    assert r.status_code == 404


def test_market_comparison_empty_when_no_scores(engine, monkeypatch) -> None:
    """AC5: valueup_score 미적재 → market-comparison은 빈 봉투(500 아님)."""
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    r = TestClient(fastapi_app).get("/stats/market-comparison")
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0, "page": 1, "size": 0}


def test_macro_fixed_four_slots_with_nulls(client) -> None:
    """AC3: 4개 지표 자리 항상 보장, 미수집 지표는 date/value null."""
    r = client.get("/stats/macro")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 4
    by_indicator = {i["indicator"]: i for i in body["items"]}
    assert set(by_indicator) == {"base_rate", "bond_3y", "usd_krw", "leading_index"}
    assert by_indicator["base_rate"]["value"] == 3.5
    assert by_indicator["bond_3y"]["value"] is None
    assert by_indicator["bond_3y"]["date"] is None


def test_macro_independent_as_of_default(engine, monkeypatch) -> None:
    """AC5: macro의 기본 as_of는 macro_indicator 자체 최신 관측일 — valueup_score와 독립.

    valueup_score가 전혀 없어도(다른 두 엔드포인트는 빈/404) macro는 정상 동작해야 한다.
    """
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        s.add(MacroIndicator(indicator="base_rate", date="2026-05-01", value=3.0))
        s.commit()
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    r = TestClient(fastapi_app).get("/stats/macro")
    assert r.status_code == 200
    by_indicator = {i["indicator"]: i for i in r.json()["items"]}
    assert by_indicator["base_rate"]["value"] == 3.0


def test_macro_empty_returns_four_null_slots(engine, monkeypatch) -> None:
    """AC5: macro_indicator가 완전히 비어있어도(시스템 시계 미사용) 4개 null 자리 반환."""
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    r = TestClient(fastapi_app).get("/stats/macro")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 4
    assert all(i["value"] is None for i in body["items"])


def test_explicit_as_of_and_invalid_date_422(client) -> None:
    """AC5: as_of 명시 조회 + 무효 날짜 422(전역 핸들러, {detail,code})."""
    r = client.get("/stats/market-comparison", params={"as_of": AS_OF})
    assert r.status_code == 200
    r2 = client.get("/stats/summary", params={"as_of": "2026-02-30"})
    assert r2.status_code == 422
    assert set(r2.json()) == {"detail", "code"}

```
