"""시장·매크로 통계 조회 저장소 (AD-2: SQL은 여기서만).

`valuation_metrics` VIEW·`valueup_score`·`macro_indicator`를 **읽기만**(각 writer는
어댑터/엔진, AD-4/AD-7/AD-10 불변). look-ahead 안전 최신 지표 조회는 2.1/2.3(gap_engine·
mna_engine)의 SQL 패턴을 재사용하되, 완료된 Epic 2 파일(`mna_score.py`)은 건드리지 않고
이 모듈에 독립 작성한다(blast radius 격리, 3번째 소비자가 생기면 공통 헬퍼로 추출 검토).
"""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import bindparam, func, select, text
from sqlalchemy.orm import Session

from app.models import Company, MacroIndicator, ValueupScore

# macro_indicator CHECK 제약과 동일한 고정 화이트리스트(app/models.py:MacroIndicator).
# 관측이 없어도 이 4개 자리는 항상 보장 — "지표 자체가 없음"과 "아직 값이 없음"을 구분.
MACRO_INDICATORS = ("base_rate", "bond_3y", "usd_krw", "leading_index")

# 이 스토리(AC1)가 다루는 시장은 KOSPI/KOSDAQ뿐 — `Company.market`은 nullable이고
# KONEX·기타 값도 들어올 수 있어(GPT 리뷰 High), 명시적으로 필터하지 않으면 None 키가
# 정렬(`sorted`)에서 TypeError를 내거나 계약 밖 시장이 응답에 새어나간다.
SUPPORTED_MARKETS = ("KOSPI", "KOSDAQ")


def _finite_or_none(value: float | None) -> float | None:
    """NaN/Infinity는 null로 정규화(GPT 리뷰 Med) — JSON 직렬화 500·방언별 특수값 차이 방지."""
    if value is None:
        return None
    return value if math.isfinite(value) else None


def _latest_metrics_by_market(session: Session, as_of: str) -> dict[str, list[dict[str, Any]]]:
    """as_of 시점 look-ahead 안전 최신 1건/종목의 roe·pbr·ev_ebitda를 market별로 묶는다.

    2.1/2.3과 동일한 사업보고서 배제 규칙(`year<yr OR (year=yr AND quarter<4)`).
    corp별 최신행 선택은 DISTINCT ON(PostgreSQL 전용) 대신 정렬 후 Python dedupe —
    SQLite/PostgreSQL 양쪽 이식성(1.7 known-limitation 컨벤션).
    """
    as_of_year = int(as_of[:4])
    rows = session.execute(
        text(
            "SELECT vm.corp_code, c.market, vm.roe, vm.pbr, vm.ev_ebitda, vm.year, vm.quarter "
            "FROM valuation_metrics vm JOIN company c ON c.corp_code = vm.corp_code "
            "WHERE (vm.year < :yr OR (vm.year = :yr AND vm.quarter < 4)) "
            "AND c.market IN :markets "
            "ORDER BY vm.corp_code, vm.year DESC, vm.quarter DESC"
        ).bindparams(bindparam("markets", expanding=True)),
        {"yr": as_of_year, "markets": list(SUPPORTED_MARKETS)},
    ).mappings().all()

    latest_per_corp: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = row["corp_code"]
        if code not in latest_per_corp:  # 정렬상 corp별 첫 행 = 최신
            latest_per_corp[code] = row

    by_market: dict[str, list[dict[str, Any]]] = {}
    for rec in latest_per_corp.values():
        by_market.setdefault(rec["market"], []).append(rec)
    return by_market


def _avg(values: list[float | None]) -> float | None:
    """null-safe 평균 — None·NaN·Infinity는 전부 제외(GPT 리뷰 Med), 유효값이 하나도
    없으면 None(0으로 나누지 않음)."""
    valid = [v for v in values if v is not None and math.isfinite(v)]
    if not valid:
        return None
    return sum(valid) / len(valid)


def _washing_counts_by_market(
    session: Session, as_of: str
) -> dict[str, tuple[int, int]]:
    """as_of 스냅샷의 시장별 (n_judged, n_washing). judged=washing_flag IS NOT NULL.

    SQL 집계(COUNT/CASE) 대신 Python에서 세는 이유: 결과 행 수가 종목 수 규모(수십~수백)에
    불과해 성능 문제가 없고, 방언별 boolean 집계 표현 차이(SQLite/PostgreSQL)를 피한다.
    """
    stmt = (
        select(Company.market, ValueupScore.washing_flag)
        .join(ValueupScore, ValueupScore.corp_code == Company.corp_code)
        .where(ValueupScore.as_of == as_of, Company.market.in_(SUPPORTED_MARKETS))
    )
    counts: dict[str, tuple[int, int]] = {}
    for market, washing_flag in session.execute(stmt).all():
        n_judged, n_washing = counts.get(market, (0, 0))
        if washing_flag is not None:
            n_judged += 1
            if washing_flag:
                n_washing += 1
        counts[market] = (n_judged, n_washing)
    return counts


def market_comparison(session: Session, as_of: str) -> list[dict[str, Any]]:
    """시장별(KOSPI/KOSDAQ) n·avg_roe·avg_pbr·avg_ev_ebitda·washing_ratio(2.4~2.6과 동일
    look-ahead·null 계약). 데이터 없는 시장은 행 자체를 만들지 않는다(all-null 행 금지)."""
    by_market = _latest_metrics_by_market(session, as_of)
    washing = _washing_counts_by_market(session, as_of)

    markets = sorted(set(by_market) | set(washing))
    items = []
    for market in markets:
        recs = by_market.get(market, [])
        n_judged, n_washing = washing.get(market, (0, 0))
        items.append({
            "market": market,
            "n": len(recs),
            "avg_roe": _avg([r["roe"] for r in recs]),
            "avg_pbr": _avg([r["pbr"] for r in recs]),
            "avg_ev_ebitda": _avg([r["ev_ebitda"] for r in recs]),
            "n_judged": n_judged,
            "n_washing": n_washing,
            "washing_ratio": (n_washing / n_judged) if n_judged > 0 else None,
        })
    return items


def summary(session: Session, as_of: str) -> dict[str, Any]:
    """시장 구분 없는 전체 헤드라인 KPI."""
    by_market = _latest_metrics_by_market(session, as_of)
    all_recs = [r for recs in by_market.values() for r in recs]
    washing = _washing_counts_by_market(session, as_of)
    n_judged = sum(j for j, _ in washing.values())
    n_washing = sum(w for _, w in washing.values())
    n_companies = session.scalar(select(func.count()).select_from(Company)) or 0

    return {
        "as_of": as_of,
        "n_companies": n_companies,
        "n_metrics": len(all_recs),
        "avg_roe": _avg([r["roe"] for r in all_recs]),
        "avg_pbr": _avg([r["pbr"] for r in all_recs]),
        "avg_ev_ebitda": _avg([r["ev_ebitda"] for r in all_recs]),
        "n_judged": n_judged,
        "n_washing": n_washing,
        "washing_ratio": (n_washing / n_judged) if n_judged > 0 else None,
    }


def latest_macro_as_of(session: Session) -> str | None:
    """macro_indicator 자체의 최신 관측일. market-comparison/summary의 as_of(valueup_score
    기반)와 독립 — 서로 다른 데이터 계열이라 각자의 최신값을 기본으로 삼는다(AD-8 정신:
    시스템 시계 대신 데이터 기반 기본값)."""
    return session.scalar(select(func.max(MacroIndicator.date)))


def macro_snapshot(session: Session, as_of: str) -> list[dict[str, Any]]:
    """4개 매크로 지표 각각의 as_of 이전 최신 관측. 관측이 없으면 date/value null이되
    지표 자리 자체는 항상 4개 보장(고정 화이트리스트 순회)."""
    result: dict[str, dict[str, Any]] = {
        ind: {"indicator": ind, "date": None, "value": None} for ind in MACRO_INDICATORS
    }
    stmt = (
        select(MacroIndicator)
        .where(MacroIndicator.indicator.in_(MACRO_INDICATORS), MacroIndicator.date <= as_of)
        .order_by(MacroIndicator.indicator, MacroIndicator.date.desc())
    )
    seen: set[str] = set()
    for obj in session.scalars(stmt):
        if obj.indicator in seen:
            continue
        seen.add(obj.indicator)
        result[obj.indicator] = {
            "indicator": obj.indicator, "date": obj.date,
            "value": _finite_or_none(obj.value),
        }
    return [result[ind] for ind in MACRO_INDICATORS]
