---
baseline_commit: fde6b860e4de5af73a53d72e6c31110d695f626c
---

# Story 1.6: 지분구조 수집 (DART 지분공시)

Status: done

## Story

As a 애널리스트,
I want DART에서 최대주주 지분율과 자사주 비중이 `ownership`에 적재되는 것,
so that M&A 타겟 스코어(2.3)에서 지배구조 취약성(낮은 최대주주 지분율·높은 자사주)을 판정할 수 있다.

## Acceptance Criteria

1. **Given** `ownership` 테이블 모델과 alembic 마이그레이션(0007), **When** `alembic upgrade head`, **Then** 테이블이 생성된다. FK는 `corp_code`(8자리, AD-5), 자연키 유니크 `(corp_code, as_of)`(AD-7).
2. **Given** DART 지분공시 어댑터(dart_adapter, AD-3), **When** 한 종목 corp_code로 수집하면, **Then** `ownership`(corp_code, as_of, largest_shareholder_pct, treasury_stock_pct)가 적재된다.
3. **Given** DART 계정/응답이 회사마다 상이하거나 미공시일 수 있음, **When** 특정 값을 못 구하면, **Then** 그 필드는 `null`로 남고 수집은 실패하지 않는다(NFR2).
4. **Given** 이미 적재된 종목, **When** 같은 배치를 재실행하면, **Then** 자연키 `(corp_code, as_of)` 기준 **멱등 upsert**로 중복 행이 생기지 않는다(AD-7).
5. **Given** `DART_API_KEY` 미설정, **When** 라이브 수집을 시도하면, **Then** 키/URL을 노출하지 않는 명확한 `DartAdapterError`로 안내한다(1.2/1.5와 동일 정책).
6. **Given** fixture(가짜 hyslrSttus·stockTotqySttus 응답), **When** 정규화·upsert 단위 테스트를 돌리면, **Then** 지분율 계산·null 폴백·멱등성이 라이브 키 없이 검증된다.

## Tasks / Subtasks

- [x] **T1: 모델 & 마이그레이션** (AC: 1) — `app/models.py`에 `Ownership` 추가(ownership), 리비전 `0007_ownership.py`(revises `0006_valueup_plan`). 유니크 `(corp_code, as_of)`, FK `corp_code→company`. `alembic upgrade head` 검증.
- [x] **T2: DART 지분 어댑터** (AC: 2, 3, 5) — `app/ingest/dart_ownership.py` `DartOwnershipAdapter(SourceAdapter)`. `fetch`=`hyslrSttus.json`(최대주주) + `stockTotqySttus.json`(주식총수). `normalize`=지분율 계산(순수). **기존 dart.py의 `DartAdapterError`·세션/Retry/`_RateLimiter`·`_get`(JSON) 패턴 재사용**(재발명 금지). 이번엔 구조화 JSON이라 1.5의 ZIP/문서 경로는 불필요.
- [x] **T3: 멱등 upsert 저장소** (AC: 3, 4) — `app/repositories/ownership.py` `upsert_ownership(session, rec)`. 자연키 `(corp_code, as_of)`, None은 기존 non-null 안 덮음(1.2 `upsert_financial` 패턴).
- [x] **T4: 수집 트리거** (AC: 2, 5) — `app/ingest/run.py`에 `ingest_ownership(corp_codes, bsns_year, reprt_code)`. 종목별 커밋 + 실패목록(`IngestResult`), fetch는 트랜잭션 밖(기존 `ingest_financials` 패턴 그대로).
- [x] **T5: 테스트** (AC: 3, 4, 6) — `tests/test_ownership_ingest.py`(지분율 계산·"계"행 선택·null 폴백·멱등·키에러). SQLite in-memory, fixture 기반(라이브 키 불필요).

### Review Findings (code review 2026-07-10, BMAD 3-layer: Blind/EdgeCase/Auditor)

Auditor: AC1~6·AD-3/5/7/10·FR9 전부 충족. Blind/Edge가 파서 견고성·자연키 이슈 다수 발견(1.5와 같은 '틀린 값·데이터 손실' 계열).

**Patch (반영)**
- [x] [Review][Patch] **분기 reprt_code인데 as_of가 -12-31 고정 → 자연키 충돌** [dart_ownership.py fetch] — `_REPRT_QUARTER`가 분기코드를 허용하는데 as_of가 항상 연말이라 Q3·사업보고서가 `(corp, "2024-12-31")`로 충돌·덮어씀. reprt_code→기간말 매핑(11013=03-31/11012=06-30/11014=09-30/11011=12-31). (Blind/Edge High)
- [x] [Review][Patch] **largest "계"행 ratio가 null이면 개별행 폴백 도달 불가** [dart_ownership.py] — 보통주 "계"행이 있으나 지분율이 `""`/`"-"`면 그대로 None 반환, 개별행에 값 있어도 손실. 계 ratio None이면 fallthrough + **요약행(계/소계/합계) 제외** 개별 보통주 합으로(P5 이중집계 방지). (Edge High + Blind Med)
- [x] [Review][Patch] **treasury 합계행 없을 때 rows[0]로 부분값 오산** [dart_ownership.py] — 합계 없으면 첫 행(보통주)으로 종목 전체 자사주율처럼 계산. 정확 "합계" 매칭(strip 완전일치), 없으면 None(null>오값). (Blind/Edge/Auditor Med)
- [x] [Review][Patch] **treasury 범위 미가드** [dart_ownership.py] — tesstk>istc(데이터오류)나 회계음수면 >100%·음수 반환. `0<=pct<=100` 아니면 None. (Edge Low-Med)
- [x] [Review][Patch] **양 지표 모두 None인데 행 생성(all-NULL 성공 처리)** [dart_ownership.py normalize] — 행은 있으나 파싱 전무면 두 컬럼 null인 무의미 행이 자연키 점유+succeeded 카운트. 둘 다 None이면 `[]`(no-data 취급). (Blind/Edge Med)
- [x] [Review][Patch] **`_get_json`이 JSONDecodeError 미포착** [dart_ownership.py] — 비JSON 200(HTML 점검페이지)에서 `resp.json()`이 ValueError → RequestException만 잡아 누출. ValueError도 DartAdapterError로 래핑. (Blind Med)
- [x] [Review][Patch] **`_parse_ratio` "%" suffix·nan/inf** [dart_ownership.py] — "12.34%"→None(손실), "nan"/"inf"→그대로 누출. `%` strip + `math.isfinite` 거부. (Blind/Edge Low)
- [x] [Review][Patch] **no-data가 failed에 섞임** [run.py] — 미공시를 진짜 에러와 같은 failed에. degraded로 분리. (Blind/Edge Low)

**Deferred (코드베이스 공통/큰 변경, deferred-work 기록)**
- [x] [Review][Defer] rate-limit(200+status 020) 미재시도(전 DART 어댑터 공통), JSONDecodeError 미포착을 dart.py/dart_valueup에도 전파(공통 패턴), log(type명) vs failed(str(e)) 불일치(공통), DB CheckConstraint(비율 범위), 합계행 tesstk 결측 시 개별행 복구(복잡).

## Dev Notes

### DART 지분공시 API (조사 결과)

1.5(자유서식)와 달리 **구조화 JSON** 두 엔드포인트를 쓴다 → 1.2(재무제표) 패턴에 가깝다:

1. **최대주주 현황** — `GET https://opendart.fss.or.kr/api/hyslrSttus.json` (DS002)
   - params: `crtfc_key`, `corp_code`, `bsns_year`(YYYY), `reprt_code`(**기본 11011=사업보고서**; `_REPRT_QUARTER`(dart.py) 밖 값은 fail-fast).
   - 응답 `list[]`: 최대주주 및 특수관계인별 행 + **"계"(합계) 행**. 필드: `nm`(성명), `stock_knd`(주식종류: 보통주/우선주), `trmend_posesn_stock_qota_rt`(기말소유주식 지분율, 예: `"12.34"`).
   - **largest_shareholder_pct** = **보통주 기준 "계"행**의 `trmend_posesn_stock_qota_rt`. ⚠️ 지배구조 취약성은 **의결권 있는 보통주** 기준이라, 우선주(무의결권) 포함 "계"를 잡으면 지배력이 왜곡된다. 규칙: `nm=="계"` **AND** `stock_knd` 보통주(또는 stock_knd 미표기 시 단일 "계") 행을 선택. "계"행이 여럿이면 보통주 계 우선, 하나도 없으면 특수관계인 행들의 `trmend_posesn_stock_qota_rt` 합(보통주만)으로 폴백. 못 구하면 null.
2. **주식의 총수 현황** — `GET https://opendart.fss.or.kr/api/stockTotqySttus.json` (DS002)
   - params: 동일(`crtfc_key`, `corp_code`, `bsns_year`, `reprt_code`).
   - 응답 `list[]`: 주식 종류별(보통주/우선주/**합계**) 행. 필드 `istc_totqy`(발행주식 총수), `tesstk_co`(자기주식수), `se`(구분).
   - **treasury_stock_pct** = `합계` 행의 `tesstk_co / istc_totqy * 100`(0 나눗셈 방어 → null). `se`에 "합계" 포함 행 우선, 없으면 보통주 행.
- **as_of**: 사업보고서(연간) 기준 `f"{bsns_year}-12-31"`. 자연키 `(corp_code, as_of)`. ⚠️ **3월 결산 등 비12월 결산사는 실제 기준일과 어긋난다**(멱등성엔 무해하나 날짜 라벨 오류) — v1 한계로 문서화, 정밀 기준일은 회사 결산월/reprt 기간말에서 유도(후속). 분기 지원 시 reprt별 기간말 매핑.
- **비율 파싱**: 지분율은 문자열(`"12.34"`), 수량은 콤마 포함(`"1,234,567"`). 지분율용 `_parse_ratio`(콤마·공백 제거 후 float, `"-"`·`""`·`None`·미공시·파싱실패 → None) 신규. 수량(정수)은 `_parse_amount`(dart.py) 재사용.
- **분당 100요청 제한** — `_RateLimiter`(dart.py, 0.65s)가 스로틀. 종목당 요청 2건(hyslrSttus+stockTotqySttus).
- **완전 미공시 처리(1.2 교훈)**: 양 엔드포인트가 모두 status 013(데이터 없음)이면 **ownership 행을 만들지 않는다**(no-data ≠ 필드 누락). 한쪽만 있으면 있는 값만 채우고 나머지 null. `_get`의 `allow_no_data=True`로 013을 빈 리스트로 받아 구분.

### 재사용 (재발명 금지 — 기존 코드에서 가져올 것)

| 필요 | 기존 위치 | 재사용 방법 |
|---|---|---|
| HTTP 하드닝 + JSON status(000/013) 처리 | `app/ingest/dart.py:75-87,165-187`, `dart_valueup.py:_get_json` | **JSON 전용 `_get_json`을 미러/공유**(1.5 `dart_valueup._get_json`과 동일 구조; ⚠️ `DartAdapter._get`을 직접 import하지 말 것 — 인스턴스 바운드). 세션+Retry+`_RateLimiter` 재사용. `allow_no_data=True`로 013 구분. 1.5의 ZIP/document 경로는 불필요. |
| 키 미노출 예외 | `app/ingest/dart.py` `DartAdapterError` | import 재사용. 예외에 crtfc_key/URL 금지. |
| 수량 파싱(콤마·회계음수) | `app/ingest/dart.py:_parse_amount` | 자기주식수·발행총수(정수)에 재사용. 지분율(소수)은 `_parse_ratio` 신규. |
| 어댑터 인터페이스 | `app/ingest/base.py` `SourceAdapter` | 그대로 구현(AD-3). |
| 멱등 upsert(None-safe) | `app/repositories/financials.py:upsert_financial` | 같은 구조로 `(corp_code, as_of)` 키, None은 기존값 보존. |
| 종목별 커밋 + 실패목록, fetch는 txn 밖 | `app/ingest/run.py:ingest_financials` | `ingest_ownership`도 동일 패턴. |
| fixture 기반 테스트 | `tests/test_dart_ingest.py`, `tests/test_valueup_ingest.py` | 동일 방식. hyslrSttus·stockTotqySttus fixture. |

### 아키텍처 제약

- **AD-3**: dart_adapter가 ownership의 유일 writer(`source="dart"`). 공통 인터페이스 준수.
- **AD-5**: corp_code(8자리) FK·정식 키.
- **AD-7**: 멱등 upsert 자연키 `(corp_code, as_of)`.
- **AD-2**: 수집은 서빙과 분리. repository가 upsert, 라우터/서비스 없음(조회는 후속 없음 — ownership은 2.3 M&A 엔진이 직접 읽음).
- **AD-10 입력**: ownership은 mna_engine(2.3)의 지배구조 요소 입력.
- **NFR2**: 미공시·계정 누락 시 null 허용, 수집 실패 금지.

### 데이터 모델 (ownership)

`app/models.py`에 추가([Source: db-schema.md#ownership]):
- `id`: Integer PK autoincrement (기존 Financial/Price 관례)
- `corp_code`: String(8), FK→company.corp_code, index
- `as_of`: String(10) ISO(YYYY-MM-DD) — 자연키 일부
- `largest_shareholder_pct`: Float, nullable(%)
- `treasury_stock_pct`: Float, nullable(%)
- `__table_args__`: `UniqueConstraint("corp_code", "as_of", name="uq_ownership_corp_asof")`
- 관례는 기존 모델과 일치. 비율이라 Float(수량 아님).

### 소스 트리 (이 스토리)

```
app/
  models.py                     # UPDATE: Ownership 추가
  ingest/dart_ownership.py      # NEW: DartOwnershipAdapter (hyslrSttus + stockTotqySttus)
  ingest/run.py                 # UPDATE: ingest_ownership()
  repositories/ownership.py     # NEW: 멱등 upsert (corp_code, as_of)
alembic/versions/0007_ownership.py   # NEW
tests/test_ownership_ingest.py  # NEW
```

### 테스트 표준

- 라이브 키 없이 **fixture 기반 단위 테스트**: (a) hyslrSttus "계"행 → largest_shareholder_pct, (b) stockTotqySttus 합계행 → treasury_stock_pct(=자기주식/발행총수*100), (c) 미공시/누락 → null, (d) 0 발행총수 → null(0 나눗셈 방어), (e) 재실행 멱등, (f) 키 미설정 `DartAdapterError`.
- `normalize`는 **순수 함수**(fetch 반환 dict 직접 주입). SQLite in-memory.
- 실행: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest -q`.

### Previous Story Intelligence (1.2 DART, 1.5 밸류업)

- **구조는 1.2에 가깝다**(구조화 JSON 매핑) — 1.5의 ZIP/문서/자유서식 파싱 복잡성 없음. 목표필드 오탐 리스크 낮음.
- **방어적 매칭**(1.2 total_debt 교훈): 회사마다 행 구성/라벨이 다를 수 있음 → "계"행 없으면 폴백, 애매하면 null.
- **키 redaction**: 예외·로그에 crtfc_key/URL 미포함(1.2 GPT High 반영).
- **부분성공 정책**: 한 종목 실패가 배치 전체를 막지 않음(`IngestResult.failed`).
- **1.2/1.3/1.4/1.5 공통 deferred**(중복 지적 금지, 동일 적용): 동시성 DB-native upsert(on_conflict)는 v1 단일프로세스 배치라 보류; 원천 감사메타(ingested_at)는 전 원천 공통 후속.
- **콘솔 인코딩**: 한글 다수 → `PYTHONIOENCODING=utf-8`(cp949 표시깨짐은 데이터 정상).

### 알려진 한계 / 스코프 경계 (v1)

- **최대주주 지분율 정의**: **보통주 기준 "최대주주+특수관계인 합계"**("계"행) 채택(우선주 무의결권 제외 — 지배력 왜곡 방지). 순수 최대주주 단독 지분이 필요하면 후속(2.3 지배구조 취약성엔 합계가 적절).
- **as_of 기준일 근사**: v1은 `{연도}-12-31`. **비12월 결산사(예: 3월 결산)는 라벨 오류** — 멱등성엔 무해하나 정밀 기준일은 회사 결산월/reprt 기간말에서 유도(후속). 분기 지원 시 reprt별 기간말 매핑.
- **treasury_stock_pct 출처**: stockTotqySttus(주식총수) 기반. 정밀 자사주 취득/소각 이력은 `tesstkAcqsDspsSttus`(자기주식 취득·처분) 별도 — 2.1 워싱 판정의 buyback과 연계는 후속.
- **완전 미공시 → 행 미생성**: 양 엔드포인트 모두 데이터 없으면 빈 row 안 만듦(1.2 no-data 교훈). 한쪽만 있으면 부분 적재.
- **조회 API 없음**: 이 스토리는 수집만. ownership은 2.3 M&A 엔진이 직접 읽음.

### 스택

FastAPI 0.139.0 / SQLAlchemy 2.0.51 / PostgreSQL 17(개발 SQLite) / alembic / requests. Python 3.12. 신규 의존성 없음(구조화 JSON이라 stdlib·requests로 충분).

### References

- [Source: epics.md#Story-1.6] — AC 원본, FR9
- [Source: db-schema.md] — ownership 컬럼(corp_code, as_of, largest_shareholder_pct, treasury_stock_pct)
- [Source: ARCHITECTURE-SPINE.md#AD-3,5,7,10] — dart_adapter writer·corp_code 키·멱등 upsert(corp_code+as_of)·M&A 엔진 입력
- [Source: 1-2-ingest-financials-dart.md] — DART OpenDART REST 패턴, `_get`(JSON)·`_RateLimiter`·키 redaction·`_parse_amount`·per-corp 커밋·fixture 테스트
- OpenDART 최대주주 현황(hyslrSttus)·주식의 총수 현황(stockTotqySttus) DS002: https://opendart.fss.or.kr/guide/

## Dev Agent Record

### Agent Model Used
claude-sonnet-5 (bmad-dev-story)

### Debug Log References
- **구조화 JSON**(1.2 패턴): hyslrSttus·stockTotqySttus 모두 JSON → dart.py `_get` 패턴을 미러한 `_get_json`(status 000/013) 사용, `DartAdapter._get` 직접 import 안 함(L1). 1.5의 ZIP/document 경로 불필요.
- **M2 보통주 기준**: `_largest_shareholder_pct`가 `nm=="계" AND stock_knd 보통주` 행 우선 → 우선주(무의결권) "계" 배제. 미표기 단일 "계" → 보통주 개별행 합 폴백. 테스트로 40%(보통주) vs 5%(우선주) 확인.
- **M3 no-data**: 양 엔드포인트 빈 응답이면 normalize가 `[]` 반환(행 미생성), run.py가 failed에 "데이터 없음" 사유로 분리. 한쪽만 있으면 부분 적재.
- **재사용**: dart.py의 `DartAdapterError`·`_RateLimiter`·`_BASE`·`_TIMEOUT`·`_REPRT_QUARTER`·`_YEAR_RE`·`_parse_amount`(수량) import. 지분율(소수)은 `_parse_ratio` 신규(콤마·"-"·미공시→null).
- **파싱 순수 함수**(`_largest_shareholder_pct`·`_treasury_stock_pct`·`_parse_ratio`) → 네트워크 없이 단위 테스트.

### Completion Notes List
- `Ownership` 모델 + 마이그레이션 0007(revises 0006) → `alembic upgrade head`로 ownership 생성 검증(test_alembic_upgrade_head 통과, AC1). 자연키 `(corp_code, as_of)`, FK corp_code(AD-5/7).
- `DartOwnershipAdapter`(AD-3, source="dart"): hyslrSttus→largest_shareholder_pct(보통주 계), stockTotqySttus→treasury_stock_pct(자기주식/발행총수, 0나눗셈 방어). reprt_code·bsns_year fail-fast(L3).
- 멱등 upsert `(corp_code, as_of)`(AD-7): None-safe(일시 미공시로 기존값 소실 방지).
- `ingest_ownership`(run.py): 종목별 커밋 + 실패목록, no-data는 failed 분리, fetch는 트랜잭션 밖.
- **검증**: pytest **70 passed**(ownership 9 신규 + 기존 61 회귀 0), 라이브 키 없이 fixture 기반.
- **스코프 메모**: as_of는 `{연도}-12-31` 근사(비12월 결산 라벨오류 한계 문서화), 정밀 자사주 취득/소각 이력·순수 최대주주 단독 지분은 후속.

### File List
- `app/models.py` (UPDATE: Ownership)
- `alembic/versions/0007_ownership.py` (NEW)
- `app/ingest/dart_ownership.py` (NEW: DartOwnershipAdapter + 파싱 헬퍼)
- `app/repositories/ownership.py` (NEW: 멱등 upsert)
- `app/ingest/run.py` (UPDATE: ingest_ownership + import)
- `tests/test_ownership_ingest.py` (NEW)

## Change Log
- 2026-07-10: Story 1.6 컨텍스트 생성(bmad-create-story) — 지분구조(DART hyslrSttus+stockTotqySttus 구조화 JSON) 수집, ownership 모델·마이그레이션 0007, DartOwnershipAdapter, 멱등 upsert(corp_code+as_of), fixture 테스트. 기존 DART 어댑터 재사용(구조화라 1.5 ZIP 경로 불필요). Status: ready-for-dev.
- 2026-07-10: 스토리 점검 반영 — **M2** largest_shareholder를 **보통주 기준 "계"행**으로(우선주 무의결권 제외, 지배력 왜곡 방지), **M1** as_of 비12월 결산 라벨 오류 한계 명시, **M3** 완전 미공시(양 엔드포인트 빈 응답)→행 미생성(1.2 no-data 교훈), **L1** `_get_json` 미러(DartAdapter._get 직접 import 금지) 명시, **L2** `_parse_ratio` 방어(미공시→null), **L3** reprt_code 기본 11011·fail-fast.
- 2026-07-10: Story 1.6 구현(bmad-dev-story) — Ownership 모델+마이그레이션 0007, DartOwnershipAdapter(hyslrSttus+stockTotqySttus 구조화 JSON, 보통주 기준 최대주주·자사주 비중), 멱등 upsert(corp_code+as_of), ingest_ownership. 점검 M2(보통주)·M3(no-data)·L1~3 코드 반영. **pytest 70 passed**(ownership 9 신규, 회귀 0). Status → review.
- 2026-07-10: BMAD 3-layer 코드리뷰 — **Patch 8건 반영**: as_of를 reprt별 기간말로(분기 자연키 충돌 해소, High), '계'행 null시 요약행 제외 개별합 폴백(High), treasury 정확 '합계' 매칭+범위가드(0~100), 양 지표 None시 no-data, `_get_json` ValueError 포착, `_parse_ratio` %/isfinite, no-data→degraded. 리뷰 중 "특수관계인"의 "계" 부분문자열 오탐도 정확일치로 수정(테스트가 검출). 회귀 테스트 8종 추가 → **pytest 78 passed**. Deferred 5건(대부분 전 DART 어댑터 공통). Status → done. **Epic 1 완료.**
