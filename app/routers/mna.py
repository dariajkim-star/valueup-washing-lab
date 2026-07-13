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
    # min_length=1: 빈 문자열(?market=)이 "필터 없음"으로 조용히 확대되지 않게 422
    # (2-5 GPT 리뷰 Med — 정확일치/prefix 계약상 빈 값은 무효 입력)
    market: str | None = Query(None, min_length=1),
    sector: str | None = Query(
        None, min_length=1, pattern=r"^\d{2,5}$",
        description="KSIC 업종코드 prefix(예: 26, 64)",
    ),
    # date 타입 = FastAPI가 달력 검증(2026-02-30/garbage → 422, 2.4 일괄리뷰 교훈)
    as_of: date | None = Query(None, description="기준일(YYYY-MM-DD), 기본=최신"),
    # page 상한: 무제한 int가 OFFSET 64비트 초과 → 500이 되는 것을 422로 차단(GPT 리뷰 Med)
    page: int = Query(1, ge=1, le=1_000_000),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[MnaRankingOut]:
    filters = {"market": market, "sector": sector,
               "as_of": as_of.isoformat() if as_of else None}
    return service.ranking(db, filters, page, size)
