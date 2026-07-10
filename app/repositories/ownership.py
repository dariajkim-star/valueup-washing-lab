"""ownership 멱등 upsert 저장소.

수집 경로 전용(서빙 아님). 자연키 (corp_code, as_of) 기준으로 존재하면 갱신,
없으면 삽입 → 재실행 안전(AD-7). None은 기존 non-null을 덮지 않는다(1.2 패턴).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Ownership


def upsert_ownership(session: Session, rec: dict) -> Ownership:
    """(corp_code, as_of) 자연키 기준 ownership upsert."""
    stmt = select(Ownership).where(
        Ownership.corp_code == rec["corp_code"],
        Ownership.as_of == rec["as_of"],
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        obj = Ownership(corp_code=rec["corp_code"], as_of=rec["as_of"])
        session.add(obj)
    # 값 필드는 None이 아닐 때만 갱신(일시적 미공시로 기존값 소실 방지)
    for field in ("largest_shareholder_pct", "treasury_stock_pct"):
        if rec.get(field) is not None:
            setattr(obj, field, rec[field])
    return obj
