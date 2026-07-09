"""macro_indicator 멱등 upsert (수집 경로 전용). 자연키 (indicator, date), AD-7."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MacroIndicator


def upsert_macro(session: Session, rec: dict) -> MacroIndicator:
    """(indicator, date) 기준 upsert. value None은 기존값을 덮지 않는다."""
    stmt = select(MacroIndicator).where(
        MacroIndicator.indicator == rec["indicator"],
        MacroIndicator.date == rec["date"],
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        obj = MacroIndicator(indicator=rec["indicator"], date=rec["date"])
        session.add(obj)
    if rec.get("value") is not None:
        obj.value = rec["value"]
    if rec.get("frequency") is not None:
        obj.frequency = rec["frequency"]
    return obj
