"""/valueup 라우터 — 갭분석·워싱랭킹 (HTTP 경계, AD-2)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Company
from app.schemas import GapAnalysisOut, Page, RefreshOut
from app.services import refresh as refresh_service
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
    # 3.4 상세화면 단건 조회용(정확일치, 8자리)
    corp_code: str | None = Query(None, min_length=8, max_length=8, pattern=r"^\d{8}$"),
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
    filters = {"corp_code": corp_code, "market": market, "min_progress": min_progress,
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


@router.post(
    "/refresh/{corp_code}",
    response_model=RefreshOut,
    description=(
        "해당 종목의 밸류업 공시를 DART에서 다시 받아 valueup_plan을 갱신하고(rcept_no 포함) "
        "점수를 재계산한다. **불투명도 순위는 전 종목이 함께 재계산된다** — opacity_rank는 "
        "모집단 백분위라 한 종목만 갱신하면 서로 다른 모집단 기준의 등수가 섞이기 때문. "
        "외부 API(DART) 호출이 포함돼 수 초 이상 걸릴 수 있다."
    ),
)
def refresh_company(
    corp_code: str = Path(min_length=8, max_length=8, pattern=r"^\d{8}$"),
    as_of: date | None = Query(None, description="재채점 기준일(YYYY-MM-DD), 기본=오늘"),
    db: Session = Depends(get_db),
) -> RefreshOut:
    # 존재하지 않는 종목에 DART 호출을 낭비하지 않는다(그리고 404가 200 빈 결과보다 정직하다)
    if db.get(Company, corp_code) is None:
        raise HTTPException(status_code=404, detail=f"종목을 찾을 수 없습니다: {corp_code}")
    r = refresh_service.refresh_company(corp_code, as_of.isoformat() if as_of else None)
    return RefreshOut(**vars(r), complete=r.complete)
