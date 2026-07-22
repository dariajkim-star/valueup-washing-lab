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
- **음수 분모 미방어 → 지표 부호 왜곡** (Medium) — ~~`NULLIF(x,0)`은 0만 방어~~ **[일부 patch됨 2026-07-10, GPT 2차]**: roe·roa·pbr·per·ev_ebitda·debt_ratio·payout_ratio는 `CASE WHEN 분모>0` 가드로 음수 분모→NULL 처리(스크리너 오염 해소). **남은 defer**: `yoy_income_growth`는 LAG 기반이라 이전연도 순이익이 음수면 부호 왜곡(-100→-50이 -50% 표기) — 성장률 % 자체의 음수기저 한계라 별도. [app/sql_views.py]
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

## Deferred from: GPT 2차 cross-check of story-1.7 (2026-07-10)

- **과거 마이그레이션이 app 상수에 의존(재현성)** (Med) — `0005_valuation_metrics_view.py`가 `app/sql_views.py`의 `CREATE_VALUATION_METRICS`를 import. 이후 뷰 SQL을 수정하면 새 DB에서 0005 실행 시 '당시 SQL'이 아니라 수정본이 돎 → 마이그레이션 히스토리 재현 불가. 마이그레이션/테스트 SQL 공유는 drift 방지 위한 의도적 선택(스토리 Dev Notes)이나, 뷰 변경이 잦아지면 버전별 불변 SQL 모듈(`sql_views_v0005.py`)로 분리 검토.
- **`/metrics` total과 items가 동일 스냅샷 아님** (Low) — READ COMMITTED에서 COUNT와 목록 SELECT 사이 데이터 갱신 시 total≠len(items) 가능. 단순 조회 API라 eventual consistency 수용(문서화). 강한 일관성 필요 시 `COUNT(*) OVER()` 단일 쿼리 or repeatable-read.

## Deferred from: code review of story-1.5 (2026-07-10)

밸류업 공시 파서의 best-effort 정제 — 실제 DART 원문 다양성 샘플 확보 후 튜닝. raw_text가 원문 보존이므로 재파싱 가능(파괴적 아님). [app/ingest/dart_valueup.py]
- **ROE가 인접 지표 %를 잡음** (Med, EdgeCase F2) — `_ROE_RE`의 20자 윈도우가 "ROE 개선…배당성향 30%"에서 30을 ROE로. 윈도우 축소/키워드 경계 필요(부분해라 실샘플 필요).
- **"30%→35%"에서 FROM 채택** (Med, F3) — `.search`가 첫 %를 잡아 현재치(30)를 목표로 저장(목표는 35). 화살표/증감 문맥 판별 필요.
- **period 과거범위 오표기** (Med, F5) — start≤end 검증은 **patch됨**(2026-07-10). 남은 건 "2020-2023 실적…" 같은 과거범위를 목표기간으로 잡는 문맥 오인 — 목표/기간 앵커는 실공시 샘플 후.
- **report_nm이 이행현황/철회도 매칭** (Med, F9) — "기업가치제고계획" 부분일치가 "…이행현황"·"…철회신고서"도 잡아 계획 아닌 공시를 적재. 부정 키워드 제외는 실제 report_nm 샘플 확인 후(정정 공시는 유지해야 함).
- **인라인 산문의 인접지표·"현재→목표" 우변 채택** (High, GPT G2/G3 잔여) — 셀 경계보존(개행)으로 표는 해결했으나, 한 줄 산문 "현재 ROE 5%, 목표 ROE 10%"·"30%→35%"에서 첫 값(현재/출발)을 채택하는 문제는 목표 키워드 앵커·A→B 우변 로직 필요(실공시 샘플 후). raw_text 보존+전체교체로 재파싱 가능.
- **raw_text가 원문(태그포함) 아님** (Med, GPT G12) — 태그·셀·줄바꿈 제거된 평문이라 셀 단위 재파싱 불가. 원본 XML/ZIP 별도 저장 + `plain_text` 컬럼 분리 검토.
- **DB CheckConstraint 부재** (Med, GPT G15) — `target_pbr>0`·비율 범위·날짜형식 등 DB 강제 없음. 애매값 null 저장 원칙과 병행해 일부 제약 추가 검토.
- **SELECT→INSERT 동시성** (Med, GPT G14) — 병렬 수집 시 같은 자연키 동시 INSERT가 UNIQUE 위반. **코드베이스 공통 defer**(1.2/1.3/1.4와 동일, 병렬화 시 on_conflict).
- **`IngestResult.failed`의 `str(e)` 노출 표면** (Low, GPT G18) — 예상외 예외 메시지가 URL/DB정보 포함 가능. **코드베이스 공통**(전 ingest 함수), allowlist 에러코드로 후속.
- **decode utf-8-first mojibake** (Low) — CP949 바이트가 우연히 유효 UTF-8이면 조용히 깨짐. 페이로드/헤더 기반 인코딩 감지가 정석.

## Deferred from: 일괄 code review of 1-9·1-10·2-7·2-4 (2026-07-13, GPT)

- **score_run 배치 메타데이터(run_id·status·config_hash·완료 판정)** (High×2, 2-4) — (a) `latest_as_of`가 '최신 완료 스냅샷'이 아니라 단순 MAX(as_of)라 부분/디버그 실행이 기본 조회를 오염 가능, (b) 같은 as_of 안에 서로 다른 코드/설정 세대의 점수가 섞여도 식별 불가. 해결책은 score_run 테이블(+staging 원자 활성화) — 엔진·API·운영 절차를 가로지르는 별도 스토리. v1 완화: 엔진 docstring "게시용=전체 실행" 계약 + 부분 실행은 테스트 용도 문서화.
- **입력 원천별 watermark/최소 커버리지 검증** (Med, 2-7) — `not metrics and not ownership` 가드는 두 원천 동시 공백만 방어. 한쪽만의 ETL 장애는 권위 있는 null로 덮일 수 있음. score_run과 같은 스토리 계열.
- **count/items 스냅샷 불일치** (Low, 2-4) — 1-7의 기존 defer(eventual consistency 수용)와 동일 계열. completed-run 서빙 도입 시 자연 해소.
- **미인식 배당 라벨 로그/집계** (Low, 1-9, GPT 제안) — allowlist 밖 se 라벨을 로깅해 신규 라벨(예: 현금배당금총액(원)) 발견 시 명시적으로 추가하는 운영 루프.

## Deferred from: code review of story-2.3 (2026-07-10, GPT)

- **가격 point-in-time 미보장 → 과거 as_of의 valuation_score 오염** (High, 최중요) — `valuation_metrics` VIEW가 as_of와 무관하게 전역 최신가(`MAX(p2.date)`)를 붙임(1.7 설계). mna_engine의 pbr·ev_ebitda(valuation_score 35% 가중)가 과거 as_of에서 미래 가격을 사용. 해결: VIEW에 price_date 노출 + repository에서 `price_date <= as_of` 필터 — 1.7 VIEW·/metrics API와 공유되는 변경이라 별도 스토리. [app/sql_views.py, app/repositories/mna_score.py]
- **전년도 Q4 사업보고서 연초 사용** (High) — as_of=2025-01-15에 FY2024 사업보고서(통상 3월 공시)가 `year<2025`로 통과. 2-1의 available_at defer와 동일 뿌리 — rcept_dt 수집 스토리로 일괄 해결.
- **market universe / 생존편향** (High) — 백분위 모집단에 상장·상폐일 필터 없음(미래 상장사가 과거 모집단에, 상폐사가 과거에서 소실). company에 상장/상폐일 데이터 자체가 없어 DART 수집 스토리 선행 필요.
- **macro 신선도(staleness) 계약** (Med) — 월간 시계열 수집 중단을 금리 동결로 오인 가능. frequency별 기대 주기 검사 + ingestion heartbeat 설계 후속. 단 한은 기준금리는 변경 간격이 1년+일 수 있어 단순 max_age 규칙은 오탐(GPT 자체 부연).
- **부분 실행 스냅샷 혼합** (Med, 문서화됨) — corp_codes 부분집합 실행 시 같은 as_of에 구/신 모집단 점수 혼재. v1은 "게시용=전체 실행" 계약으로 완화(run docstring), 진짜 필요해지면 population_version/staging 교체.

## Deferred from: code review of story-2.1 (2026-07-10, GPT)

- **1~3분기 보고서의 동일연도 내 look-ahead 잔여 리스크** (High) — gap_engine의 `latest_metrics`/`latest_financial_buyback`이 같은 연도 사업보고서(quarter=4)는 무조건 배제(다음해 공시 확정사실이라 안전)하지만, 분기/반기 보고서는 실제 공시일을 모르므로 완전 차단 불가. as_of가 실제 공시일보다 이른 시점이면 여전히 미래정보를 쓸 수 있음. **완전 해결**: `financials`(및 `valuation_metrics` 뷰)에 실제 공시일(`available_at`, DART `rcept_dt`) 컬럼 추가 필요 — DART 어댑터(dart.py)·스키마·뷰를 가로지르는 별도 스토리 스코프. [app/repositories/valueup_score.py]
- **날짜 컬럼 전부 String(10) → Date 타입 전환** (Low) — 2.1은 `run()` 진입점에서 `as_of` 포맷만 fail-fast 검증. 전체 7개 테이블(0001~0008 마이그레이션 전부)이 날짜를 문자열로 저장하는 기존 컨벤션 자체를 바꾸는 건 대규모 변경이라 스코프 밖.
- **valueup_score도 select-then-insert 동시성 미보장** (Low, 공통) — `upsert_financial`/`upsert_ownership`/`upsert_valueup_plan`과 동일한 기존 공통 defer(단일 프로세스 배치 v1, 병렬화 시 `ON CONFLICT` 전환).
- **target_pbr 여전히 스코어 미사용** (Low, 2.1 스토리 자체 결정) — 리드 확정: 계산 제외, `valueup_plan` 원본에 참고값으로만 존재. 2.4(갭분석 API)에서 응답 노출 여부 결정.

## Deferred from: code review of story-1.8 (2026-07-10, 자체+GPT 교차검증)

buyback 집계는 실공시 샘플 없이 보수적 규칙(총계 우선·상충/소계-only는 null)으로 근사. 실샘플 확보 후 튜닝.
- **`"-"`의 의미(0 vs 미상) 미확정** (High, GPT) — 현재 `"-"`→None(unknown, 보수적). 실공시에서 대시가 "변동 없음(=0)"을 뜻하면 공시된 0을 null로 잘못 저장(None-safe upsert로 과거 값 잔존 가능). **실응답 fixture로 의미 확정 후** tri-state(disclosed_zero/unknown/value) 파서 전환 판단. [app/ingest/dart.py:_parse_quantity]
- **취득 목적 미분류 + 처분(dsps) 미사용** (High, GPT) — 모든 `change_qy_acqs`를 주주환원성 매입으로 취급(합병·임직원보상 등 포함), 취득 후 전량 처분해도 purchased_only 가능. `acqs_mth1/2/3` 실어휘 확보 후 목적 분류 + `change_qy_dsps`·`trmend_qy` 활용은 **2.1 buyback_status 설계**에서 반영.
- **change_qy_* 기간 의미(분기 누적 vs 단독)** (Med, GPT) — 연간(11011, quarter=4) 기준으론 무해. 분기 수집 시 누적/차분 확정 필요(1-7 TTM defer와 동일 계열). 필드명 `_ytd_qty` 리네이밍 검토.
- **materiality 임계 부재(1주=10%와 동일 30점)** (Med, GPT) — `>0` 이진 신호의 의도된 한계. 2.1에서 `취득수량/발행주식수` 등 임계(config) 도입 검토.
- **소계-only 응답 데이터 손실** (Med) — 소계 계층 검증 불가로 null 처리(null>오값). 실샘플에서 소계 구조 확정되면 승격.
- **buyback_status 상태 세분화** (Med, GPT) — retired/purchased_only/none/unknown(스펙 반영됨) 외 acquired_and_disposed 등 세분은 2.1 설계에서.
- **요약행 판정 공유 헬퍼** (Low, 자체) — `_buyback_row_kind`(dart.py)와 `_is_summary`(dart_ownership.py)가 같은 1.6 교훈을 중복 인코딩. 공유 헬퍼 추출은 어댑터 공통 정비 시.
- **DEV_PLAN.md의 '금융공공데이터' buyback 출처 잔존** (Low, 자체) — 구식 계획 문서. 이중 writer 오해 소지, 문서 정비 시 정리.

## Deferred from: code review of story-1.6 (2026-07-10)

대부분 **전 DART 어댑터 공통** — 개별 스토리가 아니라 dart.py 계열 일괄 개선으로 후속.
- **rate-limit(HTTP 200 + status "020") 미재시도** (Low, 공통) — urllib3 Retry는 429/5xx만. DART 쿼터 초과는 200+status라 재시도 없이 hard fail. 1.3/1.4의 circuit-breaker defer와 동일 계열.
- **`resp.json()` ValueError 처리를 dart.py/dart_valueup에도 전파** (Med, 공통) — 1.6 `_get_json`은 ValueError 포착으로 고쳤으나, `dart.py:_get`·`dart_valueup:_get_json`은 아직 RequestException만 잡음(비JSON 200에서 raw ValueError 누출). 일괄 반영 필요.
- **log(type명) vs `failed`(str(e)) 불일치** (Low, 공통) — 전 ingest 함수에서 로그는 예외 타입명만, failed엔 str(e). 진단 일관성 위해 통일(안전 에러코드/ID) 후속.
- **DB CheckConstraint(비율 범위)** (Low, GPT계열) — ownership에 `0<=largest/treasury<=100` 등 DB 제약 없음(앱단 가드만). 다른 원천과 함께 제약 정책 후속.
- **합계행 tesstk 결측 시 개별행 복구** (Low) — stockTotqySttus 합계행에 `tesstk_co` 없고 종류별 행에만 있으면 현재 None. 종류별 합산 복구는 복잡도 대비 실익 낮아 defer(합계행 정상이 일반적).

## Deferred from: code review of story-2.5 (2026-07-13, GPT)

- **valueup·metrics 라우터 HTTP 경계 정비(2.5와 패리티)** — 2.5 리뷰에서 잡힌 세 가지가 기존 라우터에도 동일하게 존재: ① 빈 문자열 필터(`?market=`)가 "필터 없음"으로 확대(truthiness), ② `page` 상한 없음(OFFSET 오버플로 → 500 가능), ③ (해소됨) 422 에러 계약 — 이것만은 main.py 전역 핸들러라 이미 전 라우터에 적용됨. ①②를 2.5와 동일 방식(min_length=1·le=1_000_000·repo `is not None`)으로 /valueup/*·/metrics/*에 적용하는 소규모 정비 스토리 또는 2-6에 편승.
- **as_of 관대 파싱(Dismiss 기록)** — `as_of=2026-07-13T00:00:00`·epoch 문자열도 유효 날짜로 해석돼 200(pydantic v2 lax). 계약을 "달력상 유효한 날짜로 해석 가능한 입력"으로 정의하고 수용 — 유효 날짜로만 해석되고 500·오동작 없음, 2.4와 동작 일치 유지. 엄격 `YYYY-MM-DD` 강제가 필요해지면(외부 공개 등) 정규식 validator를 전 라우터 공통으로.

## Deferred from: code review of story-3.3 재리뷰 (2026-07-13, GPT)

- **2단계 IN 필터의 확장성** — /screening 지표·시총 필터가 "통과 corp_code 집합 → IN 조건" 방식. 현재 33종목 규모에선 정합(COUNT·페이지네이션 SQL 유지, 리뷰어도 확인)하나, 전체 KRX 유니버스로 확장 시 매 요청 전체 뷰 스캔·거대 IN 바인드·DB 파라미터 제한이 병목. 전환 방향: valuation_metrics를 selectable로 매핑하거나 `ROW_NUMBER() OVER (PARTITION BY corp_code ORDER BY year DESC, quarter DESC)` CTE로 메인 쿼리에 직접 JOIN. **유니버스 확대 스토리의 선행 조건.**
- **1~3분기 동일연도 look-ahead(재확인)** — 재리뷰가 2-1 defer를 재발견(명시적 과거 as_of 조회 시 그 해 이후 분기 지표 혼입 가능). 상태 변화 없음: 완전 해결은 공시일(available_at) 수집 스토리 몫, 달력 분기 휴리스틱은 엔드포인트 간 규칙 분기를 만들어 기각. 이번에 docstring "안전"→"부분 차단" 정정 + OpenAPI 설명에 한계 명시로 과대표현만 해소.
- **미지원 업종 판정의 백엔드 명시화(1차 리뷰 defer 유지)** — 프론트 KSIC prefix 추론 대신 백엔드가 score_status(UNSUPPORTED_SECTOR 등)를 내려주는 방향. 레벨2(업종별 변수세트) 스토리와 병합 후보.

## Deferred from: code review of story-3.4 (2026-07-13, GPT)

- **운영 정적 호스팅 SPA fallback rewrite** — dashboard가 BrowserRouter라 /company/:corpCode 직접 진입·새로고침은 서버가 모든 경로를 index.html로 rewrite해야 함. Vite dev는 내장이라 개발 환경은 문제없으나 운영 배포 시 필수 설정 — **배포 스토리(아키텍처 Deferred "배포·운영 envelope")의 체크리스트 항목**.

## Deferred from: code review of gap_engine 트랜잭션 정책 (2026-07-21, party 리뷰)

**결정된 것(이번에 적용):** `gap_engine.run()`의 트랜잭션 정책 = **종목별 커밋 + 실패 목록**
(`ScoreRunResult`). 수집 레이어 `app/ingest/run.py`와 동일 정책·동일 결과 표현으로 통일.
세션 소유권도 함께 이동 — `run(session, ...)` → `run(as_of, ..., session_factory=SessionLocal)`.

검토한 대안과 기각 사유(재논의 시 출발점으로 쓸 것):

| 안 | 내용 | 장점 | 기각 사유 |
|---|---|---|---|
| 전량 원자성 | 하나 실패 시 전량 롤백 | as_of 스냅샷 시점 일관성 보장 | 1종목 실패로 전량 소실 + **어느 종목이 왜 실패했는지 정보까지 소실** |
| 종목별 커밋 ✅ | 실패는 목록에 담고 계속 | 부분 성공 보존, 실패 원인 구조화, 기존 레이어와 일관 | 같은 as_of에 실행분이 섞일 수 있음 → `complete` 플래그로 **숨기지 않고 노출**해 수용 |
| 스테이징 스왑 | 임시 테이블 계산 후 원자적 교체 | 무중단 + 완벽한 일관성 | 스키마 변경·다운스트림 전면 수정. 현 규모에 오버엔지니어링 |

- ~~**`ScoreRunResult.complete` 소비자 없음**~~ — **해소(2026-07-22, Story 4-1)**. `run()`의 첫
  프로덕션 호출자 `app/analysis/run_scoring.py`가 `complete`를 **종료 코드**로 번역한다
  (0=완전 / 1=부분 실패 / 2=사용법·입력 오류). 실행 메타 테이블(`score_run`)은 2026-07-14 리드
  결정으로 이미 닫혀 있어 재론하지 않았고, API 노출은 배포 스토리 몫으로 남는다. 근거: 배치의
  1차 소비자는 셸·스케줄러이고 종료 코드가 그 계층이 이해하는 유일한 신호 — 요약만 찍고 0을
  반환하면 엔진이 애써 노출한 `complete`가 그 지점에서 다시 숨겨진다.
- ~~**`mna_engine.run()` 미적용**~~ — **해소(2026-07-22, Story 4-2)**. 판단 결과는 gap과 **반대**인
  **전량 원자성 + 실패 보고**였다. 근거: (1) `mna_target_score`는 백분위 순위라 세대가 섞이면
  "일부만 오래된 값"이 아니라 순위 자체가 무의미해진다(gap은 종목별 절대 측정치라 다르다),
  (2) 읽기가 전부 루프 이전에 끝나 루프 안은 순수 계산 + upsert뿐이라 종목별 커밋이 방어할
  실패 유형 자체가 구조적으로 적다, (3) gap에서 원자성을 기각한 사유("실패 정보까지 소실")는
  실패 목록을 DB가 아니라 `MnaRunResult`·로그로 남기면 해소된다 — 롤백되는 건 점수뿐이고
  실패 사실은 보고된다. 세션 소유권도 엔진으로 이동(`run(as_of, corp_codes, *, session_factory)`).

## Deferred from: code review 전체 스캔 (2026-07-21, party 리뷰)

- **gap_engine 종목당 3쿼리 N+1** — `run()`이 종목마다 latest_valueup_plan·latest_metrics·
  latest_financial_buyback을 개별 호출(33종목 × 3 = 99왕복, 현 규모 밀리초). 전체 KRX
  유니버스(~2,600종목) 확대 시 ~7,800왕복이 배치 병목. 전환 스케치: mna_engine의 배치 패턴
  (`all_latest_metrics(session, as_of)` — 모집단을 루프 전 1회 조회 후 dict 룩업)을 gap repo에
  이식. plan은 corp별 최신 1건이 필요하므로 `ROW_NUMBER() OVER (PARTITION BY corp_code ORDER BY
  disclosure_date DESC, plan_id DESC)` 또는 전건 조회 후 Python 그룹핑. 읽기 배치는 쓰기 전
  단일 세션에서, 쓰기는 종목별 트랜잭션 유지(2026-07-21 정책과 양립). **유니버스 확대 스토리의
  선행 조건**(3.3의 "2단계 IN 필터" 항목과 같은 트리거 — 두 항목을 한 스토리에서 함께 해소).
- **배포 전 보안 게이트(비협상 체크리스트)** — 현재 전 엔드포인트 무인증·CORS 미설정·
  rate-limit 없음·`/screening` page 상한 1,000,000(size 100과 조합 시 저비용 DB 부하 유발 가능).
  로컬 단독 실행에선 리스크 0이나, **외부 노출(EC2·터널링 포함) 전 반드시**: (1) 최소 API 키
  인증 또는 IP 제한, (2) CORSMiddleware 명시 설정, (3) 리버스 프록시 레벨 rate-limit,
  (4) page 상한 현실화(예: le=10_000) 또는 keyset 페이지네이션. 3-4의 "SPA fallback rewrite"와
  같은 **배포 스토리 체크리스트 항목**.
- **임포트 시점 engine/settings 생성(fail-fast로 결정, Dismiss 기록)** — create_engine은 lazy
  connect라 임포트 사망 경로는 설정 기형뿐이고 그건 부팅 거부가 정당(app/db.py docstring 명시).
  orchestrated 배포에서 liveness/readiness 분리가 필요해지면 lazy-init(get_engine() 팩토리) 재검토.
- **`_washing_flag`의 buyback_planned raw 전달(Dismiss 기록)** — 방어 누락으로 보였으나 재검증
  결과 의도된 설계: 이미 bool|None 3치라 래핑 불필요, None은 Kleene unknown으로 정확히 처리.
  회귀 테스트 2건으로 계약 고정(test_washing_flag_buyback_planned_none_*).

## Deferred from: progress_rate 일 단위 정합화 (2026-07-21, 결정 B 후속)

- **단년 계획(end==start) 수용 여부** — 연 단위 시절 `end<=start → None`은 0나눗셈 방어였으나,
  일 단위 전환으로 단년 계획(2025~2025)도 분모 364일로 계산 가능해졌다. 다만 AC3 계약이
  "null·end<=start 무효"로 문서화돼 있어 수용은 계약 변경 — 실데이터에 단년 계획 공시가
  실제로 존재하는지 확인 후 결정. **트리거: 단년 계획 공시 실물 발견 시.**
- **발표 자료 숫자 재확인** — progress_rate 예시 숫자가 덱·리허설 스크립트에 있으면 일 단위
  기준으로 갱신 필요(임계 근처 예시는 판정 자체가 바뀔 수 있음). **트리거: 다음 발표 준비 시.**
