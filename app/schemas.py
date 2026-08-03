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
    """company + valueup_score + mna_score + opacity_score outer join 결과 (2.6 다중조건 스크리닝).

    null 계약 승계: washing_flag null=판단 불가(빈칸/아니오 표시 금지, 2.4),
    mna_target_score null=산출 불가(0점/최하위 표시 금지, 2.5).
    opacity_rank null=순위 불가(계획 미공시·표지 통지문·peer 부족 — 0점/최투명 표시 금지).
    has_valueup_score/has_mna_score/has_opacity_score: 엔진 실행 여부(score row 존재) —
    "row 없음(미실행)"과 "row는 있으나 전부 null(엄격 게이팅 산출 불가)"은 필드값만으론
    구분 불가라 명시 노출.
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
    has_opacity_score: bool
    execution_score: float | None = None
    # execution_score의 채점 근거(5-1): 'roe+buyback+payout' 등 + 구분 토큰.
    # null이면 점수도 null. population_basis와 같은 역할 — 기준이 다른 값을 같은 척도로
    # 쓰는 것을 막기 위해 점수와 항상 함께 전달한다.
    score_basis: str | None = None
    washing_flag: bool | None = None
    buyback_status: str | None = None
    # 소각 **시점** 판정(0022, P1-4): in_period/outside_period(계획 기간 기준) ·
    # after_disclosure/before_disclosure(공시일 기준) · same_year_unknown(같은 해라 판정
    # 불가) · null(소각 없음). buyback_status가 "무엇을"이라면 이건 "언제"다.
    buyback_timing: str | None = None
    buyback_executed: bool | None = None
    mna_target_score: float | None = None
    population_basis: str | None = None
    # 공시 불투명도 순위(washing_flag 대체) — 미공시 목표 축 수의 peer 백분위(0~1, 높을수록
    # 불투명). opacity_basis는 그 순위의 모집단 식별(mna의 population_basis와 같은 규약) —
    # 기준이 다른 순위를 같은 척도로 비교하지 않도록 순위와 함께 전달한다.
    opacity_rank: float | None = None
    opacity_count: int | None = None
    opacity_basis: str | None = None
    # 근거 공시의 본문 신호(0018) — '순위 불가'가 "부실 공시(no_targets)"인지
    # "타 지표로 공시(other_metric — 우리 자에 눈금이 없음)"인지 목록에서 구분한다.
    # 상세의 plan_body_signal과 같은 값(source_plan_id 조인만, 선택규칙 재현 없음).
    plan_body_signal: str | None = None


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


class RefreshOut(BaseModel):
    """단건 새로고침 결과 — 단계별로 보고한다.

    '성공/실패' 한 값으로 뭉치지 않는 이유: 부분 성공이 정상 경로다(수집은 됐는데 채점이
    실패하거나, 반대이거나). 어느 단계가 어떻게 됐는지 화면이 말할 수 있어야 사용자가
    다시 눌러야 할지 판단한다 — 이 프로젝트의 null 계약과 같은 정신.
    """

    corp_code: str
    as_of: str
    plans_ingested: int = 0
    ingest_ok: bool = False
    ingest_error: str | None = None
    scored: bool = False
    score_error: str | None = None
    # 주의: 전 종목 재계산 결과다(백분위라 부분 갱신 불가) — 이 종목만의 상태가 아니다.
    opacity_reranked: bool = False
    opacity_error: str | None = None
    warnings: list[str] = []
    complete: bool = False


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
    score_basis: str | None = None  # 채점 근거(5-1) — ScreeningOut과 같은 계약
    # 채점에서 제외된 축과 사유(0021). "roe:no_period" = 계획 기간 미상이라 진척 대비
    # 달성을 말할 수 없어 ROE 축을 뺐다. score_basis에서 빠진 것만으로는 "애초에 약속
    # 안 함"과 구분되지 않으므로 별도로 남긴다.
    excluded_axes: str | None = None
    washing_flag: bool | None = None
    buyback_status: str | None = None
    # 소각 **시점** 판정(0022, P1-4): in_period/outside_period(계획 기간 기준) ·
    # after_disclosure/before_disclosure(공시일 기준) · same_year_unknown(같은 해라 판정
    # 불가) · null(소각 없음). buyback_status가 "무엇을"이라면 이건 "언제"다.
    buyback_timing: str | None = None
    # 출처(0015) — 이 점수가 **어느 공시**에서 나왔는가. 목표값만 보여주고 출처를 감추면
    # 사용자가 신선도를 판단할 수 없다(실측: 7종목이 최신 공시보다 과거 공시에 목표가 더
    # 많다). rcept_no가 null이면 0015 이전 적재분 = DART 원문 링크 조립 불가.
    plan_disclosure_date: str | None = None
    plan_rcept_no: str | None = None
    # 근거 공시가 그 종목의 최신이 아닌가(= 최신 공시에 목표가 없어 이전 공시로 폴백).
    # 이 사실 자체가 출처의 일부다 — "2024-10-29 공시 기준"만 쓰면 왜 최신이 아닌지 모른다.
    plan_is_fallback: bool = False
    plan_newest_disclosure_date: str | None = None
    # 본문이 왜 우리 축을 못 채웠는가(0018): axis_targets / other_metric / refiling /
    # no_targets. "미공시"와 "다른 지표로 공시"는 다른 사실이다 — 전자는 부실 공시고
    # 후자는 우리 자에 눈금이 없는 것이다.
    plan_body_signal: str | None = None
    # ── 환원 축의 목표·실적·달성배율 (2026-07-31) ─────────────────────────────
    # 그간 상세는 ROE 축만 목표/실적을 보여줬다. 그래서 `score_basis="payout"`인 100점이
    # **왜** 100점인지 화면에서 확인할 수 없었다.
    #
    # 실측(표본 359): payout 단독 100점 21개사 중 **16개가 자기 과거 실적보다 낮은 목표**를
    # 공시했다(예: 목표 배당성향 10% / 실적 33.7%, 목표 15% / 2023년 133.6%).
    # `_axis_score`가 [0,1]로 clamp하므로 과달성이 점수에서 사라지고, 낮은 목표일수록
    # 만점을 받기 쉬운 구조다.
    #
    # payout_achievement는 **캡을 걸지 않는다**(실적/목표 원값). 점수는 그대로 두고
    # 사실만 드러낸다 — 고의를 판정하지 않고 격차를 보여준다는 원칙(레아).
    target_payout_ratio: float | None = None
    target_total_return_ratio: float | None = None
    actual_payout_ratio: float | None = None
    actual_total_return_ratio: float | None = None
    payout_achievement: float | None = None  # 실적/목표(무제한). 1.0 초과 = 목표 초과 달성
