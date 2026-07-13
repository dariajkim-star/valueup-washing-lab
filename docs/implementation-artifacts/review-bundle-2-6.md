# Review Bundle — Story 2.6: 다중조건 스크리닝 API (2026-07-13)

역할: 당신은 이 프로젝트 컨텍스트가 전혀 없는 시니어 파이썬/FastAPI 리뷰어다. 아래 AC·제약·코드(verbatim, 축약 없음)만 보고 실제 버그·계약 위반·SQL 방언 문제를 찾아라. 스타일 지적보다 동작 결함 우선.

## 스토리 AC 요약

1. `GET /screening` — company + valueup_score + mna_score를 (corp_code, as_of) **outer join**. 한쪽 엔진 미실행 시 그쪽 필드 null(정직 노출). 두 스코어 모두 없는 종목은 제외.
2. 필터 AND 조합: `min/max_execution_score`·`min/max_mna_score`(범위, inf/NaN 422), `washing_only`(IS TRUE), `buyback_executed`(true/false — null은 어느 쪽에도 미포함), `market`(정확일치)·`sector`(KSIC prefix). 범위 필터는 null을 매칭하지 않아야 함.
3. `sort`: `field`/`-field` 규약, 화이트리스트(execution_score·mna_target_score)만. null last + corp_code 안정 정렬. 화이트리스트 밖 → 400 `{detail, code}`. 기본 정렬 corp_code(중립).
4. `as_of`(date, 기본=두 테이블 latest 중 max), 무효 날짜 422 `{detail,code}`(전역 핸들러 기존재). 미적재 → 빈 봉투 200. page le=1_000_000.
5. 레이어: routers→services→repositories, SQL은 repository에서만. 두 스코어 테이블 읽기 전용(writer는 각 엔진).
6. [편승] valueup·metrics 라우터 패리티: 빈 문자열 필터 422(min_length=1)·page 상한·repo `is not None`.

## 아키텍처 제약(위반 여부 볼 것)

- AD-2: 라우터·서비스는 SQL 실행 금지(repository만).
- AD-5: corp_code(8자리)가 유일 조인 키.
- AD-6: 목록 봉투 {items,total,page,size}, 에러 {detail,code}, 정렬 field/-field 규약.
- AD-4/AD-10: valueup_score·mna_score의 writer는 각 엔진뿐 — API는 읽기 전용이어야 함.

## 이미 알려진 것(재보고 불필요)

- 최신 as_of에서 execution_score non-null이 1종목뿐(엄격 게이팅 + 배당 커버리지) — 데이터 특성이지 필터 버그 아님(분해 검증 완료).
- latest_as_of의 부분 실행 오염 → score_run 메타데이터 별도 스토리 defer.
- as_of 관대 파싱(datetime/epoch 문자열 수용) — 2-5에서 Dismiss 결정(계약="달력상 유효 날짜").
- metrics 라우터의 sort 400이 {detail}만 반환(code 없음) — 이번 스토리의 /screening은 {detail,code} 준수, metrics 기존 코드는 스코프 밖.
- count/items 스냅샷 비원자성 — 1-7부터 Low defer 계열.
- SQLite·PostgreSQL 양쪽 지원이 목표(방언 차이 나는 코드가 있으면 지적).

## 코드 (verbatim)


### `app/repositories/screening.py`

```python
"""다중조건 스크리닝 조회 저장소 (AD-2: SQL은 여기서만).

company 기준으로 valueup_score·mna_score를 (corp_code, as_of) outer join — 한쪽 엔진이
그 as_of에 실행되지 않았으면 그쪽 필드가 null로 드러난다(세대 혼합을 조인으로 감추지 않고
정직 노출). 두 스코어 테이블 모두 **읽기 전용**(writer는 각 엔진, AD-4/AD-10).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models import Company, MnaScore, ValueupScore

# 정렬 허용 필드 화이트리스트(AD-6 `field`/`-field` 규약). 사용자 입력을 컬럼 객체로만
# 매핑 — 여기 없는 필드는 ValueError(라우터가 400으로 변환). metrics.py 패턴의 ORM 판.
SORT_COLUMNS = {
    "execution_score": ValueupScore.execution_score,
    "mna_target_score": MnaScore.mna_target_score,
}


def latest_as_of(session: Session) -> str | None:
    """두 스코어 테이블 latest as_of 중 max(가장 최근 엔진 실행 시점). 둘 다 없으면 None."""
    v = session.scalar(select(func.max(ValueupScore.as_of)))
    m = session.scalar(select(func.max(MnaScore.as_of)))
    candidates = [x for x in (v, m) if x is not None]
    return max(candidates) if candidates else None


def list_screening(
    session: Session, filters: dict[str, Any], page: int, size: int,
    sort: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """스크리닝 조회(2.6). 필터는 AND 조합, 범위 필터의 null은 SQL 3치 논리로 자연 배제
    ("산출 불가는 조건 매칭 불가"). buyback_executed=false는 `IS FALSE` — null(판단 불가)은
    true에도 false에도 안 걸린다(null 세탁 금지, 2.1 원칙).
    """
    as_of = filters["as_of"]
    conds: list[Any] = []
    if filters.get("market") is not None:
        conds.append(Company.market == filters["market"])
    if filters.get("sector") is not None:
        conds.append(Company.sector.startswith(filters["sector"], autoescape=True))
    if filters.get("min_execution_score") is not None:
        conds.append(ValueupScore.execution_score >= filters["min_execution_score"])
    if filters.get("max_execution_score") is not None:
        conds.append(ValueupScore.execution_score <= filters["max_execution_score"])
    if filters.get("min_mna_score") is not None:
        conds.append(MnaScore.mna_target_score >= filters["min_mna_score"])
    if filters.get("max_mna_score") is not None:
        conds.append(MnaScore.mna_target_score <= filters["max_mna_score"])
    if filters.get("washing_only"):
        conds.append(ValueupScore.washing_flag.is_(True))
    if filters.get("buyback_executed") is not None:
        conds.append(ValueupScore.buyback_executed.is_(filters["buyback_executed"]))

    base = (
        select(Company, ValueupScore, MnaScore)
        .select_from(Company)
        .join(
            ValueupScore,
            and_(ValueupScore.corp_code == Company.corp_code,
                 ValueupScore.as_of == as_of),
            isouter=True,
        )
        .join(
            MnaScore,
            and_(MnaScore.corp_code == Company.corp_code, MnaScore.as_of == as_of),
            isouter=True,
        )
        # 두 스코어 모두 없는 종목 제외 — 회사정보만 있는 노이즈 행 방지
        .where(or_(ValueupScore.id.is_not(None), MnaScore.id.is_not(None)), *conds)
    )

    total = session.scalar(
        select(func.count()).select_from(base.subquery())
    ) or 0

    order = _order_by(sort)
    rows = session.execute(
        base.order_by(*order).limit(size).offset((page - 1) * size)
    ).all()

    items = []
    for company, vs, ms in rows:
        items.append({
            "corp_code": company.corp_code,
            "corp_name": company.corp_name,
            "market": company.market,
            "sector": company.sector,
            "as_of": as_of,
            "execution_score": vs.execution_score if vs else None,
            "washing_flag": vs.washing_flag if vs else None,
            "buyback_status": vs.buyback_status if vs else None,
            "buyback_executed": vs.buyback_executed if vs else None,
            "mna_target_score": ms.mna_target_score if ms else None,
            "population_basis": ms.population_basis if ms else None,
        })
    return items, total


def _order_by(sort: str | None) -> list[Any]:
    """sort=`field`/`-field`를 화이트리스트로 안전 변환(null last 명시 + corp_code 안정 정렬).

    기본 정렬은 corp_code — 스크리닝은 양방향(워싱↔M&A 후보)이라 임의 기본 정렬로
    의미를 암시하지 않는다. 허용 밖 필드는 ValueError(라우터가 400 {detail,code}로 변환).
    """
    if not sort:
        return [Company.corp_code.asc()]
    desc = sort.startswith("-")
    field = sort[1:] if desc else sort
    col = SORT_COLUMNS.get(field)
    if col is None:
        raise ValueError(f"invalid sort field: {field!r}")
    direction = col.desc() if desc else col.asc()
    return [col.is_(None), direction, Company.corp_code.asc()]  # null last(명시적)

```

### `app/services/screening.py`

```python
"""다중조건 스크리닝 유스케이스 (routers→services→repositories, AD-2)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.repositories import screening as repo
from app.schemas import Page, ScreeningOut


def screening(
    session: Session, filters: dict[str, Any], page: int, size: int,
    sort: str | None = None,
) -> Page[ScreeningOut]:
    filters["as_of"] = filters.get("as_of") or repo.latest_as_of(session)
    if filters["as_of"] is None:  # 두 스코어 모두 미적재 → 빈 봉투(500 아님)
        return Page(items=[], total=0, page=page, size=size)
    rows, total = repo.list_screening(session, filters, page, size, sort)
    return Page(items=[ScreeningOut(**r) for r in rows], total=total, page=page, size=size)

```

### `app/routers/screening.py`

```python
"""/screening 라우터 — 다중조건 스크리닝 (HTTP 경계, AD-2)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import Page, ScreeningOut
from app.services import screening as service

router = APIRouter(prefix="/screening", tags=["screening"])


@router.get(
    "",
    response_model=Page[ScreeningOut],
    description=(
        "워싱·저평가·M&A 후보 양방향 스크리닝(valueup_score + mna_score outer join). "
        "washing_flag: null=판단 불가(빈칸/아니오 표시 금지). "
        "mna_target_score: null=산출 불가(0점/최하위 표시 금지). "
        "buyback_executed 필터: true/false 모두 null(판단 불가)은 미포함. "
        "sort: `field`/`-field` 규약, 허용=execution_score·mna_target_score(기본=corp_code). "
        "범위 필터는 null을 매칭하지 않는다(산출 불가는 조건 판단 불가)."
    ),
)
def screening_list(
    market: str | None = Query(None, min_length=1),
    sector: str | None = Query(
        None, min_length=1, pattern=r"^\d{2,5}$",
        description="KSIC 업종코드 prefix(예: 26, 64)",
    ),
    min_execution_score: float | None = Query(None, allow_inf_nan=False),
    max_execution_score: float | None = Query(None, allow_inf_nan=False),
    min_mna_score: float | None = Query(None, allow_inf_nan=False),
    max_mna_score: float | None = Query(None, allow_inf_nan=False),
    washing_only: bool = Query(False),
    buyback_executed: bool | None = Query(
        None, description="true=매입 실행 / false=미실행 — null(판단 불가)은 양쪽 다 제외"
    ),
    sort: str | None = Query(None, description="execution_score | mna_target_score, `-` 내림차순"),
    as_of: date | None = Query(None, description="기준일(YYYY-MM-DD), 기본=최신 실행 시점"),
    page: int = Query(1, ge=1, le=1_000_000),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[ScreeningOut] | JSONResponse:
    filters = {
        "market": market, "sector": sector,
        "min_execution_score": min_execution_score,
        "max_execution_score": max_execution_score,
        "min_mna_score": min_mna_score, "max_mna_score": max_mna_score,
        "washing_only": washing_only, "buyback_executed": buyback_executed,
        "as_of": as_of.isoformat() if as_of else None,
    }
    try:
        return service.screening(db, filters, page, size, sort)
    except ValueError as e:
        # sort 화이트리스트 밖 필드 — AD-6 에러 계약 {detail, code}로 400
        return JSONResponse(
            status_code=400, content={"detail": str(e), "code": "INVALID_SORT"}
        )

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
    한쪽 스코어 필드가 전부 null이면 그 엔진이 이 as_of에 실행되지 않은 것.
    """

    corp_code: str
    corp_name: str | None = None
    market: str | None = None
    sector: str | None = None
    as_of: str
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
from app.routers import valueup as valueup_router

logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name, version=__version__)
app.include_router(metrics_router.router)
app.include_router(valueup_router.router)
app.include_router(mna_router.router)
app.include_router(screening_router.router)


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

### `app/routers/valueup.py`

```python
"""/valueup 라우터 — 갭분석·워싱랭킹 (HTTP 경계, AD-2)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import GapAnalysisOut, Page
from app.services import valueup as service

router = APIRouter(prefix="/valueup", tags=["valueup"])


@router.get(
    "/gap-analysis",
    response_model=Page[GapAnalysisOut],
    description=(
        "밸류업 계획 대비 이행 갭 분석. execution_score 오름차순(이행 나쁜 순), null last. "
        "washing_flag: true=워싱 의심 / false=근거 없음 / null=판단 불가(데이터 부족) — "
        "UI에서 null을 빈칸이나 '아니오'로 표시하지 말고 '판단 불가'로 표시할 것."
    ),
)
def gap_analysis(
    # min_length=1·page 상한: 2-5 리뷰 패리티 정비(빈 필터 확대·OFFSET 오버플로 방지)
    market: str | None = Query(None, min_length=1),
    min_progress: float | None = Query(None, ge=0.0, le=1.0),
    # date 타입 = FastAPI가 달력 검증(2026-02-30/garbage → 422, 일괄리뷰 Med — 빈 200으로
    # "데이터 없음"과 "잘못된 요청"이 섞이지 않게)
    as_of: date | None = Query(None, description="기준일(YYYY-MM-DD), 기본=최신"),
    page: int = Query(1, ge=1, le=1_000_000),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[GapAnalysisOut]:
    filters = {"market": market, "min_progress": min_progress,
               "as_of": as_of.isoformat() if as_of else None}
    return service.gap_analysis(db, filters, page, size)


@router.get(
    "/washing-ranking",
    response_model=Page[GapAnalysisOut],
    description=(
        "워싱 의심(washing_flag=true) 종목만, execution_score 오름차순. "
        "판단 불가(null)·근거 없음(false)은 제외 — 전체는 /valueup/gap-analysis 사용."
    ),
)
def washing_ranking(
    # min_length=1·page 상한: 2-5 리뷰 패리티 정비(빈 필터 확대·OFFSET 오버플로 방지)
    market: str | None = Query(None, min_length=1),
    min_progress: float | None = Query(None, ge=0.0, le=1.0),
    # date 타입 = FastAPI가 달력 검증(2026-02-30/garbage → 422, 일괄리뷰 Med — 빈 200으로
    # "데이터 없음"과 "잘못된 요청"이 섞이지 않게)
    as_of: date | None = Query(None, description="기준일(YYYY-MM-DD), 기본=최신"),
    page: int = Query(1, ge=1, le=1_000_000),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[GapAnalysisOut]:
    filters = {"market": market, "min_progress": min_progress,
               "as_of": as_of.isoformat() if as_of else None}
    return service.washing_ranking(db, filters, page, size)

```

### `app/routers/metrics.py`

```python
"""/metrics 라우터 — 밸류에이션 지표 조회 (HTTP 경계, AD-2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import MetricOut, Page
from app.services import metrics as service

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("", response_model=Page[MetricOut])
def list_metrics(
    # min_length=1·page 상한: 2-5 리뷰 패리티 정비(빈 필터 확대·OFFSET 오버플로 방지)
    market: str | None = Query(None, min_length=1),
    sector: str | None = Query(None, min_length=1),
    # 수치 필터는 NaN/inf 거부(DB별 비교 규칙이 갈리고 필터가 무력화됨) → 422
    max_pbr: float | None = Query(None, allow_inf_nan=False),
    min_roe: float | None = Query(None, allow_inf_nan=False),
    max_debt_ratio: float | None = Query(None, allow_inf_nan=False),
    min_payout_ratio: float | None = Query(None, allow_inf_nan=False),
    sort: str | None = Query(
        None,
        description="정렬 필드(공통 규약). `-field`는 내림차순. "
        "예: `-pbr`, `roe`. 허용: roe·roa·pbr·per·ev_ebitda·debt_ratio·"
        "payout_ratio·year 등(화이트리스트).",
    ),
    page: int = Query(1, ge=1, le=1_000_000),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[MetricOut]:
    filters = {
        "market": market, "sector": sector, "max_pbr": max_pbr,
        "min_roe": min_roe, "max_debt_ratio": max_debt_ratio,
        "min_payout_ratio": min_payout_ratio,
    }
    try:
        return service.list_metrics(db, filters, page, size, sort)
    except ValueError as e:
        # 화이트리스트 밖 sort 필드 → 400 (인젝션 시도도 여기서 차단)
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{corp_code}", response_model=list[MetricOut])
def metrics_by_corp(corp_code: str, db: Session = Depends(get_db)) -> list[MetricOut]:
    return service.metrics_by_corp(db, corp_code)

```

### `app/repositories/valueup_score.py`

```python
"""valueup_score 입력 조회 + 멱등 upsert 저장소 (AD-2: SQL은 여기서만).

gap_engine(app/analysis/gap_engine.py)의 유일한 DB 접근 지점. 세 가지 읽기(공시 목표·
실적 지표·자사주 원천)와 한 가지 쓰기(스코어 upsert)로 구성. gap_engine 자체는 dict/스칼라만
다루고 SQL을 직접 실행하지 않는다(AD-2).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import Session

from app.models import Company, Financial, ValueupPlan, ValueupScore


def list_all_corp_codes(session: Session) -> list[str]:
    """전 종목 corp_code 목록(run()의 corp_codes 기본값). SQL은 여기서만(AD-2)."""
    return list(session.scalars(select(Company.corp_code)).all())


def latest_valueup_plan(
    session: Session, corp_code: str, as_of: str
) -> dict[str, Any] | None:
    """as_of 이전(포함) 최신 valueup_plan 1건. 여러 공시 중 as_of 직전 최신 것을 target으로 채택
    (2026-07-10 리드 결정 A: 기간-포함 판정 대신 단순·재현 가능한 규칙).

    동일 disclosure_date(원공시+정정공시 등) tie-break은 plan_id 내림차순(코드리뷰 Med,
    GPT) — 접수번호 등 진짜 우선순위 필드가 없어 "나중에 적재된 것"을 결정적으로 채택.
    """
    stmt = (
        select(ValueupPlan)
        .where(
            ValueupPlan.corp_code == corp_code,
            ValueupPlan.disclosure_date <= as_of,
        )
        .order_by(ValueupPlan.disclosure_date.desc(), ValueupPlan.plan_id.desc())
        .limit(1)
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        return None
    return {
        "target_roe": obj.target_roe,
        "target_payout_ratio": obj.target_payout_ratio,
        "target_pbr": obj.target_pbr,  # 계산 미사용, 참고 보관만(리드 결정)
        "period_start": obj.period_start,
        "period_end": obj.period_end,
        "buyback_planned": obj.buyback_planned,
    }


def latest_metrics(session: Session, corp_code: str, as_of: str) -> dict[str, Any] | None:
    """as_of 이전 최신 (year,quarter) valuation_metrics 행. look-ahead 부분 차단(코드리뷰 High,
    GPT): 같은 연도의 **사업보고서(quarter=4)는 그 해 안에 공시될 수 없음**(결산 후 통상 90일
    이내 = 다음 해)이므로 무조건 제외 — `year<as_of_year OR (year=as_of_year AND quarter<4)`.
    1~3분기 보고서의 동일연도 내 공시시차는 실제 공시일 데이터가 없어 잔여 리스크로 defer
    (deferred-work.md 2-1 섹션). AD-1: 뷰가 계산한 값을 읽기만.
    """
    as_of_year = int(as_of[:4])
    row = session.execute(
        text(
            "SELECT roe, payout_ratio FROM valuation_metrics "
            "WHERE corp_code = :cc AND (year < :yr OR (year = :yr AND quarter < 4)) "
            "ORDER BY year DESC, quarter DESC LIMIT 1"
        ),
        {"cc": corp_code, "yr": as_of_year},
    ).mappings().one_or_none()
    return dict(row) if row is not None else None


def latest_financial_buyback(
    session: Session, corp_code: str, as_of: str
) -> dict[str, Any] | None:
    """as_of 이전 최신 (year,quarter) financials의 buyback 수량 필드.
    look-ahead 부분 차단은 latest_metrics와 동일 규칙(사업보고서 동일연도 제외)."""
    as_of_year = int(as_of[:4])
    stmt = (
        select(Financial)
        .where(
            Financial.corp_code == corp_code,
            or_(
                Financial.year < as_of_year,
                and_(Financial.year == as_of_year, Financial.quarter < 4),
            ),
        )
        .order_by(Financial.year.desc(), Financial.quarter.desc())
        .limit(1)
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        return None
    return {
        "buyback_amount": obj.buyback_amount,
        "buyback_retired_amount": obj.buyback_retired_amount,
    }


def upsert_valueup_score(session: Session, rec: dict[str, Any]) -> ValueupScore:
    """(corp_code, as_of) 자연키 기준 valueup_score upsert(AD-7 확장 패턴).

    gap_engine 산출값은 항상 그 as_of의 '권위 있는 재계산 결과'이므로 null 포함 전체
    교체한다(valueup_plan upsert와 동일 원칙 — 재계산 시 과거 오탐이 null로 정정되게).
    `rec[field]`(직접 인덱싱, 코드리뷰 Med, GPT): 키 누락은 프로그래밍 오류이므로
    `.get()`으로 조용히 None 넘기지 않고 KeyError로 즉시 드러낸다.
    """
    stmt = select(ValueupScore).where(
        ValueupScore.corp_code == rec["corp_code"],
        ValueupScore.as_of == rec["as_of"],
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        obj = ValueupScore(corp_code=rec["corp_code"], as_of=rec["as_of"])
        session.add(obj)
    for field in (
        "target_roe", "actual_roe", "roe_gap",
        "achievement_rate", "progress_rate", "execution_score", "washing_flag",
        "buyback_executed", "buyback_retired", "buyback_status",
    ):
        setattr(obj, field, rec[field])
    return obj


def latest_as_of(session: Session) -> str | None:
    """valueup_score의 최신 as_of(기본 조회 기준일, 2.4). 없으면 None."""
    from sqlalchemy import func

    return session.scalar(select(func.max(ValueupScore.as_of)))


def list_scores(
    session: Session, filters: dict[str, Any], page: int, size: int
) -> tuple[list[dict[str, Any]], int]:
    """갭분석/워싱랭킹 서빙 조회(2.4). company 조인 + 필터 + execution_score 오름차순.

    null 정렬은 방언(SQLite NULLS FIRST/PG NULLS LAST 기본 차이)을 타지 않도록
    명시적 2단 키(`IS NULL` 우선순위 → 값)로 처리(1.7 defer 교훈). 동순위는 corp_code로
    안정 정렬(페이지네이션 결정성).
    """
    from sqlalchemy import func

    from app.models import Company

    conds = [ValueupScore.as_of == filters["as_of"]]
    # `is not None`: 빈 문자열이 "필터 없음"으로 새지 않게(2-5 리뷰 패리티 — 1차 방어는
    # 라우터 min_length=1의 422)
    if filters.get("market") is not None:
        conds.append(Company.market == filters["market"])
    if filters.get("min_progress") is not None:
        conds.append(ValueupScore.progress_rate >= filters["min_progress"])
    if filters.get("washing_only"):
        conds.append(ValueupScore.washing_flag.is_(True))

    base = select(ValueupScore, Company).join(
        Company, Company.corp_code == ValueupScore.corp_code
    ).where(*conds)

    total = session.scalar(
        select(func.count()).select_from(base.subquery())
    ) or 0
    rows = session.execute(
        base.order_by(
            ValueupScore.execution_score.is_(None),  # null last(명시적)
            ValueupScore.execution_score.asc(),
            ValueupScore.corp_code.asc(),
        ).limit(size).offset((page - 1) * size)
    ).all()

    items = []
    for score, company in rows:
        items.append({
            "corp_code": score.corp_code,
            "corp_name": company.corp_name,
            "market": company.market,
            "as_of": score.as_of,
            "target_roe": score.target_roe,
            "actual_roe": score.actual_roe,
            "roe_gap": score.roe_gap,
            "achievement_rate": score.achievement_rate,
            "progress_rate": score.progress_rate,
            "execution_score": score.execution_score,
            "washing_flag": score.washing_flag,
            "buyback_status": score.buyback_status,
        })
    return items, total


def delete_valueup_score(session: Session, corp_code: str, as_of: str) -> None:
    """plan이 사라진 (corp_code, as_of)의 오래된 score를 정리(코드리뷰 High, GPT: 정합성
    reconciliation). gap_engine이 valueup_score의 유일 writer(AD-4)이므로 근거가 사라진
    행을 제거할 책임도 이 모듈에 있다. 없으면 no-op(멱등)."""
    stmt = select(ValueupScore).where(
        ValueupScore.corp_code == corp_code, ValueupScore.as_of == as_of,
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is not None:
        session.delete(obj)

```

### `app/repositories/metrics.py`

```python
"""valuation_metrics 뷰 조회 저장소 (AD-2: SQL은 여기서만).

뷰(지표) + company(표시·필터) 조인. 필터·정렬·페이지네이션.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

_BASE_SELECT = """
SELECT vm.corp_code, c.corp_name, c.market, c.sector,
       vm.year, vm.quarter, vm.roe, vm.roa, vm.pbr, vm.per, vm.ev_ebitda,
       vm.debt_ratio, vm.payout_ratio, vm.net_cash, vm.ebitda_margin,
       vm.yoy_revenue_growth, vm.yoy_income_growth
FROM valuation_metrics vm
JOIN company c ON c.corp_code = vm.corp_code
"""

# 정렬 허용 컬럼 화이트리스트: 사용자 입력(sort)을 절대 raw로 SQL에 넣지 않는다.
# 키(공개 필드명) → 값(신뢰된 SQL 컬럼). 여기 없는 필드는 거부(인젝션 방어).
SORT_COLUMNS = {
    "corp_code": "vm.corp_code",
    "corp_name": "c.corp_name",
    "market": "c.market",
    "sector": "c.sector",
    "year": "vm.year",
    "quarter": "vm.quarter",
    "roe": "vm.roe",
    "roa": "vm.roa",
    "pbr": "vm.pbr",
    "per": "vm.per",
    "ev_ebitda": "vm.ev_ebitda",
    "debt_ratio": "vm.debt_ratio",
    "payout_ratio": "vm.payout_ratio",
    "net_cash": "vm.net_cash",
    "ebitda_margin": "vm.ebitda_margin",
    "yoy_revenue_growth": "vm.yoy_revenue_growth",
    "yoy_income_growth": "vm.yoy_income_growth",
}
# 페이지네이션 안정성을 위한 결정적 tiebreaker(항상 정렬 끝에 부가).
_TIEBREAK = "vm.corp_code, vm.year, vm.quarter"


def _order_by(sort: str | None) -> str:
    """공통 규약 sort=`field`/`-field`(내림차순)를 화이트리스트로 안전 변환.

    허용되지 않은 필드는 ValueError(라우터가 400으로 변환). raw 문자열 직접 삽입 금지.
    """
    if not sort:
        return f" ORDER BY {_TIEBREAK}"
    desc = sort.startswith("-")
    field = sort[1:] if desc else sort
    col = SORT_COLUMNS.get(field)
    if col is None:
        raise ValueError(f"invalid sort field: {field!r}")
    direction = "DESC" if desc else "ASC"
    return f" ORDER BY {col} {direction}, {_TIEBREAK}"


def _where(filters: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    # `is not None`: 빈 문자열이 "필터 없음"으로 새지 않게(2-5 리뷰 패리티 — 1차 방어는
    # 라우터 min_length=1의 422)
    if filters.get("market") is not None:
        clauses.append("c.market = :market")
        params["market"] = filters["market"]
    if filters.get("sector") is not None:
        clauses.append("c.sector = :sector")
        params["sector"] = filters["sector"]
    if filters.get("max_pbr") is not None:
        clauses.append("vm.pbr <= :max_pbr")
        params["max_pbr"] = filters["max_pbr"]
    if filters.get("min_roe") is not None:
        clauses.append("vm.roe >= :min_roe")
        params["min_roe"] = filters["min_roe"]
    if filters.get("max_debt_ratio") is not None:
        clauses.append("vm.debt_ratio <= :max_debt_ratio")
        params["max_debt_ratio"] = filters["max_debt_ratio"]
    if filters.get("min_payout_ratio") is not None:
        clauses.append("vm.payout_ratio >= :min_payout_ratio")
        params["min_payout_ratio"] = filters["min_payout_ratio"]
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def list_metrics(
    session: Session, filters: dict[str, Any], page: int, size: int,
    sort: str | None = None,
) -> tuple[list[dict], int]:
    where, params = _where(filters)
    order = _order_by(sort)  # 화이트리스트 검증(잘못된 필드는 ValueError)
    total = session.execute(
        text(f"SELECT COUNT(*) FROM valuation_metrics vm JOIN company c "
             f"ON c.corp_code = vm.corp_code{where}"),
        params,
    ).scalar_one()
    rows = session.execute(
        text(_BASE_SELECT + where + order + " LIMIT :limit OFFSET :offset"),
        {**params, "limit": size, "offset": (page - 1) * size},
    ).mappings().all()
    return [dict(r) for r in rows], total


def metrics_by_corp(session: Session, corp_code: str) -> list[dict]:
    rows = session.execute(
        text(_BASE_SELECT + " WHERE vm.corp_code = :cc ORDER BY vm.year, vm.quarter"),
        {"cc": corp_code},
    ).mappings().all()
    return [dict(r) for r in rows]

```

### `tests/test_screening_api.py`

```python
"""Story 2.6 — 다중조건 스크리닝 API 검증 (SQLite in-memory + TestClient)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Company, MnaScore, ValueupScore

AS_OF = "2026-07-13"


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
        ("00000001", "워싱저평가", "KOSPI", "26100"),  # 워싱 의심 + M&A 매력
        ("00000002", "이행양호", "KOSPI", "26200"),    # 실행점수 높음, M&A 매력 낮음
        ("00000003", "밸류업만", "KOSDAQ", "47000"),   # valueup_score만 있음
        ("00000004", "엠앤에이만", "KOSPI", "64110"),  # mna_score만 있음
        ("00000005", "스코어없음", "KOSPI", "10000"),  # 두 스코어 다 없음 → 제외
    ):
        s.add(Company(corp_code=code, corp_name=name, market=market, sector=sector))
    s.add(ValueupScore(
        corp_code="00000001", as_of=AS_OF,
        execution_score=20.0, washing_flag=True,
        buyback_executed=True, buyback_status="purchased_only",
    ))
    s.add(MnaScore(
        corp_code="00000001", as_of=AS_OF,
        mna_target_score=80.0, population_basis="sector:26",
    ))
    s.add(ValueupScore(
        corp_code="00000002", as_of=AS_OF,
        execution_score=95.0, washing_flag=False,
        buyback_executed=False, buyback_status="planned",
    ))
    s.add(MnaScore(
        corp_code="00000002", as_of=AS_OF,
        mna_target_score=30.0, population_basis="sector:26",
    ))
    s.add(ValueupScore(  # buyback_executed=null(판단 불가)
        corp_code="00000003", as_of=AS_OF,
        execution_score=50.0, washing_flag=None,
        buyback_executed=None, buyback_status="unknown",
    ))
    s.add(MnaScore(
        corp_code="00000004", as_of=AS_OF,
        mna_target_score=60.0, population_basis="market_fallback",
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


def test_outer_join_and_universe(client) -> None:
    """AC1: outer join 정직 노출 — 한쪽만 있으면 그쪽만, 둘 다 없으면 제외."""
    r = client.get("/screening")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "total", "page", "size"}
    assert body["total"] == 4  # 00000005(스코어 없음) 제외
    by_code = {i["corp_code"]: i for i in body["items"]}
    assert "00000005" not in by_code
    # valueup만 있는 종목: mna 필드 null
    assert by_code["00000003"]["execution_score"] == 50.0
    assert by_code["00000003"]["mna_target_score"] is None
    # mna만 있는 종목: valueup 필드 null
    assert by_code["00000004"]["mna_target_score"] == 60.0
    assert by_code["00000004"]["execution_score"] is None
    assert by_code["00000004"]["washing_flag"] is None


def test_range_filters_and_combination(client) -> None:
    """AC2: 범위 필터 AND 조합 + null은 범위에 매칭되지 않음."""
    # 실행점수 낮고(워싱 방향) M&A 매력 높은 종목
    r = client.get("/screening", params={
        "max_execution_score": 40, "min_mna_score": 70,
    })
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000001"]
    # min_mna_score=0: mna null(00000003)은 매칭 안 됨
    r2 = client.get("/screening", params={"min_mna_score": 0})
    codes = {i["corp_code"] for i in r2.json()["items"]}
    assert codes == {"00000001", "00000002", "00000004"}


def test_washing_only_and_buyback_filters(client) -> None:
    """AC2: washing_only + buyback_executed(true/false 모두 null 미포함)."""
    r = client.get("/screening", params={"washing_only": True})
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000001"]
    r_true = client.get("/screening", params={"buyback_executed": True})
    assert [i["corp_code"] for i in r_true.json()["items"]] == ["00000001"]
    r_false = client.get("/screening", params={"buyback_executed": False})
    # null(00000003)은 false에도 포함되지 않는다(판단 불가 세탁 금지)
    assert [i["corp_code"] for i in r_false.json()["items"]] == ["00000002"]


def test_sort_whitelist_and_null_last(client) -> None:
    """AC3: field/-field 규약 + null last + 화이트리스트 밖 400 {detail,code}."""
    r = client.get("/screening", params={"sort": "-mna_target_score"})
    codes = [i["corp_code"] for i in r.json()["items"]]
    # 80 → 60 → 30 → null(00000003) last
    assert codes == ["00000001", "00000004", "00000002", "00000003"]
    r2 = client.get("/screening", params={"sort": "execution_score"})
    codes2 = [i["corp_code"] for i in r2.json()["items"]]
    # 20 → 50 → 95 → null(00000004) last
    assert codes2 == ["00000001", "00000003", "00000002", "00000004"]
    r3 = client.get("/screening", params={"sort": "corp_name; DROP TABLE"})
    assert r3.status_code == 400
    assert set(r3.json()) == {"detail", "code"}
    assert r3.json()["code"] == "INVALID_SORT"


def test_market_sector_blank_rejected_and_pagination(client) -> None:
    """AC2/4: market/sector 필터 + 빈 문자열 422 + 페이지네이션."""
    r = client.get("/screening", params={"market": "KOSDAQ"})
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000003"]
    r2 = client.get("/screening", params={"sector": "26"})
    assert {i["corp_code"] for i in r2.json()["items"]} == {"00000001", "00000002"}
    assert client.get("/screening?market=").status_code == 422
    assert client.get("/screening?sector=").status_code == 422
    r3 = client.get("/screening", params={"page": 2, "size": 3})
    assert r3.json()["total"] == 4 and len(r3.json()["items"]) == 1


def test_empty_scores_returns_empty_envelope(engine, monkeypatch) -> None:
    """AC4: 두 스코어 모두 미적재 → 빈 봉투(500 아님)."""
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    r = TestClient(fastapi_app).get("/screening")
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0, "page": 1, "size": 20}


def test_parity_blank_filters_valueup_metrics(client) -> None:
    """AC6[편승]: valueup·metrics 라우터도 빈 필터 422 + 거대 page 422."""
    assert client.get("/valueup/gap-analysis?market=").status_code == 422
    assert client.get("/metrics?market=").status_code == 422
    assert client.get("/metrics?sector=").status_code == 422
    huge = "100000000000000000000"
    assert client.get("/valueup/gap-analysis", params={"page": huge}).status_code == 422
    assert client.get("/metrics", params={"page": huge}).status_code == 422

```
