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
    market: str | None = None,
    min_progress: float | None = Query(None, ge=0.0, le=1.0),
    # date 타입 = FastAPI가 달력 검증(2026-02-30/garbage → 422, 일괄리뷰 Med — 빈 200으로
    # "데이터 없음"과 "잘못된 요청"이 섞이지 않게)
    as_of: date | None = Query(None, description="기준일(YYYY-MM-DD), 기본=최신"),
    page: int = Query(1, ge=1),
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
    market: str | None = None,
    min_progress: float | None = Query(None, ge=0.0, le=1.0),
    # date 타입 = FastAPI가 달력 검증(2026-02-30/garbage → 422, 일괄리뷰 Med — 빈 200으로
    # "데이터 없음"과 "잘못된 요청"이 섞이지 않게)
    as_of: date | None = Query(None, description="기준일(YYYY-MM-DD), 기본=최신"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[GapAnalysisOut]:
    filters = {"market": market, "min_progress": min_progress,
               "as_of": as_of.isoformat() if as_of else None}
    return service.washing_ranking(db, filters, page, size)
