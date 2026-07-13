"""/stats 라우터 — 시장·매크로 통계 (HTTP 경계, AD-2).

market-comparison·macro는 Page[T] 봉투(AD-6)를 쓰되 실제 페이지네이션 파라미터는 받지
않는다 — 고정 소수 카디널리티(시장 2개·매크로 지표 4개)라 페이지 개념이 없다(3.1 dev notes
근거). summary는 목록이 아니므로 봉투 없이 단일 객체(스코어 미적재 시 404).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
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
    description="시장 구분 없는 전체 헤드라인 KPI. valueup_score 미적재 시 404 {detail,code}.",
)
def summary(
    as_of: date | None = Query(None, description="기준일(YYYY-MM-DD), 기본=valueup_score 최신"),
    db: Session = Depends(get_db),
) -> StatsSummaryOut | JSONResponse:
    result = service.summary(db, as_of.isoformat() if as_of else None)
    if result is None:
        # HTTPException은 main.py 전역 핸들러(RequestValidationError 전용)를 안 타서
        # AD-6 {detail,code} 계약을 벗어난다(GPT 리뷰 Med) — JSONResponse로 직접 맞춘다.
        return JSONResponse(
            status_code=404,
            content={
                "detail": "valueup_score 데이터가 없습니다",
                "code": "VALUEUP_SCORE_NOT_FOUND",
            },
        )
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
