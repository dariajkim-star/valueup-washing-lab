"""M&A Target Score 엔진 (writer = 이 모듈, AD-10).

2.1(gap_engine, 종목별 독립 계산)과 다른 아키텍처: **cross-sectional 백분위** — 한 종목의
점수가 전체 모집단 분포에 의존한다. 따라서 (1) 전체 모집단을 배치로 먼저 구성하고,
(2) 그 안에서 각 종목의 백분위를 계산하는 2단계 구조. 산식은 scoring.md M&A 섹션 참조.

null 규칙(엄격, 리드 결정 2026-07-10): 요소의 서브지표가 하나라도 null이면 요소 점수 null,
요소가 하나라도 null이면 mna_target_score null — "일부만 알면서 평균 내서 숫자 만들기" 금지
(2.1 execution_score와 동일 원칙, NFR2 "null > 틀린 값").

grouping seam(리드 결정, finance 스코프 분리): 백분위 모집단은 `_build_populations`의
`group_of` 콜러블이 결정한다. v1 = 전체시장 단일 그룹. 후속 2-7이 `company.sector` 기반
peer-group으로 갈아끼울 이음새 — 백분위 계산부는 population 출처를 모른다.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from sqlalchemy.orm import Session

from app.analysis.gap_engine import _validate_as_of  # as_of 검증 재사용(중복 정의 금지)
from app.config import settings
from app.repositories import mna_score as repo

# 전체시장 그룹키(폴백·sector 미상 종목용)
_WHOLE_MARKET = "_all"


def _sector_bucket(sector: str | None) -> str | None:
    """DART induty_code → KSIC 2자리 버킷(2.7 택소노미 v1 — 수작업 매핑 없이 결정적).

    2자리 미만·비숫자는 None(분류 불가 → market 모집단, 값을 만들지 않음).
    """
    if not sector:
        return None
    prefix = str(sector).strip()[:2]
    return prefix if len(prefix) == 2 and prefix.isdigit() else None

# (지표명, 방향) — 요소별 서브지표 정의. low=낮을수록 좋음, high=높을수록 좋음.
_VALUATION_INDICATORS = (("ev_ebitda", "low"), ("pbr", "low"))
_CAPACITY_INDICATORS = (("debt_ratio", "low"), ("net_cash", "high"), ("ebitda_margin", "high"))
_OWNERSHIP_INDICATORS = (("largest_shareholder_pct", "low"), ("treasury_stock_pct", "high"))


def _percentile_rank(value: float | None, population: Sequence[float | None]) -> float | None:
    """population 내 value의 백분위(0~1), **mid-rank** — (below + (equal-1)/2) / (N-1).

    동점을 최하위에 몰지 않고 구간 중앙에 배치(코드리뷰 2026-07-10 High): min-rank였다면
    전원 동일값에서 전원 rank 0 → pct_low 1.0("모두 똑같은데 최고점") — 기준금리처럼 장기
    동결되는 시계열에서 실제로 발생. mid-rank는 전원 동일 → 0.5(중립), 고유 최솟값 0·최댓값 1.
    NaN/Inf는 대상값·모집단 모두 배제(비교 연산 왜곡 방지, 리뷰 Med). 유효 peer<2 → None.
    """
    if value is None or not math.isfinite(value):
        return None
    pop = [v for v in population if v is not None and math.isfinite(v)]
    if len(pop) < 2:
        return None
    below = sum(1 for v in pop if v < value)
    equal = sum(1 for v in pop if v == value)
    return (below + max(equal - 1, 0) / 2) / (len(pop) - 1)


def _pct_rank_low(value: float | None, population: Sequence[float | None]) -> float | None:
    """낮을수록 좋은 지표(EV/EBITDA·PBR·부채비율·최대주주지분율·기준금리) → 역백분위."""
    rank = _percentile_rank(value, population)
    return None if rank is None else 1.0 - rank


def _pct_rank_high(value: float | None, population: Sequence[float | None]) -> float | None:
    """높을수록 좋은 지표(순현금·EBITDA마진·자사주비중) → 백분위 그대로."""
    return _percentile_rank(value, population)


def _avg_scores(*scores: float | None) -> float | None:
    """서브지표 점수 평균. 하나라도 None이면 전체 None(엄격, 리드 결정 — 결측이 잦은
    지표가 은근히 가중치를 왜곡하는 '있는 것만 평균' 부작용 방지)."""
    if any(s is None for s in scores):
        return None
    return sum(scores) / len(scores)


def _mna_target_score(
    valuation: float | None,
    capacity: float | None,
    ownership: float | None,
    macro: float | None,
    w_valuation: float,
    w_capacity: float,
    w_ownership: float,
    w_macro: float,
) -> float | None:
    """가중합 0~100. 요소 하나라도 None이면 전체 None(NFR2)."""
    if valuation is None or capacity is None or ownership is None or macro is None:
        return None
    return 100 * (
        w_valuation * valuation
        + w_capacity * capacity
        + w_ownership * ownership
        + w_macro * macro
    )


def _build_populations(
    rows: Mapping[str, Mapping[str, Any]],
    group_of: Callable[[str], str],
) -> dict[str, dict[str, list[float]]]:
    """corp별 지표 dict → 그룹별·지표별 population(유효값 리스트).

    grouping seam: `group_of(corp_code) -> 그룹키`. v1은 상수(전체시장), 2-7에서
    sector 버킷으로 교체. 백분위 계산부는 이 함수가 준 population만 소비한다.
    """
    pops: dict[str, dict[str, list[float]]] = {}
    for corp_code, indicators in rows.items():
        group = group_of(corp_code)
        bucket = pops.setdefault(group, {})
        for name, value in indicators.items():
            if value is not None:
                bucket.setdefault(name, []).append(value)
    return pops


def _factor_score(
    indicators: tuple[tuple[str, str], ...],
    corp_row: Mapping[str, Any] | None,
    population: Mapping[str, list[float]],
) -> float | None:
    """요소 점수 = 서브지표 백분위들의 평균(엄격 null). corp 데이터 자체가 없으면 None."""
    if corp_row is None:
        return None
    scores: list[float | None] = []
    for name, direction in indicators:
        value = corp_row.get(name)
        pop = population.get(name, [])
        rank = _pct_rank_low(value, pop) if direction == "low" else _pct_rank_high(value, pop)
        scores.append(rank)
    return _avg_scores(*scores)


def run(
    session: Session, as_of: str, corp_codes: Sequence[str] | None = None
) -> int:
    """as_of 기준 corp별 mna_score를 계산·upsert. 적재 행 수 반환.

    - 백분위 모집단은 corp_codes 부분집합과 무관하게 **전체 시장**(all_latest_* 배치 결과)
      기준 — 부분 실행이어도 순위 기준이 흔들리면 안 된다.
    - 종목별 3요소(valuation/capacity/ownership)가 전부 None이면 행을 만들지 않는다
      (macro는 전 종목 공통이라 그것만으론 종목별 정보가 없음 — all-null 행 방지, 1-6 교훈).
      기존 행이 있으면 정리(2.1 reconciliation 패턴). 단, **metrics·ownership이 통째로
      비면**(업스트림 수집 장애/ETL 중간 상태 가능성) 오삭제를 막기 위해 계산·삭제 모두
      스킵하고 0을 반환한다(코드리뷰 2026-07-10 Med 가드).
    - **부분 실행 주의(문서화된 한계, 리뷰 High)**: corp_codes 부분집합 실행은 대상 종목만
      최신 모집단 기준으로 갱신하고 나머지 행은 과거 모집단 점수로 남긴다 — 같은 as_of
      테이블 안에 서로 다른 population snapshot이 섞일 수 있다. **게시용 점수는 반드시
      전체 실행(corp_codes=None)으로 재계산**할 것. 부분 실행은 테스트/디버깅 용도.
    """
    _validate_as_of(as_of)
    if corp_codes is None:
        corp_codes = repo.list_all_corp_codes(session)

    # 1단계: 전체 모집단 배치 구성(cross-sectional — corp 루프 전에 끝나야 함)
    metrics = repo.all_latest_metrics(session, as_of)
    ownership = repo.all_latest_ownership(session, as_of)
    if not metrics and not ownership:
        return 0  # 입력 전무 — 업스트림 장애 가능성, reconciliation 오삭제 방어
    current_rate, rate_history = repo.latest_macro_percentile_basis(session, as_of)
    sectors = repo.all_company_sectors(session)

    # 시장 모집단(폴백·sector 미상·ownership용) + sector 버킷 모집단(2.7, valuation·capacity용)
    market_pops = _build_populations(metrics, group_of=lambda c: _WHOLE_MARKET)
    sector_pops = _build_populations(
        metrics, group_of=lambda c: _sector_bucket(sectors.get(c)) or _WHOLE_MARKET
    )
    # 버킷 sector 승격 판정(일괄리뷰 High: '행 개수'가 아니라 **지표별 유효값 개수** 기준 —
    # 행은 6개인데 ev_ebitda 유효값이 2개면 mna_peer_min의 small-N 방어가 우회되던 문제).
    # valuation·capacity의 5개 서브지표 전부가 peer_min 이상일 때만 sector 사용(단일
    # basis의 의미 보존), 하나라도 미달이면 그 버킷 전체를 시장 폴백.
    _factor_indicators = tuple(
        name for name, _ in _VALUATION_INDICATORS + _CAPACITY_INDICATORS
    )
    sector_ready: dict[str, bool] = {}
    for b, pops in sector_pops.items():
        if b == _WHOLE_MARKET:
            continue
        sector_ready[b] = all(
            len(pops.get(name, [])) >= settings.mna_peer_min
            for name in _factor_indicators
        )
    # ownership은 업종 무관(절대적 취약성 신호, epics 2.7 AC) — 시장 모집단 유지
    owner_pops = _build_populations(ownership, group_of=lambda c: _WHOLE_MARKET)
    # macro_score: 종목 무관, as_of당 1회(낮은 금리 = 차입인수 유리 → 역백분위)
    macro_score = _pct_rank_low(current_rate, rate_history)

    count = 0
    for corp_code in corp_codes:
        bucket = _sector_bucket(sectors.get(corp_code))
        if bucket is None:
            pop, basis = market_pops.get(_WHOLE_MARKET, {}), "market"
        elif sector_ready.get(bucket, False):
            pop, basis = sector_pops.get(bucket, {}), f"sector:{bucket}"
        else:  # 버킷 지표별 peer 미달 → 시장 폴백(small-N 노이즈 방어)
            pop, basis = market_pops.get(_WHOLE_MARKET, {}), "market_fallback"

        valuation = _factor_score(_VALUATION_INDICATORS, metrics.get(corp_code), pop)
        capacity = _factor_score(_CAPACITY_INDICATORS, metrics.get(corp_code), pop)
        owner = _factor_score(
            _OWNERSHIP_INDICATORS, ownership.get(corp_code),
            owner_pops.get(_WHOLE_MARKET, {}),
        )
        if valuation is None and capacity is None:
            # basis 과장 방지(일괄리뷰 Med): 이 종목의 valuation·capacity에 모집단이
            # 실제로 쓰이지 않았으면(둘 다 null) basis를 기록하지 않는다.
            basis = None
        if valuation is None and capacity is None and owner is None:
            repo.delete_mna_score(session, corp_code, as_of)  # 근거 없는 기존 행 정리
            continue

        total = _mna_target_score(
            valuation, capacity, owner, macro_score,
            settings.mna_w_valuation, settings.mna_w_capacity,
            settings.mna_w_ownership, settings.mna_w_macro,
        )
        repo.upsert_mna_score(
            session,
            {
                "corp_code": corp_code,
                "as_of": as_of,
                "mna_target_score": total,
                "valuation_score": valuation,
                "capacity_score": capacity,
                "ownership_score": owner,
                "macro_score": macro_score,
                "population_basis": basis,
            },
        )
        count += 1

    session.flush()
    return count
