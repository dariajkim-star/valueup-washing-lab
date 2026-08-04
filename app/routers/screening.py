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
        "워싱·저평가·M&A 후보 양방향 스크리닝(valueup_score + mna_score + opacity_score "
        "outer join). "
        "washing_flag: null=판단 불가(빈칸/아니오 표시 금지). "
        "mna_target_score: null=산출 불가(0점/최하위 표시 금지). "
        "opacity_rank: 공시 불투명도 백분위(0~1, 높을수록 불투명, washing_flag 대체). "
        "null=순위 불가(계획 미공시·본문 4축 전무·peer 부족 — 0/최투명 표시 금지). "
        "min/max_opacity_rank 필터가 구 washing_only를 대체한다(그 토글은 washing_flag "
        "실측 True=0이라 항상 빈 결과였다). "
        "buyback_executed 필터: true/false 모두 null(판단 불가)은 미포함. "
        "sort: `field`/`-field` 규약, 허용=execution_score·mna_target_score·opacity_rank"
        "(기본=corp_code). "
        "범위 필터는 null을 매칭하지 않는다(산출 불가는 조건 판단 불가). "
        "look-ahead: 지표는 **실제 공시일**(사업보고서 rcept_dt) 기준으로 차단한다"
        "(2026-08-04, 커버리지 706/706). 공시일 미수집 행만 연도 휴리스틱으로 폴백. "
        "남은 한계: 시총 필터는 최신가 기준(point-in-time 아님)."
    ),
)
def screening_list(
    # 3.4 상세화면 단건 조회용(정확일치, 8자리)
    corp_code: str | None = Query(None, min_length=8, max_length=8, pattern=r"^\d{8}$"),
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
    max_ev_ebit: float | None = Query(None, allow_inf_nan=False),
    max_debt_ratio: float | None = Query(None, allow_inf_nan=False),
    # 시총구간 필터(KRW 원) — prices 최신 시총 기준(AD-9)
    min_market_cap: int | None = Query(None, ge=0),
    max_market_cap: int | None = Query(None, ge=0),
    # 불투명도 범위 필터(AC2) — 구 washing_only 대체. washing_flag는 실측 True=0이라
    # 그 토글이 항상 빈 결과를 냈다(죽은 필터). 고의 판정 대신 격차로 거른다.
    min_opacity_rank: float | None = Query(None, ge=0.0, le=1.0, allow_inf_nan=False),
    max_opacity_rank: float | None = Query(None, ge=0.0, le=1.0, allow_inf_nan=False),
    # 목표 야심도 필터(P1-7): 자기 과거 대비 격차가 이 값 이하인 기업만.
    # 0을 주면 "하던 것만큼도 약속하지 않은" 기업이 남는다. 기준선이 없는 기업은
    # 산출 불가라 매칭되지 않는다(범위 필터 전반의 null 계약과 같다).
    max_own_gap: float | None = Query(
        None, allow_inf_nan=False,
        description="자기 과거 대비 목표 격차(%p) 상한 — 0이면 '하던 것보다 낮은 목표'",
    ),
    buyback_executed: bool | None = Query(
        None, description="true=매입 실행 / false=미실행 — null(판단 불가)은 양쪽 다 제외"
    ),
    # '매입만·소각 0' 필터(2026-08-04): buyback_status=purchased_only + min_total_return
    # 조합이 "환원율은 높은데 소각 기준으론 0"을 뽑는다(scoring.md 의도된 이중 시선).
    buyback_status: str | None = Query(
        None, pattern=r"^(retired|purchased_only|none|unknown)$",
        description="소각 3단계 상태 정확일치 — purchased_only=매입만·소각 0",
    ),
    min_total_return: float | None = Query(
        None, allow_inf_nan=False,
        description="총주주환원율(%) 하한 — 최신 지표 기준, null은 매칭 안 됨",
    ),
    sort: str | None = Query(
        None,
        description="execution_score | mna_target_score | opacity_rank, `-` 내림차순",
    ),
    as_of: date | None = Query(None, description="기준일(YYYY-MM-DD), 기본=최신 실행 시점"),
    page: int = Query(1, ge=1, le=1_000_000),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[ScreeningOut] | JSONResponse:
    filters = {
        "corp_code": corp_code, "market": market, "sector": sector,
        "min_execution_score": min_execution_score,
        "max_execution_score": max_execution_score,
        "min_mna_score": min_mna_score, "max_mna_score": max_mna_score,
        "min_roe": min_roe, "max_pbr": max_pbr,
        "max_ev_ebit": max_ev_ebit, "max_debt_ratio": max_debt_ratio,
        "min_market_cap": min_market_cap, "max_market_cap": max_market_cap,
        "min_opacity_rank": min_opacity_rank, "max_opacity_rank": max_opacity_rank,
        "max_own_gap": max_own_gap,
        "buyback_executed": buyback_executed,
        "buyback_status": buyback_status,
        "min_total_return": min_total_return,
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
