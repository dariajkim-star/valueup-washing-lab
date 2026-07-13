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
