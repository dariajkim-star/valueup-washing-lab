"""company / financials 멱등 upsert 저장소.

수집 경로 전용(서빙 아님). 자연키 기준으로 존재하면 갱신, 없으면 삽입 → 재실행 안전(AD-7).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Financial


def upsert_company(session: Session, rec: dict) -> Company:
    """corp_code 기준 company upsert. 소스에서 값이 None이면 기존 값을 덮어쓰지 않는다
    (일시적 응답 누락으로 정상 데이터가 삭제되는 것 방지)."""
    obj = session.get(Company, rec["corp_code"])
    if obj is None:
        obj = Company(corp_code=rec["corp_code"], corp_name=rec.get("corp_name") or "")
        session.add(obj)
    for field in ("stock_code", "corp_name", "market", "sector"):
        val = rec.get(field)
        if val is not None:
            setattr(obj, field, val)
    return obj


def upsert_financial(session: Session, rec: dict) -> Financial:
    """(corp_code, year, quarter) 자연키 기준 financials upsert."""
    stmt = select(Financial).where(
        Financial.corp_code == rec["corp_code"],
        Financial.year == rec["year"],
        Financial.quarter == rec["quarter"],
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        obj = Financial(
            corp_code=rec["corp_code"], year=rec["year"], quarter=rec["quarter"]
        )
        session.add(obj)
    # fs_div(연결/개별 출처)는 항상 반영
    if "fs_div" in rec:
        obj.fs_div = rec["fs_div"]
    # 값 필드는 None이 아닌 경우에만 갱신 — 매핑 실패로 기존 non-null이 지워지지 않게
    for field in (
        "revenue", "net_income", "operating_income", "depreciation",
        "equity", "total_assets", "total_liabilities", "cash", "total_debt",
        "dividend_total", "buyback_amount", "buyback_retired_amount",
    ):
        if rec.get(field) is not None:
            setattr(obj, field, rec[field])
    return obj
