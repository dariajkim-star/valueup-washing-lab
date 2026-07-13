---
baseline_commit: c3a0fb1
---

# Story 3.1: 시장·매크로 통계 API

Status: done

## Story

As a 애널리스트,
I want 시장·시총구간별 평균 지표·워싱 비율과 매크로 지표를 받는 것,
so that 코스피-코스닥 양극화와 매크로 국면을 파악한다.

## Acceptance Criteria

1. **Given** 지표·스코어·매크로가 적재된 상태, **When** `GET /stats/market-comparison`을 호출하면, **Then** 시장(KOSPI/KOSDAQ)별로 `n`(as_of 시점 최신 지표를 가진 종목 수)·`avg_roe`·`avg_pbr`·`avg_ev_ebitda`(null-safe 평균, look-ahead 안전 as_of 시점 최신 1건/종목)·`n_judged`·`n_washing`·`washing_ratio`(FR7)가 반환된다. 데이터가 없는 시장은 행 자체가 없다(전부-null 행을 지어내지 않음).
2. **Given** `GET /stats/summary`, **Then** 시장 구분 없는 전체 헤드라인 KPI(`n_companies`·`n_metrics`·`avg_roe`·`avg_pbr`·`avg_ev_ebitda`·`n_judged`·`n_washing`·`washing_ratio`)가 단일 객체로 반환된다.
3. **Given** `GET /stats/macro`, **Then** 4개 매크로 지표(`base_rate`·`bond_3y`·`usd_krw`·`leading_index`, `company.sector` CHECK 제약과 동일 화이트리스트) 각각의 as_of 이전 최신 관측(`date`·`value`)이 반환되고, 관측이 없는 지표는 `date`·`value`가 null로 표시된다(4개 지표 자리 자체는 항상 보장).
4. **Given** `washing_ratio`, **Then** `n_judged`(washing_flag가 null이 아닌 종목 수)를 분모로 `n_washing`(washing_flag=true) 비율이 계산되고, `n_judged=0`이면 `washing_ratio`는 null(0으로 나누지 않음, "판단 불가"를 분모에서 정직하게 제외 — 2.1의 null≠0 계약 승계).
5. **Given** `as_of`(date, FastAPI 달력 검증 → 422), **Then** `/stats/market-comparison`·`/stats/summary`의 기본값은 `valueup_score`의 최신 as_of(2.4~2.6과 동일 소스), `/stats/macro`의 기본값은 `macro_indicator` 자체의 최신 관측일(서로 다른 데이터 계열이라 독립적 기본값 — 시스템 시계 사용 금지, AD-8 정신 계승). `valueup_score`가 비어있으면 market-comparison/summary는 빈/null 집계(500 아님).
6. **Given** 레이어 규약, **Then** routers→services→repositories(AD-2), SQL은 repository에서만. look-ahead 방지(같은 해 사업보고서 배제)는 2.1/2.3의 기존 SQL 패턴을 그대로 재사용한다.
7. **Given** 응답 형태, **Then** `/stats/market-comparison`·`/stats/macro`는 `Page[T]` 봉투(AD-6)를 쓰되 실제 페이지네이션 파라미터는 받지 않는다(고정 소수 카디널리티라 페이지 개념이 없음 — `page=1`·`size=len(items)` 고정, 이 결정은 dev notes에 근거 기록). `/stats/summary`는 목록이 아니므로 봉투 없이 단일 객체.
8. **Given** 테스트, **Then** null-safe 평균·washing_ratio 분모 제외·look-ahead 배제·매크로 4지표 고정 자리·독립 as_of 기본값·빈 데이터 처리가 검증되고 기존 210 회귀 0.

## Tasks / Subtasks

- [x] **T1**: `app/repositories/stats.py`(NEW) — `market_comparison(session, as_of)`, `summary(session, as_of)`, `macro_snapshot(session, as_of)`. look-ahead 안전 최신 지표 조회는 2.1/2.3 SQL 패턴(`year<yr OR (year=yr AND quarter<4)`)을 재사용하되, corp별 최신 1건 선택은 **Python 측 dedupe**(1.7 known-limitation의 DISTINCT ON 회피 컨벤션 — SQLite/PostgreSQL 양쪽 이식성).
- [x] **T2**: `app/schemas.py`에 `MarketComparisonOut`·`StatsSummaryOut`·`MacroSnapshotOut`.
- [x] **T3**: `app/services/stats.py`(NEW) — as_of 해소(market-comparison/summary는 valueup_score 소스, macro는 macro_indicator 소스)→repo 위임.
- [x] **T4**: `app/routers/stats.py`(NEW) — 3개 GET 엔드포인트, `app/main.py` 등록.
- [x] **T5**: 테스트 `tests/test_stats_api.py`(NEW, 8종) — null-safe 평균, washing_ratio 분모 제외, look-ahead 배제, 매크로 4지표 고정 자리(일부 미수집 시 null), 두 as_of 기본값 독립성, 빈 데이터.
- [x] **T6**: 라이브 스모크(valueup.db) + 전체 pytest 회귀 0.

## Dev Notes

### 🚨 핵심 설계 결정 (dev 착수 전 이해 필수)

1. **Page[T] 봉투를 쓰되 페이지네이션은 없다** — AD-6은 "목록 응답은 {items,total,page,size}"라 명시하지만, market-comparison(시장 2개)·macro(지표 4개)는 카디널리티가 고정·소수라 실제 페이지 개념이 없다. 봉투 형태 일관성(AD-6 준수)과 정직성(가짜 페이지네이션 파라미터를 받지 않음) 사이에서 **봉투는 유지하되 `page`/`size` 쿼리 파라미터를 라우터가 받지 않고 항상 `page=1, size=len(items)`로 고정**하는 절충을 택했다. summary는 애초에 목록이 아니므로 봉투 자체를 안 쓴다.
2. **look-ahead 안전 최신 지표는 2.1/2.3 SQL을 재사용하되, 코드는 독립 작성** — `mna_score.all_latest_metrics`가 이미 거의 같은 일(look-ahead 안전 배치 최신 조회)을 하지만 `roe`를 선택하지 않고(mna_engine이 안 씀) `mna_score.py`에 있어 Epic 2 "done" 파일을 건드리게 된다. 이번 스토리는 **`app/repositories/stats.py`에 독립된 함수를 새로 작성**(WHERE절 패턴만 재사용, roe 포함, company.market 조인)해 완료된 Epic 2 코드의 blast radius를 0으로 유지한다. 3번째 소비자가 생기면 그때 공통 헬퍼로 추출(rule of three) — 지금은 조기 추출보다 격리 우선.
3. **DISTINCT ON 금지, Python dedupe** — corp별 최신 (year,quarter) 선택은 `ORDER BY corp_code, year DESC, quarter DESC` 후 Python에서 첫 등장만 채택(`mna_score.all_latest_metrics`와 동일 패턴). PostgreSQL `DISTINCT ON`은 SQLite에 없어 이식성 위반(1.7 known-limitation에 이미 명시된 컨벤션).
4. **washing_ratio 분모 = n_judged(판단 가능 종목), n_metrics 아님** — 지표 평균(n)과 워싱비율(n_judged)은 서로 다른 모집단이다(지표는 있어도 스코어가 아직 없거나 washing_flag가 null인 종목이 있을 수 있음). 두 분모를 하나로 섞지 말 것 — 이 스토리의 핵심 정직성 계약.
5. **market-comparison은 존재하는 시장만 반환** — KOSPI/KOSDAQ 중 데이터가 없는 쪽은 all-null 행을 만들지 않고 아예 행이 없다(1-6 "no-data는 행 미생성" 원칙 승계). Tableau 쪽에서 두 막대를 항상 기대한다면 소비 측에서 처리.
6. **macro는 4개 지표 자리를 항상 보장, 값은 null 가능** — `MacroIndicator` CHECK 제약의 4값(`base_rate`·`bond_3y`·`usd_krw`·`leading_index`)을 고정 화이트리스트로 순회하며 없으면 `date`/`value` null인 행을 만든다(macro는 지표 자체가 "이 4종을 추적한다"는 계약이 있어 market-comparison과 반대로 자리는 항상 보장하는 것이 맞음 — 소비자가 "이 지표가 아예 없는지 아직 값이 없는지" 구분 가능).

### 아키텍처 가드레일

- AD-2(레이어), AD-6(에러 계약 {detail,code} — main.py 전역 핸들러 이미 적용됨). CAP-7 → `routers/stats`(AD-2, AD-6, epics.md 매핑표).
- 이 스토리는 `valueup_score`·`mna_score`·`macro_indicator` **읽기만**(각 엔진/어댑터가 유일 writer, AD-4/AD-7/AD-10 불변).

### 재사용 (재발명 금지 — 참고할 기존 코드)

| 필요 | 기존 위치 | 재사용 방법 |
|---|---|---|
| look-ahead 안전 WHERE절 | `app/repositories/mna_score.py:all_latest_metrics` | 동일 조건문(`year<yr OR (year=yr AND quarter<4)`) 패턴 복제(호출은 안 함, 독립 함수). |
| valueup_score 최신 as_of | `app/repositories/valueup_score.py:latest_as_of` | import해서 그대로 호출(중복 정의 금지 — screening.py도 이렇게 함). |
| null-safe 평균 원칙 | `app/analysis/gap_engine.py` null 전파 헬퍼 | SQL `AVG()`가 NULL을 자연 스킵 — 별도 헬퍼 불필요, Python 집계 시에도 `None` 제외 후 평균. |
| Page[T] 봉투 | `app/schemas.py:Page` | 그대로 사용, page/size는 라우터가 하드코딩. |

### Review Findings (code review 2026-07-13, GPT — High 1·Med 3·Low 1, 전건 patch)

- [x] [Patch][High] `Company.market`이 nullable인데 필터 없이 사용 — `market=None`이나 KONEX 등 계약 밖 값이 있으면 `sorted(set(...))`가 None/str 혼합 정렬로 TypeError를 내거나(500), AC1의 KOSPI/KOSDAQ 전용 계약을 벗어난 시장이 응답에 새어나갈 수 있었음 → `SUPPORTED_MARKETS=("KOSPI","KOSDAQ")` 도입, raw SQL(`IN` expanding bindparam)·ORM 쿼리(`Company.market.in_(...)`) 양쪽 필터 + 스키마도 `Literal["KOSPI","KOSDAQ"]`로 방어적으로 좁힘.
- [x] [Patch][Med] 명시적 `as_of`가 valueup_score 완전 미적재 정책을 우회 — `resolved = as_of or latest_as_of()`는 as_of가 주어지면 미적재 여부를 아예 확인 안 함 → 서비스 레이어가 `latest_as_of()`를 as_of 유무와 무관하게 항상 먼저 확인하도록 재구성("테이블 전체 미적재" vs "이 특정 as_of엔 없음"을 구분).
- [x] [Patch][Med] summary의 404가 `HTTPException`이라 AD-6 `{detail,code}` 에러 계약을 벗어남(전역 핸들러는 RequestValidationError만 처리) → 라우터가 `JSONResponse(404, {detail,code:"VALUEUP_SCORE_NOT_FOUND"})`를 직접 반환.
- [x] [Patch][Med] `_avg`가 None만 걸러 NaN/Infinity를 그대로 통과시켜 JSON 직렬화 500 가능(방언별 특수값 차이) → `math.isfinite` 검사를 `_avg`와 macro `value`에 공통 적용(`_finite_or_none`).
- [x] [Patch][Low] 위 결함들을 놓치는 테스트 공백 — market=None 종목·명시 as_of 우회·NaN 값 테스트 3종 추가.
- GPT Clean 판정: washing_ratio 분모(n_judged)·null-safe 평균 원칙·look-ahead SQL 이식성(DISTINCT ON 회피)·매크로 4자리 고정·독립 as_of 기본값·레이어 준수 전부 문제없음.

## Dev Agent Record

### Agent Model Used

claude-fable-5 (bmad-create-story + bmad-dev-story 연속 실행)

### Debug Log References

- look-ahead 안전 배치 조회: `_latest_metrics_by_market`가 2.1/2.3과 동일 WHERE절을 독립 작성(company.market 조인 + roe 추가), corp별 최신행은 정렬 후 Python dedupe(DISTINCT ON 회피).
- washing 카운트는 SQL 집계 대신 Python 루프(`_washing_counts_by_market`) — 데이터 규모가 작아 성능 문제 없고 방언별 boolean 집계 차이를 피함.
- `_avg`: None 제외 평균, 값 없으면 None(0으로 나누지 않음) — market-comparison/summary 공용.
- macro 기본 as_of: `latest_macro_as_of`(macro_indicator 자체 MAX(date)) — valueup_score와 독립. 완전 공백 시 서비스 레이어에서 DB 재조회 없이 4개 null 슬롯 직접 구성(시스템 시계 미사용).
- summary의 404: valueup_score 미적재 시 서비스가 None 반환 → 라우터가 HTTPException(404)로 변환(market-comparison은 목록이라 빈 봉투 200, summary는 단일 리소스라 404가 더 정직한 계약).

### Completion Notes List

- pytest **218 passed**(3.1 신규 8 + 기존 210 회귀 0).
- 라이브 스모크(valueup.db, KOSPI 33종목): market-comparison n=33·avg_roe=8.13·avg_pbr=2.30·n_judged=19·n_washing=0(대형 우량주 표본에서 워싱 0 — Epic 2 드레스 리허설과 정합). summary가 market-comparison과 동일 값(단일 시장 유니버스라 자연스러운 일치). macro 4종 전부 실데이터 확인(base_rate 2.5·bond_3y 3.768·usd_krw 1504.2·leading_index 104.8) — 빈 슬롯 없음.
- 스토리 문서에 명시한 대로 Epic 2 완료 파일(`mna_score.py`) 미수정 — look-ahead SQL은 독립 작성.

### File List

- `app/repositories/stats.py` (NEW)
- `app/schemas.py` (UPDATE: MarketComparisonOut·StatsSummaryOut·MacroSnapshotOut)
- `app/services/stats.py` (NEW)
- `app/routers/stats.py` (NEW)
- `app/main.py` (UPDATE: stats 라우터 등록)
- `tests/test_stats_api.py` (NEW: 8종)

## Change Log

- 2026-07-13: Story 3.1 생성(ready-for-dev) — Epic 3 첫 스토리. market-comparison/summary/macro 3개 엔드포인트, Page[T] 봉투를 페이지네이션 없이 쓰는 절충 설계, washing_ratio 분모 정직성(n_judged≠n_metrics), Epic 2 완료 코드 격리(독립 SQL, mna_score.py 미수정).
- 2026-07-13: Story 3.1 구현 — 3개 엔드포인트 + 격리된 look-ahead SQL, 218 passed, 라이브 스모크 OK(33종목 실데이터, 매크로 4종 전부 확인). Status → review(GPT 교차리뷰 대기).
- 2026-07-13: GPT 리뷰 반영(High 1·Med 3·Low 1 전건 patch, 위 Review Findings) — 시장 화이트리스트·명시 as_of 우회 차단·404 에러계약·NaN/Inf 정규화·테스트 3종 추가. **221 passed**, 라이브 스모크 재확인(값 동일 — KOSPI 단일 유니버스라 필터 영향 없음, 정상). Status → done.
