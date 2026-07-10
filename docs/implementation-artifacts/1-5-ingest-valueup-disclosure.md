---
baseline_commit: fde6b860e4de5af73a53d72e6c31110d695f626c
---

# Story 1.5: 밸류업 계획공시 수집 (DART)

Status: done

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

- [x] **T1: 모델 & 마이그레이션** (AC: 1) — `app/models.py`에 `ValueupPlan` 추가(valueup_plan), 리비전 `0006_valueup_plan.py`(revises `0005_valuation_metrics_view`). 유니크 `(corp_code, disclosure_date)`, FK `corp_code→company`. `alembic upgrade head` 검증.
- [x] **T2: DART 밸류업 어댑터** (AC: 2, 3, 5) — `app/ingest/dart_valueup.py` `DartValueupAdapter(SourceAdapter)`. `fetch`=공시검색(list.json, pblntf_ty="I") + 문서본문(document.xml ZIP) 다운로드→텍스트. `normalize`=raw_text에서 목표필드 best-effort 파싱(못 찾으면 null). **기존 dart.py의 `DartAdapterError`·`_parse_amount`·세션/Retry/`_RateLimiter` 패턴 재사용**(재발명 금지).
- [x] **T3: 멱등 upsert 저장소** (AC: 4) — `app/repositories/valueup_plan.py` `upsert_valueup_plan(session, rec)`. 자연키 `(corp_code, disclosure_date)`, None은 기존 non-null 안 덮음, `raw_text`는 항상 반영.
- [x] **T4: 수집 트리거** (AC: 2, 5) — `app/ingest/run.py`에 `ingest_valueup_plans(corp_codes, date_from, date_to)`. 종목별 커밋 + 실패목록(`IngestResult`), fetch는 트랜잭션 밖(기존 `ingest_financials` 패턴 그대로).
- [x] **T5: 테스트** (AC: 3, 4, 6) — `tests/fixtures/`에 가짜 list.json·공시본문 텍스트 추가, `tests/test_valueup_ingest.py`(파싱 매핑·null 폴백·raw_text 보존·멱등·키에러). SQLite in-memory, fixture 기반(CI에서 라이브 키 불필요).

### Review Findings (code review 2026-07-10, BMAD 3-layer: Blind/EdgeCase/Auditor)

핵심: 다수가 "정규식이 느슨해 **틀린 non-null 값**을 만든다"(연도를 PBR로, 인접지표 %를 ROE로 등). accepted "못 찾으면 null"과 다름 — 틀린 target은 null보다 나쁘므로 **파서 보수화**가 스토리 철학에 부합.

**Patch (데이터 손실/크래시/명백한 오값 — 반영)**
- [x] [Review][Patch] raw_text가 빈 재수집에 덮어써짐(정보 손실) [repositories/valueup_plan.py] — 목표필드는 None-safe인데 raw_text는 ""도 무조건 반영 → 문서 fetch 일시 실패("")가 기존 원문을 지움. 새 값이 비어있고 기존이 있으면 보존. (Blind High/EdgeCase F12)
- [x] [Review][Patch] `_PBR_RE`가 연도·percent를 target_pbr로 오추출 [dart_valueup.py] — `배?` 옵셔널이라 "PBR을 2024년까지" → pbr=2024. `배` 단위 필수화. (Blind/EdgeCase F1, High)
- [x] [Review][Patch] 문서 1건 fetch 실패가 corp의 이미 수집된 plan 전부 폐기 [dart_valueup.py fetch/_fetch_document] — `_fetch_document` 예외가 while 밖으로 전파 → run.py가 corp 전체 failed. 문서 실패는 raw_text=""로 격리하고 계속. (Blind Med)
- [x] [Review][Patch] 빈/무효 disclosure_date가 자연키 붕괴 [dart_valueup.py] — rcept_dt 없으면 `_to_iso("")=""` → (corp,"")로 모든 무키 공시가 한 행에 충돌. 유효 날짜 없으면 해당 plan skip. (EdgeCase F11)
- [x] [Review][Patch] report_nm이 JSON null이면 AttributeError로 corp 크래시 [dart_valueup.py fetch] — `item.get("report_nm","")`는 값이 null이면 None 반환 → `.replace` 폭발. `(item.get("report_nm") or "")`. (Blind Low/Med)
- [x] [Review][Patch] total_page 비정상값 크래시/무한루프 [dart_valueup.py fetch] — 비숫자면 ValueError, 과대값이면 rate-limited 요청 폭주. try/except + 페이지 상한. (EdgeCase F10)
- [x] [Review][Patch] `%p`(퍼센트포인트)를 절대목표로 오독 [dart_valueup.py _PCT] — "ROE 10%p 개선" → roe=10. `%` 뒤 `p/포인트` 부정형 lookahead. (EdgeCase F4)
- [x] [Review][Patch] 자사주 부정문을 계획으로 오판 [dart_valueup.py parse_targets] — "자사주 취득 계획 없음" → buyback=True. 근처 없음/않 부정어면 True 안 함. (EdgeCase F6)
- [x] [Review][Patch] 발견로직(fetch) 무테스트 [tests] — report_nm 필터·`_to_iso`·다중페이지 미검증(AC6/Dev Notes가 fake list.json 명시). 위 하드닝 포함 테스트 추가. (Auditor)

**Deferred (best-effort 정제 — 실공시 샘플 필요, deferred-work 기록)**
- [x] [Review][Defer] ROE가 인접 지표 %를 잡음(F2)·"30%→35%"에서 FROM 채택(F3)·period 과거범위 오표기(F5)·report_nm이 이행현황/철회도 매칭(F9)·ZIP 멤버 필터/사이즈캡·zip-bomb(F13)·decode utf-8-first mojibake — 실제 DART 원문 다양성 대응은 패턴 튜닝(후속). raw_text 보존이므로 재파싱 가능.

**Dismissed**: euc-kr 폴백 dead code(cp949 상위집합, 제거), period 연도 vs ISO 포맷(best-effort), upsert가 갱신도 ingested 카운트(코드베이스 관례=dart.py 동일), `from None`+타입명만(1.2서 확립한 키 redaction 관례), 음수부호·범위 하한(희소/수용).

### GPT 교차검증 통합 (2026-07-10) — 독립 리뷰 18건, BMAD와 강하게 일치

GPT는 BMAD 9개 patch를 모른 채 독립 리뷰 → **대부분 재발견(확증)** + 2개 심화. **추천 세트(그룹1~6) 전부 반영**:
- **★ G9(전체교체)**: None-safe upsert가 파서 수정 후에도 옛 오탐값(예: PBR 2027)을 영구 보존 → "문서 fetch 성공/실패"를 구분해 **유효 파싱은 null 포함 전체 교체**로 변경(fetch 실패는 upsert 안 함→기존 보존). BMAD의 raw_text 가드 설계를 대체하는 더 정확한 모델.
- **G7 문서별 격리**: 한 문서/후반 페이지 실패가 종목의 다른 공시를 안 날림(부분결과 보존).
- **G2 셀 경계보존**: `_strip_tags`가 태그→개행, 정규식 gap이 개행 못 넘음 → 인접 지표 침범 차단.
- **G10 날짜 엄격검증**(strptime, 무효 skip), **G1 PBR 배 필수+범위**, **G4 %p 제외**, **G5 자사주 부정/과거→False**, **G6 period start≤end**, **G11 ZIP 텍스트멤버+사이즈캡**, total_page/report_nm 견고화.
- 회귀 테스트 9종 추가 → **pytest 61 passed**.

**Deferred(실공시 샘플 필요/큰 변경)**: 인라인 산문의 인접지표·"현재→목표" 우변 채택(깊은 문맥/DOM), raw_text 원문(태그포함) 별도 저장 + plain_text 분리(G12), DB CheckConstraint(G15), SELECT→INSERT 동시성(G14, 코드베이스 공통), `str(e)` allowlist(G18, 공통). → deferred-work 기록.

## Dev Notes

### DART 밸류업 공시 접근 (조사 결과 — 정확도 중요)

밸류업 공시("기업가치 제고 계획")는 **OpenDART에 구조화 재무 API가 없다**. `fnlttSinglAcntAll.json`(1.2) 같은 계정→금액 JSON이 아니라 **자유서식 공시 문서**다. 따라서 2단계:

1. **공시 발견** — `GET https://opendart.fss.or.kr/api/list.json` (JSON)
   - params: `crtfc_key`, `corp_code`, `bgn_de`(YYYYMMDD), `end_de`, `page_no`, `page_count`. **`pblntf_ty`는 생략 권장** — "I"(거래소공시)로 좁히면 유형 코드가 어긋날 때 공시를 놓친다(과대필터). `report_nm` 매칭으로 거르는 게 안전.
   - 응답 `list[]`: `{corp_code, corp_name, stock_code, report_nm, rcept_no, rcept_dt, flr_nm, rm}` + `total_page`.
   - **필터**: `report_nm`에 `"기업가치 제고 계획"` 포함(공백 제거 후 부분일치, 접미 `"(예고)"/"(공시)"/"(이행)"/"(정정)"` 허용). `disclosure_date = rcept_dt`(YYYYMMDD→ISO).
   - **다중 공시·다중 페이지**: 한 종목이 예고·본공시·정정 등 여러 건을 낼 수 있다 → `total_page`까지 순회해 **매칭되는 모든 공시를 각각 valueup_plan 행**으로(자연키 corp_code+disclosure_date). 종목당 요청이 늘어나므로 `_RateLimiter`가 스로틀.
   - JSON 응답이므로 **1.2 `_get` 재사용 가능**: `"000"`=정상, `"013"`=데이터없음(빈 리스트), 그 외 `DartAdapterError`.
2. **본문 다운로드·파싱** — `GET https://opendart.fss.or.kr/api/document.xml?crtfc_key=..&rcept_no=..`
   - **⚠️ 응답은 JSON이 아니라 ZIP 바이너리다. `_get`(=`resp.json()`) 재사용 금지 — 즉시 터진다.** 세션+Retry+`_RateLimiter`만 공유하고 **`resp.content`(바이너리)**를 읽는 별도 메서드(예: `_fetch_document`)를 둔다. HTTP 실패 시 예외에 키/URL 미포함(1.2 정책).
   - stdlib `zipfile`로 해제 → **DART 전용 XML 마크업(dsd 포맷; 깔끔한 HTML 아님)** 태그를 `re`로 스트립해 평문 `raw_text`(무거운 의존성 lxml/bs4 지양). 텍스트가 없으면(첨부·이미지형 공시) 목표필드 전부 null + raw_text만(또는 빈값) 저장, **실패 아님**.
   - `raw_text`에서 **best-effort 정규식 추출**(못 찾으면 null, NFR2):
     - `target_roe`: "ROE ... 10%", "목표 ROE 10% 이상" → 10.0
     - `target_payout_ratio`: "배당성향 ... 30%" → 30.0. **⚠️ 공시는 보통 "주주환원율"(배당+자사주 / 순이익)을 발표하는데 이는 배당성향(배당/순이익)과 다른 지표다.** 2.1 갭 스코어가 `valuation_metrics.payout_ratio`(=배당성향)와 비교하므로, 주주환원율을 그대로 넣으면 사과-오렌지 비교가 된다 → **"배당성향"이 명시된 값을 우선 매칭**, 주주환원율만 있으면 target_payout_ratio에 넣지 말고 raw_text만 보존(거짓 target 금지).
     - `target_pbr`: "PBR ... 1배/1.0" → 1.0
     - `period_start`/`period_end`: "2024~2026", "2025년 ~ 2027년", "3개년" → 연도 문자열(String(10))
     - `buyback_planned`: "자기주식 취득/매입/소각 계획" 키워드 존재 → True, 명시적 부재/미파싱 → null
   - **파싱 정확도는 본질적으로 제한적**(회사마다 서술이 상이). 정확성 계약의 핵심은 **raw_text 보존 + 멱등 upsert**이고, 목표필드는 튜닝 가능한 패턴셋의 best-effort다. 라이브 실공시 검증은 수동/후속(deferred).

### 재사용 (재발명 금지 — 기존 코드에서 가져올 것)

| 필요 | 기존 위치 | 재사용 방법 |
|---|---|---|
| HTTP 하드닝(세션+Retry 429/5xx backoff 0.6, `_RateLimiter` 0.65s, connect/read timeout 분리) | `app/ingest/dart.py:75-87,165-187` | 세션+Retry+`_RateLimiter` 공유. **단 `_get`은 JSON 전용(`resp.json()`+status 검사)** — `list.json`엔 재사용 OK, **`document.xml`(ZIP 바이너리)엔 재사용 금지** → 별도 `_fetch_document`가 `resp.content` 사용. |
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
- `raw_text`: Text, nullable(원문 보존, AC3)
- **import 추가**: `from sqlalchemy import Boolean, Text`(기존 models.py import엔 없음 — BigInteger/CheckConstraint/Float/ForeignKey/String/UniqueConstraint만 있음)
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
- **동일 disclosure_date 충돌**: 같은 날 정정공시 등 동일 `(corp_code, disclosure_date)`는 자연키상 덮어씀 → v1 허용(최신 파싱값 유지). rcept_no를 키에 포함하는 정교화는 후속.
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
claude-opus-4-8 (bmad-dev-story)

### Debug Log References
- **C1(점검) 실증**: `document.xml`은 ZIP 바이너리라 dart.py `_get`(resp.json)을 못 쓴다 → 별도 `_fetch_document`(resp.content) + `_zip_to_text`(stdlib zipfile 해제 + `re` 태그 스트립). 비-ZIP 응답(에러)은 빈 문자열 반환(best-effort, 실패 아님). 테스트로 ZIP 왕복 검증.
- **E1(점검) 반영**: `_PAYOUT_RE`는 "배당성향"만 매칭. "주주환원율 35%"만 있는 원문은 target_payout_ratio를 None으로 남김(거짓 target 금지) — 전용 테스트로 고정.
- **재사용**: dart.py의 `DartAdapterError`·`_RateLimiter`·`_BASE`·`_TIMEOUT`·`_MIN_INTERVAL`을 import해 세션+Retry+rate-limit·키 미노출 예외를 그대로 재사용. `_get_json`은 dart `_get`과 동일한 status(000/013) 처리.
- **파싱은 순수 함수**(`parse_targets`, `_zip_to_text`, `_strip_tags`) → 네트워크 없이 단위 테스트. normalize도 fetch 반환 dict를 직접 넣어 검증.
- **콘솔 인코딩**: 한글 다수 → `PYTHONIOENCODING=utf-8`(1.2/1.4와 동일, cp949 표시깨짐은 데이터 정상).

### Completion Notes List
- `ValueupPlan` 모델 + 마이그레이션 0006(revises 0005) → `alembic upgrade head`로 valueup_plan 생성 검증(test_alembic_upgrade_head 통과, AC1).
- `DartValueupAdapter`(AD-3, source="dart"): list.json(JSON, `_get` 패턴) 다중페이지 순회 + report_nm 공백제거 부분일치, document.xml(ZIP) → raw_text. normalize=best-effort 파싱(못 찾으면 null, NFR2), raw_text 항상 보존.
- 멱등 upsert `(corp_code, disclosure_date)`(AD-7): 목표필드 None-safe, raw_text 항상 반영. 재실행 중복 없음·값 갱신 테스트.
- `ingest_valueup_plans`(run.py): 종목별 커밋 + 실패목록(부분성공), fetch는 트랜잭션 밖(기존 패턴).
- **검증**: pytest **49 passed**(밸류업 8 신규 + 기존 41 회귀), 라이브 키 없이 fixture 기반.
- **스코프 메모**: T5의 fixture는 별도 `tests/fixtures/` 파일 대신 테스트 내 상수/인메모리 ZIP으로 인라인(더 간결, 동등). 라이브 실공시 파싱 정확도 검증은 수동/후속(스토리 한계에 명시).

### File List
- `app/models.py` (UPDATE: ValueupPlan + Boolean/Text import)
- `alembic/versions/0006_valueup_plan.py` (NEW)
- `app/ingest/dart_valueup.py` (NEW: DartValueupAdapter + 파싱 헬퍼)
- `app/repositories/valueup_plan.py` (NEW: 멱등 upsert)
- `app/ingest/run.py` (UPDATE: ingest_valueup_plans + import)
- `tests/test_valueup_ingest.py` (NEW)

## Change Log
- 2026-07-09: Story 1.5 컨텍스트 생성(bmad-create-story) — 밸류업 계획공시(DART list.json+document.xml) best-effort 파싱, valueup_plan 모델·마이그레이션 0006, DartValueupAdapter, 멱등 upsert(corp_code+disclosure_date), fixture 테스트. 기존 DART 어댑터 하드닝 재사용 지침 포함. Status: ready-for-dev.
- 2026-07-09: 스토리 점검(quality review) 반영 — **C1**: `document.xml`은 ZIP 바이너리라 `_get`(resp.json) 재사용 금지, 별도 `_fetch_document`(resp.content) 명시(재사용표·접근절 수정). **E1**: target_payout_ratio↔주주환원율 의미 불일치 경고(거짓 target 금지). **E2**: 다중 공시·다중 페이지 순회 + pblntf_ty 생략 권장(과대필터 방지). **M1** dsd XML 마크업, **M2** Boolean import, **M3** 동일 disclosure_date 충돌 한계 추가.
- 2026-07-10: Story 1.5 구현(bmad-dev-story) — ValueupPlan 모델+마이그레이션 0006, DartValueupAdapter(list.json 다중페이지 + document.xml ZIP→raw_text, best-effort 파싱), 멱등 upsert(corp_code+disclosure_date), ingest_valueup_plans. 점검 C1(ZIP 별도 fetch)·E1(주주환원율 구분) 코드로 실증. **pytest 49 passed**(밸류업 8 신규, 회귀 0). Status → review.
- 2026-07-10: BMAD 3-layer + GPT 독립 교차검증 통합 triage. **추천 patch 세트(그룹1~6) 반영**: fetch 문서별 격리 + 성공/실패 구분 + **유효파싱 전체교체**(G9, 옛 오값 정정), 날짜 strptime 검증, 정규식 하드닝(PBR 배 필수·%p 제외·자사주 부정→False·period start≤end), 셀 경계보존 strip(인접지표 침범 차단), ZIP 텍스트멤버+사이즈캡, total_page/report_nm 견고화. 회귀 테스트 9종 추가 → **pytest 61 passed**. 깊은 문맥파싱·raw_text 원문저장 등은 deferred(raw_text 보존+전체교체로 재파싱 가능). Status → done.
