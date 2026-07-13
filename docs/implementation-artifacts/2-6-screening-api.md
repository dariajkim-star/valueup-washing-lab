---
baseline_commit: 83fa446
---

# Story 2.6: 다중조건 스크리닝 API

Status: done

## Story

As a 애널리스트,
I want 여러 조건을 조합해 종목을 걸러내는 것,
so that 워싱·저평가·M&A 후보를 양방향으로 스크리닝한다.

## Acceptance Criteria

1. **Given** 지표·두 스코어가 준비된 상태, **When** `GET /screening`을 호출하면, **Then** company + valueup_score + mna_score를 **corp_code·as_of 기준 outer join**한 행이 반환된다(한쪽 엔진 미실행 시 그쪽 필드 null — 정직 노출). 두 스코어가 모두 없는 종목은 제외(스크리닝 대상 아님).
2. **Given** 필터, **Then** `min/max_execution_score`·`min/max_mna_score`(범위, `allow_inf_nan=False`), `washing_only`(true→`washing_flag IS TRUE`), `buyback_executed`(true/false — **null은 어느 쪽에도 미포함**, "판단 불가"를 false로 세탁 금지), `market`·`sector`(2.5 규약: min_length=1, sector는 KSIC prefix)가 AND 조합으로 동작한다(FR6).
3. **Given** 정렬, **Then** AD-6 `field`/`-field` 규약의 `sort` 파라미터(화이트리스트: `execution_score`·`mna_target_score`)가 동작하고 null last + corp_code 안정 정렬, 화이트리스트 밖 필드는 400 `{detail, code}`. 기본 정렬은 corp_code(중립 — 스크리닝은 양방향이라 정답 방향이 없음).
4. **Given** `as_of`(date, 기본=두 스코어 테이블 latest 중 max), **Then** 스냅샷 조회가 동작하고 무효 날짜는 422 `{detail, code}`(2.5 전역 핸들러). 스코어 미적재 → 빈 봉투 200. 응답은 `{items,total,page,size}`(AD-6), `page`는 `le=1_000_000`(2.5 교훈).
5. **Given** 레이어 규약, **Then** routers→services→repositories(AD-2), SQL은 repository에서만, 랭킹·랭킹 API의 null 계약(washing null=판단 불가, mna null=산출 불가)이 OpenAPI 설명에 승계된다.
6. **[편승] Given** 2-5 리뷰 defer(패리티 정비), **Then** valueup·metrics 라우터에 빈 문자열 필터 422(min_length=1)·page 상한(le=1_000_000)이 적용되고 repo 필터가 `is not None`으로 정비된다.
7. **Given** 테스트, **Then** outer join null 정직성·범위/불리언 필터·sort 화이트리스트·봉투·패리티 정비가 검증되고 기존 199 회귀 0.

## Tasks / Subtasks

- [x] **T1**: `app/repositories/screening.py`(NEW) — `latest_as_of`(두 테이블 max 중 max), `list_screening(session, filters, page, size, sort)` (Company 기준 outer join 2개, 최소 한쪽 스코어 존재 조건, 화이트리스트 sort).
- [x] **T2**: `app/schemas.py`에 `ScreeningOut`(corp 3종+sector·as_of·execution_score·washing_flag·buyback_status·buyback_executed·mna_target_score·population_basis).
- [x] **T3**: `app/services/screening.py`(NEW) — as_of 해소→미적재 빈 봉투→repo 위임(2.4/2.5 패턴).
- [x] **T4**: `app/routers/screening.py`(NEW) — GET /screening, 잘못된 sort는 400 `{detail, code:"INVALID_SORT"}`(AD-6). `app/main.py` 등록.
- [x] **T5**: 패리티 편승 — `routers/valueup.py`(market min_length·page 상한 ×2 엔드포인트), `routers/metrics.py`(market/sector min_length·page 상한), `repositories/valueup_score.py`·`repositories/metrics.py` 필터 `is not None`.
- [x] **T6**: 테스트 `tests/test_screening_api.py`(NEW, 7종) + valueup/metrics 패리티 422 테스트 포함.
- [x] **T7**: 라이브 스모크(valueup.db) + 전체 pytest 회귀 0.

## Dev Notes

- **as_of 단일 파라미터**: 두 테이블에 같은 as_of를 적용한다(엔진은 전체실행 권장이라 실무상 동일). 한쪽만 실행된 as_of면 그쪽 필드가 null로 보인다 — 세대 혼합을 조인으로 감추지 않고 null로 드러내는 것이 의도. 기본값은 두 latest 중 **max**(가장 최근 실행 시점).
- **두 스코어 모두 없는 종목 제외**: 전 종목을 돌려주면 회사정보만 있는 노이즈 행이 생긴다. `vs.id IS NOT NULL OR ms.id IS NOT NULL`.
- **buyback_executed=false의 의미**: `IS FALSE` — null(수집 실패·판단 불가)은 true에도 false에도 안 걸린다. 2.1부터 이어진 "null 세탁 금지" 원칙.
- **sort 기본값 없음(corp_code)**: 갭랭킹(오름차순)·M&A랭킹(내림차순)과 달리 스크리닝은 방향 중립 — 임의 기본 정렬로 의미를 암시하지 않는다.
- **sort 화이트리스트는 metrics 패턴 재사용**: 다만 ORM 조인이라 SQL 문자열 대신 컬럼 객체 매핑. 400 응답은 metrics(detail만)와 달리 `{detail, code}`로 AD-6 준수 — metrics 400의 code 패리티는 소규모라 이 스토리에서 함께 정비.
- **범위 필터의 null**: `execution_score >= x`는 null을 자연 배제(SQL 3치 논리) — "산출 불가는 조건 매칭 불가"가 올바른 의미라 그대로 둔다.

### 아키텍처 가드레일

- AD-2(레이어)·AD-5(corp_code 조인)·AD-6(봉투·에러·정렬 규약). 이 스토리도 두 스코어 테이블 **읽기 전용**(AD-4/AD-10 writer 규칙 침범 금지).

### Review Findings (code review 2026-07-13, GPT — Med 3·Low 2, High 없음, 전건 patch)

- [x] [Patch][Med] 스코어 미적재 시 잘못된 sort가 검증 전에 빈 봉투 200으로 short-circuit(데이터 유무로 계약이 갈림) → `validate_sort` 순수 함수를 서비스 진입 직후(DB 조회 전) 호출.
- [x] [Patch][Med] 라우터가 광범위 `ValueError`를 잡아 pydantic ValidationError(내부 오류)까지 400 INVALID_SORT로 세탁 → 전용 `InvalidSortError`만 catch, 그 외는 500으로 노출.
- [x] [Patch][Med] "필드 전부 null=엔진 미실행" 스키마 설명이 거짓 가능(row 있으나 엄격 게이팅으로 전부 null인 경우와 구분 불가) → `has_valueup_score`/`has_mna_score` 플래그 추가 + 설명 수정.
- [x] [Patch][Low] 빈 sort(`?sort=`)가 truthiness로 기본 정렬에 조용히 흡수 → `is None`만 생략으로 인정, 빈 문자열·`-`단독은 400(생략과 빈 입력 구분).
- [x] [Patch][Low] 두 테이블 latest가 다른 교차 시나리오 테스트 부재 → vs=07-12/ms=07-13 fixture로 max 선택·미조인측 null·has_* 검증 추가.
- GPT Clean 판정: outer join universe·범위 필터의 3치 논리 null 배제·`is_(True/False)` 방언 호환·null-last 정렬·startswith autoescape·sort 컬럼 객체 화이트리스트(인젝션 경로 없음)·AD-2 준수 전부 문제없음.

## Dev Agent Record

### Agent Model Used

claude-fable-5 (bmad-create-story + bmad-dev-story 연속 실행)

### Debug Log References

- outer join: Company 기준 LEFT JOIN ×2(각각 corp_code+as_of 복합 ON), `vs.id IS NOT NULL OR ms.id IS NOT NULL`로 무스코어 종목 제외.
- sort: metrics.py 화이트리스트 패턴의 ORM 판(SQL 문자열 대신 컬럼 객체 매핑) — 허용 밖 필드는 ValueError → 라우터에서 400 `{detail, code:"INVALID_SORT"}`(AD-6, metrics의 detail-only 400과 달리 계약 준수).
- buyback_executed 필터: `.is_(True/False)` — null(판단 불가)은 양쪽 모두 미포함(null 세탁 금지).
- 범위 필터는 SQL 3치 논리로 null 자연 배제("산출 불가는 조건 매칭 불가").
- as_of 기본 = 두 스코어 테이블 latest 중 max. 한쪽 엔진 미실행 as_of면 그쪽 필드 null(정직 노출).

### Completion Notes List

- pytest **206 passed**(2.6 신규 7 + 기존 199 회귀 0).
- 라이브 스모크(valueup.db, KOSPI 33종목): `/screening` total 32(무스코어 1종 제외), `-mna_target_score` 정렬 = 2.5 랭킹과 일치. `min_mna_score=60&market=KOSPI` 5건, `buyback_executed=true` 19건, sort 인젝션(`sort=evil`) → 400 `{detail,code}` 확인.
- **데이터 특성 기록**: 최신 as_of에서 execution_score non-null이 기아 1곳뿐(2.1 엄격 게이팅) — `max_execution_score` 필터는 실질 1종목에만 작동. 워싱 방향 스크리닝의 실효성은 배당·달성률 커버리지 확대(deferred: 주주환원율 필드) 이후 개선될 것. 필터 로직 결함 아님(분해 검증 완료).
- 패리티 편승 완료: valueup·metrics 라우터 빈 필터 422·page 상한, repo `is not None` — 2-5 리뷰 defer 해소.

### File List

- `app/repositories/screening.py` (NEW)
- `app/schemas.py` (UPDATE: ScreeningOut)
- `app/services/screening.py` (NEW)
- `app/routers/screening.py` (NEW)
- `app/main.py` (UPDATE: screening 라우터 등록)
- `app/routers/valueup.py`·`app/routers/metrics.py`·`app/repositories/valueup_score.py`·`app/repositories/metrics.py` (UPDATE: 패리티 정비)
- `tests/test_screening_api.py` (NEW: 7종)

## Change Log

- 2026-07-13: Story 2.6 생성(ready-for-dev) — outer join 스크리닝 + sort 규약 + 2-5 리뷰 패리티 편승.
- 2026-07-13: Story 2.6 구현 — /screening + 패리티 정비, 206 passed, 라이브 스모크 OK. Status → review(GPT 교차리뷰 대기).
- 2026-07-13: GPT 리뷰 반영(Med 3·Low 2 전건 patch, 위 Review Findings) — sort 선검증·InvalidSortError·has_* 플래그·빈 sort 400·교차 latest 테스트. **210 passed**. Status → done.
