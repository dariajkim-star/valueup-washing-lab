# DB 스키마 & 지표 SQL VIEW

> SPEC-valueup-washing companion. 애널리스트 스크리너 5테이블 + 밸류업 확장. 원천 → 파생(VIEW) → 스코어.

## 테이블 구조

```
company ─┬─< financials        (원천: 재무제표)
         ├─< prices            (원천: 시세)
         ├─< valueup_plan      (원천: 밸류업 계획 공시)
         ├─< ownership         (원천: 지분구조)
         ├─< valuation_metrics (파생: SQL VIEW, 즉석 계산)
         ├─< valueup_score     (스코어: 워싱/실행점수)
         └─< mna_score         (스코어: M&A 타겟)
macro_indicator                (원천: ECOS 매크로, 종목 무관 시계열)
```

| 테이블 | 성격 | 핵심 컬럼 | 소스 |
|---|---|---|---|
| `company` | 원천 | corp_code(PK), stock_code, corp_name, market(KOSPI/KOSDAQ), sector | DART |
| `financials` | 원천 | corp_code, year, quarter, revenue, net_income, equity, total_assets, total_liabilities, operating_income, depreciation, cash, total_debt, dividend_total, buyback_amount, **buyback_retired_amount** | DART |

> **자사주 필드 각주(1.8)**: `buyback_amount`·`buyback_retired_amount`는 `tesstkAcqsDspsSttus`(자기주식 취득·처분 현황)의 **취득/소각 수량(주)**이다(KRW 액 아님). 워싱 판정이 `>0`(실행/소각 여부)로만 소비하므로 수량을 presence-proxy로 저장. 엔드포인트가 금액을 제공하지 않음. KRW 정밀액은 후속(수량×결산일 종가).
| `prices` | 원천 | corp_code, date, close, volume, trading_value, market_cap | KRX |
| `valueup_plan` | 원천 | plan_id, corp_code, disclosure_date, target_roe, target_payout_ratio, target_pbr, period_start, period_end, buyback_planned | DART 밸류업 공시 |
| `ownership` | 원천 | corp_code, as_of, largest_shareholder_pct, treasury_stock_pct | DART 지분공시 |
| `macro_indicator` | 원천 | indicator, date, value | ECOS |
| `valuation_metrics` | **파생 VIEW** | corp_code, year, quarter, roe, roa, pbr, per, **ev_ebitda**, debt_ratio, payout_ratio, **net_cash, ebitda_margin**, yoy_revenue_growth, yoy_income_growth | financials×prices 계산 |
| `valueup_score` | 스코어 | corp_code, as_of, achievement_rate, progress_rate, washing_flag, execution_score, buyback_executed, buyback_retired, buyback_status | gap_engine |
| `mna_score` | 스코어 | corp_code, as_of, mna_target_score, valuation_score, capacity_score, ownership_score, macro_score | mna_engine |

> **AD-9**: 시가총액 단일원천 = `prices`. `company`에 market_cap 없음.

## 설계 결정: 물리 테이블이 아니라 SQL VIEW

`valuation_metrics`는 **뷰**로 구현 → 조회 시점의 최신 주가로 항상 즉석 계산. 윈도우 함수·CTE·다중 조인이 들어가 SQL 역량을 그대로 보여주는 포폴 핵심 산출물이다. (대용량 전환 시 `MATERIALIZED VIEW` 승격.)

## 실제 뷰 DDL (PostgreSQL)

```sql
CREATE OR REPLACE VIEW valuation_metrics AS
WITH latest_price AS (              -- 종목별 최신 시가총액
    SELECT DISTINCT ON (corp_code)
           corp_code, market_cap
    FROM prices
    ORDER BY corp_code, date DESC
),
ttm AS (                            -- 최근 4개 분기 순이익 합(TTM)
    SELECT corp_code, year, quarter,
           SUM(net_income) OVER (
               PARTITION BY corp_code
               ORDER BY year, quarter
               ROWS BETWEEN 3 PRECEDING AND CURRENT ROW
           ) AS net_income_ttm
    FROM financials
)
SELECT
    f.corp_code, f.year, f.quarter,
    ROUND(f.net_income::numeric / NULLIF(f.equity, 0)          * 100, 2) AS roe,
    ROUND(f.net_income::numeric / NULLIF(f.total_assets, 0)    * 100, 2) AS roa,
    ROUND(p.market_cap::numeric / NULLIF(f.equity, 0)              , 2) AS pbr,
    ROUND(p.market_cap::numeric / NULLIF(t.net_income_ttm, 0)      , 2) AS per,
    -- EV/EBITDA: EV = 시총 + 순부채(총차입금 - 현금), EBITDA = 영업이익 + 감가상각비
    ROUND((p.market_cap + f.total_debt - f.cash)::numeric
          / NULLIF(f.operating_income + f.depreciation, 0)         , 2) AS ev_ebitda,
    ROUND(f.total_liabilities::numeric / NULLIF(f.equity, 0)   * 100, 2) AS debt_ratio,
    ROUND(f.dividend_total::numeric / NULLIF(f.net_income, 0)  * 100, 2) AS payout_ratio,
    -- M&A 엔진 입력 (F-4): 순현금, EBITDA 마진
    (f.cash - f.total_debt)                                             AS net_cash,
    ROUND((f.operating_income + f.depreciation)::numeric
          / NULLIF(f.revenue, 0)                              * 100, 2) AS ebitda_margin,
    ROUND((f.revenue - LAG(f.revenue, 4) OVER w)::numeric
          / NULLIF(LAG(f.revenue, 4) OVER w, 0)              * 100, 2) AS yoy_revenue_growth,
    ROUND((f.net_income - LAG(f.net_income, 4) OVER w)::numeric
          / NULLIF(LAG(f.net_income, 4) OVER w, 0)           * 100, 2) AS yoy_income_growth
FROM financials f
JOIN latest_price p ON p.corp_code = f.corp_code
JOIN ttm          t ON t.corp_code = f.corp_code
                   AND t.year = f.year AND t.quarter = f.quarter
WINDOW w AS (PARTITION BY f.corp_code ORDER BY f.year, f.quarter);
```

**SQL 어필 포인트**: `DISTINCT ON`(종목별 최신행), `SUM(...) OVER (ROWS BETWEEN 3 PRECEDING AND CURRENT ROW)`(TTM), `LAG(...,4)`(YoY 전년동기), `NULLIF`(0 나눗셈 방어), CTE 2단.
