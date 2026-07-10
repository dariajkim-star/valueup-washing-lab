---
baseline_commit: fde6b860e4de5af73a53d72e6c31110d695f626c
---

# Story 1.4: 매크로 지표 수집 (ECOS)

Status: done

### Review Findings (GPT 교차검증 2026-07-08) — 21건 → 12 patch / 6 defer / 3 dismiss

*Patch 적용:*
- [x] [High] **페이지네이션 미구현(1/1000 고정)** → `_get_all` 루프로 list_total_count까지 반복 fetch, 누락 시 `EcosApiError`. 라이브 2년+ 1162건 검증
- [x] [High] list_total_count 검증 — 수집수 != total이면 실패
- [x] [High] 재시도/백오프/타임아웃 — Session+Retry(429/5xx), rate-limit 최소간격
- [x] [High] 키 URL 경로 노출 — `except RequestException ... from None`(URL/키 미포함), redaction 테스트(str·__cause__까지)
- [x] [High] RESULT 코드 커버리지 — INFO-200만 빈결과, INFO-100/ERROR-*는 `EcosApiError` fail-fast(에러코드 매트릭스 테스트)
- [x] [High] 지표별 부분실패 격리 — fetch가 지표별로 잡아 `raw['failed']`, ingest_macro가 result.failed/succeeded로 분리
- [x] [Med] **frequency 컬럼** 추가(월/일 look-ahead 판별) + 저장
- [x] [Med] `_to_float` 엣지(".", "N/A") + `_time_to_iso` 이상포맷(분기·13월) None 처리 후 스킵(자연키 오염 방지)
- [x] [Low] indicator CheckConstraint(허용값 4종) — 오타 방어
- [x] [Low] 테스트 — 페이지네이션(mock 1001건 2페이지)·에러코드 매트릭스·redaction·bad-time·float엣지

*Defer(→ deferred-work.md):* value Numeric 정밀도 / DB-native upsert / circuit breaker / Q·S·A 주기 확장 / 원천메타(stat_code·item_code·unit·ingested_at) / 카탈로그 smoke test
*Dismiss:* 월 범위 넓어짐(월 granularity라 의도됨) / 자연키 충돌(indicator명 고유)


## Story

As a 애널리스트,
I want ECOS에서 기준금리·국고채3년·원달러환율·경기선행지수가 `macro_indicator`에 적재되는 것,
so that 매크로 컨텍스트와 M&A 타이밍 신호(저금리=차입인수 유리)를 얻는다.

## Acceptance Criteria

1. **Given** `macro_indicator` 테이블·마이그레이션(0004), **When** `alembic upgrade head`, **Then** 생성. 자연키 (indicator, date), AD-7.
2. **Given** `ecos_adapter`(SourceAdapter: fetch→normalize→upsert, AD-3), **When** 수집, **Then** 4개 지표(기준금리·국고채3년·원달러·경기선행)가 시계열로 적재된다.
3. **Given** 지표별 통계코드·주기(월M/일D), **When** 수집, **Then** ECOS StatisticSearch로 조회해 (indicator, date, value)로 정규화한다. TIME(YYYYMM/YYYYMMDD)을 ISO date로.
4. **Given** 재실행, **When** 같은 구간 재수집, **Then** (indicator, date) 멱등 upsert로 중복 없음(AD-7).
5. **Given** ECOS_API_KEY 미설정, **When** 수집 시도, **Then** 명확한 에러(부팅 안 막음).
6. **Given** ECOS 응답에 데이터 없음(INFO-200), **When** 발생, **Then** 실패가 아니라 빈 결과로 처리(수집 계속).
7. **Given** fixture(가짜 ECOS 응답), **When** 정규화·upsert 단위테스트, **Then** 매핑·멱등성 검증(키 없이 CI).

## Tasks / Subtasks

- [x] **T1: 모델 & 마이그레이션** — `MacroIndicator`(indicator, date, value, 자연키). 리비전 0004 → upgrade head 검증.
- [x] **T2: ECOS 어댑터** — `app/ingest/ecos.py`. 지표 카탈로그 4종 내장, StatisticSearch, TIME→ISO(월은 01일), 키 redaction(URL에 키 포함→예외 미노출), INFO-200 빈결과, 키 미설정 에러.
- [x] **T3: 멱등 upsert** — `app/repositories/macro.py` (indicator, date), None 안 덮음.
- [x] **T4: 수집 트리거** — `ingest_macro()`.
- [x] **T5: 테스트** — `tests/test_ecos_ingest.py`(TIME변환·매핑·결측·멱등·키에러). 33 passed.

## Dev Notes

### ECOS API — 조사 완료 (라이브 탐침)
- URL: `https://ecos.bok.or.kr/api/StatisticSearch/{KEY}/json/kr/{start}/{end}/{통계표}/{주기}/{시작}/{종료}/{항목}`
- 응답: `{"StatisticSearch": {"list_total_count", "row": [{TIME, DATA_VALUE, ITEM_NAME1, UNIT_NAME, ...}]}}`. 데이터 없으면 `{"RESULT": {"CODE":"INFO-200", ...}}`.
- **지표 카탈로그(확정)**:
  | indicator | 통계표 | 항목 | 주기 |
  |---|---|---|---|
  | `base_rate`(기준금리) | 722Y001 | 0101000 | M |
  | `bond_3y`(국고채3년) | 817Y002 | 010200000 | D |
  | `usd_krw`(원달러) | 731Y001 | 0000001 | D |
  | `leading_index`(경기선행) | 901Y067 | I16E | M |
- TIME 포맷: 월=`YYYYMM`, 일=`YYYYMMDD` → ISO `YYYY-MM-DD`(월은 01일로).

### 아키텍처 제약
- **AD-3**: ecos_adapter가 macro_indicator 유일 writer. SourceAdapter 준수(1.2 base.py).
- **AD-7**: (indicator, date) 멱등 upsert.
- **AD-10**: macro_indicator는 M&A 엔진(2.3) 입력. 기준금리가 M&A 매크로 요소.
- **NFR2**: 값 파싱 실패/결측 null 허용.

### 확립된 패턴 재사용 (1.2/1.3)
- SourceAdapter, requests(DART와 동일 REST 방식), 지연 없음(가벼움), None 안 덮음, IngestResult.
- DART 리뷰 교훈: 키 redaction(요청 URL에 키 포함 → 예외에 URL 미노출), 재시도/타임아웃.

### 소스 트리
```
app/models.py                    # UPDATE: MacroIndicator
app/ingest/ecos.py               # NEW: EcosAdapter
app/repositories/macro.py        # NEW: 멱등 upsert
app/ingest/run.py                # UPDATE: ingest_macro
alembic/versions/0004_macro.py   # NEW
tests/test_ecos_ingest.py        # NEW
```

### References
- [Source: epics.md#Story-1.4], [db-schema.md] macro_indicator(indicator,date,value)
- [Source: ARCHITECTURE-SPINE.md#AD-3,7,10]
- [Source: 1-2/1-3 stories] SourceAdapter·IngestResult·키redaction 패턴
- ECOS: https://ecos.bok.or.kr/api/

## Dev Agent Record

### Agent Model Used
claude-opus-4-8 (bmad-dev-story)

### Debug Log References
- **ECOS 코드 라이브 탐침**: 통계표/항목/주기를 실제 API로 확인. 국고채3년은 주기가 D(월 아님)라 초기 실패 → 아이템목록(StatisticItemList) 조회로 010200000/D 확정. 환율도 D, 기준금리·경기선행은 M.
- **키 redaction**: ECOS는 키가 URL 경로에 포함(`/api/.../{KEY}/...`) → 예외 메시지에 URL/키 미노출(DART 리뷰 교훈 선반영).
- **주기 혼재**: 월(YYYYMM)·일(YYYYMMDD) TIME을 ISO date로 통일(월은 01일). 요청 시 D는 YYYYMMDD, M은 YYYYMM으로 범위 변환.

### Completion Notes List
- `MacroIndicator` + 마이그레이션 0004. 종목 무관 시계열, 자연키 (indicator, date).
- `EcosAdapter`: 카탈로그 4종(base_rate/bond_3y/usd_krw/leading_index), StatisticSearch REST, INFO-200(데이터없음)은 빈결과로 관대 처리(수집 계속).
- 멱등 upsert(indicator, date), None 안 덮음. `_parse_rows`/`_time_to_iso` 순수 분리로 키 없이 단위테스트.
- **검증**: pytest 33 passed, alembic upgrade head, **라이브 128건 수집**(기준금리 3.5%·국고채3년 3.322%·원달러 1346.8·경기선행 99.7).

### File List
- `app/models.py` (UPDATE: MacroIndicator + Float import)
- `app/ingest/ecos.py` (NEW: EcosAdapter)
- `app/repositories/macro.py` (NEW: 멱등 upsert)
- `app/ingest/run.py` (UPDATE: ingest_macro)
- `alembic/versions/0004_macro.py` (NEW)
- `tests/test_ecos_ingest.py` (NEW)
- `.env` (ECOS_API_KEY 추가, gitignored)

## Change Log
- 2026-07-08: Story 1.4 구현 — MacroIndicator 모델+마이그레이션0004, ECOS 어댑터(카탈로그 4종·키 redaction·INFO-200 처리), 멱등 upsert. 라이브 128건 수집 검증. pytest 33 passed.
- 2026-07-08: GPT 교차검증 반영 — 12 patch(페이지네이션·total검증·Session+Retry·에러코드 매트릭스·지표별 부분실패·frequency 컬럼·CheckConstraint·파싱방어). 라이브 2년+ 1162건 검증(페이지네이션 동작). pytest 36 passed.
