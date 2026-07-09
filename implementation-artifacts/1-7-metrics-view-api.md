---
baseline_commit: fde6b860e4de5af73a53d72e6c31110d695f626c
---

# Story 1.7: 밸류에이션 지표 SQL VIEW + 지표 조회 API

Status: done

## Story

As a 애널리스트,
I want ROE·ROA·PBR·PER·EV/EBITDA·부채비율·배당성향·YoY를 SQL VIEW로 계산해 조회하는 것,
so that 종목을 정량 비교하고 스코어링(Epic 2)의 입력을 얻는다.

## Acceptance Criteria

1. **Given** `valuation_metrics` **SQL VIEW**(마이그레이션 0005 raw SQL), **When** `alembic upgrade head`, **Then** 뷰가 생성된다. **앱코드가 아니라 DB 뷰가 지표를 계산한다(AD-1).**
2. **Given** financials·prices 데이터, **When** 뷰를 조회하면, **Then** 최신 주가 기준으로 roe·roa·pbr·per·ev_ebitda·debt_ratio·payout_ratio·net_cash·ebitda_margin·yoy_revenue_growth·yoy_income_growth가 계산된다.
3. **Given** EV/EBITDA, **When** 계산하면, **Then** `(시총 + 순부채) / (영업이익 + 감가상각비)`. net_cash·ebitda_margin은 M&A 엔진(2.3) 입력.
4. **Given** YoY, **When** 계산하면, **Then** 전년(연간 데이터) 대비 성장률(윈도우 함수 LAG). 0 나눗셈은 NULLIF로 방어(NFR2).
5. **Given** 이식성, **When** SQLite(개발)·PostgreSQL(운영) 어디서든, **Then** 동일 뷰 SQL이 동작한다(DISTINCT ON 미사용, 최신주가는 상관 서브쿼리).
6. **Given** `GET /metrics`, **When** 호출하면, **Then** 지표 목록이 `{items,total,page,size}` 봉투(AD-6)로 반환된다. `GET /metrics/{corp_code}`는 종목 시계열. 필터: market·sector·max_pbr·min_roe·max_debt_ratio.
7. **Given** 레이어(AD-2), **When** 구현하면, **Then** routers→services→repositories로만 접근한다.

## Tasks / Subtasks

- [x] **T1: 뷰 마이그레이션** — `0005_valuation_metrics_view.py` raw SQL(app/sql_views.py 공용). 이식성(SQLite·PG).
- [x] **T2: 뷰 SQL** — `app/sql_views.py` CREATE/DROP. 최신주가 상관서브쿼리, YoY LAG, NULLIF, EBITDA는 COALESCE(감가상각비,0) 폴백.
- [x] **T3: repository** — `app/repositories/metrics.py` text() 쿼리(뷰+company 조인), 필터·정렬·페이지네이션.
- [x] **T4: service + router + schema** — `services/metrics.py`, `routers/metrics.py`, `schemas.py`(Page 봉투·MetricOut). `/metrics`, `/metrics/{corp_code}`.
- [x] **T5: main 라우터 등록** — include_router.
- [x] **T6: 테스트** — 뷰 계산값(ROE 12.5·PBR 2.5·EV/EBITDA 15·YoY) + NULLIF + /metrics API 필터. 39 passed.

### Review Findings (code review 2026-07-09, BMAD 3-layer: Blind/EdgeCase/Auditor)

**Decision-needed → 해결(defer)**
- [x] [Review][Decision] 시계열 엔드포인트 AD-6 봉투 미적용 — `GET /metrics/{corp_code}`가 `list[MetricOut]` 원시 리스트 반환 [app/routers/metrics.py:33]. **결정(2026-07-09, 사용자): 리스트 유지 + defer.** 코드가 스토리 AC6 의도와 일치하고, 시계열은 페이지네이션 대상이 아니라 page/size가 무의미. AD-6 예외로 문서화하고 API_SPEC 확정(Epic 3) 시 최종 결정. deferred-work.md 기록.

**Patch**
- [x] [Review][Patch] YoY 윈도우가 전년이 아닌 '직전 행' 기준 — 분기/결측 데이터에서 QoQ를 YoY로 오표기 [app/sql_views.py:41]. 수정: `WINDOW w AS (PARTITION BY f.corp_code, f.quarter ORDER BY f.year)`. 연간 데이터(quarter=4만)에선 결과 동일 → 기존 테스트 유지. (적용됨 2026-07-09)

**Deferred** (deferred-work.md 기록)
- [x] [Review][Defer] 최신가 선택이 market_cap NULL 행도 채택 [app/sql_views.py:40] — 거래정지 등으로 MAX(date) 행 시총 NULL이면 유효한 이전값이 있어도 pbr/per/ev_ebitda 전부 NULL. deferred.
- [x] [Review][Defer] NULLIF가 0만 방어, 음수 분모 미방어 [app/sql_views.py:23,29,35] — 적자기업 음수 PER/payout, 이전연도 음수 기저 시 YoY 부호 왜곡. 손실 표현 제품규칙 확정 시 처리. deferred.
- [x] [Review][Defer] YoY 연도 비연속(gap) — 2023→2025처럼 결측 시 2년 성장을 1기 성장으로 오산(LAG 특성). 날짜차 검증 로직 필요. deferred.
- [x] [Review][Defer] `GET /metrics/{corp_code}` 미존재 종목에 200 `[]` — 404 미구분. API_SPEC 확정(Epic 3) 시 결정. deferred.
- [x] [Review][Defer] 스토리 소스트리의 `ValuationMetric` ORM 뷰 매핑 미구현(문서 불일치) — 리포지토리는 `text()`로 뷰 조회, models.py 매핑 없음. 스토리 문서 정정 필요. deferred.

**Dismissed** (10건): Blind '무타입 숫자필터'·'op import 누락'(둘 다 리뷰 전달용 축약 아티팩트, 실제 코드엔 타입·import 존재), 가격행 fan-out(uq_prices_corp_date 유니크로 불가), net_cash float 500(bigint 연산, 누출 없음), NULL컬럼 필터 드롭(스크리너 의도된 SQL 시맨틱), 무가격→NULL valuation(데이터모델 의도), 재무없는 회사 누락(스크리너 의도), 빈문자열 필터 무시(사소), 페이지 초과 빈 items(표준 페이지네이션), PER 연간 vs TTM(스토리 Dev Notes 승인).

### GPT 교차검증 triage (2026-07-09, 21건)

**Patch 적용 (완료·검증)**
- [x] [GPT][Patch] `/metrics` sort 파라미터 미구현(API명세 공통 params 위반) + 인젝션 방어 [app/repositories/metrics.py, app/routers/metrics.py] — `SORT_COLUMNS` 화이트리스트로 `sort=field`/`-field` 안전 매핑(허용 밖 필드·raw SQL 시도는 400), 누락돼 있던 `min_payout_ratio` 필터 추가(API명세 253행). sort 오름/내림·인젝션 차단·필터 회귀 테스트 추가 → **pytest 41 passed**. (GPT #10 기본정렬 UX는 sort 제공으로 해소, 기본순서는 안정 유지) (GPT #10/#11/#12 + min_payout_ratio)

**이미 처리됨/중복 (재작업 안 함)**: GPT #1(과거행 최신시총)=알려진 accepted+deferred, #3(LAG YoY)=이미 patch(F1, `PARTITION BY corp_code, quarter`), #8(음수 PER/payout)=deferred(F5), #9(음수 EBITDA)=F5 defer 포함, #13(시계열 AD-6 봉투)=사용자 결정 defer(F10).

**Deferred (deferred-work.md 기록)**: corp_code 형식검증(#14, 사용자 선택으로 이번엔 defer), price_date/market_cap 노출(#2 auditability), 일반 VIEW 성능·materialized view 승격(#4/#5), PostgreSQL 통합 테스트로 AC5 실검증(#6/#15), debt/cash NULL→EV/EBITDA NULL COALESCE 정책(#7).

**Dismissed**: #17(LAG CTE 리팩터), #18(offset 深페이지), #19(sector exact match), #21(뷰 교체전략 — downgrade에 `DROP VIEW IF EXISTS` 존재).

## Dev Notes

### 뷰 설계 (이식성: SQLite + PostgreSQL)
- **최신 주가**: `DISTINCT ON`(PG전용) 대신 상관 서브쿼리 `p.date = (SELECT MAX(date) FROM prices p2 WHERE p2.corp_code=p.corp_code)`.
- **YoY**: 데이터가 연간(reprt 11011, quarter=4)이므로 `LAG(1) OVER (PARTITION BY corp_code ORDER BY year, quarter)` = 전년. (운영 분기데이터면 LAG(4) — db-schema.md 참조)
- **PER**: `시총 / net_income`(연간 순이익). TTM은 분기·누적보고 복잡성으로 v1 제외(연간 순이익이 이미 12개월).
- **float 강제**: `* 100.0`, `* 1.0`로 정수나눗셈 방지(양 DB 공통). `ROUND(..., 2)`. `NULLIF(x,0)` 0방어.
- **SQL 어필**: CTE·다중 조인·self/상관 서브쿼리·윈도우 함수(LAG)·NULLIF·ROUND — 포폴 핵심.

### 아키텍처 제약
- **AD-1**: 지표는 앱코드 아닌 DB VIEW로만 계산(파이썬 계산 금지).
- **AD-2**: routers→services→repositories→DB. 라우터가 SQL 직접실행 금지.
- **AD-6**: 목록 응답 봉투.
- **AD-10 입력**: net_cash·ebitda_margin·ev_ebitda는 M&A 엔진이 사용.

### 소스 트리
```
alembic/versions/0005_valuation_metrics_view.py  # NEW: CREATE VIEW
app/models.py                # UPDATE: ValuationMetric(읽기전용 뷰 매핑)
app/schemas.py               # NEW: MetricOut, Page
app/repositories/metrics.py  # NEW
app/services/metrics.py      # NEW
app/routers/metrics.py       # NEW
app/main.py                  # UPDATE: include_router
tests/test_metrics.py        # NEW
```

### 데모 데이터
- 삼성(00126380)·하이닉스(00164779) 2023·2024 연간 재무 + KRX 시세 적재 후 뷰 조회 → 실 ROE·PBR·EV/EBITDA·YoY 확인.

### References
- [Source: db-schema.md] 뷰 DDL(PostgreSQL 버전), 지표 산식
- [Source: ARCHITECTURE-SPINE.md#AD-1,2,6,10], [API_SPEC.md] /metrics
- [Source: 1-2/1-3] financials·prices 스키마

## Dev Agent Record

### Agent Model Used
claude-opus-4-8 (bmad-dev-story)

### Debug Log References
- **이식성**: `DISTINCT ON`(PG전용) 대신 최신주가는 상관 서브쿼리(MAX(date)), float은 *100.0/*1.0, WINDOW+LAG는 SQLite 3.25+/PG 공통 → 동일 뷰 SQL이 양쪽에서 동작(SQLite 3.49 검증).
- **감가상각비 부재(실데이터 발견)**: DART fnlttSinglAcntAll(전체재무제표)에 **감가상각비 라인이 없음**(삼성 확인 — 표준계정만 반환, CF 감가상각비 누락). → EBITDA = 영업이익 + **COALESCE(감가상각비,0)**로 EBIT 근사. 감가상각비 있으면 정확한 EBITDA, 없으면 EBIT(자본집약 기업엔 EBITDA 과소 → EV/EBITDA 과대). deferred-work 기록.
- **테스트 in-memory 이슈**: TestClient 워커 스레드가 SingletonThreadPool로 다른 연결→빈 DB. `StaticPool + check_same_thread=False`로 해결(테스트 인프라).
- **뷰는 Base.metadata 밖**: create_all이 뷰를 테이블로 만들지 않게 뷰는 raw SQL(app/sql_views.py)로만 생성. 조회는 repository text().

### Completion Notes List
- `valuation_metrics` **SQL VIEW**로 지표 계산(AD-1: 앱코드 계산 없음). CTE 없이 상관서브쿼리+LAG 윈도우+NULLIF+ROUND.
- `/metrics`(필터·정렬·페이지네이션·봉투 AD-6), `/metrics/{corp_code}`(시계열). routers→services→repositories(AD-2).
- **라이브 검증**: 삼성(ROE 8.57%·PBR 0.79·PER 9.22·EV/EBITDA 8.65·부채비율 27.93%)·하이닉스(ROE 26.78%·PBR 1.71·EV/EBITDA 6.0·EBITDA마진 35.45%), YoY(삼성 매출+16.2%·순익+122%). `/metrics?max_pbr=1.0` → 삼성만(필터 동작). pytest 39 passed.

### File List
- `app/sql_views.py` (NEW: VIEW SQL)
- `alembic/versions/0005_valuation_metrics_view.py` (NEW: CREATE VIEW)
- `app/schemas.py` (NEW: Page, MetricOut)
- `app/repositories/metrics.py` (NEW)
- `app/services/metrics.py` (NEW)
- `app/routers/metrics.py` (NEW)
- `app/main.py` (UPDATE: include_router)
- `tests/test_metrics.py` (NEW)

## Change Log
- 2026-07-08: Story 1.7 구현 — valuation_metrics SQL VIEW(이식성·윈도우함수·NULLIF), /metrics API(필터·봉투·레이어). 라이브 삼성·하이닉스 실지표 계산 검증. pytest 39 passed. EV/EBITDA는 감가상각비 부재 시 EBIT 근사(COALESCE).
- 2026-07-09: BMAD 3-layer 코드리뷰(Blind/EdgeCase/Auditor). **Patch 1건**: YoY 윈도우 `PARTITION BY corp_code, quarter ORDER BY year`로 수정(직전행→전년 동분기, QoQ 오표기 해소; 연간 데이터 결과 불변). 분기 YoY 회귀 테스트 추가 → **pytest 40 passed**. Deferred 6건(최신가 NULL시총·음수분모·YoY gap·404·ORM매핑·AD-6 시계열 봉투), Dismissed 10건(축약 아티팩트 2·유니크제약 반증 2 등). Status → done.
- 2026-07-09: GPT 교차검증(21건) triage. **Patch 1건**: `/metrics` sort 파라미터 구현(SORT_COLUMNS 화이트리스트로 인젝션 차단, 허용밖 필드 400) + 누락된 `min_payout_ratio` 필터 추가(API명세 정합). sort/필터 회귀 테스트 추가 → **pytest 41 passed**. Deferred 5건(corp_code검증·price_date노출·VIEW성능·PG통합테스트·debt/cash NULL), Dismissed 4건. 나머지는 기존 리뷰와 중복.
