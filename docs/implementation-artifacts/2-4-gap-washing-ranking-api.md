---
baseline_commit: 08a43c8
---

# Story 2.4: 갭분석 & 워싱 랭킹 API

Status: done

## Story

As a 애널리스트,
I want 갭 분석과 워싱 랭킹을 API로 받는 것,
so that 이행 갭이 큰 기업을 상위부터 본다.

## Acceptance Criteria

1. **Given** 적재된 `valueup_score`, **When** `GET /valueup/gap-analysis`를 호출하면, **Then** **목표·실제·갭**(target_roe/actual_roe/roe_gap — 엔진 계산 시점에 동결 저장, 서빙 시 재계산 금지)·achievement/progress/execution_score·washing_flag·buyback_status가 **execution_score 오름차순(null last)**으로 반환된다.
2. **Given** `GET /valueup/washing-ranking`, **Then** `washing_flag IS TRUE`인 종목만 동일 정렬로 반환된다(워싱 의심 랭킹).
3. **Given** 필터, **Then** `market`·`min_progress`(progress_rate >= x)·`as_of`(기본: 최신 as_of) 필터와 페이지네이션이 동작하고 응답은 `{items,total,page,size}` 봉투(AD-6).
4. **Given** washing_flag null(판단 불가), **Then** API는 null을 그대로 반환하며(2.1 리드 결정: false로 강제 금지) OpenAPI 설명에 **"null=판단 불가 — UI에서 빈칸/아니오로 표시 금지"**를 명시한다(UI 표시 계약 인계).
5. **Given** 레이어 규약, **Then** routers→services→repositories(AD-2), SQL은 repository에서만, null 정렬은 SQLite/PG 방언 차이를 타지 않는 명시적 키(`IS NULL` 우선순위)로 처리한다(1.7 defer 교훈).
6. **Given** 테스트, **Then** 정렬(null last)·필터·봉투·워싱 필터·target/gap 동결값이 검증되고 기존 173 회귀 0.

## Tasks / Subtasks

- [x] **T1**: `ValueupScore`에 `target_roe`/`actual_roe`/`roe_gap`(Float, nullable) 추가 + 마이그레이션 0011 — "목표·실제·갭"을 엔진 계산 시점에 동결(서빙 재계산 시 as_of 정합 깨짐 방지). gap_engine이 세 값 기록(gap = actual − target, 둘 다 있을 때만).
- [x] **T2**: `app/repositories/valueup_score.py`에 서빙 조회 `list_scores(session, filters, page, size)` — company 조인(corp_name·market), 명시적 null-last 정렬, COUNT+목록, `latest_as_of(session)`.
- [x] **T3**: `app/schemas.py`에 `GapAnalysisOut`, `app/services/valueup.py`, `app/routers/valueup.py`(두 엔드포인트) + main.py 등록.
- [x] **T4**: 테스트 — 정렬·washing 필터·min_progress·봉투·null 표시 계약.

## Dev Notes

- **재사용**: 1.7의 `Page[T]` 봉투(schemas.py)·라우터/서비스/리포 3층 구조(metrics.py 계열) 그대로.
- **"목표·실제·갭" 동결 저장 결정**: 서빙 시 valueup_plan·metrics를 다시 조인하면 엔진의 as_of 선택 로직(최신공시·look-ahead)을 API가 중복 구현하게 됨 — 엔진이 이미 고른 값을 저장하는 게 단일 진실. AC3 게이팅(achievement null)과 무관하게 표시용 원값은 저장(정보 제공 목적).
- **washing null 계약(2.1에서 인계된 메모)**: "True→워싱 의심 / False→근거 없음 / null→판단 불가(빈칸·아니오 표시 금지)" — OpenAPI description에 명문화.

### Review Findings (일괄 code review 2026-07-13, GPT)

- [x] [Patch][Med] as_of 쿼리 달력 미검증(2026-02-30→빈 200) → FastAPI `date` 타입으로 422.
- [x] [Patch][Med] 마이그레이션 0011 backfill 부재 → 라이브 gap_engine 재실행으로 동결값 backfill(roe_gap 9/26), "마이그레이션 후 엔진 전체 재실행" 절차를 이 스토리에 기록.
- [x] [Defer][High×2] score_run 메타데이터(부분 실행이 latest_as_of 오염·세대 혼합 식별 불가) — 별도 스토리(deferred-work 상세).
- [x] [Defer][Low] count/items 스냅샷(1-7 계열).
- GPT SQL 판정: `is_(None)` 정렬·subquery COUNT는 PostgreSQL 포함 clean(성능 여지만 언급).

## Dev Agent Record

### Agent Model Used

claude-fable-5 (bmad-dev-story)

### Debug Log References

- 목표·실제·갭 동결: gap_engine이 target_roe/actual_roe/roe_gap을 계산 시점에 저장(마이그레이션 0011) — 서빙이 엔진의 as_of 선택 로직을 중복 구현하지 않음(단일 진실).
- null-last 정렬: `execution_score.is_(None)` 1차 키(방언 무관) + corp_code 안정 정렬(페이지네이션 결정성).
- washing null 계약: OpenAPI description에 "null=판단 불가, 빈칸/아니오 표시 금지" 명문화(2.1 인계 메모 이행).
- 스코어 미적재 시 빈 봉투(500 아님).

### Completion Notes List

- pytest **178 passed**(2.4 신규 5 + 전체 회귀 0). 라이브 스모크: /valueup/gap-analysis 26행(기아 exec=100 선두, null last), /valueup/washing-ranking 0행(대형주 워싱 의심 없음 — 타당).

### File List

- `app/models.py`·`alembic/versions/0011_valueup_score_gap_fields.py` (target/actual/gap 동결)
- `app/analysis/gap_engine.py`·`app/repositories/valueup_score.py` (동결값 기록 + 서빙 조회 `list_scores`/`latest_as_of`)
- `app/schemas.py`(GapAnalysisOut)·`app/services/valueup.py`·`app/routers/valueup.py`·`app/main.py` (NEW/UPDATE)
- `tests/test_valueup_api.py` (NEW: 5종)

## Change Log

- 2026-07-13: Story 2.4 생성·착수.
- 2026-07-13: Story 2.4 구현 — 두 엔드포인트+동결 갭 컬럼+null 계약, 178 passed, 라이브 스모크 OK. Status → review(GPT 일괄 리뷰 대기).
- 2026-07-13: 일괄 GPT 리뷰 반영(위 Review Findings) — 191 passed(리뷰 회귀 13종 추가), 재파싱·엔진 재실행 검증. Status → done.
