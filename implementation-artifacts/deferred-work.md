# Deferred Work

## Deferred from: code review of story-1.1 (2026-07-08)

- **API 키 필수화** — `dart_api_key`·`ecos_api_key`를 `Field(...)`로 필수화. 지금 필수화하면 키 없이 부팅하는 스캐폴딩/테스트가 깨지므로, 키가 실제 필요해지는 **Story 1.2(DART 수집)** 착수 시 적용. (현재는 빈 SecretStr 기본값)
- **`extra="forbid"`로 .env 오타 방지** — `ECOS_API_KEY` 오타가 조용히 무시되는 리스크. 유연성 트레이드오프라 보류. 운영/CI 도입 시 재검토(또는 .env.example 대비 검증 스크립트).

## Deferred from: code review of story-1.2 (2026-07-08)

- **동시성 안전 upsert** — 현재 `SELECT→INSERT`는 단일 프로세스 배치엔 안전하나, 병렬 수집 시 같은 자연키 동시 insert가 `IntegrityError` 가능. 병렬화할 때 PostgreSQL `insert().on_conflict_do_update()`로 전환(SQLite 호환 위해 dialect 분기 필요).
- **계정명 중복 우선순위** — 같은 account_nm이 여러 재무제표에 나올 때 현재 "첫 값 유지"(DART 응답순 안정적이라 실무상 결정적). 엄밀히는 sj_div/account_id 우선순위 필요. 문제 발생 시 보강.
- **어댑터 타입 계약** — `base.py` SourceAdapter가 `Any` 반환. `TypedDict`(RawPayload/CompanyRecord/FinancialRecord)로 스키마 강제하면 타입체커가 계약 위반을 잡음.
- **감가상각비 라벨** — DART가 "유형자산감가상각비" 등으로 제공. 후보 라벨 추가 확인 필요(현재 2개 후보).

## Deferred from: code review of story-1.3 (2026-07-08)

- **KRX 동시성 upsert** — prices도 SELECT→INSERT 패턴. 병렬 수집 시 on_conflict 필요(1.2와 동일).
- **KRX 예외 타입 세분화** — 현재 단일 `KrxAdapterError`. `KrxAuthError`/`KrxNoDataError`/`KrxRateLimitError`/`KrxSchemaError`로 분리하면 실패 원인 분류·재시도 정책이 명확.
- **병합 결측률 임계치** — `_merge_frames`가 outer-join(한쪽만 있는 날 null). ohlcv-only/cap-only 날짜 비율이 임계치 넘으면 실패로 승격하는 정책.
- **종목 부분성공 status** — 100거래일 중 일부만 cap 매칭 시 success/partial/failed 세분화 + 누락 날짜 수 반환.
- **원천 테이블 감사 메타** — financials/prices에 `ingested_at`, `source_run_id` 등 추가하면 "이 null 누가 언제 넣었나" 추적 가능. 전 원천 테이블 공통 적용 검토.
- **KRX rate-limit/circuit breaker** — 현재 pykrx 자체 호출만. 과호출·로그인반복 방어(sleep/backoff/jitter) 추가. 인증 실패는 재시도 금지.

## Deferred from: code review of story-1.4 (2026-07-08)

- **매크로 값 정밀도(Numeric)** — `MacroIndicator.value`가 Float. 금리·환율은 `Numeric(18,6)`이 재현성 좋음. 스코어 계산에서 부동소수점 오차 우려 시 전환.
- **ECOS DB-native upsert** — SELECT→INSERT 패턴. 병렬 시 on_conflict 필요(전 원천 공통).
- **ECOS circuit breaker/호출한도** — 현재 Session+Retry+최소간격만. 일일 호출한도 초과 계열은 재시도 말고 다음 실행으로 미루는 정책.
- **주기 확장(Q/S/A)** — `_time_to_iso`가 M/D만. 분기·반기·연 지표 카탈로그 추가 시 변환규칙 + `frequency` enum.
- **원천 메타데이터** — macro_indicator에 stat_code·item_code·unit_name·ingested_at 추가하면 "이 값 어디서 왔나" 추적. financials/prices와 공통 적용 검토(반복 지적).
- **카탈로그 smoke test** — 지표별 최소 예상 건수(예: 최근1년 bond_3y≥200) 검증으로 코드 변경·INFO-200 조용한 실패 탐지.

## Deferred from: story-1.7 (2026-07-08)

- **감가상각비 미수집 → EV/EBITDA 부정확** (Major): DART `fnlttSinglAcntAll`에 감가상각비 라인이 없어 EBITDA를 EBIT로 근사(COALESCE 0). 반도체 등 자본집약 기업은 EBITDA 과소→EV/EBITDA 과대. **해결책 후보**: (a) DART 손익계산서 주석/현금흐름표 별도 파싱, (b) 사업보고서 XBRL 상세, (c) 유형·무형자산 증감으로 추정. M&A 스코어(2.3) 저평가 요소 정확도에 직결이라 우선순위 높음.
- **뷰 PBR/PER의 과거 행 시총** — 현재 뷰는 모든 연도 행에 '최신' 시총을 붙임(현재 밸류에이션 관점). 과거 시점 PBR이 필요하면 행 시점의 시총 조인 필요.
- **분기 데이터 TTM/YoY** — 현재 연간(reprt 11011) 기준 LAG(1)=전년. 분기 수집 시 누적보고(반기=H1) 차분 처리 + LAG(4)로 전환 필요.

## Deferred from: code review of story-1.7 (2026-07-09)

- **최신가 선택이 market_cap NULL 행도 채택** (Medium) — 뷰의 최신가 상관서브쿼리가 `MAX(p2.date)`를 무조건 선택. 최신 행이 거래정지 등으로 `market_cap` NULL이면 유효한 이전 시총이 있어도 pbr/per/ev_ebitda가 전부 NULL. 해결: 서브쿼리에 `AND p2.market_cap IS NOT NULL` 추가(단일가격 원천 KRX에선 현재 미발생이라 defer). [app/sql_views.py:40]
- **음수 분모 미방어 → 지표 부호 왜곡** (Medium) — `NULLIF(x,0)`은 0만 방어. 적자기업은 음수 PER·음수 payout_ratio를 유효값처럼 반환하고, 이전연도 순이익이 음수면 `yoy_income_growth` 부호가 뒤집힘(-100→-50이 -50%로 표기). 손실 종목 표현 규칙(음수 표기 vs N/A) 제품 결정 후 CASE 가드 추가. [app/sql_views.py:23,29,35-36]
- **YoY 연도 비연속(gap) 오산** (Medium) — LAG는 직전 '행'을 참조하므로 2023→2025처럼 연도가 빠지면 2년치 성장을 1기 성장으로 계산(NULL 아님, 조용히 틀림). 연속성 검증(연도차=1 확인) 또는 날짜차 기반 로직 필요. 코드리뷰 patch로 window를 `PARTITION BY corp_code, quarter ORDER BY year`로 바꿔 QoQ 오표기는 해소했으나 gap 문제는 별도. [app/sql_views.py:41]
- **`GET /metrics/{corp_code}` 미존재 종목 200 `[]`** (Low) — 오타/미존재 종목과 '재무 아직 없음'을 구분 못 함(404 없음). REST 계약(API_SPEC) 확정 시 404 여부 결정. [app/routers/metrics.py:33-35]
- **스토리 소스트리 `ValuationMetric` ORM 매핑 미구현(문서 불일치)** (Low) — 스토리 소스트리에 `models.py# UPDATE: ValuationMetric(읽기전용 뷰 매핑)`이 있으나 실제로는 리포지토리가 `text()` raw SQL로 뷰를 조회(의도된 설계). 스토리 소스트리 문구를 정정하거나, ORM 뷰 매핑이 정말 필요하면 추가. 기능 영향 없음.
- **`GET /metrics/{corp_code}` 시계열 AD-6 봉투 미적용** (Medium, 사용자 결정=defer 2026-07-09) — 시계열 엔드포인트가 `list[MetricOut]` 원시 리스트 반환. AD-6("모든 라우터 목록 봉투")과 긴장하나, 스토리 AC6이 봉투 없이 기술했고 시계열은 페이지네이션 대상이 아니라 page/size가 무의미. **결정: 리스트 유지 + AD-6 예외로 문서화.** 프론트(Epic 3) API_SPEC 확정 시 봉투 통일 여부 최종 결정. [app/routers/metrics.py:33]

## Deferred from: GPT cross-check of story-1.7 (2026-07-09)

- **corp_code 형식 검증 없음** (Med, GPT #14, 사용자 선택=이번엔 defer) — `GET /metrics/{corp_code}`의 path param이 `str`이라 `abc`·`005930`(6자리)·`../../x`도 통과해 DB까지 감. 파라미터라이즈드 쿼리라 인젝션은 없으나 AD-5(8자리 정식키) 정합·입력검증 차원에서 `corp_code: str = Path(..., pattern=r"^\d{8}$")` 권장. [app/routers/metrics.py:34]
- **price_date/market_cap 미노출로 auditability 부족** (Med, GPT #2) — 뷰가 '어느 날짜 시총'으로 PBR/PER/EV를 계산했는지 응답에 없어, 같은 종목의 과거 연도 행이 최신 시총 기준임을 API 사용자가 식별 불가. 뷰에 `lp.date AS price_date, lp.market_cap`을 노출 + MetricOut 추가하면 accepted된 '과거행 최신시총' 한계를 투명화. [app/sql_views.py]
- **일반 VIEW 성능(운영 규모)** (High, GPT #4/#5) — valuation_metrics는 매 조회마다 financials+prices+LAG+상관서브쿼리를 재계산. COUNT와 목록이 각각 실행돼 비용 2배, 계산컬럼(pbr/roe/debt_ratio) 필터는 인덱스 미탐→full scan. 종목·연도 증가 시 병목. 대응: (a) 단기 CTE+`COUNT(*) OVER()`로 1회 계산, (b) 운영 PostgreSQL은 materialized view 또는 physical metrics 테이블 승격 + pbr/roe/debt_ratio 인덱스. 승격 기준(종목수·응답시간 임계) 정의 필요.
- **AC5 이식성 실검증(PostgreSQL 통합 테스트)** (Med, GPT #6/#15) — 현재 테스트는 SQLite in-memory만. CREATE VIEW·ROUND·WINDOW(LAG)·상관서브쿼리·LIMIT/OFFSET을 PostgreSQL 컨테이너(testcontainers 또는 CI PG 서비스)로 최소 1회 검증해야 '동일 뷰 SQL 양쪽 동작(AC5)'이 실증됨. 정렬 NULL 순서(SQLite=NULLS FIRST/PG=NULLS LAST 기본차)도 함께 확인.
- **debt/cash NULL → EV/EBITDA 전체 NULL** (Med, GPT #7) — `market_cap + total_debt - cash`는 하나라도 NULL이면 NULL. DART 수집서 debt/cash 누락 가능→EV/EBITDA 대량 NULL 가능. 보수적 근사 원하면 `COALESCE(total_debt,0)`·`COALESCE(cash,0)`(감가상각비 COALESCE 패턴과 일관). 단 '원천 결측 vs 실제 0'은 metadata로 구분해야 하므로 정책 결정 후 반영. [app/sql_views.py]
