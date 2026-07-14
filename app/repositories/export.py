"""Tableau export 조회 저장소 (AD-2: SQL은 여기서만).

모든 함수는 **읽기 전용** SELECT(AD-4/AD-10의 writer 제약과 직교). 파생지표는
`valuation_metrics` VIEW를 SELECT할 뿐 재계산하지 않는다(AD-1). 스코어 계열은
호출자가 넘긴 **단일 as_of**의 행만 조회 — 뷰별 CSV가 서로 다른 기준일로 뽑혀
대시보드에서 시점이 섞이는 것(3.4 리뷰 High와 같은 함정)을 저장소 계약으로 차단.

look-ahead 최신 지표는 screening/stats와 동일한 "부분 차단" 규칙
(`year < yr OR (year = yr AND quarter < 4)`) — 규칙이 엔드포인트 간 갈라지면
CSV와 API 수치 패리티가 깨진다(이 스토리 AC의 검증 축).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import Company, MacroIndicator, MnaScore, ValueupScore


def latest_common_as_of(session: Session) -> str | None:
    """두 엔진 **모두** 실행된 최신 as_of(교집합 max). 없으면 None.

    screening의 latest_as_of(두 max 중 큰 쪽)는 API에선 옳지만 — 없는 쪽이
    null로 정직 노출됨 — 정적 export에선 한 엔진 CSV가 통째로 0행이 되며
    조용히 성공한다(GPT 리뷰 High). export는 교집합 기준일만 쓴다.
    """
    return session.scalar(
        select(func.max(ValueupScore.as_of)).where(
            ValueupScore.as_of.in_(select(MnaScore.as_of).distinct())
        )
    )


def engine_latest_as_of(session: Session) -> dict[str, str | None]:
    """엔진별 개별 최신 as_of — 교집합보다 최신인 엔진이 있으면 호출자가
    "그 데이터는 이번 스냅숏에 없다"고 경고하기 위한 조회(조용한 과거 후퇴 방지)."""
    return {
        "valueup": session.scalar(select(func.max(ValueupScore.as_of))),
        "mna": session.scalar(select(func.max(MnaScore.as_of))),
    }


def as_of_exists_in_both(session: Session, as_of: str) -> dict[str, bool]:
    """명시 as_of가 두 엔진에 실재하는지 — --as-of 오버라이드 검증용."""
    return {
        "valueup": session.scalar(
            select(func.count()).where(ValueupScore.as_of == as_of)
        ) > 0,
        "mna": session.scalar(
            select(func.count()).where(MnaScore.as_of == as_of)
        ) > 0,
    }


def _latest_metrics_map(session: Session, as_of: str) -> dict[str, dict[str, Any]]:
    """corp별 look-ahead 부분 차단 최신 지표 행(전 컬럼). screening._latest_metrics_map과
    같은 규칙이지만 산점도·업종맵이 쓰는 컬럼이 더 넓어(year·quarter 포함) 독립 작성
    (시그니처가 소비자마다 다른 look-ahead 패턴 5번째 사용처 — 공통화는 deferred-work 기존 항목).
    """
    as_of_year = int(as_of[:4])
    rows = session.execute(
        text(
            "SELECT corp_code, year, quarter, roe, pbr, per, ev_ebitda, debt_ratio, "
            "payout_ratio FROM valuation_metrics "
            "WHERE year < :yr OR (year = :yr AND quarter < 4) "
            "ORDER BY corp_code, year DESC, quarter DESC"
        ),
        {"yr": as_of_year},
    ).mappings().all()
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["corp_code"] not in latest:  # 정렬상 corp별 첫 행 = 최신
            latest[row["corp_code"]] = dict(row)
    return latest


def _companies(session: Session) -> list[dict[str, Any]]:
    """company 4컬럼 전체(corp_code 정렬). 뷰 2·3·4가 공유 — 호출자(export_all)가
    한 번 조회해 주입할 수 있게 분리(같은 쿼리 3회 반복 제거)."""
    return [
        dict(r)
        for r in session.execute(
            select(Company.corp_code, Company.corp_name, Company.market, Company.sector)
            .order_by(Company.corp_code)
        ).mappings()
    ]


def valueup_scores_rows(session: Session, as_of: str) -> list[dict[str, Any]]:
    """뷰 1(밸류업 점수): valueup_score(as_of 고정) ⋈ company."""
    rows = session.execute(
        select(
            Company.corp_code, Company.corp_name, Company.market, Company.sector,
            ValueupScore.as_of, ValueupScore.execution_score,
            ValueupScore.achievement_rate, ValueupScore.progress_rate,
            ValueupScore.washing_flag, ValueupScore.buyback_status,
        )
        .join(ValueupScore, ValueupScore.corp_code == Company.corp_code)
        .where(ValueupScore.as_of == as_of)
        .order_by(Company.corp_code)
    ).mappings().all()
    return [dict(r) for r in rows]


def sector_valuation_rows(
    session: Session,
    as_of: str,
    metrics: dict[str, dict[str, Any]] | None = None,
    companies: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """뷰 2(업종별 저평가 맵): 최신 지표 ⋈ company ⋈ mna_score(as_of 고정).

    mna_score가 없는 종목(미지원 업종 등)도 지표가 있으면 행을 남기고 스코어는
    빈 값 — null을 조인으로 감추지 않는다(스크리닝 저장소와 같은 정직 노출).
    metrics/companies는 호출자가 미리 조회해 주입 가능(뷰 간 중복 쿼리 제거) —
    미주입 시 자체 조회(단독 사용 호환).
    """
    if metrics is None:
        metrics = _latest_metrics_map(session, as_of)
    if companies is None:
        companies = _companies(session)
    mna = {
        r["corp_code"]: r
        for r in session.execute(
            select(
                MnaScore.corp_code, MnaScore.mna_target_score,
                MnaScore.valuation_score, MnaScore.population_basis,
            ).where(MnaScore.as_of == as_of)
        ).mappings()
    }
    out: list[dict[str, Any]] = []
    for c in companies:
        m = metrics.get(c["corp_code"])
        if m is None:  # 지표 자체가 없는 종목은 맵에 놓을 수치가 없음
            continue
        s = mna.get(c["corp_code"], {})
        out.append({
            "corp_code": c["corp_code"], "corp_name": c["corp_name"],
            "market": c["market"], "sector": c["sector"], "as_of": as_of,
            "metrics_year": m["year"], "metrics_quarter": m["quarter"],
            "pbr": m["pbr"], "per": m["per"], "ev_ebitda": m["ev_ebitda"],
            "mna_target_score": s.get("mna_target_score"),
            "valuation_score": s.get("valuation_score"),
            "population_basis": s.get("population_basis"),
        })
    return out


def roe_pbr_rows(
    session: Session,
    as_of: str,
    metrics: dict[str, dict[str, Any]] | None = None,
    companies: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """뷰 3(ROE-PBR 산점도): 최신 지표 ⋈ company ⋈ valueup_score(as_of 고정, 색·모양 인코딩용).
    metrics/companies 주입 규약은 sector_valuation_rows와 동일."""
    if metrics is None:
        metrics = _latest_metrics_map(session, as_of)
    if companies is None:
        companies = _companies(session)
    vs = {
        r["corp_code"]: r
        for r in session.execute(
            select(
                ValueupScore.corp_code, ValueupScore.execution_score,
                ValueupScore.washing_flag,
            ).where(ValueupScore.as_of == as_of)
        ).mappings()
    }
    out: list[dict[str, Any]] = []
    for c in companies:
        m = metrics.get(c["corp_code"])
        if m is None or (m["roe"] is None and m["pbr"] is None):
            continue  # 산점도에 놓을 좌표가 전혀 없는 행은 제외(한 축만 null이면 유지 — Tableau가 축별 제외)
        s = vs.get(c["corp_code"], {})
        out.append({
            "corp_code": c["corp_code"], "corp_name": c["corp_name"],
            "market": c["market"], "sector": c["sector"], "as_of": as_of,
            "metrics_year": m["year"], "metrics_quarter": m["quarter"],
            "roe": m["roe"], "pbr": m["pbr"],
            "execution_score": s.get("execution_score"),
            "washing_flag": s.get("washing_flag"),
        })
    return out


def period_buyback_status(
    buyback_amount: int | None, buyback_retired_amount: int | None
) -> str | None:
    """해당 기간의 자사주 상태를 그 기간의 원천 수량에서 계산.

    현재 스냅숏의 ValueupScore.buyback_status를 과거 전 연도에 반복하면
    "2023년에도 소각했다"로 오독된다(GPT 리뷰 High) — 시계열 뷰의 상태는
    반드시 그 행의 기간 데이터에서 나와야 한다. 둘 다 관측 없음(null)이면
    null — "활동 없음(none)"과 "관측 없음"을 구분(1.8 계보).
    """
    if buyback_retired_amount is not None and buyback_retired_amount > 0:
        return "retired"
    if buyback_amount is not None and buyback_amount > 0:
        return "purchased_only"
    if buyback_amount is not None or buyback_retired_amount is not None:
        return "none"
    return None


def dividend_buyback_rows(
    session: Session,
    as_of: str,
    companies: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """뷰 4(배당/자사주): financials 연도별 환원 원천 + valuation_metrics.payout_ratio.
    시계열 축(year)을 가진 유일한 뷰 — look-ahead 규칙은 지표 뷰와 동일하게
    적용(같은 해 사업보고서 배제). 기간별 상태는 period_buyback_status로 계산
    (스냅숏 상태의 시계열 반복 금지). companies 주입 규약은 뷰 2·3과 동일.
    """
    as_of_year = int(as_of[:4])
    fin = session.execute(
        text(
            "SELECT f.corp_code, f.year, f.quarter, f.dividend_total, "
            "f.buyback_amount, f.buyback_retired_amount, vm.payout_ratio "
            "FROM financials f "
            "LEFT JOIN valuation_metrics vm ON vm.corp_code = f.corp_code "
            "AND vm.year = f.year AND vm.quarter = f.quarter "
            "WHERE f.year < :yr OR (f.year = :yr AND f.quarter < 4) "
            "ORDER BY f.corp_code, f.year, f.quarter"
        ),
        {"yr": as_of_year},
    ).mappings().all()
    if companies is None:
        companies = _companies(session)
    names = {c["corp_code"]: c for c in companies}
    out: list[dict[str, Any]] = []
    for f in fin:
        c = names.get(f["corp_code"])
        if c is None:
            continue
        out.append({
            "corp_code": f["corp_code"], "corp_name": c["corp_name"],
            "market": c["market"], "sector": c["sector"], "as_of": as_of,
            "year": f["year"], "quarter": f["quarter"],
            "dividend_total": f["dividend_total"],
            "payout_ratio": f["payout_ratio"],
            "buyback_amount": f["buyback_amount"],
            "buyback_retired_amount": f["buyback_retired_amount"],
            "period_buyback_status": period_buyback_status(
                f["buyback_amount"], f["buyback_retired_amount"]
            ),
        })
    return out


def macro_rows(session: Session) -> list[dict[str, Any]]:
    """매크로 레이어: macro_indicator 전체(본질이 시계열이라 as_of 스냅숏 예외 —
    3.4의 시계열 차트와 같은 근거)."""
    rows = session.execute(
        select(
            MacroIndicator.indicator, MacroIndicator.date,
            MacroIndicator.value, MacroIndicator.frequency,
        ).order_by(MacroIndicator.indicator, MacroIndicator.date)
    ).mappings().all()
    return [dict(r) for r in rows]
