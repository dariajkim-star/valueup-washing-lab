---
baseline_commit: 9b9b491
---

# Story 2.5: M&A 타겟 랭킹 API

Status: done

## Story

As a 애널리스트,
I want M&A 타겟 점수 랭킹을 API로 받는 것,
so that 인수 매력 높은 종목을 상위부터 본다.

## Acceptance Criteria

1. **Given** 적재된 `mna_score`, **When** `GET /mna/ranking`을 호출하면, **Then** **mna_target_score 내림차순(null last)**으로 요소별 분해(valuation_score·capacity_score·ownership_score·macro_score)와 **population_basis**(2.7 — 어느 모집단으로 백분위를 매겼는지)가 함께 반환된다.
2. **Given** 필터, **Then** `market`(KOSPI/KOSDAQ)·`sector`(KSIC 코드 prefix 매칭 — 2.7 버킷 택소노미와 동일 단위)·`as_of`(FastAPI `date` 타입, 기본=최신) 필터와 페이지네이션이 동작하고 응답은 `{items,total,page,size}` 봉투다(AD-2·AD-6).
3. **Given** mna_target_score null(엄격 null 정책 — 요소 하나라도 산출 불가면 총점 null, 2.3 리드 결정), **Then** API는 null을 그대로 반환하며(값 조작 금지) OpenAPI 설명에 **"null=산출 불가(입력 데이터 부족) — 0점이나 최하위로 표시 금지"**를 명시한다(2.4 washing null 계약과 대칭).
4. **Given** 레이어 규약, **Then** routers→services→repositories(AD-2), SQL은 repository에서만, null 정렬은 방언 무관 명시적 키(`IS NULL` 우선 → 값 내림차순 → corp_code 안정 정렬)로 처리한다(2.4 확립 패턴).
5. **Given** 스코어 미적재 상태, **Then** 빈 봉투 200(500 아님). 달력상 무효 `as_of`(2026-02-30 등)는 422(2.4 일괄리뷰 교훈).
6. **Given** 테스트, **Then** 정렬(desc·null last)·market/sector 필터·봉투·null 계약·as_of 스냅샷이 검증되고 기존 191 테스트 회귀 0.

## Tasks / Subtasks

- [x] **T1**: `app/repositories/mna_score.py`에 서빙 조회 섹션 추가 — `latest_as_of(session)`, `list_scores(session, filters, page, size)` (company 조인: corp_name·market·sector, 명시적 null-last 내림차순 정렬, COUNT+목록). 기존 엔진용 배치 조회와 구획 주석으로 분리.
- [x] **T2**: `app/schemas.py`에 `MnaRankingOut`(corp_code·corp_name·market·sector·as_of·mna_target_score·4요소·population_basis).
- [x] **T3**: `app/services/mna.py`(NEW) — 2.4 `services/valueup.py` 패턴(as_of 해소→미적재 빈 봉투→repo 위임).
- [x] **T4**: `app/routers/mna.py`(NEW) — `GET /mna/ranking`, `as_of: date | None`(달력 검증), null 계약 description. `app/main.py` 등록.
- [x] **T5**: 테스트 `tests/test_mna_api.py`(NEW) — 2.4 `test_valueup_api.py` 패턴(SQLite in-memory + StaticPool + TestClient). 정렬·필터·봉투·null·422·빈 봉투.
- [x] **T6**: 라이브 스모크 — valueup.db(33종목) 대상 `/mna/ranking` 구동 확인, 전체 pytest 회귀 0.

## Dev Notes

- **재사용이 스토리의 90%**: 2.4가 확립한 3층 구조(routers/valueup.py → services/valueup.py → repositories의 list_scores)를 mna로 복제한다. `Page[T]` 봉투(schemas.py)·null-last 명시 정렬·빈 봉투·date 422 전부 기존 패턴 그대로 — 새 발명 금지.
- **정렬 방향 주의**: 2.4는 오름차순(이행 나쁜 순), **2.5는 내림차순**(인수 매력 높은 순). null last는 동일 — `mna_target_score.is_(None)` 1차 키 + `.desc()` 2차 + corp_code 3차(페이지네이션 결정성).
- **sector 필터 = prefix 매칭**: `Company.sector`는 DART induty_code 원문. 2.7이 KSIC 2자리 버킷을 택소노미로 확정했으므로 `sector=64`가 "64로 시작하는 업종 전부"를 잡는 `startswith`(LIKE 'xx%') 매칭이 정합적. 정확일치로 하면 유니버스 종목의 세분류 코드(4~5자리)를 사용자가 알 수 없어 필터가 사실상 죽는다. escape 문자(`%`,`_`) 처리는 SQLAlchemy `.startswith(value, autoescape=True)` 사용.
- **latest_as_of 오염 known-limitation**: 부분 실행이 latest_as_of를 오염시키는 score_run 메타데이터 문제는 2.4와 공통의 defer(deferred-work.md) — 이 스토리에서 해결하지 않고 동일 한계로 둔다.
- **population_basis 노출 이유**: "이 종목의 백분위가 sector:26 내 상대값인지 전체시장 폴백인지"는 점수 해석에 필수(2.7 AC4의 식별 가능성 요구를 API까지 관통). 숨기면 sector 필터와 조합 시 오독 위험.
- **금융주 null**: 리허설에서 확인된 금융주 valuation/capacity null(변수 세트 한계, 레벨 2 defer)은 이 API에서 mna_target_score null로 그대로 보인다 — AC3 계약이 이를 "산출 불가"로 정직하게 전달하는 장치.
- **MnaScore에 서빙용 컬럼 추가 없음**: 2.4는 동결 컬럼(마이그레이션 0011)이 필요했지만 2.5는 mna_score에 이미 모든 표시값이 있다 — 마이그레이션 불필요.

### 이전 스토리 인텔리전스 (2.4/2.7)

- 2.4 리뷰에서 나온 것: as_of `date` 타입 검증(422), 빈 200과 422 구분, count/items 스냅샷은 Low defer.
- GPT SQL 판정: `is_(None)` 정렬·subquery COUNT는 PG 포함 clean.
- 서비스 레이어의 `_resolve_as_of` → 미적재 시 `Page(items=[], ...)` 패턴 재사용.
- 테스트는 `monkeypatch.setattr(db_module, "SessionLocal", Session_)` 방식.

### 아키텍처 가드레일

- AD-2(레이어 단방향), AD-6(봉투·에러·정렬 규약), AD-5(corp_code 조인 키), AD-10(이 스토리는 mna_score **읽기만** — 쓰기는 엔진 소유).
- 임계치·가중치 등 config 주입 대상 없음(순수 조회 스토리).

### Review Findings (code review 2026-07-13, GPT — Med 3·Low 1, High 없음)

- [x] [Patch][Med] 빈 문자열 필터(`?market=`·`?sector=`)가 truthiness로 "필터 없음"으로 확대 → 라우터 `min_length=1`(sector는 `pattern=^\d{2,5}$` 추가)로 422 + repo `is not None` 이중 방어.
- [x] [Patch][Med] 422가 FastAPI 기본 형태로 나가 AD-6 `{detail,code}` 에러 계약 위반 → main.py 전역 `RequestValidationError` 핸들러(`code=VALIDATION_ERROR`, `jsonable_encoder`로 ctx 직렬화) — 전 라우터 공통 해소.
- [x] [Patch][Med] `page` 무상한 → 거대 정수 OFFSET이 64비트 초과 시 500 → `le=1_000_000`으로 422.
- [x] [Dismiss][Low] `as_of` 관대 파싱(datetime·epoch 문자열 수용) — 실측 확인 후 수용 결정: 유효 달력 날짜로만 해석되고 500·오동작 없음, 2.4와 동작 일치 유지. 엄격 형식 필요 시점에 전 라우터 공통 validator(deferred-work 기록).
- [x] [Defer] valueup·metrics 라우터의 빈 필터·page 상한 패리티 정비(deferred-work.md — 2-6 편승 후보).
- GPT Clean 판정: null-last desc 정렬·subquery COUNT·startswith autoescape·레이어 준수·AD-10(읽기 전용)·AD-5(corp_code 조인) 전부 문제없음.

## Dev Agent Record

### Agent Model Used

claude-fable-5 (bmad-create-story + bmad-dev-story 연속 실행)

### Debug Log References

- 정렬: `mna_target_score.is_(None)`(null last) → `.desc()`(인수 매력 높은 순) → corp_code asc(안정 정렬). 2.4와 골격 동일, 방향만 반대.
- sector 필터: `Company.sector.startswith(value, autoescape=True)` — LIKE 특수문자(%·_) 이스케이프 처리. prefix 매칭이라 `sector=26`(KSIC 2자리 버킷)과 `sector=26100`(세분류) 모두 동작.
- null 계약: OpenAPI description에 "null=산출 불가, 0점/최하위 표시 금지" 명문화(2.4 washing null 계약과 대칭).
- 스코어 미적재 시 빈 봉투(500 아님), 무효 as_of는 FastAPI date 타입으로 422.
- 마이그레이션 없음 — mna_score에 표시값이 이미 전부 있음.

### Completion Notes List

- pytest **196 passed**(2.5 신규 5 + 기존 191 회귀 0). 경고 2건은 기존과 동일(starlette TestClient deprecation — 라이브러리 몫).
- 라이브 스모크(valueup.db, KOSPI 33종목): `/mna/ranking` total 31, 상위 = 포스코홀딩스 71.1 → 네이버 68.0 → 크래프톤 67.4(전부 market_fallback — 소형 유니버스 폴백 설계대로). `sector=64` → 금융지주 5종목 전부 null(레벨 2 변수세트 한계 그대로 정직 노출, basis도 None — 2.7 리뷰 패치와 정합). null last·KOSDAQ 0건(KOSPI 유니버스) 확인.

### File List

- `app/repositories/mna_score.py` (UPDATE: 서빙 조회 섹션 — latest_as_of·list_scores)
- `app/schemas.py` (UPDATE: MnaRankingOut)
- `app/services/mna.py` (NEW)
- `app/routers/mna.py` (NEW)
- `app/main.py` (UPDATE: mna 라우터 등록)
- `tests/test_mna_api.py` (NEW: 5종)

## Change Log

- 2026-07-13: Story 2.5 생성(ready-for-dev) — 2.4 API 패턴 복제 + 내림차순·sector prefix 필터·null 계약 대칭.
- 2026-07-13: Story 2.5 구현 — /mna/ranking + 요소별 분해·population_basis 노출, 196 passed, 라이브 스모크 OK. Status → review(GPT 교차리뷰 대기).
- 2026-07-13: GPT 리뷰 반영(Med 3 patch·Low 1 dismiss, 위 Review Findings) — **199 passed**(리뷰 테스트 3종 추가). Status → done.
