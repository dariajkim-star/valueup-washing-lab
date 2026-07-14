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
    # 지표 범위 필터(3.3 리뷰 반영, AC2) — null 지표는 어느 범위에도 매칭 안 됨
    min_roe: float | None = Query(None, allow_inf_nan=False),
    max_pbr: float | None = Query(None, allow_inf_nan=False),
    max_ev_ebitda: float | None = Query(None, allow_inf_nan=False),
    max_debt_ratio: float | None = Query(None, allow_inf_nan=False),
    # 시총구간 필터(KRW 원) — prices 최신 시총 기준(AD-9)
    min_market_cap: int | None = Query(None, ge=0),
    max_market_cap: int | None = Query(None, ge=0),
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
        "min_roe": min_roe, "max_pbr": max_pbr,
        "max_ev_ebitda": max_ev_ebitda, "max_debt_ratio": max_debt_ratio,
        "min_market_cap": min_market_cap, "max_market_cap": max_market_cap,
        "washing_only": washing_only, "buyback_executed": buyback_executed,
        "as_of": as_of.isoformat() if as_of else None,
    }
    try:
        return service.screening(db, filters, page, size, sort)
    except service.InvalidSortError as e:
        # 전용 예외만 400 — 광범위 ValueError를 잡으면 pydantic ValidationError(내부
        # 오류)까지 INVALID_SORT로 세탁돼 장애가 숨는다(GPT 리뷰 Med). 그 외는 500으로.
        return JSONResponse(
            status_code=400, content={"detail": str(e), "code": "INVALID_SORT"}
        )
