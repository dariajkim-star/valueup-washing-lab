"""API 응답 pydantic 스키마."""

from __future__ import annotations

from typing import Generic, TypeVar

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
