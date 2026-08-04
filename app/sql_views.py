"""SQL VIEW 정의 (마이그레이션·테스트 공용).

valuation_metrics: 지표를 앱코드가 아니라 DB VIEW로 계산(AD-1).
이식성: SQLite(개발)·PostgreSQL(운영) 모두 동작하도록 작성.
  - 최신 주가: DISTINCT ON(PG전용) 대신 상관 서브쿼리(MAX(date)).
  - float: *100.0 / *1.0 로 정수나눗셈 방지, NULLIF로 0방어.
  - YoY: LAG 윈도우 함수(연간 데이터 → 전년).
"""

from __future__ import annotations

VALUATION_METRICS_VIEW = "valuation_metrics"

CREATE_VALUATION_METRICS = f"""
CREATE VIEW {VALUATION_METRICS_VIEW} AS
SELECT
    f.corp_code,
    f.year,
    f.quarter,
    -- 이 재무를 언제부터 알 수 있었나(0029) — 사업보고서 rcept_dt. look-ahead 게이트가
    -- 이 열로 판정하고, null이면 연도 휴리스틱으로 폴백한다(app/analysis/lookahead.py).
    f.available_at,
    -- 음수/0 분모는 무의미(자본잠식·적자) → NULL. NULLIF(0)만으론 '음수 분모'가 통과해
    -- 지표 부호가 뒤집히고 스크리너를 오염(예: min_roe가 자본잠식 기업을 우량으로 통과)한다.
    -- 그래서 분모 > 0 조건을 CASE로 명시한다(GPT 교차검증 반영).
    ROUND(CASE WHEN f.equity > 0 THEN f.net_income * 100.0 / f.equity END, 2)      AS roe,
    ROUND(CASE WHEN f.total_assets > 0 THEN f.net_income * 100.0 / f.total_assets END, 2) AS roa,
    ROUND(CASE WHEN f.equity > 0 THEN lp.market_cap * 1.0 / f.equity END, 2)       AS pbr,
    ROUND(CASE WHEN f.net_income > 0 THEN lp.market_cap * 1.0 / f.net_income END, 2) AS per,
    -- EV/EBIT (EBITDA 아님). EBIT > 0일 때만.
    -- [2026-08-04] 감가상각비를 쓰지 않는다 — 실측 결정. 요약 API(fnlttSinglAcntAll)에
    -- 감가상각 행이 없어 357곳 중 299곳(84%)이 결측이었고, 이전 정의는 COALESCE(dep, 0)로
    -- 메워 **아는 58곳만 EBITDA, 모르는 299곳은 EBIT**로 재고 있었다. 백분위는 그 둘을 같은
    -- 자로 세우므로, 순위가 '감가상각을 공시했다는 사실'에 가점을 주고 있었다(실측: 58곳의
    -- 백분위가 전원 EBIT 대비 중앙값 6.4%p 이동, 14곳은 10%p 초과, 최대 37%p — 전부 한 방향).
    -- 편향은 무작위도 아니었다: SKT·LGU+·한전·포스코처럼 감가상각이 실제로 중요한 곳에 얹혔다.
    -- 개별 정확도(58곳의 진짜 EBITDA)보다 **비교 가능성**을 택한다 — 이 열의 쓰임이 절대값이
    -- 아니라 cross-sectional 백분위이기 때문이다. 진짜 EBITDA가 필요하면 XBRL 원본 수집이
    -- 선행되어야 한다(백로그). financials.depreciation은 수집한 사실이므로 그대로 보존한다.
    ROUND(CASE WHEN f.operating_income > 0
               THEN (lp.market_cap + f.total_debt - f.cash) * 1.0
                    / f.operating_income END, 2)                                   AS ev_ebit,
    ROUND(CASE WHEN f.equity > 0 THEN f.total_liabilities * 100.0 / f.equity END, 2) AS debt_ratio,
    ROUND(CASE WHEN f.net_income > 0 THEN f.dividend_total * 100.0 / f.net_income END, 2) AS payout_ratio,
    -- 총주주환원율 = (배당총액 + 자사주매입액)/순이익 (5-1). 배당성향과 **다른 지표**다 —
    -- 기업 다수가 이쪽으로 목표를 공시하므로 목표와 같은 정의의 실적이 필요하다.
    -- 자사주매입액이 null이면 0으로 메우지 않는다(그러면 환원을 과소평가) → 전체 null.
    -- [2026-08-04] 분자를 buyback_amount(**수량, 주**) → buyback_amount_krw(**금액, 원**)로
    -- 정정. 원에 주식 수를 더하고 있었다. 실측: 산출된 579행 중 564행에서 이 값이
    -- payout_ratio와 소수 둘째자리까지 같았고, 자사주 1,445만 주를 매입한 종목조차 기여가
    -- 0.01%p였다 — 즉 이 축은 배당성향의 복제였고, **자사주로 환원한 기업을 미이행으로
    -- 보이게 했다**(false negative). 축 정의는 업계 표준(배당+매입) 유지 — 매입만 하고
    -- 소각하지 않은 자사주를 환원으로 볼 것인지는 소각 '금액' 수집 후에 다시 연다(백로그).
    ROUND(CASE WHEN f.net_income > 0 AND f.buyback_amount_krw IS NOT NULL
               THEN (f.dividend_total + f.buyback_amount_krw) * 100.0 / f.net_income END, 2)
                                                                               AS total_return_ratio,
    -- [2026-08-04 2차, 0028] 소각 '금액'(buyback_retired_krw, SCE 원천)이 채워져 백로그
    -- ("소각하지 않은 자사주를 환원으로 볼 것인지")를 다시 열었다 — 정의를 바꾸지 않고
    -- **두 번째 시선을 나란히 둔다**(scoring.md 의도된 이중 시선의 수치화).
    -- retired_return_ratio: 소각 기준 총환원율 = (배당 + 소각액)/순이익. 매입 기준
    -- (total_return_ratio)과의 차이가 곧 '매입만 한 기업' 신호다.
    ROUND(CASE WHEN f.net_income > 0 AND f.buyback_retired_krw IS NOT NULL
               THEN (f.dividend_total + f.buyback_retired_krw) * 100.0 / f.net_income END, 2)
                                                                               AS retired_return_ratio,
    -- retirement_rate: 소각률 = 소각액/취득액(같은 회계연도). 이월 자사주 소각(전년
    -- 취득분을 올해 소각)이 있으면 100%를 넘을 수 있다 — 캡을 걸지 않는다(원값 보존,
    -- payout_achievement와 같은 원칙). 취득 0인 해의 소각은 분모가 없어 null(0% 아님).
    ROUND(CASE WHEN f.buyback_amount_krw > 0 AND f.buyback_retired_krw IS NOT NULL
               THEN f.buyback_retired_krw * 100.0 / f.buyback_amount_krw END, 2)
                                                                               AS retirement_rate,
    (f.cash - f.total_debt)                                                        AS net_cash,
    -- 매출 > 0에서만. EBIT 자체는 음수 가능(음수 마진은 유의미)이라 분자 부호는 유지.
    -- 감가상각을 쓰지 않는 이유는 ev_ebit 주석 참조(같은 결정, 같은 실측).
    ROUND(CASE WHEN f.revenue > 0
               THEN f.operating_income * 100.0 / f.revenue END, 2)                 AS ebit_margin,
    ROUND((f.revenue - LAG(f.revenue) OVER w) * 100.0
          / NULLIF(LAG(f.revenue) OVER w, 0), 2)                                   AS yoy_revenue_growth,
    ROUND((f.net_income - LAG(f.net_income) OVER w) * 100.0
          / NULLIF(LAG(f.net_income) OVER w, 0), 2)                                AS yoy_income_growth
FROM financials f
LEFT JOIN prices lp
       ON lp.corp_code = f.corp_code
      AND lp.date = (SELECT MAX(p2.date) FROM prices p2 WHERE p2.corp_code = f.corp_code)
-- YoY: 같은 분기끼리 전년 대비(PARTITION BY quarter). 연간(quarter=4만) 데이터에선
-- LAG(1)=전년으로 기존과 동일하고, 분기 데이터가 섞여도 QoQ 오표기 없이 전년 동분기와 비교.
WINDOW w AS (PARTITION BY f.corp_code, f.quarter ORDER BY f.year)
""".strip()

DROP_VALUATION_METRICS = f"DROP VIEW IF EXISTS {VALUATION_METRICS_VIEW}"


# ── plan_own_gap: 목표의 야심도 중 '자기 과거' 기준선 (P1-7 화면 반영, 2026-08-03) ──
#
# **왜 뷰인가**: 이 값은 상세(단건)와 목록(필터·정렬) 양쪽이 쓴다. 파이썬과 SQL에 각각
# 계산을 두면 두 정의가 언젠가 갈라지고, 그때 상세는 "-3.9%p"라 하고 목록 배지는 다른 말을
# 한다. 그래서 **뷰를 단일 정의처로 두고 `_ambition`이 이것을 읽는다**(선택 규칙을 서빙이
# 재현하지 않는다는 이 프로젝트의 기존 원칙과 같은 형태).
#
# **long 포맷인 이유**: (plan, 지표) 한 행씩이라 지표가 늘어도 컬럼이 안 늘고, 목록이 쓰는
# "가장 낮은 격차"를 `MIN(own_gap) GROUP BY plan_id`로 얻는다 — 집계 MIN은 NULL을 자연히
# 무시하므로 SQLite/PostgreSQL에서 동작이 같다(스칼라 min/LEAST는 NULL 처리가 갈린다).
#
# **기준연도**: 공시 **직전 연도**("이미 하던 것"). 그 해 실적이 없으면 한 해 더 뒤로 간다.
# 지표마다 따로 정한다 — ROE는 있는데 배당성향은 없는 해가 실제로 있다.
#
# ⚠ **peer(업종) 기준선은 여기 올리지 않는다.** 표본 5개 미만이면 값을 내지 않는 계약이라
# (그 이유를 화면이 말한다), SQL 필터에 넣으면 그 null이 조용히 배제돼 **"업종 표본이 부족한
# 기업"이 "야심찬 기업"으로 세탁된다.** 신호도 자기 과거 쪽에 몰려 있다(배당성향 45% vs 24%).
PLAN_OWN_GAP_VIEW = "plan_own_gap"

# (지표명, 목표 컬럼, 실적 컬럼) — valueup_score._AMBITION_METRICS와 같은 축.
_OWN_GAP_METRICS = (
    ("roe", "target_roe", "roe"),
    ("payout_ratio", "target_payout_ratio", "payout_ratio"),
    ("total_return_ratio", "target_total_return_ratio", "total_return_ratio"),
)


def _own_gap_block(metric: str, target_col: str, actual_col: str) -> str:
    """지표 한 축의 SELECT 블록. 공시연도-1 → 없으면 -2 순으로 기준선을 잡는다."""
    dy = "CAST(substr(p.disclosure_date, 1, 4) AS INTEGER)"

    def past(offset: int) -> str:
        return (
            f"(SELECT vm.{actual_col} FROM valuation_metrics vm "
            f"WHERE vm.corp_code = p.corp_code AND vm.year = {dy} - {offset} "
            f"AND vm.{actual_col} IS NOT NULL)"
        )

    own_past = f"COALESCE({past(1)}, {past(2)})"
    return f"""
SELECT
    p.plan_id,
    p.corp_code,
    '{metric}' AS metric,
    p.{target_col} AS target,
    CASE WHEN {past(1)} IS NOT NULL THEN {dy} - 1
         WHEN {past(2)} IS NOT NULL THEN {dy} - 2 END      AS baseline_year,
    {own_past}                                             AS own_past,
    ROUND(p.{target_col} - {own_past}, 2)                  AS own_gap
FROM valueup_plan p
WHERE p.{target_col} IS NOT NULL
  AND p.disclosure_date IS NOT NULL
""".strip()


CREATE_PLAN_OWN_GAP = (
    f"CREATE VIEW {PLAN_OWN_GAP_VIEW} AS\n"
    + "\nUNION ALL\n".join(_own_gap_block(*m) for m in _OWN_GAP_METRICS)
)

DROP_PLAN_OWN_GAP = f"DROP VIEW IF EXISTS {PLAN_OWN_GAP_VIEW}"
