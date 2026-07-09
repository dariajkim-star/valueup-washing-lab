---
baseline_commit: fde6b860e4de5af73a53d72e6c31110d695f626c
---

# Story 1.5: 밸류업 계획공시 수집 (DART)

Status: ready-for-dev

## Story

As a 애널리스트,
I want DART "기업가치 제고 계획" 공시의 목표치(목표 ROE·배당성향·PBR·목표기간·자사주계획)가 구조화 저장되는 것,
so that Value-up 갭 스코어링(2.1)에서 계획 대비 실적 갭을 잴 수 있다.

## Acceptance Criteria

1. **Given** `valueup_plan` 테이블 모델과 alembic 마이그레이션(0006), **When** `alembic upgrade head`, **Then** 테이블이 생성된다. FK는 `corp_code`(8자리, AD-5), 자연키 유니크 `(corp_code, disclosure_date)`(AD-7).
2. **Given** DART 밸류업 공시 파서(dart_adapter, AD-3), **When** 한 종목 corp_code로 수집하면, **Then** `valueup_plan`(corp_code, disclosure_date, target_roe, target_payout_ratio, target_pbr, period_start, period_end, buyback_planned, **raw_text**)가 적재된다.
3. **Given** 밸류업 공시는 자유서식(구조화 API 없음), **When** 특정 목표 필드를 파싱 못 하면, **Then** 그 필드는 `null`로 남고 수집은 실패하지 않는다(NFR2). **원문 `raw_text`는 항상 보존**한다.
4. **Given** 이미 적재된 공시, **When** 같은 배치를 재실행하면, **Then** 자연키 `(corp_code, disclosure_date)` 기준 **멱등 upsert**로 중복 행이 생기지 않는다(AD-7).
5. **Given** `DART_API_KEY` 미설정, **When** 라이브 수집을 시도하면, **Then** 키/URL을 노출하지 않는 명확한 `DartAdapterError`로 안내한다(부팅은 막지 않음, 1.2와 동일 정책).
6. **Given** fixture(가짜 list.json + 가짜 공시 문서 텍스트), **When** 정규화·upsert 단위 테스트를 돌리면, **Then** 목표필드 파싱·null 폴백·raw_text 보존·멱등성이 라이브 키 없이 검증된다.

## Tasks / Subtasks

- [ ] **T1: 모델 & 마이그레이션** (AC: 1) — `app/models.py`에 `ValueupPlan` 추가(valueup_plan), 리비전 `0006_valueup_plan.py`(revises `0005_valuation_metrics_view`). 유니크 `(corp_code, disclosure_date)`, FK `corp_code→company`. `alembic upgrade head` 검증.
- [ ] **T2: DART 밸류업 어댑터** (AC: 2, 3, 5) — `app/ingest/dart_valueup.py` `DartValueupAdapter(SourceAdapter)`. `fetch`=공시검색(list.json, pblntf_ty="I") + 문서본문(document.xml ZIP) 다운로드→텍스트. `normalize`=raw_text에서 목표필드 best-effort 파싱(못 찾으면 null). **기존 dart.py의 `DartAdapterError`·`_parse_amount`·세션/Retry/`_RateLimiter` 패턴 재사용**(재발명 금지).
- [ ] **T3: 멱등 upsert 저장소** (AC: 4) — `app/repositories/valueup_plan.py` `upsert_valueup_plan(session, rec)`. 자연키 `(corp_code, disclosure_date)`, None은 기존 non-null 안 덮음, `raw_text`는 항상 반영.
- [ ] **T4: 수집 트리거** (AC: 2, 5) — `app/ingest/run.py`에 `ingest_valueup_plans(corp_codes, date_from, date_to)`. 종목별 커밋 + 실패목록(`IngestResult`), fetch는 트랜잭션 밖(기존 `ingest_financials` 패턴 그대로).
- [ ] **T5: 테스트** (AC: 3, 4, 6) — `tests/fixtures/`에 가짜 list.json·공시본문 텍스트 추가, `tests/test_valueup_ingest.py`(파싱 매핑·null 폴백·raw_text 보존·멱등·키에러). SQLite in-memory, fixture 기반(CI에서 라이브 키 불필요).

## Dev Notes

### DART 밸류업 공시 접근 (조사 결과 — 정확도 중요)

밸류업 공시("기업가치 제고 계획")는 **OpenDART에 구조화 재무 API가 없다**. `fnlttSinglAcntAll.json`(1.2) 같은 계정→금액 JSON이 아니라 **자유서식 공시 문서**다. 따라서 2단계:

1. **공시 발견** — `GET https://opendart.fss.or.kr/api/list.json`
   - params: `crtfc_key`, `corp_code`, `bgn_de`(YYYYMMDD), `end_de`, `pblntf_ty="I"`(거래소공시), `page_no`, `page_count`.
   - 응답 `list[]`: `{corp_code, corp_name, stock_code, report_nm, rcept_no, rcept_dt, flr_nm, rm}`.
   - **필터**: `report_nm`에 `"기업가치 제고 계획"` 포함(공백 변형 `"기업가치제고"`, 접미 `"(예고)"/"(공시)"/"(이행)"` 포함 가능 — 공백 제거 후 부분일치로 방어적 매칭). `disclosure_date = rcept_dt`(YYYYMMDD→ISO).
   - status 코드 처리는 1.2 `_get`과 동일: `"000"`=정상, `"013"`=데이터없음(빈 리스트 허용), 그 외 `DartAdapterError`.
2. **본문 파싱** — `GET https://opendart.fss.or.kr/api/document.xml?crtfc_key=..&rcept_no=..`
   - 응답은 **ZIP 바이너리**(원문 XML/HTML). 파이썬 stdlib `zipfile`로 해제 → XML/HTML 태그 제거해 평문 `raw_text` 확보(무거운 의존성 금지: `re`로 태그 스트립 또는 stdlib `html.parser`. lxml/bs4 추가 지양).
   - `raw_text`에서 **best-effort 정규식 추출**(못 찾으면 null, NFR2):
     - `target_roe`: "ROE ... 10%", "목표 ROE 10% 이상" → 10.0
     - `target_payout_ratio`: "배당성향/주주환원율 ... 30%" → 30.0
     - `target_pbr`: "PBR ... 1배/1.0" → 1.0
     - `period_start`/`period_end`: "2024~2026", "2025년 ~ 2027년", "3개년" → 연도 문자열(String(10))
     - `buyback_planned`: "자기주식 취득/매입/소각 계획" 키워드 존재 → True, 명시적 부재/미파싱 → null
   - **파싱 정확도는 본질적으로 제한적**(회사마다 서술이 상이). 정확성 계약의 핵심은 **raw_text 보존 + 멱등 upsert**이고, 목표필드는 튜닝 가능한 패턴셋의 best-effort다. 라이브 실공시 검증은 수동/후속(deferred).

### 재사용 (재발명 금지 — 기존 코드에서 가져올 것)

| 필요 | 기존 위치 | 재사용 방법 |
|---|---|---|
| HTTP 하드닝(세션+Retry 429/5xx backoff 0.6, `_RateLimiter` 0.65s, connect/read timeout 분리) | `app/ingest/dart.py:75-87,165-187` | 동일 패턴 구성. 가능하면 세션/limiter/`_get`을 공용 헬퍼로 추출해 두 어댑터가 공유(과한 리팩터면 패턴 미러링). |
| 키 미노출 예외 | `app/ingest/dart.py` `DartAdapterError`, `_get`의 try/except(예외에 params 미포함) | **import 재사용**. 밸류업 어댑터도 예외 메시지에 crtfc_key/URL 금지. |
| 금액/숫자 파싱(회계 음수·괄호·△) | `app/ingest/dart.py:_parse_amount` | 퍼센트/배수 파싱에 참고·재사용. |
| 어댑터 인터페이스 | `app/ingest/base.py` `SourceAdapter`(fetch→normalize→upsert) | 그대로 구현(AD-3). |
| 멱등 upsert(None-safe 갱신) | `app/repositories/financials.py:upsert_financial` | 같은 구조로 `(corp_code, disclosure_date)` 키. **단 raw_text는 None이어도 항상 반영**(원문 보존이 목적). |
| 종목별 커밋 + 실패목록, fetch는 txn 밖 | `app/ingest/run.py:ingest_financials` | `ingest_valueup_plans`도 동일 패턴. |
| fixture 기반 테스트(라이브 키 없이) | `tests/test_dart_ingest.py`, `tests/fixtures/` | 동일 방식. list.json + 문서본문 텍스트 fixture. |

### 아키텍처 제약

- **AD-3**: dart_adapter가 valueup_plan의 유일 writer. 밸류업 어댑터는 dart 소스로 분류(`source="dart"`). 공통 인터페이스 준수.
- **AD-5**: corp_code(8자리)가 FK·정식 키. stock_code는 company 속성(밸류업엔 불필요).
- **AD-7**: 멱등 upsert 자연키 `(corp_code, disclosure_date)`.
- **AD-2**: 수집은 서빙 레이어와 분리. repository가 upsert 담당, 라우터/서비스 없음(조회 API는 후속).
- **NFR2**: 목표필드 파싱 실패 시 null 허용, 수집 실패 금지. raw_text는 항상 보존.

### 데이터 모델 (valueup_plan)

`app/models.py`에 추가([Source: db-schema.md#valueup_plan]):
- `plan_id`: Integer PK autoincrement
- `corp_code`: String(8), FK→company.corp_code, index
- `disclosure_date`: String(10) ISO(YYYY-MM-DD) — 자연키 일부
- `target_roe`, `target_payout_ratio`, `target_pbr`: Float, nullable(퍼센트/배수)
- `period_start`, `period_end`: String(10), nullable(연도/기간 best-effort)
- `buyback_planned`: Boolean, nullable
- `raw_text`: Text, nullable(원문 보존, AC3) — `from sqlalchemy import Text`
- `__table_args__`: `UniqueConstraint("corp_code", "disclosure_date", name="uq_valueup_corp_date")`
- 컬럼 타입·nullable 관례는 기존 모델(Financial/Price)과 일치. BigInteger 금액이 아니라 Float 비율임에 주의.

### 소스 트리 (이 스토리)

```
app/
  models.py                       # UPDATE: ValueupPlan 추가
  ingest/dart_valueup.py          # NEW: DartValueupAdapter (list.json + document.xml)
  ingest/run.py                   # UPDATE: ingest_valueup_plans()
  repositories/valueup_plan.py    # NEW: 멱등 upsert (corp_code, disclosure_date)
alembic/versions/0006_valueup_plan.py   # NEW
tests/fixtures/…                  # NEW: 가짜 list.json + 공시본문 텍스트
tests/test_valueup_ingest.py      # NEW
```

### 테스트 표준

- 라이브 DART 키 없이 **fixture 기반 단위 테스트**: (a) list.json 응답 → 밸류업 공시 필터·disclosure_date 매핑, (b) 공시본문 텍스트 → 목표필드 파싱(성공/부분/전부 실패=null), (c) raw_text 보존, (d) 재실행 멱등(값 갱신·중복 없음), (e) 키 미설정 `DartAdapterError`.
- `normalize`는 **순수 함수**로 설계해 네트워크 없이 테스트(fetch가 반환하는 dict를 직접 넣어 검증). ZIP 해제·태그 스트립은 작은 헬퍼로 분리해 텍스트 입력으로 단위 테스트.
- SQLite in-memory. 콘솔 인코딩: 한글 다수 → `PYTHONIOENCODING=utf-8`(Windows cp949 표시깨짐은 데이터 정상, 1.2/1.4서 확인).
- 실행: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest -q`.

### Previous Story Intelligence (1.2 DART, 1.4 ECOS)

- **1.2 라이브 교훈**: `fs.extract`(dart-fss) 대신 **OpenDART REST 직접 호출**이 안정적 → 밸류업도 requests 직접. dart-fss 의존 없음.
- **1.2 방어적 매칭 교훈**(total_debt 버그): 회사마다 라벨/서술이 달라 "첫 매칭"이 틀릴 수 있음 → 밸류업 파싱도 **여러 후보 패턴을 방어적으로** 시도하고, 애매하면 null(거짓 값보다 안전).
- **키 redaction**: 예외·로그에 crtfc_key/URL 절대 미포함(1.2 GPT High 반영). 밸류업 `_get`도 동일.
- **부분성공 정책**: 한 종목 실패가 배치 전체를 막지 않음(`IngestResult.failed`).
- **1.2/1.3/1.4 공통 deferred**(중복 지적 금지, 이 스토리도 동일 적용): 동시성 DB-native upsert(on_conflict)는 v1 단일프로세스 배치라 보류; 원천 감사메타(ingested_at/source_run_id)는 전 원천 공통으로 후속.

### 알려진 한계 / 스코프 경계 (v1)

- **파싱 정확도**: 자유서식이라 목표필드 추출은 best-effort. 실공시 다양성 대응은 패턴 튜닝(후속). raw_text가 원천 보존이므로 나중에 재파싱 가능.
- **document.xml ZIP**: 일부 공시는 첨부/이미지 기반일 수 있음 → 텍스트 없으면 목표필드 전부 null + raw_text만(또는 빈) 저장. 실패 아님.
- **공시 유형**: 예고/본공시/이행 구분은 report_nm best-effort. v1은 계획(목표치)에 집중.
- **커버리지**: 일부 밸류업 계획은 KRX KIND 위주 게시 가능 → DART 커버리지 부분적일 수 있음(정상, null 허용).
- **조회 API 없음**: 이 스토리는 수집만. `/valueup/*` 조회·갭분석은 Epic 2(2.1/2.4).

### 스택

FastAPI 0.139.0 / SQLAlchemy 2.0.51 / PostgreSQL 17(개발 SQLite) / alembic / requests. Python 3.12. ZIP·태그처리는 **stdlib**(`zipfile`, `re`/`html.parser`) — 신규 무거운 의존성 추가 금지.

### References

- [Source: epics.md#Story-1.5] — AC 원본, FR1/CAP-1
- [Source: db-schema.md] — valueup_plan 컬럼(target_roe·target_payout_ratio·target_pbr·period·buyback_planned)
- [Source: ARCHITECTURE-SPINE.md#AD-3,5,7] — dart_adapter writer·corp_code 키·멱등 upsert(corp_code+disclosure_date)
- [Source: 1-2-ingest-financials-dart.md] — DART OpenDART REST 패턴, `_RateLimiter`·Retry·키 redaction·`_parse_amount`·per-corp 커밋·fixture 테스트
- OpenDART 공시검색(list.json) DS001, 문서본문(document.xml): https://opendart.fss.or.kr/guide/

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

## Change Log
- 2026-07-09: Story 1.5 컨텍스트 생성(bmad-create-story) — 밸류업 계획공시(DART list.json+document.xml) best-effort 파싱, valueup_plan 모델·마이그레이션 0006, DartValueupAdapter, 멱등 upsert(corp_code+disclosure_date), fixture 테스트. 기존 DART 어댑터 하드닝 재사용 지침 포함. Status: ready-for-dev.
