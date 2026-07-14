"""API 응답 pydantic 스키마."""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """목록 응답 봉투 (AD-6)."""

    items: list[T]
    total: int
    page: int
    size: int


class MetricOut(BaseModel):
    """valuation_metrics 뷰 + company 조인 결과."""

    corp_code: str
    corp_name: str | None = None
    market: str | None = None
    sector: str | None = None
    year: int
    quarter: int
    roe: float | None = None
    roa: float | None = None
    pbr: float | None = None
    per: float | None = None
    ev_ebitda: float | None = None
    debt_ratio: float | None = None
    payout_ratio: float | None = None
    net_cash: int | None = None
    ebitda_margin: float | None = None
    yoy_revenue_growth: float | None = None
    yoy_income_growth: float | None = None


class ScreeningOut(BaseModel):
    """company + valueup_score + mna_score outer join 결과 (2.6 다중조건 스크리닝).

    null 계약 승계: washing_flag null=판단 불가(빈칸/아니오 표시 금지, 2.4),
    mna_target_score null=산출 불가(0점/최하위 표시 금지, 2.5).
    has_valueup_score/has_mna_score: 엔진 실행 여부(score row 존재) — "row 없음(미실행)"과
    "row는 있으나 전부 null(엄격 게이팅 산출 불가)"은 필드값만으론 구분 불가라 명시 노출.
    """

    corp_code: str
    corp_name: str | None = None
    market: str | None = None
    sector: str | None = None
    as_of: str
    # 핵심지표(AC3, 3.3 리뷰 반영) — look-ahead 안전 최신값, null=지표 없음
    roe: float | None = None
    pbr: float | None = None
    has_valueup_score: bool
    has_mna_score: bool
    execution_score: float | None = None
    washing_flag: bool | None = None
    buyback_status: str | None = None
    buyback_executed: bool | None = None
    mna_target_score: float | None = None
    population_basis: str | None = None


class MnaRankingOut(BaseModel):
    """mna_score + company 조인 결과 (2.5 M&A 타겟 랭킹).

    mna_target_score 계약: **null=산출 불가**(요소 하나라도 입력 데이터 부족이면 총점
    null — 2.3 엄격 null 정책). UI에서 0점이나 최하위로 표시 금지, "산출 불가"로 표시.
    population_basis: 백분위 모집단 식별(sector:{KSIC2} / market_fallback / market, 2.7).
    """

    corp_code: str
    corp_name: str | None = None
    market: str | None = None
    sector: str | None = None
    as_of: str
    mna_target_score: float | None = None
    valuation_score: float | None = None
    capacity_score: float | None = None
    ownership_score: float | None = None
    macro_score: float | None = None
    population_basis: str | None = None


class MarketComparisonOut(BaseModel):
    """시장별(KOSPI/KOSDAQ) 헤드라인 통계 (3.1). n=as_of 시점 최신 지표 보유 종목 수,
    washing_ratio 분모는 n_judged(washing_flag가 null이 아닌 종목) — n과 다른 모집단.
    market은 이 스토리가 다루는 KOSPI/KOSDAQ로 한정(repository가 이미 필터하지만
    스키마에서도 계약을 좁혀 방어)."""

    market: Literal["KOSPI", "KOSDAQ"]
    n: int
    avg_roe: float | None = None
    avg_pbr: float | None = None
    avg_ev_ebitda: float | None = None
    n_judged: int
    n_washing: int
    washing_ratio: float | None = None


class StatsSummaryOut(BaseModel):
    """시장 구분 없는 전체 헤드라인 KPI (3.1)."""

    as_of: str
    n_companies: int
    n_metrics: int
    avg_roe: float | None = None
    avg_pbr: float | None = None
    avg_ev_ebitda: float | None = None
    n_judged: int
    n_washing: int
    washing_ratio: float | None = None


class MacroSnapshotOut(BaseModel):
    """매크로 지표 스냅샷 (3.1). date/value null = 아직 관측 없음(지표 자리는 항상 보장)."""

    indicator: str
    date: str | None = None
    value: float | None = None


class GapAnalysisOut(BaseModel):
    """valueup_score + company 조인 결과 (2.4 갭분석/워싱랭킹).

    washing_flag 계약: true=워싱 의심 / false=워싱 근거 없음 / **null=판단 불가**
    (입력 데이터 부족 — UI에서 빈칸이나 '아니오'로 표시 금지, "판단 불가"로 표시할 것).
    """

    corp_code: str
    corp_name: str | None = None
    market: str | None = None
    as_of: str
    target_roe: float | None = None
    actual_roe: float | None = None
    roe_gap: float | None = None
    achievement_rate: float | None = None
    progress_rate: float | None = None
    execution_score: float | None = None
    washing_flag: bool | None = None
    buyback_status: str | None = None
