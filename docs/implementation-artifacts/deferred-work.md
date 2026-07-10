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
