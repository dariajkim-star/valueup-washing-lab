"""valuation_metrics 뷰 조회 저장소 (AD-2: SQL은 여기서만).

뷰(지표) + company(표시·필터) 조인. 필터·정렬·페이지네이션.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

_BASE_SELECT = """
SELECT vm.corp_code, c.corp_name, c.market, c.sector,
       vm.year, vm.quarter, vm.roe, vm.roa, vm.pbr, vm.per, vm.ev_ebit,
       vm.debt_ratio, vm.payout_ratio, vm.net_cash, vm.ebit_margin,
       vm.yoy_revenue_growth, vm.yoy_income_growth
FROM valuation_metrics vm
JOIN company c ON c.corp_code = vm.corp_code
"""

# 정렬 허용 컬럼 화이트리스트: 사용자 입력(sort)을 절대 raw로 SQL에 넣지 않는다.
# 키(공개 필드명) → 값(신뢰된 SQL 컬럼). 여기 없는 필드는 거부(인젝션 방어).
SORT_COLUMNS = {
    "corp_code": "vm.corp_code",
    "corp_name": "c.corp_name",
    "market": "c.market",
    "sector": "c.sector",
    "year": "vm.year",
    "quarter": "vm.quarter",
    "roe": "vm.roe",
    "roa": "vm.roa",
    "pbr": "vm.pbr",
    "per": "vm.per",
    "ev_ebit": "vm.ev_ebit",
    "debt_ratio": "vm.debt_ratio",
    "payout_ratio": "vm.payout_ratio",
    "net_cash": "vm.net_cash",
    "ebit_margin": "vm.ebit_margin",
    "yoy_revenue_growth": "vm.yoy_revenue_growth",
    "yoy_income_growth": "vm.yoy_income_growth",
}
# 페이지네이션 안정성을 위한 결정적 tiebreaker(항상 정렬 끝에 부가).
_TIEBREAK = "vm.corp_code, vm.year, vm.quarter"


def _order_by(sort: str | None) -> str:
    """공통 규약 sort=`field`/`-field`(내림차순)를 화이트리스트로 안전 변환.

    허용되지 않은 필드는 ValueError(라우터가 400으로 변환). raw 문자열 직접 삽입 금지.
    """
    if not sort:
        return f" ORDER BY {_TIEBREAK}"
    desc = sort.startswith("-")
    field = sort[1:] if desc else sort
    col = SORT_COLUMNS.get(field)
    if col is None:
        raise ValueError(f"invalid sort field: {field!r}")
    direction = "DESC" if desc else "ASC"
    return f" ORDER BY {col} {direction}, {_TIEBREAK}"


def _where(filters: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    # `is not None`: 빈 문자열이 "필터 없음"으로 새지 않게(2-5 리뷰 패리티 — 1차 방어는
    # 라우터 min_length=1의 422)
    if filters.get("market") is not None:
        clauses.append("c.market = :market")
        params["market"] = filters["market"]
    if filters.get("sector") is not None:
        clauses.append("c.sector = :sector")
        params["sector"] = filters["sector"]
    if filters.get("max_pbr") is not None:
        clauses.append("vm.pbr <= :max_pbr")
        params["max_pbr"] = filters["max_pbr"]
    if filters.get("min_roe") is not None:
        clauses.append("vm.roe >= :min_roe")
        params["min_roe"] = filters["min_roe"]
    if filters.get("max_debt_ratio") is not None:
        clauses.append("vm.debt_ratio <= :max_debt_ratio")
        params["max_debt_ratio"] = filters["max_debt_ratio"]
    if filters.get("min_payout_ratio") is not None:
        clauses.append("vm.payout_ratio >= :min_payout_ratio")
        params["min_payout_ratio"] = filters["min_payout_ratio"]
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def list_metrics(
    session: Session, filters: dict[str, Any], page: int, size: int,
    sort: str | None = None,
) -> tuple[list[dict], int]:
    where, params = _where(filters)
    order = _order_by(sort)  # 화이트리스트 검증(잘못된 필드는 ValueError)
    total = session.execute(
        text(f"SELECT COUNT(*) FROM valuation_metrics vm JOIN company c "
             f"ON c.corp_code = vm.corp_code{where}"),
        params,
    ).scalar_one()
    rows = session.execute(
        text(_BASE_SELECT + where + order + " LIMIT :limit OFFSET :offset"),
        {**params, "limit": size, "offset": (page - 1) * size},
    ).mappings().all()
    return [dict(r) for r in rows], total


def returns_breakdown(session: Session, corp_code: str) -> list[dict]:
    """연도별 주주환원 구성(2026-08-04, Sally) — 환원율 점프를 구성으로 설명한다.

    총환원율이 갑자기 뛴 종목(에이피알 0%→55.7%)의 "왜"를 화면이 말하려면 분자의
    구성(배당 vs 자사주 취득)이 필요하다. 비율은 여기서 재계산하지 않고
    **valuation_metrics 뷰에서 조인**한다 — 정의처는 뷰 하나다(0026 단위 정정 이래).
    사업보고서(quarter=4) 행만 준다: 배당·CF취득은 연 단위 사실이라 분기 행은 소음이다.
    소각은 buyback_retired_amount(**수량, 주**) — 금액이 아니라는 것을 필드명이 말한다.
    """
    rows = session.execute(
        text(
            "SELECT f.year, f.dividend_total, f.buyback_amount_krw, "
            "f.buyback_retired_amount AS buyback_retired_qty, "
            "f.buyback_retired_krw, f.net_income, "
            "vm.total_return_ratio, vm.payout_ratio, "
            "vm.retired_return_ratio, vm.retirement_rate "
            "FROM financials f "
            "LEFT JOIN valuation_metrics vm "
            "ON vm.corp_code = f.corp_code AND vm.year = f.year AND vm.quarter = f.quarter "
            "WHERE f.corp_code = :cc AND f.quarter = 4 ORDER BY f.year"
        ),
        {"cc": corp_code},
    ).mappings().all()
    return [dict(r) for r in rows]


def metrics_by_corp(session: Session, corp_code: str) -> list[dict]:
    rows = session.execute(
        text(_BASE_SELECT + " WHERE vm.corp_code = :cc ORDER BY vm.year, vm.quarter"),
        {"cc": corp_code},
    ).mappings().all()
    return [dict(r) for r in rows]
