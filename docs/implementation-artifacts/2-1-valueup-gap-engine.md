---
baseline_commit: 1147c85929b4f0a601cdd42ed34e8cd314e83001
---

# Story 2.1: Value-up 갭 스코어링 엔진

Status: done

## Story

As a 애널리스트,
I want 계획 대비 달성률·진척률·실행점수가 산출되는 것,
so that 밸류업 이행 정도를 종목 간 비교할 수 있다.

## 배경 — Epic 1→2 전환 (읽고 시작할 것)

Epic 1(수집)이 Story 1.8로 재완료됐다. **Epic 2는 새 패턴** — HTTP 어댑터가 아니라 **순수 계산 엔진**이다.
입력은 전부 이미 DB에 있다: `valuation_metrics` VIEW(1.7) + `valueup_plan`(1.5) + `financials.buyback_*`(1.2+1.8, 이제 실데이터).
`app/analysis/gap_engine.py`가 이 스토리의 신규 산출물이며 `valueup_score`의 **유일 writer**(AD-4).

**1.8이 이 스토리를 가능하게 했다**: `financials.buyback_retired_amount`가 1.8 이전엔 구조적 100% null이었다.
이제 실데이터(수량, `>0` 신호)가 들어오고, 오늘 코드리뷰로 **scoring.md의 washing/`buyback_status` 계약이
"null≠소각안함"으로 강화**됐다([Source: scoring.md 상단 경고문]) — 이 스토리는 그 강화된 계약을 **그대로 구현**해야 한다(재완화 금지).

## Acceptance Criteria

1. **Given** `valueup_plan`·`valuation_metrics` 뷰·`financials`(buyback_amount·buyback_retired_amount)(AD-4)
   **When** `gap_engine.run(session, as_of, corp_codes=None)`을 특정 as_of로 실행하면
   **Then** `valueup_score`(corp_code, as_of, achievement_rate, progress_rate, execution_score, **buyback_executed, buyback_retired, buyback_status**)가 적재되고(gap_engine이 유일 writer, AD-4)
2. **Given** 위 실행,
   **Then** `achievement_rate = actual_roe / target_roe`(target_roe는 as_of 시점 유효 `valueup_plan`, actual_roe는 as_of 이전 최신 `valuation_metrics.roe`), `target_roe<=0`이면 achievement_rate는 null(0 나눗셈·역설 방어).
3. **Given** `valueup_plan.period_start`/`period_end`(4자리 연도 문자열, 1.5 `_PERIOD_RE` 산출물),
   **Then** `progress_rate = clamp((as_of연도 - period_start) / (period_end - period_start), 0, 1)`이 연도 단위로 계산되고, period_start/end가 null이거나 `period_end <= period_start`면 **progress_rate와 achievement_rate가 둘 다 null**(계획기간이 무효면 목표 자체를 신뢰할 수 없다는 데이터품질 게이트, NFR2). ~~washing 판정~~은 AC6의 3치(Kleene) 규칙을 따로 따른다(하나가 null이어도 다른 항이 확정 False면 washing은 확정 False 가능 — AC3의 무효게이트로 washing까지 일괄 null화하지 않는다. 2026-07-10 코드리뷰 정정, 최초 구현이 achievement_rate를 별도 계산해 이 AC를 위반했던 버그 수정됨).
4. **Given** `buyback_amount`(취득 수량)·`buyback_retired_amount`(소각 수량, 1.8, 둘 다 null 가능),
   **Then** `buyback_executed = (buyback_amount > 0)`(null이면 null), `buyback_retired = (buyback_retired_amount == 0 ? False : (buyback_retired_amount > 0 ? True : null))`(즉 **확정 0만 False**, null은 null — scoring.md 오늘자 계약), `buyback_status`는 `retired`(소각>0) / `purchased_only`(취득>0 AND 소각=확정0) / `none`(취득=확정0 AND 소각=확정0) / **`unknown`**(취득·소각 중 하나라도 null)로 도출된다.
5. **Given** config 임계치·가중치(NFR3, 이미 `app/config.py`에 존재 — 신규 불필요),
   **Then** `execution_score = 100 * clamp(0.5*min(achievement_rate,1) + 0.3*(buyback_executed?1:0) + 0.2*min(actual_payout/target_payout,1), 0, 1)`가 산출되고(achievement_rate 또는 actual_payout/target_payout 계산 불가 시 해당 항은 0으로 취급하지 않고 **전체 execution_score가 null**), `settings.score_w_achievement/score_w_buyback/score_w_payout`를 하드코딩 대신 주입한다.
6. **Given** 워싱 판정 대상,
   **Then** `washing_flag`은 네 항(`progress_rate>=min`, `achievement_rate<max`, `buyback_planned`, `NOT buyback_retired`)의 **3치(Kleene) AND**로 계산된다: 하나라도 **확정 False**면 나머지가 unknown(null)이어도 전체 **확정 False**(예: 소각이 확정됐으면[`buyback_retired=True`] 진척률을 몰라도 워싱 아님이 확정), 확정 False가 없고 하나라도 unknown이면 **null**(판단불가), 전부 확정 True면 **True**. (2026-07-10 코드리뷰 정정: 최초 구현은 "하나라도 null→전체 null"이라 과잉보수적이었음 — false positive는 없었으나 확정 가능한 케이스까지 불필요하게 null로 냈다. scoring.md에 3치 논리로 명문화됨.)
7. **Given** 동일 `(corp_code, as_of)`로 재실행,
   **Then** 멱등 upsert로 중복 행 없이 갱신된다(AD-7 패턴, valueup_score 신규 자연키). **plan이 삭제되면 근거를 잃은 기존 score도 함께 정리된다**(reconciliation, 2026-07-10 코드리뷰 추가).
8. **Given** fixture 기반 단위 테스트,
   **Then** achievement_rate·progress_rate(연도 경계 포함)·buyback_status 4분류(retired/purchased_only/none/unknown)·washing_flag의 3치 논리·execution_score 산식·멱등성·**look-ahead 부분차단(같은 해 사업보고서 배제)**·**as_of 포맷 검증**이 라이브 DB 없이 검증되고 **기존 100 테스트 회귀 0**.

## Tasks / Subtasks

- [x] **T1: `ValueupScore` 모델 + 마이그레이션 0008** (AC: 1, 7) — `app/models.py`에 `ValueupScore` 추가. 컬럼: `id`(PK), `corp_code`(FK, index), `as_of`(String(10)), `achievement_rate`/`progress_rate`/`execution_score`(Float, nullable), `washing_flag`(Boolean, **nullable** — null 전파 필수), `buyback_executed`/`buyback_retired`(Boolean, nullable), `buyback_status`(String, nullable, 4값). `UniqueConstraint(corp_code, as_of)`. `alembic/versions/0008_valueup_score.py`(revises `0007_ownership`). `alembic upgrade head` 검증.
- [x] **T2: 입력 조회 저장소** (AC: 2, 3, 4) — `app/repositories/valueup_score.py`에 읽기 함수: (a) `latest_valueup_plan(session, corp_code, as_of)` — corp의 `valueup_plan` 중 `disclosure_date <= as_of`인 것 중 최신 1건(없으면 None), (b) `latest_metrics(session, corp_code, as_of)` — `valuation_metrics` 뷰에서 corp의 최신 (year,quarter) 행 1건을 `text()` raw SQL로(AD-1, repositories/metrics.py 패턴 재사용), (c) `latest_financial_buyback(session, corp_code, as_of)` — `financials`에서 최신 (year,quarter)의 `buyback_amount`/`buyback_retired_amount`. **AD-2**: 이 세 함수만 SQL 실행, gap_engine은 dict/ORM 객체만 다룸.
- [x] **T3: 계산 순수 함수** (AC: 2, 3, 4, 5, 6) — `app/analysis/gap_engine.py`에 순수 함수(DB 미접촉, 테스트 용이):
  - `_progress_rate(period_start, period_end, as_of_year) -> float | None`
  - `_achievement_rate(actual_roe, target_roe) -> float | None`
  - `_buyback_signals(amount, retired_amount) -> tuple[bool|None, bool|None, str]` (executed, retired, status — status는 항상 4값 중 하나, executed/retired가 None이어도 status는 "unknown"으로 확정 가능)
  - `_execution_score(achievement_rate, buyback_executed, actual_payout, target_payout, weights) -> float | None`
  - `_washing_flag(progress_rate, achievement_rate, buyback_planned, retired_amount, thresholds) -> bool | None`
- [x] **T4: 엔진 오케스트레이션 + 멱등 upsert** (AC: 1, 7) — `gap_engine.run(session, as_of, corp_codes=None)`: corp_codes 없으면 `company` 전체 순회. corp별로 T2 조회 → T3 계산 → `upsert_valueup_score(session, rec)`(신규, `app/repositories/valueup_score.py`, `(corp_code, as_of)` 자연키, ownership 패턴 미러). **plan이 없는 corp는 스킵**(계획 자체가 없으면 갭을 잴 수 없음 — 행 미생성, no-data와 동일 취급). 트랜잭션은 전체 배치 1건(수집 어댑터와 달리 순수 계산이라 부분실패 격리 불필요 — 실패 시 전체 롤백해도 재실행 비용이 낮음).
- [x] **T5: 테스트** (AC: 8) — `tests/test_gap_engine.py`(신규): T3 순수 함수 단위 테스트(연도 경계 progress_rate 0/1/클램프, target_roe<=0 null, buyback 4분류 전부, washing null 전파 3가지 이상 케이스) + T4 통합(SQLite in-memory, `CREATE_VALUATION_METRICS` 뷰 생성 후 시드 → run() → 결과 검증, 재실행 멱등).

### Review Findings (code review 2026-07-10, GPT)

GPT가 "merge 보류" 판정 — High 5건·Med 5건. 검증 결과 대부분 확인됐고, 1건(tie-break)은 재검증 결과 스키마 제약(1.5 UniqueConstraint)으로 발생 불가능함이 확인됨(REFUTED).

**Patch (반영)**
- [x] [Review][Patch] **AC3 위반: achievement_rate가 progress_rate 무효여도 별도 계산됨** (High) — 최초 구현이 `achievement_rate`를 `period_start/end`와 무관하게 독립 계산해 스토리가 직접 명시한 AC3("period 무효면 achievement_rate도 null")를 어겼다. `run()`에서 `progress_rate` 계산 후 `None`이면 `achievement_rate`도 강제 null로 게이팅. [gap_engine.py:159-166]
- [x] [Review][Patch] **plan 삭제 시 오래된 valueup_score가 안 지워짐** (High) — plan이 사라진 corp는 `continue`만 하고 기존 score 행이 고아로 남음. gap_engine이 유일 writer(AD-4)이므로 정합성 정리 책임도 이 모듈에 있음. `repo.delete_valueup_score` 신규, plan 없으면 호출. [gap_engine.py:148-150, valueup_score.py]
- [x] [Review][Patch] **look-ahead 부분차단: 같은 해 사업보고서 사용** (High) — `year<=as_of_year`만으로는 같은 연도의 사업보고서(quarter=4, 통상 다음해 3월 공시)를 그 해 안에 써버리는 미래정보 누출이 가능. `year<as_of_year OR (year=as_of_year AND quarter<4)`로 수정(사업보고서 동일연도 무조건 배제 — 이 규칙은 항상 참). 1~3분기 보고서의 동일연도 내 시차는 실제 공시일 데이터 없이는 완전 해결 불가 → **잔여 리스크로 defer**(아래). [valueup_score.py: latest_metrics, latest_financial_buyback]
- [x] [Review][Patch] **음수 자사주 수량이 확정 활동없음으로 취급됨** (High) — `_buyback_signals`가 음수를 그대로 `>0` 비교해 False(확정) 처리. 1.8의 `_parse_quantity`가 상류에서 음수를 이미 걸러 현재 DB엔 못 들어오지만, gap_engine 자체 방어 부재는 사실 — 음수도 unknown 처리(belt-and-suspenders). [gap_engine.py:_buyback_signals]
- [x] [Review][Patch] **as_of 비표준 포맷이 문자열 날짜비교를 깨뜨릴 수 있음** (High) — `disclosure_date <= as_of` 사전식 비교는 양쪽이 zero-padded YYYY-MM-DD일 때만 안전. `run()` 진입 시 정규식으로 fail-fast(전체 프로젝트가 날짜를 String(10)으로 저장하는 기존 컨벤션 자체는 스코프 밖 — dart.py의 `_YEAR_RE.match` 패턴과 동일한 입력 검증만 추가). [gap_engine.py:_AS_OF_RE]
- [x] [Review][Patch] **washing_flag null 전파가 과잉보수적(Kleene 3치 논리 미적용)** (Med) — "하나라도 None→전체 None"은 안전하지만 확정 가능한 케이스(예: 소각 확정 True)까지 불필요하게 null로 냄. Kleene 3치 AND로 재작성(확정 False 우선 판정) + scoring.md·AC6 텍스트 동기화. [gap_engine.py:_washing_flag, scoring.md]
- [x] [Review][Patch] **gap_engine이 직접 SQL 실행(AD-2 자기모순)** (Med) — 모듈 docstring이 "SQL 직접 실행 안 함"이라 써놓고 `select(Company.corp_code)`를 gap_engine.py에서 직접 실행. `repo.list_all_corp_codes` 신규로 이동. [gap_engine.py, valueup_score.py]
- [x] [Review][Patch] **`rec.get(field)`가 키 누락을 조용히 None으로 넘김** (Med) — 유일 호출자가 항상 7개 키를 채워 현재는 안전하나, 미래 실수 방지 위해 `rec[field]`(KeyError로 즉시 노출)로 강화. [valueup_score.py:upsert_valueup_score]
- [x] [Review][Patch] **동일 disclosure_date 시 최신 공시 선택이 비결정적** (Med) — `.order_by(disclosure_date.desc(), plan_id.desc())`로 2차 정렬키 추가(무해한 방어코드). **재검증 결과**: `valueup_plan`의 `UniqueConstraint(corp_code, disclosure_date)`(1.5, AD-7)가 이미 이 시나리오 자체를 DB 레벨에서 차단 — 같은 날짜에 두 공시가 절대 존재할 수 없어 tie-break은 실제로 발생 불가능함을 회귀 테스트로 확인(REFUTED, 그래도 정렬키는 유지). [valueup_score.py:latest_valueup_plan]
- [x] [Review][Patch] **회귀 테스트 부재** (Med) — 위 항목 전부에 대해 9개 신규 테스트 추가(AC3 게이팅·plan삭제 정리·look-ahead 배제·음수 unknown·as_of 검증·Kleene 확정-False 3종·tie-break 불가능 검증).

**Deferred (deferred-work.md 2-1 섹션 기록)**
- [x] [Review][Defer] **1~3분기 보고서의 동일연도 내 look-ahead 잔여 리스크** (High) — 사업보고서(연간)는 무조건 다음해 공시라 확정 배제 가능했지만, 분기/반기 보고서는 실제 공시일 데이터가 없어 완전 차단 불가(예: as_of가 분기보고서 공시 전이면 여전히 look-ahead 가능). 완전한 해결은 `financials`/`valuation_metrics`에 실제 공시일(`available_at`) 추가가 필요 — DART 어댑터·스키마를 가로지르는 별도 스토리 스코프.
- [x] [Review][Defer] **날짜 컬럼을 전부 String(10)이 아닌 DB Date 타입으로 전환** (Low) — 이번엔 `run()` 진입점 입력검증(fail-fast)만 추가. 전체 7개 테이블의 날짜 컬럼을 Date로 바꾸는 건 이 프로젝트 전체의 기존 컨벤션(마이그레이션 0001~0008 전부 String)을 깨는 큰 변경이라 스코프 밖.
- [x] [Review][Defer] **select-then-insert 동시성** (Low) — `upsert_valueup_score`도 동일 패턴. `upsert_financial`/`upsert_ownership`/`upsert_valueup_plan`과 동일한 기존 공통 defer 항목(단일 프로세스 배치 v1이라 보류, 병렬화 시 `ON CONFLICT` 전환).

## Dev Notes

### 🚨 핵심 설계 결정 (dev 착수 전 이해 필수)

1. **achievement_rate의 기준 지표 = ROE만** — `valueup_plan`은 `target_roe`·`target_payout_ratio`·`target_pbr` 세 목표를 갖지만, `execution_score` 산식(scoring.md)은 배당을 `actual_payout/target_payout`(0.2 가중)으로 **별도** 반영하고, `target_pbr`은 산식 어디에도 등장하지 않는다. 따라서 achievement_rate(0.5 가중, "목표 달성")는 **ROE 단독**으로 해석했다 — 배당까지 achievement_rate에 넣으면 0.2 가중과 이중 반영된다. **target_pbr은 이 스토리에서 미사용**(정보성 컬럼으로 남김) — 아래 "확인 요망" 참조.
2. **as_of는 연도 단위 정밀도** — `period_start`/`period_end`는 1.5 파서(`_PERIOD_RE`)가 만든 **4자리 연도 문자열**("2024")이지 ISO 날짜가 아니다. `progress_rate` 계산은 `as_of`(YYYY-MM-DD 가정)에서 연도만 취해 `int(as_of[:4])`로 비교한다. 날짜 단위 정밀도를 시도하지 말 것(입력이 연도뿐이라 거짓 정밀도).
3. **null 전파가 이 스토리의 핵심 계약** (오늘 1.8 코드리뷰로 scoring.md에 명문화, GPT High) — `buyback_retired_amount IS NULL`은 "모름"이지 "소각 안 함"이 아니다. `washing_flag`·`buyback_status`·`achievement_rate`·`progress_rate` 중 입력이 애매하면 **해당 스코어도 null**로 전파한다(0/False로 강제 금지). DB 컬럼은 전부 `nullable=True`(Boolean 포함) — SQLAlchemy `Boolean` 컬럼에 `None`을 넣으면 NULL로 저장됨, 앱 코드에서 `bool(None)`류 강제 캐스팅 금지.
4. **plan 없는 corp는 valueup_score 행 자체를 안 만든다** — `valueup_plan`이 없으면 target이 없어 갭을 정의할 수 없다(1-6 "no-data는 행 미생성" 교훈과 동일 원칙). all-null 행을 만들지 말 것.
5. **다중 공시(같은 corp, 여러 disclosure_date) 처리** — corp가 예고/본공시/정정 등 여러 `valueup_plan` 행을 가질 수 있다(1.5 스토리 노트). 이 스토리는 **as_of 시점에 유효한 가장 최신 공시**(`disclosure_date <= as_of` 중 MAX)를 target으로 채택한다. "목표기간(period_start~end)이 as_of를 포함하는 공시"를 우선하는 대안도 있으나, period가 연도 문자열뿐이라 정밀 판정이 어려워 **단순 최신 공시** 규칙으로 시작 — 아래 확인 요망 참조.
6. **actual_roe의 시점 정렬** — `valuation_metrics`는 (corp_code, year, quarter)별 행이 여러 개다. "as_of 시점의 실적"은 **as_of 이전 가장 최신 (year, quarter) 행**을 사용한다(미래 데이터 누수 방지 — as_of보다 미래 분기 실적을 쓰면 look-ahead bias). `year <= as_of연도`로 필터 후 최신 1건.

### AD-1 준수 (지표는 VIEW 전용, 스코어는 Python)

`valuation_metrics.roe`는 이미 VIEW가 계산한 값을 **그대로 읽기만** 한다(AD-1: "파이썬 지표 계산 금지"는 ROE·PBR 등 *밸류에이션 지표*에 적용되는 규칙). `achievement_rate`·`progress_rate`·`execution_score`는 지표가 아니라 **스코어**이고 AD-4가 명시적으로 `gap_engine`(Python)에 배정한 책임이다 — 이 둘을 혼동해 achievement_rate를 SQL로 옮기려 하지 말 것.

### null-safe 산술 헬퍼 (신규 필요, 재발명 금지 지점)

Python에서 `None > 0`, `None / x` 등은 예외 또는 잘못된 truthy 평가를 낸다(오늘 GPT 리뷰가 정확히 이 패턴을 1.8에서 지적). T3 순수 함수 작성 시 다음 원칙을 지킬 것:
```python
def _safe_ratio(actual: float | None, target: float | None) -> float | None:
    if actual is None or target is None or target <= 0:
        return None
    return actual / target
```
이런 헬퍼를 gap_engine.py 모듈 상단에 한 번 정의하고 achievement_rate·payout ratio 계산에 공유. `if x:` 같은 암묵적 truthy 체크로 `0`과 `None`을 섞지 말 것(1.8 리뷰의 핵심 교훈 — 0은 "확정된 활동 없음", None은 "모름").

### 재사용 (재발명 금지 — 기존 코드에서 가져올 것)

| 필요 | 기존 위치 | 재사용 방법 |
|---|---|---|
| valuation_metrics 뷰 raw SQL 조회 패턴 | `app/repositories/metrics.py:_BASE_SELECT`, `metrics_by_corp` | corp 1건 최신 조회로 변형(`ORDER BY year DESC, quarter DESC LIMIT 1`), `text()` + named params. |
| 멱등 upsert(None-safe, 자연키) | `app/repositories/ownership.py:upsert_ownership` | `(corp_code, as_of)` 동일 자연키 구조 그대로 미러. |
| config 임계치·가중치 주입 | `app/config.py` (이미 완비: `washing_progress_min/achievement_max`, `score_w_*`) | import해서 읽기만, 신규 설정 불필요. |
| 모델·마이그레이션 패턴 | `app/models.py Ownership`, `alembic/versions/0007_ownership.py` | 구조 그대로(id PK, corp_code FK, UniqueConstraint). |
| SQLite in-memory + 뷰 생성 테스트 fixture | `tests/test_metrics.py` (`CREATE_VALUATION_METRICS` import, `Base.metadata.create_all` + `conn.execute(text(...))`) | gap_engine 통합 테스트가 그대로 재사용. |

### 아키텍처 제약

- **AD-1**: valuation_metrics 지표는 VIEW가 계산한 값을 읽기만; achievement_rate 등 스코어는 Python(AD-4 배정).
- **AD-2**: SQL은 `app/repositories/valueup_score.py`에서만. `gap_engine.py`는 dict/스칼라만 다룸(서비스 레이어 없음 — 2.4가 API로 노출 시 그때 services/routers 추가).
- **AD-4**: `valueup_score`의 유일 writer는 `gap_engine`. 다른 어떤 코드도 이 테이블에 쓰지 않는다.
- **AD-7 확장**: `valueup_score` 자연키 `(corp_code, as_of)`(ownership과 동일 패턴, DB-schema.md에 명시적 자연키 언급은 없으나 AD-8 as_of 컬럼 + 기존 스코어 테이블 관례로 확정).
- **AD-8**: `valueup_score`에 `as_of` 컬럼, `progress_rate` 계산의 "today"는 인자로 받은 `as_of`(시스템 시계 사용 금지 — 재현 가능한 배치를 위해).
- **NFR2**: 계산 불가(입력 null/애매)는 결과 null, 예외로 배치 중단 금지.
- **NFR3**: 임계치·가중치는 `config.py`에서 주입(이미 존재, 이 스토리에서 추가 파라미터 불필요).

### 데이터 모델 (valueup_score, 신규)

`app/models.py`에 추가([Source: db-schema.md#valueup_score]):
```python
class ValueupScore(Base):
    """Value-up 갭 스코어 (writer = gap_engine, AD-4). 자연키 (corp_code, as_of), AD-8."""

    __tablename__ = "valueup_score"
    __table_args__ = (
        UniqueConstraint("corp_code", "as_of", name="uq_valueup_score_corp_asof"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    corp_code: Mapped[str] = mapped_column(String(8), ForeignKey("company.corp_code"), index=True)
    as_of: Mapped[str] = mapped_column(String(10))
    achievement_rate: Mapped[float | None] = mapped_column(Float)
    progress_rate: Mapped[float | None] = mapped_column(Float)
    execution_score: Mapped[float | None] = mapped_column(Float)
    washing_flag: Mapped[bool | None] = mapped_column(Boolean)  # nullable 필수(null 전파)
    buyback_executed: Mapped[bool | None] = mapped_column(Boolean)
    buyback_retired: Mapped[bool | None] = mapped_column(Boolean)
    buyback_status: Mapped[str | None] = mapped_column(String(20))  # retired/purchased_only/none/unknown
```

### 소스 트리 (이 스토리)

```
app/
  models.py                      # UPDATE: ValueupScore 추가
  analysis/gap_engine.py         # NEW: run() + 순수 계산 함수 5종
  repositories/valueup_score.py  # NEW: 입력 조회 3종 + upsert_valueup_score
alembic/versions/0008_valueup_score.py   # NEW
tests/test_gap_engine.py         # NEW
docs/specs/spec-valueup-washing/db-schema.md   # UPDATE: valueup_score 자연키 명시(문서 정합)
```

**변경 없음**: `run.py`(이 스토리는 ingest 아님, 별도 진입점), `config.py`(임계치 이미 완비), 기존 어댑터·라우터.

### 테스트 표준

- T3 순수 함수는 fixture 없이 직접 인자 주입(빠름). T4는 `tests/test_metrics.py`의 SQLite in-memory + `CREATE_VALUATION_METRICS` 뷰 생성 패턴 재사용.
- 필수 케이스: progress_rate — period 정상(0.5 근처)·시작 전(0 클램프)·종료 후(1 클램프)·period_start==period_end(0 나눗셈 방어, null)·period null. achievement_rate — 정상·target_roe=0(null)·target_roe<0(null)·actual_roe null(null). buyback_status 4분류 전부(retired/purchased_only/none/unknown) + null 조합 매트릭스. washing_flag — 정상 True/False + 세 입력 중 하나씩 null인 케이스 3종(전부 null 전파 확인). 멱등 upsert(재실행 시 행 수 불변, 값 갱신).
- 실행: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest -q`. **기존 100 passed 회귀 0** 확인.

### Previous Story Intelligence (1.7 VIEW/API, 1.8 buyback 리뷰)

- **1.7**: `valuation_metrics` 뷰가 이미 `roe`·`payout_ratio`·`net_cash`·`ebitda_margin` 등을 계산 완료 — 이 스토리는 그 값을 읽기만 하면 됨. 뷰 접근은 `text()` raw SQL(`repositories/metrics.py` 패턴), SQLAlchemy ORM 매핑 없음(의도된 설계, 1-7 known-limitation에 이미 문서화됨 — "ValuationMetric ORM 매핑 미구현"은 정상).
- **1.8 리뷰(오늘)의 직접 영향**: null≠0 구분이 scoring.md에 명문화됐고, 이 스토리가 그 첫 소비자다. 특히 `_safe_ratio`류 헬퍼로 `None`과 `0`을 절대 혼동하지 말 것 — 이게 1.8에서 GPT가 잡은 최대 결함이었다.
- **1.6 "null > 틀린 값" 원칙**: 이 스토리도 동일 — 계산 불가를 억지로 0/False로 메우지 않는다.
- **콘솔 인코딩**: `PYTHONIOENCODING=utf-8`(cp949 표시깨짐은 데이터 정상, 기존 관례).

### 알려진 한계 / 스코프 경계 (v1)

- **target_pbr 미사용**: 수집은 되지만(1.5) 이 스토리의 스코어 산식에 반영되지 않음(scoring.md 자체가 미참조). 후속(2.4 갭 API 응답에 참고 표시용으로만 노출 검토).
- **다중 공시 처리 = "최신 공시 채택"**: 목표기간이 as_of를 포함하는 공시를 우선하는 정밀 로직은 v1 범위 밖(아래 확인 요망 1).
- **연도 단위 progress_rate**: 월/일 정밀도 없음(입력 데이터 자체가 연도뿐이라 구조적 한계).
- **분기 반영 지연**: `actual_roe`는 "as_of 이전 최신 공시 분기" 기준이라 실제 최신 실적 대비 시차 존재 가능(연간 데이터 위주 수집이라 보통 최대 1년 지연, 1-7 TTM defer와 유사 계열).
- **API 없음**: 이 스토리는 계산·적재만. `valueup_score` 조회는 2.4(갭분석 API)가 노출.

### 착수 전 결정 확정 (2026-07-10, 리드)

1. **다중 valueup_plan 시 target 선택 = A(as_of 이전 최신 공시)** 확정. 기간-포함 판정(B)은 하지 않는다 — 가장 단순하고 재현 가능한 규칙으로 v1 고정.
2. **target_pbr = 계산에서 완전 제외, 참고값으로만 보관** 확정. `valueup_plan.target_pbr`은 이미 컬럼으로 존재하니 이 스토리에서 추가 작업 없음(그냥 안 씀). **2.4(갭분석 API) 설계 시 응답에 참고 컬럼으로 노출할지는 그때 결정** — 이 스토리 스코프 아님.
3. **washing_flag null의 UI 표시 = 2.4/Epic 3 스코프**로 확정 이관. 이 스토리는 "null을 null 그대로 DB에 저장"까지만 책임진다. **UI 설계 메모(선반영)**: null을 빈칸/"아니오"로 표시하면 안 되고 "판단 불가"로 표시해야 함 — 2.4/UX 스토리 착수 시 이 메모 참조.

### 스택

FastAPI 0.139.0 / SQLAlchemy 2.0.51 / PostgreSQL 17(개발 SQLite) / alembic. Python 3.12. **신규 외부 의존성 없음**(순수 계산 + 기존 DB 접근 패턴).

### References

- [Source: epics.md#Story-2.1] — AC 원본, FR4
- [Source: scoring.md] — achievement_rate/progress_rate/execution_score/washing_flag/buyback_status 산식 전체(오늘 null≠0 강화 포함)
- [Source: db-schema.md#valueup_score] — 컬럼 목록
- [Source: ARCHITECTURE-SPINE.md#AD-1,2,4,7,8] — VIEW vs 스코어 계산 경계, gap_engine 유일 writer, as_of 계약
- [Source: 1-7-metrics-view-api.md] — valuation_metrics 뷰 컬럼·raw SQL 조회 패턴
- [Source: 1-8-ingest-buyback-status.md] — buyback_amount/retired_amount가 실데이터로 채워지는 경로, null≠0 코드리뷰 교훈
- [Source: app/config.py] — 기존 임계치·가중치(NFR3, 신규 불필요)

## Dev Agent Record

### Agent Model Used

claude-fable-5 (bmad-dev-story)

### Debug Log References

- **achievement_rate = ROE 단독**: `_achievement_rate`는 `_safe_ratio(actual_roe, target_roe)`만 계산. target_pbr은 어디서도 읽지 않음(리드 결정 반영, 참고 보관은 valueup_plan 원본에 그대로 존재).
- **연도 단위 progress_rate**: `_progress_rate`가 `int(period_start)`/`int(period_end)` 파싱 후 `as_of_year`(as_of 문자열 앞 4자리)로 비교. 파싱 실패·end<=start는 None.
- **null 전파 전 구간 관철**: `_safe_ratio`(target<=0/None→None), `_buyback_signals`(amount/retired_amount 중 하나라도 None→status="unknown"), `_execution_score`(achievement/buyback_executed/payout_ratio 중 하나라도 None→전체 None), `_washing_flag`(네 입력 중 하나라도 None→None) — 전부 "0/False로 강제 금지" 계약을 함수 시그니처 수준에서 강제.
- **다중 공시 = 리드 결정 A**: `latest_valueup_plan`이 `disclosure_date <= as_of` 중 `ORDER BY disclosure_date DESC LIMIT 1`. 테스트로 구버전 공시가 아니라 최신 공시의 target이 쓰이는지 확인(`test_run_picks_latest_disclosure_before_as_of`).
- **look-ahead 방지**: `latest_metrics`/`latest_financial_buyback`이 `year <= as_of_year`로 필터 후 최신 1건만 — as_of 시점에 알 수 없었을 미래 실적을 쓰지 않음.
- **plan 없는 corp는 행 미생성**: `run()`이 `plan is None`이면 continue(1-6 no-data 패턴).
- **AD-1/AD-2 경계 준수**: `latest_metrics`가 `valuation_metrics` VIEW를 `text()` raw SQL로 읽기만(계산 안 함, repositories/metrics.py 패턴 재사용). `gap_engine.py`는 SQL을 직접 실행하지 않고 `app/repositories/valueup_score.py`의 3개 읽기 함수 + 1개 upsert만 호출(AD-2).
- **AD-4 준수**: `valueup_score`의 유일 writer는 `upsert_valueup_score`(gap_engine이 호출하는 유일한 쓰기 경로).

### Completion Notes List

- `ValueupScore` 모델 + 마이그레이션 0008(revises 0007) → `alembic upgrade head` 검증 완료. 자연키 `(corp_code, as_of)`, Boolean 컬럼 전부 nullable(null 전파 필수).
- `app/repositories/valueup_score.py`: `latest_valueup_plan`/`latest_metrics`/`latest_financial_buyback`(읽기 3종) + `upsert_valueup_score`(null 포함 전체 교체, valueup_plan upsert와 동일 원칙 — 재계산 시 과거 오탐이 null로 정정).
- `app/analysis/gap_engine.py`: 순수 함수 5종(`_safe_ratio`/`_progress_rate`/`_achievement_rate`/`_buyback_signals`/`_execution_score`/`_washing_flag`) + 오케스트레이션 `run(session, as_of, corp_codes=None) -> int`.
- **검증(구현 직후)**: pytest 127 passed(gap_engine 27 신규, 회귀 0).
- **리드 결정 3건 전부 코드 반영**: (1) 최신공시 채택 A, (2) target_pbr 미사용(참고값은 valueup_plan 원본에 이미 보관, 이 스토리에서 추가 컬럼 복제 안 함), (3) washing_flag null을 DB에 그대로 저장(UI 표시는 2.4로 이관, 코드 주석에 "판단 불가" 표시 요구사항 메모).
- **코드리뷰(GPT) 반영 후 최종 검증**: pytest **136 passed**(gap_engine 36개: 구현 27 + 리뷰 회귀 9, 기존 100 회귀 0). High 5건·Med 5건 패치, 1건(tie-break) 재검증 결과 스키마 제약(1.5 UniqueConstraint)으로 발생 불가능함을 회귀 테스트로 실증(REFUTED). Defer 4건은 deferred-work.md 2-1 섹션 참조 — 가장 중요한 잔여 리스크는 "1~3분기 보고서의 동일연도 내 look-ahead"(사업보고서는 확정 배제했으나 분기/반기는 실제 공시일 데이터 없이는 완전 차단 불가, 별도 스토리 스코프).

### File List

- `app/models.py` (UPDATE: `ValueupScore` 모델 추가)
- `alembic/versions/0008_valueup_score.py` (NEW)
- `app/repositories/valueup_score.py` (NEW→UPDATE: 입력 조회 3종+upsert, 리뷰로 `list_all_corp_codes`·`delete_valueup_score` 추가, look-ahead 부분차단, tie-break 정렬키, `rec[field]` 강화)
- `app/analysis/gap_engine.py` (NEW→UPDATE: 순수 계산 함수 6종+`run()`, 리뷰로 AC3 게이팅·Kleene 3치 washing_flag·음수 방어·as_of 검증·AD-2 위반 제거)
- `tests/test_gap_engine.py` (NEW→UPDATE: 구현 27종 + 리뷰 회귀 9종 = 36)
- `docs/specs/spec-valueup-washing/scoring.md` (UPDATE: washing_flag를 Kleene 3치 논리로 명문화)
- `docs/implementation-artifacts/deferred-work.md` (UPDATE: 2-1 리뷰 defer 4건)
- `docs/implementation-artifacts/review-bundle-2-1.md` (NEW: GPT 리뷰 요청 번들)

## Change Log

- 2026-07-10: Story 2.1 컨텍스트 생성(bmad-create-story) — Value-up 갭 스코어링 엔진. Epic 2 첫 스토리(수집→계산 패턴 전환). 핵심 설계: achievement_rate=ROE단독(target_pbr 미사용, payout은 별도 가중), 연도단위 progress_rate(period_start/end가 4자리 연도 문자열), null≠0 전파 계약(1.8 리뷰로 오늘 강화된 scoring.md 그대로 구현), 최신공시 채택 규칙, look-ahead 방지 위한 as_of 이전 최신 실적 사용. Status: ready-for-dev.
- 2026-07-10: 리드 결정 확정 — (1) 다중공시 시 as_of 이전 최신 공시 채택(A), (2) target_pbr은 계산 제외·참고값 보관만(2.4에서 노출 여부 결정), (3) washing_flag null의 UI 표시("판단 불가", 빈칸/아니오 금지)는 2.4/Epic 3 스코프로 이관, 이번 스토리는 DB에 null 정확 저장까지만 책임.
- 2026-07-10: Story 2.1 구현(bmad-dev-story) — ValueupScore 모델+마이그레이션 0008, valueup_score 저장소, gap_engine.py. pytest 127 passed. Status → review.
- 2026-07-10: 코드리뷰(GPT, verbatim 번들) — **Patch 9건 반영**: AC3 위반 수정(achievement_rate가 progress_rate 무효 시 별도 계산되던 버그, High), plan 삭제 시 오래된 score 정리(reconciliation, High), look-ahead 부분차단(같은 해 사업보고서 배제, High), 음수 buyback 방어(High), as_of 포맷 fail-fast(High), washing_flag Kleene 3치 논리로 재작성(Med, scoring.md·AC6 동기화), gap_engine의 AD-2 위반 제거(Med), upsert 키 강제(Med), tie-break 정렬키(Med, 재검증 결과 REFUTED이나 방어코드 유지). 리뷰 회귀 테스트 9종 추가. **pytest 136 passed**(회귀 0). Defer 4건(1~3분기 look-ahead 잔여 리스크가 가장 중요, 별도 스토리 스코프). Status → done.
- 2026-07-10: Story 2.1 구현(bmad-dev-story) — `ValueupScore` 모델+마이그레이션 0008, `app/repositories/valueup_score.py`(입력 조회 3종+upsert), `app/analysis/gap_engine.py`(순수 계산 함수 6종+`run()`). 리드 결정 3건 전부 코드 반영(최신공시 A·target_pbr 미사용·washing null DB저장). **pytest 127 passed**(gap_engine 27 신규, 회귀 0). Status → review.
