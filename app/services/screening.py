"""다중조건 스크리닝 유스케이스 (routers→services→repositories, AD-2)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.repositories import screening as repo
from app.repositories.screening import InvalidSortError  # 라우터가 잡을 전용 예외 재노출
from app.schemas import Page, ScreeningOut

__all__ = ["screening", "InvalidSortError"]


def screening(
    session: Session, filters: dict[str, Any], page: int, size: int,
    sort: str | None = None,
) -> Page[ScreeningOut]:
    # sort 선검증(순수 함수, DB 무관): 스코어 미적재 short-circuit보다 먼저 —
    # 빈 DB에서도 잘못된 sort는 200이 아니라 400이어야 한다(GPT 리뷰 Med).
    repo.validate_sort(sort)
    filters["as_of"] = filters.get("as_of") or repo.latest_as_of(session)
    if filters["as_of"] is None:  # 두 스코어 모두 미적재 → 빈 봉투(500 아님)
        return Page(items=[], total=0, page=page, size=size)
    rows, total = repo.list_screening(session, filters, page, size, sort)
    return Page(items=[ScreeningOut(**r) for r in rows], total=total, page=page, size=size)
