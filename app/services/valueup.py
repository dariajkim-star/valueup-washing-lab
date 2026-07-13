"""갭분석/워싱랭킹 유스케이스 (routers→services→repositories, AD-2)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.repositories import valueup_score as repo
from app.schemas import GapAnalysisOut, Page


def _resolve_as_of(session: Session, as_of: str | None) -> str | None:
    return as_of or repo.latest_as_of(session)


def gap_analysis(
    session: Session, filters: dict[str, Any], page: int, size: int
) -> Page[GapAnalysisOut]:
    filters["as_of"] = _resolve_as_of(session, filters.get("as_of"))
    if filters["as_of"] is None:  # 스코어 미적재 → 빈 봉투(500 아님)
        return Page(items=[], total=0, page=page, size=size)
    rows, total = repo.list_scores(session, filters, page, size)
    return Page(items=[GapAnalysisOut(**r) for r in rows], total=total, page=page, size=size)


def washing_ranking(
    session: Session, filters: dict[str, Any], page: int, size: int
) -> Page[GapAnalysisOut]:
    return gap_analysis(session, {**filters, "washing_only": True}, page, size)
