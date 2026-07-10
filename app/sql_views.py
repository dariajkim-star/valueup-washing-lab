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
    -- 음수/0 분모는 무의미(자본잠식·적자) → NULL. NULLIF(0)만으론 '음수 분모'가 통과해
    -- 지표 부호가 뒤집히고 스크리너를 오염(예: min_roe가 자본잠식 기업을 우량으로 통과)한다.
    -- 그래서 분모 > 0 조건을 CASE로 명시한다(GPT 교차검증 반영).
    ROUND(CASE WHEN f.equity > 0 THEN f.net_income * 100.0 / f.equity END, 2)      AS roe,
    ROUND(CASE WHEN f.total_assets > 0 THEN f.net_income * 100.0 / f.total_assets END, 2) AS roa,
    ROUND(CASE WHEN f.equity > 0 THEN lp.market_cap * 1.0 / f.equity END, 2)       AS pbr,
    ROUND(CASE WHEN f.net_income > 0 THEN lp.market_cap * 1.0 / f.net_income END, 2) AS per,
    -- EBITDA = 영업이익 + 감가상각비(없으면 COALESCE로 EBIT 근사). EBITDA > 0일 때만.
    ROUND(CASE WHEN (f.operating_income + COALESCE(f.depreciation, 0)) > 0
               THEN (lp.market_cap + f.total_debt - f.cash) * 1.0
                    / (f.operating_income + COALESCE(f.depreciation, 0)) END, 2)   AS ev_ebitda,
    ROUND(CASE WHEN f.equity > 0 THEN f.total_liabilities * 100.0 / f.equity END, 2) AS debt_ratio,
    ROUND(CASE WHEN f.net_income > 0 THEN f.dividend_total * 100.0 / f.net_income END, 2) AS payout_ratio,
    (f.cash - f.total_debt)                                                        AS net_cash,
    -- 매출 > 0에서만. EBITDA 자체는 음수 가능(음수 마진은 유의미)이라 분자 부호는 유지.
    ROUND(CASE WHEN f.revenue > 0
               THEN (f.operating_income + COALESCE(f.depreciation, 0)) * 100.0 / f.revenue END, 2) AS ebitda_margin,
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
