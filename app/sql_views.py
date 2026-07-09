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
    ROUND(f.net_income * 100.0 / NULLIF(f.equity, 0), 2)                           AS roe,
    ROUND(f.net_income * 100.0 / NULLIF(f.total_assets, 0), 2)                     AS roa,
    ROUND(lp.market_cap * 1.0 / NULLIF(f.equity, 0), 2)                            AS pbr,
    ROUND(lp.market_cap * 1.0 / NULLIF(f.net_income, 0), 2)                        AS per,
    -- EBITDA = 영업이익 + 감가상각비. DART 전체재무제표에 감가상각비가 없는 경우가 많아
    -- COALESCE(...,0)으로 EBIT 근사(감가상각비 있으면 정확한 EBITDA).
    ROUND((lp.market_cap + f.total_debt - f.cash) * 1.0
          / NULLIF(f.operating_income + COALESCE(f.depreciation, 0), 0), 2)        AS ev_ebitda,
    ROUND(f.total_liabilities * 100.0 / NULLIF(f.equity, 0), 2)                    AS debt_ratio,
    ROUND(f.dividend_total * 100.0 / NULLIF(f.net_income, 0), 2)                   AS payout_ratio,
    (f.cash - f.total_debt)                                                        AS net_cash,
    ROUND((f.operating_income + COALESCE(f.depreciation, 0)) * 100.0
          / NULLIF(f.revenue, 0), 2)                                              AS ebitda_margin,
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
