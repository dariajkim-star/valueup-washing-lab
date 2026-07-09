---
baseline_commit: fde6b860e4de5af73a53d72e6c31110d695f626c
---

# Story 1.2: 재무제표 수집 (DART)

Status: done

## Story

As a 애널리스트,
I want DART에서 기본정보와 분기 재무제표(EBITDA·순부채·배당·자사주 항목 포함)가 DB에 적재되는 것,
so that ROE·EV/EBITDA·배당성향 계산과 워싱/M&A 스코어의 원천이 준비된다.

## Acceptance Criteria

1. **Given** `company`·`financials` 테이블 모델과 alembic 마이그레이션(0002), **When** `alembic upgrade head`, **Then** 두 테이블이 생성된다. 키는 `corp_code`(8자리, AD-5), `financials` 자연키 (corp_code, year, quarter).
2. **Given** `dart_adapter`(공통 인터페이스 `fetch()→normalize()→upsert()`, AD-3), **When** 한 종목 corp_code로 수집하면, **Then** `company`(corp_code, stock_code, corp_name, market, sector)와 `financials`(revenue, net_income, equity, total_assets, total_liabilities, operating_income, depreciation, cash, total_debt, dividend_total, buyback_amount, buyback_retired_amount)가 적재된다.
3. **Given** 이미 적재된 종목, **When** 같은 배치를 재실행하면, **Then** 자연키(corp_code, year, quarter) 기준 **멱등 upsert**로 중복 행이 생기지 않는다(AD-7).
4. **Given** DART XBRL 계정명이 표준과 다를 수 있음, **When** 특정 계정을 못 찾으면, **Then** 해당 필드는 `null`로 남고 수집은 실패하지 않는다(NFR2).
5. **Given** `DART_API_KEY` 미설정, **When** 라이브 수집을 시도하면, **Then** 명확한 에러 메시지로 안내한다(부팅은 막지 않음 — 키는 이 스토리에서 필수화, deferred-work의 "키 필수화" 반영).
6. **Given** fixture(가짜 DART 응답), **When** 정규화·upsert 단위 테스트를 돌리면, **Then** 매핑·멱등성이 검증된다(라이브 키 없이 CI 가능).

## Tasks / Subtasks

- [x] **T1: 모델 & 마이그레이션** (AC: 1) — `Company`·`Financial`(복합 유니크 corp_code+year+quarter), 리비전 `0002` → upgrade head 검증(테이블 2개+16컬럼 생성)
- [x] **T2: 소스 어댑터 인터페이스** (AC: 2) — `app/ingest/base.py` `SourceAdapter`(fetch→normalize→upsert, AD-3)
- [x] **T3: DART 어댑터** (AC: 2, 4, 5) — `app/ingest/dart.py`. **OpenDART REST(requests)** — company.json + fnlttSinglAcntAll.json. 계정 방어적 매핑(누락→null), CFS→OFS 폴백, 키 미설정 시 `DartAdapterError`. **라이브 삼성전자 검증 완료**.
- [x] **T4: 멱등 upsert** (AC: 3) — `app/repositories/financials.py`, (corp_code,year,quarter) 기준
- [x] **T5: 수집 트리거** (AC: 2, 5) — `app/ingest/run.py` `ingest_financials()`
- [x] **T6: 테스트** (AC: 3, 4, 6) — `tests/fixtures/` + `tests/test_dart_ingest.py`(매핑·null·멱등·키에러). 12 passed

## Dev Notes

### DART API (dart-fss) — 조사 결과
- `dart_fss.set_api_key(settings.dart_api_key.get_secret_value())`
- `dart_fss.get_corp_list()` → corp_code(8자리)·stock_code(6자리)·corp_name·sector. market(KOSPI/KOSDAQ)은 corp_list/별도 매핑.
- `dart_fss.fs.extract(corp_code, bgn_de='YYYYMMDD', report_tp='quarter', fs_tp=('bs','is','cis','cf'))` → BS/IS/CIS/CF DataFrame.
- **분당 100요청 제한** — 배치 시 유의(sleep/재시도).
- 계정 매핑(XBRL 계정명은 회사마다 상이 → 방어적 매핑):
  - revenue=매출액, net_income=당기순이익, equity=자본총계, total_assets=자산총계, total_liabilities=부채총계
  - operating_income=영업이익, depreciation=감가상각비(CF), cash=현금및현금성자산, total_debt=차입금(단기+장기)
  - **dividend_total·buyback_amount·buyback_retired_amount**는 4대 재무제표에 없고 별도 공시(배당사항·자기주식 취득/소각)에서 옴 → v1은 **best-effort, 없으면 null**. 정교한 자사주 소각 수집은 Story 1.6(지분구조)와 연계 또는 후속 보강.

### 아키텍처 제약
- **AD-3**: dart_adapter가 company·financials·valueup_plan·ownership의 유일 writer(이 스토리는 company·financials). 공통 인터페이스 준수.
- **AD-5**: corp_code(8자리) 정식 키. stock_code(6자리)는 company 속성.
- **AD-7**: 멱등 upsert (corp_code, year, quarter).
- **AD-9**: company에 market_cap 없음(시총은 prices=KRX, Story 1.3).
- **AD-2**: 수집은 서빙 레이어와 분리. repository는 upsert 담당.
- **NFR2**: 계정 누락 시 null 허용, 수집 실패 금지.

### deferred-work 반영
- Story 1.1의 "API 키 필수화" defer → **이 스토리에서 DART_API_KEY 미설정 시 명확 에러**(AC5)로 처리.

### 소스 트리 (이 스토리)
```
app/
  models.py                    # UPDATE: Company, Financial 추가
  ingest/base.py               # NEW: SourceAdapter 추상
  ingest/dart.py               # NEW: DART 어댑터
  repositories/financials.py   # NEW: 멱등 upsert
alembic/versions/0002_*.py     # NEW: company/financials 테이블
tests/fixtures/…               # NEW: 가짜 DART 응답
tests/test_dart_ingest.py      # NEW
```

### 테스트 표준
- 라이브 DART 키 없이 **fixture 기반 단위 테스트**(정규화·null·멱등성). SQLite in-memory.
- 라이브 통합은 키 확보 시(수동). CI는 fixture만.

### References
- [Source: epics.md#Story-1.2] — AC 원본
- [Source: db-schema.md] — financials 컬럼(EBITDA·순부채·배당·자사주 소각액 포함)
- [Source: ARCHITECTURE-SPINE.md#AD-3,5,7,9] — 어댑터 writer·키·멱등·시총
- [Source: 1-1-scaffolding-db.md] — Base·db·config(SecretStr 키) 패턴, deferred "키 필수화"
- dart-fss: https://dart-fss.readthedocs.io/ , https://github.com/josw123/dart-fss

### Review Findings (code review 2026-07-08)

**GPT 교차검증 (24건 → 18 patch / 1 decision / 3 defer / 2 dismiss)**

*Patch 적용:*
- [x] [High] 재시도/백오프 — `requests.Session`+`Retry`(429/5xx, backoff 0.6, total 3)
- [x] [High] rate-limit(100/min) — `_RateLimiter`(최소간격 0.65s, 스레드안전)
- [x] [High] **키 노출 방지** — `_get`을 try/except로 감싸 예외에 URL/params(crtfc_key) 미포함
- [x] [High] **total_debt 계산 버그** — 첫매칭 → 단기+유동성장기+장기+사채 **합산**(`_sum_present`). 라이브서 13.2조→19.3조로 정정 확인
- [x] [High] 트랜잭션 정책(decision) — **종목별 커밋 + 실패목록**(`IngestResult`), fetch는 트랜잭션 밖
- [x] [Med] CFS/OFS 폴백 출처 저장 — `financials.fs_div` 컬럼 추가
- [x] [Med] 데이터없음 vs 계정누락 구분 — 빈 accounts면 재무 row 미생성
- [x] [Med] reprt_code/bsns_year fail-fast 검증
- [x] [Med] corp_code 8자리·quarter 1~4 `CheckConstraint`
- [x] [Med] 회계 음수 파싱(괄호·△·유니코드 마이너스)
- [x] [Med] `_pick` 파싱 실패 시 다음 후보로 continue
- [x] [Med] company/financial 갱신 시 None은 기존값 안 덮음(overwrite_null=False)
- [x] [Low] connect/read timeout 분리 `(3.05, 20)`, `requests.Session` 재사용
- [x] [Low] 테스트 보강 — 회계음수·total_debt합·redaction·fail-fast(18 passed)

*Defer:* [x] 동시성 DB-native upsert(on_conflict) — v1 단일프로세스 배치, 병렬화 시 / 계정 순서의존(DART 응답순 안정) / base.py TypedDict 타입 → deferred-work.md
*Dismiss:* config 타입(이미 SecretStr, 번들서 config.py 누락 오인) / 인덱스 명시(Alembic이 index=True 처리)

## Dev Agent Record

### Agent Model Used
claude-opus-4-8 (bmad-dev-story)

### Debug Log References
- **DART 수집 방식 전환(설계 결정)**: dart-fss `fs.extract`(XBRL)가 특정 분기에서 `NoDataReceived`로 불안정·느림 → **OpenDART REST API를 requests로 직접 호출**로 전환. `fnlttSinglAcntAll.json`이 계정명→금액 JSON을 직반환해 normalize에 딱 맞음. **dart-fss 의존 제거**(requirements). 아키텍처 memlog에 결정 기록.
- **라이브 검증 완료**: 삼성전자(00126380) 2024 사업보고서 실수집 — 매출 300.9조·순이익 34.5조·자산 514.5조·자본 402조·KOSPI·005930 정확 매핑. 전 파이프라인(fetch→normalize→upsert→DB) 동작.
- **알려진 한계**: `depreciation`(감가상각비)은 DART가 "유형자산감가상각비" 등 다른 라벨로 제공 → 현재 null. 라벨 후보 보강은 후속(NFR2로 null 허용). 자사주/배당은 별도 공시라 best-effort null(Story 1.6 연계).
- **콘솔 인코딩**: dart 응답에 한글이 많아 Windows cp949 콘솔에서 표시 깨짐(데이터는 정상). 파일 출력·PYTHONIOENCODING=utf-8로 확인.

### Completion Notes List
- `Company`·`Financial` 모델 + 마이그레이션 0002 → `company`·`financials`(16컬럼, buyback_retired_amount 포함) 생성 확인.
- `SourceAdapter` 공통 인터페이스(AD-3) 확립 → krx/ecos가 이후 준수.
- DART 어댑터: 계정 방어적 매핑(후보 라벨, 누락→null NFR2), corp_code(8자리) 키(AD-5), 키 미설정 명확 에러(1.1 defer "키 필수화" 반영, AC5).
- 멱등 upsert(corp_code,year,quarter) — 2회 실행 테스트로 중복 없음·값 갱신 검증(AD-7).
- **검증**: pytest **14 passed**(정규화 매핑·누락 null·멱등성·값 갱신·키 에러·금액파싱·**라이브 삼성**), alembic upgrade head로 테이블 생성 확인, **라이브 실데이터 end-to-end 검증**.

### File List
- `app/models.py` (UPDATE: Company, Financial)
- `app/ingest/base.py` (NEW: SourceAdapter)
- `app/ingest/dart.py` (NEW: DartAdapter — OpenDART REST 기반)
- `app/ingest/run.py` (NEW: ingest_financials)
- `app/repositories/financials.py` (NEW: 멱등 upsert)
- `alembic/versions/0002_company_financials.py` (NEW)
- `tests/fixtures/__init__.py` (NEW: 가짜 DART 응답)
- `tests/test_dart_ingest.py` (NEW)
- `requirements.txt` (UPDATE: dart-fss 제거)
- `.env` (NEW, gitignored: DART_API_KEY)

## Change Log
- 2026-07-08: Story 1.2 구현 — company/financials 모델+마이그레이션, DART 어댑터, 멱등 upsert. pytest 12 passed(fixture 기반).
- 2026-07-08: DART API 키 확보 → **OpenDART REST(requests)로 전환**(dart-fss 제거), 라이브 삼성전자 실데이터 end-to-end 검증. pytest 14 passed.
- 2026-07-08: GPT 교차검증 반영(라운드2) — 18 patch(재시도·rate-limit·키redaction·total_debt합산버그·트랜잭션정책·fs_div·회계음수파싱·CheckConstraint 등). 라이브 재검증(total_debt 13.2→19.3조 정정, fs_div 저장). pytest 18 passed.
- 2026-07-08(후속, 하이닉스 테스트서 발견): **total_debt 계정라벨·중복 버그 수정**. 하이닉스는 `차입금`을 유동/비유동에 중복 사용(삼성은 단기/장기차입금·사채) → dedup dict가 첫 값만 잡아 total_debt=null. `_sum_debt(rows)`로 원본 rows에서 차입 라벨(차입금·리스부채 등) '모든 행' 합산하도록 변경. 하이닉스 25.45조·삼성 19.33조 검증. GPT가 지적한 H9(중복 계정명)가 실제로 발현된 사례.
