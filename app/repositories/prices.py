"""prices 멱등 upsert 저장소 (수집 경로 전용). 자연키 (corp_code, date), AD-7."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Price


def upsert_price(session: Session, rec: dict) -> Price:
    """(corp_code, date) 기준 price upsert. None 값은 기존값을 덮지 않는다."""
    stmt = select(Price).where(
        Price.corp_code == rec["corp_code"], Price.date == rec["date"]
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        obj = Price(corp_code=rec["corp_code"], date=rec["date"])
        session.add(obj)
    for field in ("close", "volume", "trading_value", "market_cap"):
        if rec.get(field) is not None:
            setattr(obj, field, rec[field])
    return obj
