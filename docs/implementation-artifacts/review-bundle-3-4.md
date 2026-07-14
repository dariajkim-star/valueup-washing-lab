# Review Bundle — Story 3.4: 종목 상세 & 투자 포인트 카드 (2026-07-13)

역할: 컨텍스트 없는 시니어 풀스택(FastAPI+React/TS) 리뷰어. 아래 AC·제약·코드(verbatim, 축약 없음)만 보고 실제 버그·계약 위반·null 처리 결함을 찾아라. 스타일보다 동작 결함 우선.

## AC 요약

1. 리스트 종목 클릭 → 상세 화면(지표 시계열·갭카드·M&A 4요소).
2. 갭 카드: /valueup/gap-analysis(corp_code 필터, 신규)의 target/actual/gap/achievement/progress/buyback, null 계약 유지.
3. M&A 4요소: /mna/ranking(corp_code 필터, 신규)의 4요소+population_basis, 산출불가/미지원업종 null 계약 유지.
4. 지표 시계열: /metrics/{corp_code}(기존, 무변경) 분기별 지표 차트.
5. 투자 포인트 자동 태깅(밸류업: 고ROE·저PBR·자사주실이행 / M&A: 저평가·저부채·낮은지분율) — 근거 null이면 태그 미생성.
6. 딥링크(/company/:corpCode) 직접 진입 가능, 뒤로가기 시 리스트 필터 보존.
7. AD-2(SQL은 repository만)·AD-6(에러계약) 준수, 기존 필터·정렬·null 계약과 충돌 없음.
8. 백엔드 pytest 회귀 0 + 신규 필터 테스트, 라이브 검증.

## 아키텍처 제약

- AD-2: 라우터·서비스는 SQL 실행 금지.
- AD-4/AD-10: valueup_score·mna_score는 각 엔진만 write — corp_code 필터는 읽기 조건 추가일 뿐.
- AD-6: 목록 봉투 {items,total,page,size}, 에러 {detail,code}.
- AD-11: 프론트는 REST만, 서버상태(TanStack Query)/UI상태(zustand) 분리.

## 설계상 의도된 선택(재보고 불필요)

- 신규 "detail" 엔드포인트를 만들지 않고 기존 3개 목록 API(`/screening`·`/valueup/gap-analysis`·`/mna/ranking`)에 `corp_code` 정확일치 필터만 추가하고 프론트가 `size=1`로 호출 — API 표면 확장 최소화가 의도.
- `/metrics/{corp_code}`는 1.7에 이미 존재하는 엔드포인트로 **무변경**.
- 투자 포인트 임계치(roe≥10%·pbr≤1.0·factor≥0.7)는 config.py의 스코어링 가중치와 무관한 **프론트 표시 로직 상수** — "셀링포인트로 부를 만한가"의 판단이지 스코어 산식이 아님.
- capacity_score를 "저부채"로 라벨링하는 것은 2.3 산식(부채비율+순현금+마진 복합)의 근사 — 100% 정확한 라벨이 아님을 스토리에 명시된 알려진 한계로 기록.
- 3.3에서 확립된 look-ahead 부분 차단(사업보고서만 확정 배제, 1~3분기 동일연도 잔여 리스크는 defer)이 이 스토리가 재사용하는 /metrics·/valueup·/mna 엔드포인트에도 동일하게 적용됨 — 이 스토리 신규 이슈 아님.

## 알려진 것(재보고 불필요)

- score_run 배치 메타데이터(latest_as_of 오염 가능성) — 2.4부터 이어진 공통 defer.
- 2단계 IN 필터 확장성(screening 지표 필터) — 3.3에서 defer 등재, 이 스토리 무관.
- capacity_score→"저부채" 라벨 근사 — 스토리에 명시된 한계.

## 파일 (verbatim)

### `docs/implementation-artifacts/3-4-detail-investment-card.md`

```markdown
---
baseline_commit: d1a5788
---

# Story 3.4: 종목 상세 & 투자 포인트 카드

Status: review

## Story

As a 애널리스트,
I want 종목을 눌러 상세 지표·스코어 분해·투자 포인트를 보는 것,
so that 개별 종목의 밸류업 이행과 인수 매력을 판단한다.

## Acceptance Criteria

1. **Given** 리스트에서 종목 행을 클릭하면, **When** 상세 화면(3.2 Screen 2 시안)으로 이동하면, **Then** 지표 분기 시계열·"계획 vs 실제" 갭 카드·M&A 4요소 분해가 표시된다.
2. **Given** 갭 카드, **Then** `/valueup/gap-analysis`(corp_code 필터, 신규)의 target_roe·actual_roe·roe_gap·achievement_rate·progress_rate·buyback_status가 표시되고, null 계약(판단 불가 등)이 리스트와 동일하게 유지된다.
3. **Given** M&A 4요소 분해, **Then** `/mna/ranking`(corp_code 필터, 신규)의 valuation_score·capacity_score·ownership_score·macro_score·population_basis가 표시되고, 산출 불가/미지원 업종 null 계약이 유지된다.
4. **Given** 지표 시계열, **Then** `/metrics/{corp_code}`(1.7 기존 엔드포인트, 변경 없음)의 분기별 roe(또는 다른 지표)가 차트로 표시된다.
5. **Given** 투자 포인트 카드, **Then** 밸류업("고ROE·저PBR·자사주 실이행")·M&A("저평가·저부채·낮은 지분율") 태그가 지표·스코어 임계치 기반으로 자동 태깅되고, 근거가 될 데이터가 null이면 그 태그는 생성하지 않는다(추측으로 태그 만들기 금지 — null 정직성 원칙 승계).
6. **Given** 딥링크, **Then** `/company/:corpCode` 라우트로 상세 화면에 직접 진입 가능하고(React Router), 뒤로가기로 리스트 필터 상태가 보존된다.
7. **Given** 레이어 규약, **Then** 3개 엔드포인트 확장 모두 AD-2(SQL은 repository만)·AD-6(에러 계약) 준수, 기존 필터·정렬·null 계약과 충돌 없음.
8. **Given** 검증, **Then** 백엔드 pytest 회귀 0 + 신규 필터 테스트, 라이브로 리스트→상세 클릭 이동·시계열·갭카드·4요소·투자포인트 태그 렌더 확인.

## Tasks / Subtasks

- [x] **T1**: 백엔드 — `/screening`·`/valueup/gap-analysis`·`/mna/ranking`에 `corp_code`(정확일치, 8자리) 필터 추가. repository 3곳에 `if filters.get("corp_code")` 조건 추가(최소 침습, 기존 로직 불변). pytest 3종 추가 → 231 passed.
- [x] **T2**: `dashboard` 라우팅 스캐폴딩 — `react-router-dom` 추가, `/`(리스트, `pages/ScreenerList.tsx`로 이관)·`/company/:corpCode`(상세) 라우트. 필터 상태(zustand)는 라우트 전환에 자동 보존.
- [x] **T3**: API 훅 3종(`api/detail.ts`) — `useMetricsByCorp`·`useGapDetail`·`useMnaDetail`(전부 `select: page.items[0] ?? null` — 없으면 null, 종목이 스코어 미보유일 수 있음). `useScreeningDetail`(헤더용, `api/screening.ts`)도 추가.
- [x] **T4**: `MetricsChart.tsx`(Recharts BarChart) — 분기별 ROE, 최신 분기만 진한 색.
- [x] **T5**: `GapCard.tsx` — 목표/실제/갭 + 달성률·진척률·자사주, `WashingBadge` 재사용.
- [x] **T6**: `MnaBreakdown.tsx` — 4요소 바 + `PopulationBasisChip` 재사용, 총점 null 시 안내문.
- [x] **T7**: `lib/investmentTags.ts`(순수 함수) + `InvestmentPoints.tsx`(카드).
- [x] **T8**: `CompanyDetail.tsx` 조립 + `ScreenerTable` 행 클릭 → `navigate`.
- [x] **T9**: vitest 12종 — 임계치 경계(roe=10·pbr=1.0·factor=0.7)·null 시 미태깅·undefined 안전성.
- [x] **T10**: 라이브 검증(아래) — 딥링크·리스트클릭·필터보존·null 렌더·태그 로직 실증.

## Dev Notes

### API 확장 설계 (신규 엔드포인트 대신 필터 추가)

기존 3개 목록 API가 이미 필요한 필드를 전부 갖고 있어 — 새 "detail" 엔드포인트를 만드는 대신 **각 API에 `corp_code` 정확일치 필터를 추가하고 프론트가 `size=1`로 호출**한다(2.4~2.6의 "목록+필터" 패턴을 그대로 재사용, REST 표면 확장 최소화). `/metrics/{corp_code}`는 이미 1.7에서 이런 패턴(단건 조회용 경로)이 있으므로 그대로 사용.

- `/screening?corp_code=X` — 헤더용(corp_name·market·sector·execution_score·mna_target_score·washing_flag·has_*_score) — **이미 corp_code 필터가 없어 이번에 추가**.
- `/valueup/gap-analysis?corp_code=X` — 갭 카드 상세(target/actual/gap/achievement/progress/buyback).
- `/mna/ranking?corp_code=X` — 4요소 분해 + population_basis.

### 자동 태깅 규칙 (AC5, 순수 함수로 구현 — 임계치는 config 아님, 프론트 표시 로직)

- 밸류업 태그: `고ROE`(roe ≥ 업종 평균 또는 절대 임계 — 이번 스코프는 절대 임계 10%대 단순 규칙, 정밀 업종상대는 후속) · `저PBR`(pbr ≤ 1.0) · `자사주 실이행`(buyback_status === "retired").
- M&A 태그: `저평가`(valuation_score ≥ 0.7) · `저부채`(capacity_score ≥ 0.7) · `낮은 지분율`(ownership_score ≥ 0.7) — capacity_score는 부채비율뿐 아니라 순현금·마진도 섞인 복합 지표이므로 "저부채" 라벨이 100% 정확하진 않음(2.3 산식 자체가 그렇게 설계됨, 라벨은 최우세 요인 근사) — 스토리 스코프 한계로 기록.
- **null이면 태그 미생성**(0으로 취급해 태그를 만들지 않음) — 관련 지표가 null인데 태그를 추측하면 API가 지킨 null 정직성이 화면 마지막 단계에서 깨짐.

### 라우팅과 상태

- `react-router-dom` 도입 — 지금까지는 단일 화면이라 라우팅이 없었음. 필터 상태(zustand)는 전역 스토어라 라우트 전환에도 유지됨(리스트로 뒤로가기 시 필터 보존, AC6).
- 상세 페이지는 리스트와 별개로 4개 API를 병렬 호출(TanStack Query 병렬 쿼리) — AD-11 준수(전부 REST).

### 아키텍처 가드레일

- AD-2(SQL은 repository만), AD-6(에러 계약), AD-4/AD-10(valueup_score·mna_score 읽기 전용 — corp_code 필터는 읽기 조건 추가일 뿐 write 경로 아님).
- 백엔드 변경은 **필터 파라미터 추가만**(응답 스키마 변경 없음) — 기존 2.4~2.6 테스트 전부 불변, 신규 테스트만 추가.

## Dev Agent Record

### Agent Model Used

claude-sonnet-5 (bmad-create-story + 인라인 구현)

### Debug Log References

- corp_code 필터는 3개 repository(screening/valueup_score/mna_score)의 `conds` 리스트에 `Company.corp_code == filters["corp_code"]` 한 줄씩 추가 — 기존 필터·정렬·페이지네이션 로직과 완전 직교(다른 필터 조합에 영향 없음).
- 상세 페이지는 4개 쿼리를 병렬 호출(TanStack Query가 자동 병렬화) — `useScreeningDetail`(헤더)·`useGapDetail`(갭카드)·`useMnaDetail`(4요소)·`useMetricsByCorp`(시계열). 각각 독립 로딩 상태라 한쪽이 늦어도 나머지는 먼저 렌더.
- 자동 태깅은 `investmentTags.ts`에 분리된 순수 함수 — 컴포넌트가 아니라 데이터만 받아 `Tag[]`를 반환하므로 vitest로 임계치 경계(정확히 10%, 정확히 1.0x, 정확히 0.7)를 직접 검증.

### Completion Notes List

- **라이브 검증(백엔드 uvicorn:8000 + Vite:5175, valueup.db 실데이터)**:
  - 딥링크 직접 진입(`/company/00155319`, 새로고침 없이 navigate) — 포스코홀딩스 4개 섹션 전부 렌더(시계열 7분기·갭카드·4요소·투자포인트).
  - **null 계약이 상세 화면까지 정확히 관통**: 포스코홀딩스는 `target_roe`가 null이라 2.1의 게이팅 규칙대로 `roe_gap`·`achievement_rate`도 함께 null 전파 — 화면에 "목표 ROE —"·"갭 —"·"달성률 —"로 정직하게 표시됨(실행점수도 null→"—"). M&A 71점은 API 응답(71.06905...)과 반올림 일치.
  - **투자 포인트 태깅이 실데이터로 정확히 동작**: capacity_score=0.39(<0.7 임계)라 "저부채" 태그가 붙지 않고 valuation=0.89·ownership=0.91만 태그 생성 — 임계치 경계 로직이 실제 스코어 분포에서 옳게 작동함을 확인.
  - 리스트 행 클릭(기아) → 상세 이동 → "리스트로" 클릭 → 리스트 필터 패널·워싱토글·모드 상태 전부 보존(zustand 전역 스토어, 언마운트 없음).
  - 콘솔 에러 0, tsc clean.
- 백엔드 pytest **231 passed**(신규 3, 회귀 0). 프론트 vitest **44 passed**(신규 12).

### File List

- `app/repositories/screening.py`·`valueup_score.py`·`mna_score.py` (UPDATE: corp_code 필터)
- `app/routers/screening.py`·`valueup.py`·`mna.py` (UPDATE: corp_code 쿼리 파라미터)
- `tests/test_screening_api.py`·`test_valueup_api.py`·`test_mna_api.py` (UPDATE: corp_code 필터 테스트 3종)
- `dashboard/src/api/detail.ts` (NEW: useGapDetail·useMnaDetail·useMetricsByCorp)
- `dashboard/src/api/screening.ts` (UPDATE: corp_code 파라미터·useScreeningDetail)
- `dashboard/src/lib/investmentTags.ts`·`investmentTags.test.ts` (NEW)
- `dashboard/src/components/detail/MetricsChart.tsx`·`GapCard.tsx`·`MnaBreakdown.tsx`·`InvestmentPoints.tsx` (NEW)
- `dashboard/src/pages/ScreenerList.tsx` (NEW, App.tsx에서 이관)·`CompanyDetail.tsx` (NEW)
- `dashboard/src/App.tsx` (UPDATE: 라우터로 축소)·`main.tsx` (UPDATE: BrowserRouter)
- `dashboard/src/components/ScreenerTable.tsx` (UPDATE: 행 클릭 navigate)
- `dashboard/package.json` (UPDATE: react-router-dom·recharts 추가)

## Change Log

- 2026-07-13: Story 3.4 생성 — 종목 상세 화면. 기존 3개 목록 API에 corp_code 필터 추가(신규 엔드포인트 회피), React Router 도입, 자동 태깅 순수 함수(null 시 미생성 원칙).
- 2026-07-13: Story 3.4 구현 — 백엔드 corp_code 필터 3곳(231 passed), 프론트 라우팅+상세 4개 컴포넌트+자동태깅(44 passed), 라이브 검증(딥링크·null 전파·태깅 임계치·필터보존 전부 실증). Status → review(GPT 교차리뷰 대기).

```

### `app/repositories/screening.py`

```python
"""다중조건 스크리닝 조회 저장소 (AD-2: SQL은 여기서만).

company 기준으로 valueup_score·mna_score를 (corp_code, as_of) outer join — 한쪽 엔진이
그 as_of에 실행되지 않았으면 그쪽 필드가 null로 드러난다(세대 혼합을 조인으로 감추지 않고
정직 노출). 두 스코어 테이블 모두 **읽기 전용**(writer는 각 엔진, AD-4/AD-10).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import Session

from app.models import Company, MnaScore, ValueupScore

# 정렬 허용 필드 화이트리스트(AD-6 `field`/`-field` 규약). 사용자 입력을 컬럼 객체로만
# 매핑 — 여기 없는 필드는 InvalidSortError(라우터가 400으로 변환). metrics.py 패턴의 ORM 판.
SORT_COLUMNS = {
    "execution_score": ValueupScore.execution_score,
    "mna_target_score": MnaScore.mna_target_score,
}


class InvalidSortError(ValueError):
    """sort 필드가 화이트리스트 밖 — 사용자 입력 오류(400).

    ValueError를 그대로 잡으면 pydantic ValidationError(ValueError 하위)까지 400
    INVALID_SORT로 세탁된다(GPT 리뷰 Med) — 전용 타입으로만 잡는다.
    """


def validate_sort(sort: str | None) -> None:
    """sort 입력의 순수 검증(DB 접근 없음). 서비스 진입 직후 호출 — 스코어 미적재
    short-circuit보다 먼저 실행돼야 빈 DB에서도 잘못된 sort가 400이다(GPT 리뷰 Med).
    빈 문자열·`-`단독도 화이트리스트 밖으로 거부(GPT 리뷰 Low — 생략(None)과 빈 입력 구분).
    """
    if sort is None:
        return
    field = sort[1:] if sort.startswith("-") else sort
    if not field or field not in SORT_COLUMNS:
        raise InvalidSortError(f"invalid sort field: {field!r}")


def latest_as_of(session: Session) -> str | None:
    """두 스코어 테이블 latest as_of 중 max(가장 최근 엔진 실행 시점). 둘 다 없으면 None."""
    v = session.scalar(select(func.max(ValueupScore.as_of)))
    m = session.scalar(select(func.max(MnaScore.as_of)))
    candidates = [x for x in (v, m) if x is not None]
    return max(candidates) if candidates else None


def _latest_metrics_map(session: Session, as_of: str) -> dict[str, dict[str, Any]]:
    """corp별 look-ahead **부분 차단** 최신 지표(roe·pbr·ev_ebitda·debt_ratio) — 3.3 리뷰 반영.

    2.1/2.3/3.1과 동일한 사업보고서 배제 규칙 + Python dedupe(DISTINCT ON 회피, 이식성).
    **"안전"이 아니라 "부분 차단"인 이유(재리뷰 정정)**: 같은 해 사업보고서(quarter=4)만
    확정 배제 가능(항상 다음 해 공시). 1~3분기 보고서의 동일연도 시차는 실제 공시일
    (`available_at`) 데이터가 없어 차단 불가 — 명시적 과거 as_of 조회 시 그 해의 이후
    분기가 섞일 수 있다. 완전 해결은 공시일 수집 별도 스토리(deferred-work 2-1, 전 엔진·
    stats·screening 공통 한계 — 여기만 달력 휴리스틱을 넣으면 엔드포인트 간 규칙이 갈라짐).
    look-ahead 패턴 4번째 사용처 — 시그니처가 소비자마다 달라 공통화는 deferred.
    """
    as_of_year = int(as_of[:4])
    rows = session.execute(
        text(
            "SELECT corp_code, roe, pbr, ev_ebitda, debt_ratio FROM valuation_metrics "
            "WHERE year < :yr OR (year = :yr AND quarter < 4) "
            "ORDER BY corp_code, year DESC, quarter DESC"
        ),
        {"yr": as_of_year},
    ).mappings().all()
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["corp_code"] not in latest:  # 정렬상 corp별 첫 행 = 최신
            latest[row["corp_code"]] = dict(row)
    return latest


def _latest_market_cap_map(session: Session) -> dict[str, int | None]:
    """corp별 최신 시가총액(prices가 단일 원천, AD-9).

    뷰의 PBR과 동일하게 '전역 최신가' 컨벤션(1.7 known-limitation — 과거 as_of의
    point-in-time 시총은 기존 defer 그대로). 시총구간 필터 전용.
    """
    rows = session.execute(
        text("SELECT corp_code, market_cap FROM prices ORDER BY corp_code, date DESC")
    ).all()
    latest: dict[str, int | None] = {}
    for corp_code, market_cap in rows:
        if corp_code not in latest:
            latest[corp_code] = market_cap
    return latest


# 지표 범위 필터 정의: (파라미터 키, 지표 컬럼, 비교 방향). null 지표는 어느 범위에도
# 매칭되지 않는다(SQL 3치 논리와 동일 의미 — "산출 불가는 조건 판단 불가", 2.1 원칙).
_METRIC_FILTERS = (
    ("min_roe", "roe", "ge"),
    ("max_pbr", "pbr", "le"),
    ("max_ev_ebitda", "ev_ebitda", "le"),
    ("max_debt_ratio", "debt_ratio", "le"),
)


def _passes_metric_filters(m: dict[str, Any] | None, filters: dict[str, Any]) -> bool:
    for key, col, op in _METRIC_FILTERS:
        bound = filters.get(key)
        if bound is None:
            continue
        val = m.get(col) if m else None
        if val is None:  # 지표 없음/산출 불가 → 범위 필터 불통과(null 세탁 금지)
            return False
        if op == "ge" and val < bound:
            return False
        if op == "le" and val > bound:
            return False
    return True


def list_screening(
    session: Session, filters: dict[str, Any], page: int, size: int,
    sort: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """스크리닝 조회(2.6). 필터는 AND 조합, 범위 필터의 null은 SQL 3치 논리로 자연 배제
    ("산출 불가는 조건 매칭 불가"). buyback_executed=false는 `IS FALSE` — null(판단 불가)은
    true에도 false에도 안 걸린다(null 세탁 금지, 2.1 원칙).
    """
    as_of = filters["as_of"]
    conds: list[Any] = []
    if filters.get("corp_code") is not None:  # 3.4 상세화면 단건 조회용(정확일치)
        conds.append(Company.corp_code == filters["corp_code"])
    if filters.get("market") is not None:
        conds.append(Company.market == filters["market"])
    if filters.get("sector") is not None:
        conds.append(Company.sector.startswith(filters["sector"], autoescape=True))
    if filters.get("min_execution_score") is not None:
        conds.append(ValueupScore.execution_score >= filters["min_execution_score"])
    if filters.get("max_execution_score") is not None:
        conds.append(ValueupScore.execution_score <= filters["max_execution_score"])
    if filters.get("min_mna_score") is not None:
        conds.append(MnaScore.mna_target_score >= filters["min_mna_score"])
    if filters.get("max_mna_score") is not None:
        conds.append(MnaScore.mna_target_score <= filters["max_mna_score"])
    if filters.get("washing_only"):
        conds.append(ValueupScore.washing_flag.is_(True))
    if filters.get("buyback_executed") is not None:
        conds.append(ValueupScore.buyback_executed.is_(filters["buyback_executed"]))

    # 지표 범위 필터(3.3 리뷰 반영, AC2): 뷰(valuation_metrics)는 ORM 매핑이 없어 조인
    # 대신 2단계 — 통과 corp_code 집합을 Python에서 구해 IN 조건으로 주입. COUNT·정렬·
    # 페이지네이션은 SQL에 그대로 남는다(페이지 후 필터링 오류 방지).
    metrics_map = _latest_metrics_map(session, as_of)
    if any(filters.get(k) is not None for k, _, _ in _METRIC_FILTERS):
        passing = [
            code for code in metrics_map
            if _passes_metric_filters(metrics_map.get(code), filters)
        ]
        conds.append(Company.corp_code.in_(passing))
    # 시총구간 필터: prices 최신 시총(AD-9 단일 원천). null 시총은 불통과.
    if filters.get("min_market_cap") is not None or filters.get("max_market_cap") is not None:
        mcap = _latest_market_cap_map(session)
        lo, hi = filters.get("min_market_cap"), filters.get("max_market_cap")
        passing_mcap = [
            code for code, v in mcap.items()
            if v is not None and (lo is None or v >= lo) and (hi is None or v <= hi)
        ]
        conds.append(Company.corp_code.in_(passing_mcap))

    base = (
        select(Company, ValueupScore, MnaScore)
        .select_from(Company)
        .join(
            ValueupScore,
            and_(ValueupScore.corp_code == Company.corp_code,
                 ValueupScore.as_of == as_of),
            isouter=True,
        )
        .join(
            MnaScore,
            and_(MnaScore.corp_code == Company.corp_code, MnaScore.as_of == as_of),
            isouter=True,
        )
        # 두 스코어 모두 없는 종목 제외 — 회사정보만 있는 노이즈 행 방지
        .where(or_(ValueupScore.id.is_not(None), MnaScore.id.is_not(None)), *conds)
    )

    total = session.scalar(
        select(func.count()).select_from(base.subquery())
    ) or 0

    order = _order_by(sort)
    rows = session.execute(
        base.order_by(*order).limit(size).offset((page - 1) * size)
    ).all()

    items = []
    for company, vs, ms in rows:
        m = metrics_map.get(company.corp_code)
        items.append({
            "corp_code": company.corp_code,
            "corp_name": company.corp_name,
            "market": company.market,
            "sector": company.sector,
            "as_of": as_of,
            # 핵심지표(AC3, 3.3 리뷰 반영): look-ahead 부분 차단 최신 지표(재리뷰 정정 —
            # 같은 해 사업보고서만 확정 배제, 1~3분기 동일연도 잔여 리스크는 기존 defer).
            # 없으면 null.
            "roe": m.get("roe") if m else None,
            "pbr": m.get("pbr") if m else None,
            # has_* 플래그: "row 없음(엔진 미실행)"과 "row는 있으나 전부 null(엄격
            # 게이팅으로 산출 불가)"을 구분(GPT 리뷰 Med — 없으면 소비자가 식별 불가)
            "has_valueup_score": vs is not None,
            "has_mna_score": ms is not None,
            "execution_score": vs.execution_score if vs else None,
            "washing_flag": vs.washing_flag if vs else None,
            "buyback_status": vs.buyback_status if vs else None,
            "buyback_executed": vs.buyback_executed if vs else None,
            "mna_target_score": ms.mna_target_score if ms else None,
            "population_basis": ms.population_basis if ms else None,
        })
    return items, total


def _order_by(sort: str | None) -> list[Any]:
    """sort=`field`/`-field`를 화이트리스트로 안전 변환(null last 명시 + corp_code 안정 정렬).

    기본 정렬은 corp_code — 스크리닝은 양방향(워싱↔M&A 후보)이라 임의 기본 정렬로
    의미를 암시하지 않는다. 입력 검증은 validate_sort가 서비스 진입에서 선수행하지만,
    여기서도 방어적으로 재검증(단일 진입점 우회 대비).
    `is None`(truthiness 아님): 빈 문자열은 기본 정렬이 아니라 검증 오류다.
    """
    if sort is None:
        return [Company.corp_code.asc()]
    validate_sort(sort)
    desc = sort.startswith("-")
    field = sort[1:] if desc else sort
    col = SORT_COLUMNS[field]
    direction = col.desc() if desc else col.asc()
    return [col.is_(None), direction, Company.corp_code.asc()]  # null last(명시적)

```

### `app/repositories/valueup_score.py`

```python
"""valueup_score 입력 조회 + 멱등 upsert 저장소 (AD-2: SQL은 여기서만).

gap_engine(app/analysis/gap_engine.py)의 유일한 DB 접근 지점. 세 가지 읽기(공시 목표·
실적 지표·자사주 원천)와 한 가지 쓰기(스코어 upsert)로 구성. gap_engine 자체는 dict/스칼라만
다루고 SQL을 직접 실행하지 않는다(AD-2).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import Session

from app.models import Company, Financial, ValueupPlan, ValueupScore


def list_all_corp_codes(session: Session) -> list[str]:
    """전 종목 corp_code 목록(run()의 corp_codes 기본값). SQL은 여기서만(AD-2)."""
    return list(session.scalars(select(Company.corp_code)).all())


def latest_valueup_plan(
    session: Session, corp_code: str, as_of: str
) -> dict[str, Any] | None:
    """as_of 이전(포함) 최신 valueup_plan 1건. 여러 공시 중 as_of 직전 최신 것을 target으로 채택
    (2026-07-10 리드 결정 A: 기간-포함 판정 대신 단순·재현 가능한 규칙).

    동일 disclosure_date(원공시+정정공시 등) tie-break은 plan_id 내림차순(코드리뷰 Med,
    GPT) — 접수번호 등 진짜 우선순위 필드가 없어 "나중에 적재된 것"을 결정적으로 채택.
    """
    stmt = (
        select(ValueupPlan)
        .where(
            ValueupPlan.corp_code == corp_code,
            ValueupPlan.disclosure_date <= as_of,
        )
        .order_by(ValueupPlan.disclosure_date.desc(), ValueupPlan.plan_id.desc())
        .limit(1)
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        return None
    return {
        "target_roe": obj.target_roe,
        "target_payout_ratio": obj.target_payout_ratio,
        "target_pbr": obj.target_pbr,  # 계산 미사용, 참고 보관만(리드 결정)
        "period_start": obj.period_start,
        "period_end": obj.period_end,
        "buyback_planned": obj.buyback_planned,
    }


def latest_metrics(session: Session, corp_code: str, as_of: str) -> dict[str, Any] | None:
    """as_of 이전 최신 (year,quarter) valuation_metrics 행. look-ahead 부분 차단(코드리뷰 High,
    GPT): 같은 연도의 **사업보고서(quarter=4)는 그 해 안에 공시될 수 없음**(결산 후 통상 90일
    이내 = 다음 해)이므로 무조건 제외 — `year<as_of_year OR (year=as_of_year AND quarter<4)`.
    1~3분기 보고서의 동일연도 내 공시시차는 실제 공시일 데이터가 없어 잔여 리스크로 defer
    (deferred-work.md 2-1 섹션). AD-1: 뷰가 계산한 값을 읽기만.
    """
    as_of_year = int(as_of[:4])
    row = session.execute(
        text(
            "SELECT roe, payout_ratio FROM valuation_metrics "
            "WHERE corp_code = :cc AND (year < :yr OR (year = :yr AND quarter < 4)) "
            "ORDER BY year DESC, quarter DESC LIMIT 1"
        ),
        {"cc": corp_code, "yr": as_of_year},
    ).mappings().one_or_none()
    return dict(row) if row is not None else None


def latest_financial_buyback(
    session: Session, corp_code: str, as_of: str
) -> dict[str, Any] | None:
    """as_of 이전 최신 (year,quarter) financials의 buyback 수량 필드.
    look-ahead 부분 차단은 latest_metrics와 동일 규칙(사업보고서 동일연도 제외)."""
    as_of_year = int(as_of[:4])
    stmt = (
        select(Financial)
        .where(
            Financial.corp_code == corp_code,
            or_(
                Financial.year < as_of_year,
                and_(Financial.year == as_of_year, Financial.quarter < 4),
            ),
        )
        .order_by(Financial.year.desc(), Financial.quarter.desc())
        .limit(1)
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        return None
    return {
        "buyback_amount": obj.buyback_amount,
        "buyback_retired_amount": obj.buyback_retired_amount,
    }


def upsert_valueup_score(session: Session, rec: dict[str, Any]) -> ValueupScore:
    """(corp_code, as_of) 자연키 기준 valueup_score upsert(AD-7 확장 패턴).

    gap_engine 산출값은 항상 그 as_of의 '권위 있는 재계산 결과'이므로 null 포함 전체
    교체한다(valueup_plan upsert와 동일 원칙 — 재계산 시 과거 오탐이 null로 정정되게).
    `rec[field]`(직접 인덱싱, 코드리뷰 Med, GPT): 키 누락은 프로그래밍 오류이므로
    `.get()`으로 조용히 None 넘기지 않고 KeyError로 즉시 드러낸다.
    """
    stmt = select(ValueupScore).where(
        ValueupScore.corp_code == rec["corp_code"],
        ValueupScore.as_of == rec["as_of"],
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        obj = ValueupScore(corp_code=rec["corp_code"], as_of=rec["as_of"])
        session.add(obj)
    for field in (
        "target_roe", "actual_roe", "roe_gap",
        "achievement_rate", "progress_rate", "execution_score", "washing_flag",
        "buyback_executed", "buyback_retired", "buyback_status",
    ):
        setattr(obj, field, rec[field])
    return obj


def latest_as_of(session: Session) -> str | None:
    """valueup_score의 최신 as_of(기본 조회 기준일, 2.4). 없으면 None."""
    from sqlalchemy import func

    return session.scalar(select(func.max(ValueupScore.as_of)))


def list_scores(
    session: Session, filters: dict[str, Any], page: int, size: int
) -> tuple[list[dict[str, Any]], int]:
    """갭분석/워싱랭킹 서빙 조회(2.4). company 조인 + 필터 + execution_score 오름차순.

    null 정렬은 방언(SQLite NULLS FIRST/PG NULLS LAST 기본 차이)을 타지 않도록
    명시적 2단 키(`IS NULL` 우선순위 → 값)로 처리(1.7 defer 교훈). 동순위는 corp_code로
    안정 정렬(페이지네이션 결정성).
    """
    from sqlalchemy import func

    from app.models import Company

    conds = [ValueupScore.as_of == filters["as_of"]]
    if filters.get("corp_code") is not None:  # 3.4 상세화면 단건 조회용(정확일치)
        conds.append(Company.corp_code == filters["corp_code"])
    # `is not None`: 빈 문자열이 "필터 없음"으로 새지 않게(2-5 리뷰 패리티 — 1차 방어는
    # 라우터 min_length=1의 422)
    if filters.get("market") is not None:
        conds.append(Company.market == filters["market"])
    if filters.get("min_progress") is not None:
        conds.append(ValueupScore.progress_rate >= filters["min_progress"])
    if filters.get("washing_only"):
        conds.append(ValueupScore.washing_flag.is_(True))

    base = select(ValueupScore, Company).join(
        Company, Company.corp_code == ValueupScore.corp_code
    ).where(*conds)

    total = session.scalar(
        select(func.count()).select_from(base.subquery())
    ) or 0
    rows = session.execute(
        base.order_by(
            ValueupScore.execution_score.is_(None),  # null last(명시적)
            ValueupScore.execution_score.asc(),
            ValueupScore.corp_code.asc(),
        ).limit(size).offset((page - 1) * size)
    ).all()

    items = []
    for score, company in rows:
        items.append({
            "corp_code": score.corp_code,
            "corp_name": company.corp_name,
            "market": company.market,
            "as_of": score.as_of,
            "target_roe": score.target_roe,
            "actual_roe": score.actual_roe,
            "roe_gap": score.roe_gap,
            "achievement_rate": score.achievement_rate,
            "progress_rate": score.progress_rate,
            "execution_score": score.execution_score,
            "washing_flag": score.washing_flag,
            "buyback_status": score.buyback_status,
        })
    return items, total


def delete_valueup_score(session: Session, corp_code: str, as_of: str) -> None:
    """plan이 사라진 (corp_code, as_of)의 오래된 score를 정리(코드리뷰 High, GPT: 정합성
    reconciliation). gap_engine이 valueup_score의 유일 writer(AD-4)이므로 근거가 사라진
    행을 제거할 책임도 이 모듈에 있다. 없으면 no-op(멱등)."""
    stmt = select(ValueupScore).where(
        ValueupScore.corp_code == corp_code, ValueupScore.as_of == as_of,
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is not None:
        session.delete(obj)

```

### `app/repositories/mna_score.py`

```python
"""mna_score 배치 입력 조회 + 멱등 upsert 저장소 (AD-2: SQL은 여기서만).

mna_engine(app/analysis/mna_engine.py)의 유일한 DB 접근 지점. 2.1(gap_engine, 종목별 단건
조회)과 달리 **cross-sectional 백분위**라 전체 모집단을 배치로 한 번에 가져온다 — 종목 루프
안에서 단건 쿼리하면 N+1이자 설계 오류(한 종목의 점수가 전체 분포에 의존).

look-ahead 부분차단은 2.1(valueup_score.py)과 동일 규칙: 같은 연도의 사업보고서(quarter=4)는
그 해 안에 공시될 수 없으므로(통상 다음해 3월) 배제 — `year<yr OR (year=yr AND quarter<4)`.
1~3분기 동일연도 시차는 공통 defer(deferred-work.md 2-1 섹션).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import Company, MacroIndicator, MnaScore, Ownership


def list_all_corp_codes(session: Session) -> list[str]:
    """전 종목 corp_code 목록(run()의 corp_codes 기본값)."""
    return list(session.scalars(select(Company.corp_code)).all())


def all_company_sectors(session: Session) -> dict[str, str | None]:
    """전 종목 corp_code → sector(DART induty_code). 2.7 버킷 택소노미 입력."""
    rows = session.execute(select(Company.corp_code, Company.sector)).all()
    return {code: sector for code, sector in rows}


def all_latest_metrics(session: Session, as_of: str) -> dict[str, dict[str, Any]]:
    """전 종목의 as_of 시점 최신 (year,quarter) valuation_metrics 행(배치).

    corp_code → {ev_ebitda, pbr, debt_ratio, net_cash, ebitda_margin}.
    look-ahead 배제 후 corp별 최신 1행을 Python에서 선택(정렬된 결과 첫 등장 유지 —
    SQLite/PostgreSQL 양쪽에서 동일 동작, 데이터 규모상 충분).
    """
    as_of_year = int(as_of[:4])
    rows = session.execute(
        text(
            "SELECT corp_code, ev_ebitda, pbr, debt_ratio, net_cash, ebitda_margin "
            "FROM valuation_metrics "
            "WHERE year < :yr OR (year = :yr AND quarter < 4) "
            "ORDER BY corp_code, year DESC, quarter DESC"
        ),
        {"yr": as_of_year},
    ).mappings().all()
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = row["corp_code"]
        if code not in latest:  # 정렬상 corp별 첫 행 = 최신
            latest[code] = {
                "ev_ebitda": row["ev_ebitda"],
                "pbr": row["pbr"],
                "debt_ratio": row["debt_ratio"],
                "net_cash": row["net_cash"],
                "ebitda_margin": row["ebitda_margin"],
            }
    return latest


def all_latest_ownership(session: Session, as_of: str) -> dict[str, dict[str, Any]]:
    """전 종목의 as_of 이전(포함) 최신 ownership 행(배치).

    corp_code → {largest_shareholder_pct, treasury_stock_pct}.
    as_of 근사치(비12월 결산 라벨오류)는 1-6 known-limitation 그대로.
    """
    stmt = (
        select(Ownership)
        .where(Ownership.as_of <= as_of)
        .order_by(Ownership.corp_code, Ownership.as_of.desc())
    )
    latest: dict[str, dict[str, Any]] = {}
    for obj in session.scalars(stmt):
        if obj.corp_code not in latest:
            latest[obj.corp_code] = {
                "largest_shareholder_pct": obj.largest_shareholder_pct,
                "treasury_stock_pct": obj.treasury_stock_pct,
            }
    return latest


def latest_macro_percentile_basis(
    session: Session, as_of: str, indicator: str = "base_rate"
) -> tuple[float | None, list[float]]:
    """(as_of 이전 최신 지표값, as_of 이전 전체 역사 시계열) — 매크로 백분위 기준.

    모집단 = as_of 이전 전체 관측값(리드 결정: 롤링 윈도우 아님, ECOS 수집 기간 길어지면
    후속 재검토). as_of 이후 관측은 look-ahead라 제외.
    """
    stmt = (
        select(MacroIndicator)
        .where(MacroIndicator.indicator == indicator, MacroIndicator.date <= as_of)
        .order_by(MacroIndicator.date.desc())
    )
    objs = list(session.scalars(stmt))
    # 현재값 = 최신 '관측 행'의 값(null이면 null 그대로 — 과거 non-null로 몰래 대체 금지,
    # 코드리뷰 2026-07-10 High: AC6 엄격 null 위반이었음). history 정제와 현재값 선택은 분리.
    current = objs[0].value if objs else None
    history = [o.value for o in objs if o.value is not None]
    return current, history


def upsert_mna_score(session: Session, rec: dict[str, Any]) -> MnaScore:
    """(corp_code, as_of) 자연키 기준 mna_score upsert.

    2.1 upsert_valueup_score와 동일 정책: 권위 있는 전체 재계산 결과이므로 null 포함 전체
    교체 + `rec[field]` 직접 인덱싱(키 누락은 프로그래밍 오류 → KeyError로 즉시 노출).
    """
    stmt = select(MnaScore).where(
        MnaScore.corp_code == rec["corp_code"], MnaScore.as_of == rec["as_of"],
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        obj = MnaScore(corp_code=rec["corp_code"], as_of=rec["as_of"])
        session.add(obj)
    for field in (
        "mna_target_score", "valuation_score", "capacity_score",
        "ownership_score", "macro_score", "population_basis",
    ):
        setattr(obj, field, rec[field])
    return obj


# ── 서빙 조회 (2.5 /mna/ranking) ─────────────────────────────────────────────
# 위쪽은 mna_engine 전용 배치 입력·upsert, 아래는 API 서빙 읽기 전용(AD-10: 쓰기는 엔진만).


def latest_as_of(session: Session) -> str | None:
    """mna_score의 최신 as_of(기본 조회 기준일). 없으면 None.

    부분 실행이 latest_as_of를 오염시키는 문제는 2.4와 공통 defer(score_run 메타데이터,
    deferred-work.md) — 여기서 해결하지 않는다.
    """
    return session.scalar(select(func.max(MnaScore.as_of)))


def list_scores(
    session: Session, filters: dict[str, Any], page: int, size: int
) -> tuple[list[dict[str, Any]], int]:
    """M&A 타겟 랭킹 서빙 조회(2.5). company 조인 + 필터 + mna_target_score 내림차순.

    2.4 list_scores와 동일 골격, 정렬 방향만 반대(인수 매력 높은 순). null 정렬은
    방언 무관 명시적 키(`IS NULL` 우선 → 값 desc → corp_code 안정 정렬)로 처리.
    sector 필터는 KSIC prefix 매칭(2.7 버킷 택소노미와 동일 단위) — 정확일치로 하면
    세분류 코드(4~5자리)를 사용자가 알 수 없어 필터가 사실상 죽는다.
    """
    conds = [MnaScore.as_of == filters["as_of"]]
    if filters.get("corp_code") is not None:  # 3.4 상세화면 단건 조회용(정확일치)
        conds.append(Company.corp_code == filters["corp_code"])
    # `is not None`(truthiness 아님): 빈 문자열이 "필터 없음"으로 새는 것을 repo 층에서도
    # 차단(GPT 리뷰 Med — 1차 방어는 라우터 min_length=1의 422).
    if filters.get("market") is not None:
        conds.append(Company.market == filters["market"])
    if filters.get("sector") is not None:
        conds.append(Company.sector.startswith(filters["sector"], autoescape=True))

    base = select(MnaScore, Company).join(
        Company, Company.corp_code == MnaScore.corp_code
    ).where(*conds)

    total = session.scalar(
        select(func.count()).select_from(base.subquery())
    ) or 0
    rows = session.execute(
        base.order_by(
            MnaScore.mna_target_score.is_(None),  # null last(명시적)
            MnaScore.mna_target_score.desc(),
            MnaScore.corp_code.asc(),
        ).limit(size).offset((page - 1) * size)
    ).all()

    items = []
    for score, company in rows:
        items.append({
            "corp_code": score.corp_code,
            "corp_name": company.corp_name,
            "market": company.market,
            "sector": company.sector,
            "as_of": score.as_of,
            "mna_target_score": score.mna_target_score,
            "valuation_score": score.valuation_score,
            "capacity_score": score.capacity_score,
            "ownership_score": score.ownership_score,
            "macro_score": score.macro_score,
            "population_basis": score.population_basis,
        })
    return items, total


def delete_mna_score(session: Session, corp_code: str, as_of: str) -> None:
    """근거(입력 데이터)를 잃은 (corp_code, as_of)의 오래된 score 정리(2.1 reconciliation
    패턴). 없으면 no-op(멱등)."""
    stmt = select(MnaScore).where(
        MnaScore.corp_code == corp_code, MnaScore.as_of == as_of,
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is not None:
        session.delete(obj)

```

### `app/routers/screening.py`

```python
"""/screening 라우터 — 다중조건 스크리닝 (HTTP 경계, AD-2)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import Page, ScreeningOut
from app.services import screening as service

router = APIRouter(prefix="/screening", tags=["screening"])


@router.get(
    "",
    response_model=Page[ScreeningOut],
    description=(
        "워싱·저평가·M&A 후보 양방향 스크리닝(valueup_score + mna_score outer join). "
        "washing_flag: null=판단 불가(빈칸/아니오 표시 금지). "
        "mna_target_score: null=산출 불가(0점/최하위 표시 금지). "
        "buyback_executed 필터: true/false 모두 null(판단 불가)은 미포함. "
        "sort: `field`/`-field` 규약, 허용=execution_score·mna_target_score(기본=corp_code). "
        "범위 필터는 null을 매칭하지 않는다(산출 불가는 조건 판단 불가). "
        "알려진 한계: roe/pbr 등 지표는 look-ahead 부분 차단(같은 해 사업보고서만 배제) — "
        "명시적 과거 as_of 조회 시 그 해의 이후 분기 지표가 섞일 수 있음(공시일 수집 전까지, "
        "전 엔드포인트 공통). 시총 필터는 최신가 기준(point-in-time 아님)."
    ),
)
def screening_list(
    # 3.4 상세화면 단건 조회용(정확일치, 8자리)
    corp_code: str | None = Query(None, min_length=8, max_length=8),
    market: str | None = Query(None, min_length=1),
    sector: str | None = Query(
        None, min_length=1, pattern=r"^\d{2,5}$",
        description="KSIC 업종코드 prefix(예: 26, 64)",
    ),
    min_execution_score: float | None = Query(None, allow_inf_nan=False),
    max_execution_score: float | None = Query(None, allow_inf_nan=False),
    min_mna_score: float | None = Query(None, allow_inf_nan=False),
    max_mna_score: float | None = Query(None, allow_inf_nan=False),
    # 지표 범위 필터(3.3 리뷰 반영, AC2) — null 지표는 어느 범위에도 매칭 안 됨
    min_roe: float | None = Query(None, allow_inf_nan=False),
    max_pbr: float | None = Query(None, allow_inf_nan=False),
    max_ev_ebitda: float | None = Query(None, allow_inf_nan=False),
    max_debt_ratio: float | None = Query(None, allow_inf_nan=False),
    # 시총구간 필터(KRW 원) — prices 최신 시총 기준(AD-9)
    min_market_cap: int | None = Query(None, ge=0),
    max_market_cap: int | None = Query(None, ge=0),
    washing_only: bool = Query(False),
    buyback_executed: bool | None = Query(
        None, description="true=매입 실행 / false=미실행 — null(판단 불가)은 양쪽 다 제외"
    ),
    sort: str | None = Query(None, description="execution_score | mna_target_score, `-` 내림차순"),
    as_of: date | None = Query(None, description="기준일(YYYY-MM-DD), 기본=최신 실행 시점"),
    page: int = Query(1, ge=1, le=1_000_000),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[ScreeningOut] | JSONResponse:
    filters = {
        "corp_code": corp_code, "market": market, "sector": sector,
        "min_execution_score": min_execution_score,
        "max_execution_score": max_execution_score,
        "min_mna_score": min_mna_score, "max_mna_score": max_mna_score,
        "min_roe": min_roe, "max_pbr": max_pbr,
        "max_ev_ebitda": max_ev_ebitda, "max_debt_ratio": max_debt_ratio,
        "min_market_cap": min_market_cap, "max_market_cap": max_market_cap,
        "washing_only": washing_only, "buyback_executed": buyback_executed,
        "as_of": as_of.isoformat() if as_of else None,
    }
    try:
        return service.screening(db, filters, page, size, sort)
    except service.InvalidSortError as e:
        # 전용 예외만 400 — 광범위 ValueError를 잡으면 pydantic ValidationError(내부
        # 오류)까지 INVALID_SORT로 세탁돼 장애가 숨는다(GPT 리뷰 Med). 그 외는 500으로.
        return JSONResponse(
            status_code=400, content={"detail": str(e), "code": "INVALID_SORT"}
        )

```

### `app/routers/valueup.py`

```python
"""/valueup 라우터 — 갭분석·워싱랭킹 (HTTP 경계, AD-2)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import GapAnalysisOut, Page
from app.services import valueup as service

router = APIRouter(prefix="/valueup", tags=["valueup"])


@router.get(
    "/gap-analysis",
    response_model=Page[GapAnalysisOut],
    description=(
        "밸류업 계획 대비 이행 갭 분석. execution_score 오름차순(이행 나쁜 순), null last. "
        "washing_flag: true=워싱 의심 / false=근거 없음 / null=판단 불가(데이터 부족) — "
        "UI에서 null을 빈칸이나 '아니오'로 표시하지 말고 '판단 불가'로 표시할 것."
    ),
)
def gap_analysis(
    # 3.4 상세화면 단건 조회용(정확일치, 8자리)
    corp_code: str | None = Query(None, min_length=8, max_length=8),
    # min_length=1·page 상한: 2-5 리뷰 패리티 정비(빈 필터 확대·OFFSET 오버플로 방지)
    market: str | None = Query(None, min_length=1),
    min_progress: float | None = Query(None, ge=0.0, le=1.0),
    # date 타입 = FastAPI가 달력 검증(2026-02-30/garbage → 422, 일괄리뷰 Med — 빈 200으로
    # "데이터 없음"과 "잘못된 요청"이 섞이지 않게)
    as_of: date | None = Query(None, description="기준일(YYYY-MM-DD), 기본=최신"),
    page: int = Query(1, ge=1, le=1_000_000),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[GapAnalysisOut]:
    filters = {"corp_code": corp_code, "market": market, "min_progress": min_progress,
               "as_of": as_of.isoformat() if as_of else None}
    return service.gap_analysis(db, filters, page, size)


@router.get(
    "/washing-ranking",
    response_model=Page[GapAnalysisOut],
    description=(
        "워싱 의심(washing_flag=true) 종목만, execution_score 오름차순. "
        "판단 불가(null)·근거 없음(false)은 제외 — 전체는 /valueup/gap-analysis 사용."
    ),
)
def washing_ranking(
    # min_length=1·page 상한: 2-5 리뷰 패리티 정비(빈 필터 확대·OFFSET 오버플로 방지)
    market: str | None = Query(None, min_length=1),
    min_progress: float | None = Query(None, ge=0.0, le=1.0),
    # date 타입 = FastAPI가 달력 검증(2026-02-30/garbage → 422, 일괄리뷰 Med — 빈 200으로
    # "데이터 없음"과 "잘못된 요청"이 섞이지 않게)
    as_of: date | None = Query(None, description="기준일(YYYY-MM-DD), 기본=최신"),
    page: int = Query(1, ge=1, le=1_000_000),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[GapAnalysisOut]:
    filters = {"market": market, "min_progress": min_progress,
               "as_of": as_of.isoformat() if as_of else None}
    return service.washing_ranking(db, filters, page, size)

```

### `app/routers/mna.py`

```python
"""/mna 라우터 — M&A 타겟 랭킹 (HTTP 경계, AD-2)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import MnaRankingOut, Page
from app.services import mna as service

router = APIRouter(prefix="/mna", tags=["mna"])


@router.get(
    "/ranking",
    response_model=Page[MnaRankingOut],
    description=(
        "M&A 타겟 점수 랭킹. mna_target_score 내림차순(인수 매력 높은 순), null last. "
        "mna_target_score: null=산출 불가(요소 하나라도 입력 데이터 부족 — 엄격 null 정책) — "
        "UI에서 null을 0점이나 최하위로 표시하지 말고 '산출 불가'로 표시할 것. "
        "population_basis: 백분위 모집단(sector:{KSIC2}=업종 peer / market_fallback=peer 미달 "
        "폴백 / market=업종 정보 없음). sector 필터는 KSIC 코드 prefix 매칭(예: 64=금융지주 계열)."
    ),
)
def mna_ranking(
    # 3.4 상세화면 단건 조회용(정확일치, 8자리)
    corp_code: str | None = Query(None, min_length=8, max_length=8),
    # min_length=1: 빈 문자열(?market=)이 "필터 없음"으로 조용히 확대되지 않게 422
    # (2-5 GPT 리뷰 Med — 정확일치/prefix 계약상 빈 값은 무효 입력)
    market: str | None = Query(None, min_length=1),
    sector: str | None = Query(
        None, min_length=1, pattern=r"^\d{2,5}$",
        description="KSIC 업종코드 prefix(예: 26, 64)",
    ),
    # date 타입 = FastAPI가 달력 검증(2026-02-30/garbage → 422, 2.4 일괄리뷰 교훈)
    as_of: date | None = Query(None, description="기준일(YYYY-MM-DD), 기본=최신"),
    # page 상한: 무제한 int가 OFFSET 64비트 초과 → 500이 되는 것을 422로 차단(GPT 리뷰 Med)
    page: int = Query(1, ge=1, le=1_000_000),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[MnaRankingOut]:
    filters = {"corp_code": corp_code, "market": market, "sector": sector,
               "as_of": as_of.isoformat() if as_of else None}
    return service.ranking(db, filters, page, size)

```

### `tests/test_screening_api.py`

```python
"""Story 2.6 — 다중조건 스크리닝 API 검증 (SQLite in-memory + TestClient)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Company, MnaScore, ValueupScore
from app.sql_views import CREATE_VALUATION_METRICS

AS_OF = "2026-07-13"


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:", future=True,
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    with eng.connect() as conn:  # roe/pbr·지표 필터가 뷰를 읽음(3.3 리뷰 반영)
        conn.execute(text(CREATE_VALUATION_METRICS))
        conn.commit()
    return eng


def _seed(s: Session) -> None:
    for code, name, market, sector in (
        ("00000001", "워싱저평가", "KOSPI", "26100"),  # 워싱 의심 + M&A 매력
        ("00000002", "이행양호", "KOSPI", "26200"),    # 실행점수 높음, M&A 매력 낮음
        ("00000003", "밸류업만", "KOSDAQ", "47000"),   # valueup_score만 있음
        ("00000004", "엠앤에이만", "KOSPI", "64110"),  # mna_score만 있음
        ("00000005", "스코어없음", "KOSPI", "10000"),  # 두 스코어 다 없음 → 제외
    ):
        s.add(Company(corp_code=code, corp_name=name, market=market, sector=sector))
    s.add(ValueupScore(
        corp_code="00000001", as_of=AS_OF,
        execution_score=20.0, washing_flag=True,
        buyback_executed=True, buyback_status="purchased_only",
    ))
    s.add(MnaScore(
        corp_code="00000001", as_of=AS_OF,
        mna_target_score=80.0, population_basis="sector:26",
    ))
    s.add(ValueupScore(
        corp_code="00000002", as_of=AS_OF,
        execution_score=95.0, washing_flag=False,
        buyback_executed=False, buyback_status="planned",
    ))
    s.add(MnaScore(
        corp_code="00000002", as_of=AS_OF,
        mna_target_score=30.0, population_basis="sector:26",
    ))
    s.add(ValueupScore(  # buyback_executed=null(판단 불가)
        corp_code="00000003", as_of=AS_OF,
        execution_score=50.0, washing_flag=None,
        buyback_executed=None, buyback_status="unknown",
    ))
    s.add(MnaScore(
        corp_code="00000004", as_of=AS_OF,
        mna_target_score=60.0, population_basis="market_fallback",
    ))
    s.commit()
    # 지표·시총(3.3 리뷰 반영): 00000001=고ROE(20%)·저PBR·저부채(50%), 00000002=저ROE(5%)·
    # 고PBR·고부채(200%). 00000003/4는 지표 없음(roe/pbr null — 범위 필터 불통과 검증용).
    # ev_ebitda = (market_cap + total_debt - cash) / operating_income:
    #   corp1 = (1000+500-100)/220 = 6.36 / corp2 = (5000+2000-100)/60 = 115.0
    s.execute(text(
        "INSERT INTO financials (corp_code, year, quarter, revenue, net_income, equity, "
        "total_assets, total_liabilities, operating_income, total_debt, cash) VALUES "
        "('00000001', 2025, 3, 1000, 200, 1000, 3000, 500, 220, 500, 100), "
        "('00000002', 2025, 3, 1000, 50, 1000, 3000, 2000, 60, 2000, 100)"
    ))
    s.execute(text(
        "INSERT INTO prices (corp_code, date, close, volume, trading_value, market_cap) VALUES "
        "('00000001', '2026-07-01', 1000, 100, 100000, 1000), "   # PBR=1.0, 시총 1000
        "('00000002', '2026-07-01', 1000, 100, 100000, 5000)"     # PBR=5.0, 시총 5000
    ))
    s.commit()


@pytest.fixture()
def client(engine, monkeypatch):
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    return TestClient(fastapi_app)


def test_outer_join_and_universe(client) -> None:
    """AC1: outer join 정직 노출 — 한쪽만 있으면 그쪽만, 둘 다 없으면 제외."""
    r = client.get("/screening")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "total", "page", "size"}
    assert body["total"] == 4  # 00000005(스코어 없음) 제외
    by_code = {i["corp_code"]: i for i in body["items"]}
    assert "00000005" not in by_code
    # valueup만 있는 종목: mna 필드 null + has_* 플래그로 미실행 식별
    assert by_code["00000003"]["execution_score"] == 50.0
    assert by_code["00000003"]["mna_target_score"] is None
    assert by_code["00000003"]["has_valueup_score"] is True
    assert by_code["00000003"]["has_mna_score"] is False
    # mna만 있는 종목: valueup 필드 null
    assert by_code["00000004"]["mna_target_score"] == 60.0
    assert by_code["00000004"]["execution_score"] is None
    assert by_code["00000004"]["washing_flag"] is None
    assert by_code["00000004"]["has_valueup_score"] is False
    assert by_code["00000004"]["has_mna_score"] is True


def test_range_filters_and_combination(client) -> None:
    """AC2: 범위 필터 AND 조합 + null은 범위에 매칭되지 않음."""
    # 실행점수 낮고(워싱 방향) M&A 매력 높은 종목
    r = client.get("/screening", params={
        "max_execution_score": 40, "min_mna_score": 70,
    })
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000001"]
    # min_mna_score=0: mna null(00000003)은 매칭 안 됨
    r2 = client.get("/screening", params={"min_mna_score": 0})
    codes = {i["corp_code"] for i in r2.json()["items"]}
    assert codes == {"00000001", "00000002", "00000004"}


def test_washing_only_and_buyback_filters(client) -> None:
    """AC2: washing_only + buyback_executed(true/false 모두 null 미포함)."""
    r = client.get("/screening", params={"washing_only": True})
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000001"]
    r_true = client.get("/screening", params={"buyback_executed": True})
    assert [i["corp_code"] for i in r_true.json()["items"]] == ["00000001"]
    r_false = client.get("/screening", params={"buyback_executed": False})
    # null(00000003)은 false에도 포함되지 않는다(판단 불가 세탁 금지)
    assert [i["corp_code"] for i in r_false.json()["items"]] == ["00000002"]


def test_sort_whitelist_and_null_last(client) -> None:
    """AC3: field/-field 규약 + null last + 화이트리스트 밖 400 {detail,code}."""
    r = client.get("/screening", params={"sort": "-mna_target_score"})
    codes = [i["corp_code"] for i in r.json()["items"]]
    # 80 → 60 → 30 → null(00000003) last
    assert codes == ["00000001", "00000004", "00000002", "00000003"]
    r2 = client.get("/screening", params={"sort": "execution_score"})
    codes2 = [i["corp_code"] for i in r2.json()["items"]]
    # 20 → 50 → 95 → null(00000004) last
    assert codes2 == ["00000001", "00000003", "00000002", "00000004"]
    r3 = client.get("/screening", params={"sort": "corp_name; DROP TABLE"})
    assert r3.status_code == 400
    assert set(r3.json()) == {"detail", "code"}
    assert r3.json()["code"] == "INVALID_SORT"


def test_corp_code_filter(client) -> None:
    """[3.4] 상세화면 단건 조회 — corp_code 정확일치 필터."""
    r = client.get("/screening", params={"corp_code": "00000001"})
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["corp_code"] == "00000001"
    r2 = client.get("/screening", params={"corp_code": "00000099"})
    assert r2.json()["total"] == 0  # 존재하지 않는 종목 → 빈 결과(404 아님)


def test_market_sector_blank_rejected_and_pagination(client) -> None:
    """AC2/4: market/sector 필터 + 빈 문자열 422 + 페이지네이션."""
    r = client.get("/screening", params={"market": "KOSDAQ"})
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000003"]
    r2 = client.get("/screening", params={"sector": "26"})
    assert {i["corp_code"] for i in r2.json()["items"]} == {"00000001", "00000002"}
    assert client.get("/screening?market=").status_code == 422
    assert client.get("/screening?sector=").status_code == 422
    r3 = client.get("/screening", params={"page": 2, "size": 3})
    assert r3.json()["total"] == 4 and len(r3.json()["items"]) == 1


def test_roe_pbr_in_response(client) -> None:
    """[3.3 리뷰 High] AC3 핵심지표 — roe·pbr이 응답에 포함되고 지표 없는 종목은 null."""
    r = client.get("/screening")
    by_code = {i["corp_code"]: i for i in r.json()["items"]}
    assert by_code["00000001"]["roe"] == pytest.approx(20.0)
    assert by_code["00000001"]["pbr"] == pytest.approx(1.0)
    assert by_code["00000002"]["roe"] == pytest.approx(5.0)
    assert by_code["00000003"]["roe"] is None  # 지표 없음 → null(0 아님)
    assert by_code["00000003"]["pbr"] is None


def test_metric_range_filters(client) -> None:
    """[3.3 리뷰 BLOCKER] AC2 지표 범위 필터 — null 지표는 어느 범위에도 매칭 안 됨."""
    # min_roe=10: 00000001(20%)만. 00000003/4(지표 null)는 제외
    r = client.get("/screening", params={"min_roe": 10})
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000001"]
    # max_pbr=2: 00000001(1.0)만
    r2 = client.get("/screening", params={"max_pbr": 2})
    assert [i["corp_code"] for i in r2.json()["items"]] == ["00000001"]
    # AND 조합: min_roe=10 & max_pbr=0.5 → 0건
    r3 = client.get("/screening", params={"min_roe": 10, "max_pbr": 0.5})
    assert r3.json()["total"] == 0
    # 스코어 필터와의 조합도 동작
    r4 = client.get("/screening", params={"min_roe": 1, "max_execution_score": 50})
    assert [i["corp_code"] for i in r4.json()["items"]] == ["00000001"]


def test_ev_ebitda_and_debt_ratio_filters(client) -> None:
    """[재리뷰 #7] 남은 지표 필터 2종 — max_ev_ebitda·max_debt_ratio."""
    # corp1 ev_ebitda=6.36 / corp2=115.0
    r = client.get("/screening", params={"max_ev_ebitda": 10})
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000001"]
    # corp1 debt_ratio=50% / corp2=200%
    r2 = client.get("/screening", params={"max_debt_ratio": 100})
    assert [i["corp_code"] for i in r2.json()["items"]] == ["00000001"]
    # 지표 없는 종목(00000003/4)은 불통과 확인(총 1건)
    assert r2.json()["total"] == 1


def test_filtered_count_and_pagination(client) -> None:
    """[재리뷰 #7] 지표 필터 적용 상태의 total·페이지네이션 정합(2단계 IN 방식 검증)."""
    r = client.get("/screening", params={"min_roe": 1, "page": 2, "size": 1})
    body = r.json()
    assert body["total"] == 2  # roe 있는 corp1(20%)·corp2(5%)
    assert len(body["items"]) == 1  # 2페이지 1건
    # 1·2페이지 합집합 = 두 종목 전부(중복·누락 없음)
    r1 = client.get("/screening", params={"min_roe": 1, "page": 1, "size": 1})
    codes = {r1.json()["items"][0]["corp_code"], body["items"][0]["corp_code"]}
    assert codes == {"00000001", "00000002"}


def test_metric_and_market_cap_combined(client) -> None:
    """[재리뷰 #7] 지표 필터 × 시총 필터 동시 적용(두 IN 조건 AND)."""
    # min_roe=1(corp1·2 통과) & max_market_cap=2000(corp1만) → corp1
    r = client.get("/screening", params={"min_roe": 1, "max_market_cap": 2000})
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000001"]
    # min_roe=10(corp1만) & min_market_cap=2000(corp2만) → 0건(교집합 공집합)
    r2 = client.get("/screening", params={"min_roe": 10, "min_market_cap": 2000})
    assert r2.json()["total"] == 0


def test_market_cap_boundary_inclusive(client) -> None:
    """[재리뷰 #2] 백엔드 비교는 포함(>=,<=) — 경계 배타는 프론트 버킷(-1)이 담당.

    시총 정확히 1000(corp1): min=1000 포함, max=1000 포함, max=999 불포함.
    """
    assert "00000001" in {i["corp_code"] for i in client.get(
        "/screening", params={"min_market_cap": 1000}).json()["items"]}
    assert "00000001" in {i["corp_code"] for i in client.get(
        "/screening", params={"max_market_cap": 1000}).json()["items"]}
    assert "00000001" not in {i["corp_code"] for i in client.get(
        "/screening", params={"max_market_cap": 999}).json()["items"]}


def test_market_cap_filter(client) -> None:
    """[3.3 리뷰 BLOCKER] AC2 시총구간 — prices 최신 시총 기준, 시총 없는 종목 불통과."""
    r = client.get("/screening", params={"min_market_cap": 2000})
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000002"]
    r2 = client.get("/screening", params={"max_market_cap": 2000})
    assert [i["corp_code"] for i in r2.json()["items"]] == ["00000001"]
    # 시총 데이터 없는 00000003/4는 어느 구간에도 안 걸림
    r3 = client.get("/screening", params={"min_market_cap": 0})
    assert {i["corp_code"] for i in r3.json()["items"]} == {"00000001", "00000002"}


def test_empty_scores_returns_empty_envelope(engine, monkeypatch) -> None:
    """AC4: 두 스코어 모두 미적재 → 빈 봉투(500 아님)."""
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    r = TestClient(fastapi_app).get("/screening")
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0, "page": 1, "size": 20}


def test_invalid_sort_rejected_when_scores_empty(engine, monkeypatch) -> None:
    """[GPT 리뷰 Med] 스코어 미적재여도 잘못된 sort는 400 — 데이터 유무로 계약이 갈리면 안 됨."""
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    r = TestClient(fastapi_app).get("/screening", params={"sort": "drop_table"})
    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_SORT"


def test_blank_sort_rejected(client) -> None:
    """[GPT 리뷰 Low] 빈 sort는 기본 정렬로 조용히 대체되지 않고 400(생략과 빈 입력 구분)."""
    r = client.get("/screening?sort=")
    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_SORT"
    # `-` 단독도 필드 없음 → 400
    assert client.get("/screening", params={"sort": "-"}).status_code == 400


def test_internal_validation_error_not_mislabeled_as_sort(engine, monkeypatch) -> None:
    """[GPT 리뷰 Med] 내부 데이터 오류(pydantic ValidationError)는 400 INVALID_SORT로
    세탁되지 않고 500으로 드러난다."""
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app
    from app.repositories import screening as repo

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    # repo가 오염된 행(corp_code=None)을 반환하는 상황을 강제
    monkeypatch.setattr(
        repo, "list_screening",
        lambda *a, **k: ([{"corp_code": None, "as_of": AS_OF}], 1),
    )
    client = TestClient(fastapi_app, raise_server_exceptions=False)
    r = client.get("/screening")
    assert r.status_code == 500  # 400 INVALID_SORT 아님


def test_latest_as_of_across_both_tables(engine, monkeypatch) -> None:
    """[GPT 리뷰 Low] 기본 as_of가 두 테이블 latest 중 max로 선택되는지 교차 검증."""
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        s.add(Company(corp_code="00000001", corp_name="옛밸류업", market="KOSPI"))
        s.add(Company(corp_code="00000002", corp_name="새엠앤에이", market="KOSPI"))
        s.add(ValueupScore(corp_code="00000001", as_of="2026-07-12", execution_score=10.0))
        s.add(MnaScore(corp_code="00000002", as_of="2026-07-13", mna_target_score=50.0))
        s.commit()
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    body = TestClient(fastapi_app).get("/screening").json()
    # max("2026-07-12","2026-07-13")="2026-07-13" — mna 쪽만 조인됨
    assert body["total"] == 1
    item = body["items"][0]
    assert item["corp_code"] == "00000002"
    assert item["as_of"] == "2026-07-13"
    assert item["execution_score"] is None and item["has_valueup_score"] is False


def test_parity_blank_filters_valueup_metrics(client) -> None:
    """AC6[편승]: valueup·metrics 라우터도 빈 필터 422 + 거대 page 422."""
    assert client.get("/valueup/gap-analysis?market=").status_code == 422
    assert client.get("/metrics?market=").status_code == 422
    assert client.get("/metrics?sector=").status_code == 422
    huge = "100000000000000000000"
    assert client.get("/valueup/gap-analysis", params={"page": huge}).status_code == 422
    assert client.get("/metrics", params={"page": huge}).status_code == 422

```

### `tests/test_valueup_api.py`

```python
"""Story 2.4 — 갭분석/워싱랭킹 API 검증 (SQLite in-memory + TestClient)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Company, ValueupScore


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:", future=True,
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    return eng


def _seed(s: Session) -> None:
    for code, name, market in (
        ("00000001", "워싱의심", "KOSPI"),
        ("00000002", "이행양호", "KOSPI"),
        ("00000003", "판단불가", "KOSDAQ"),
        ("00000004", "점수없음", "KOSPI"),
    ):
        s.add(Company(corp_code=code, corp_name=name, market=market))
    s.add(ValueupScore(
        corp_code="00000001", as_of="2026-07-13",
        target_roe=10.0, actual_roe=3.0, roe_gap=-7.0,
        achievement_rate=0.3, progress_rate=0.8, execution_score=25.0,
        washing_flag=True, buyback_status="purchased_only",
    ))
    s.add(ValueupScore(
        corp_code="00000002", as_of="2026-07-13",
        target_roe=10.0, actual_roe=11.0, roe_gap=1.0,
        achievement_rate=1.1, progress_rate=0.8, execution_score=95.0,
        washing_flag=False, buyback_status="retired",
    ))
    s.add(ValueupScore(
        corp_code="00000003", as_of="2026-07-13",
        achievement_rate=None, progress_rate=0.2, execution_score=None,
        washing_flag=None, buyback_status="unknown",
    ))
    s.add(ValueupScore(  # 다른 as_of(과거) — 최신 기본 조회에서 제외돼야
        corp_code="00000004", as_of="2025-12-31",
        execution_score=10.0, washing_flag=False,
    ))
    s.commit()


@pytest.fixture()
def client(engine, monkeypatch):
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    return TestClient(fastapi_app)


def test_gap_analysis_envelope_and_order(client) -> None:
    """AC1/3: 봉투 + execution_score 오름차순(null last) + 기본 as_of=최신."""
    r = client.get("/valueup/gap-analysis")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "total", "page", "size"}
    assert body["total"] == 3  # 최신 as_of(2026-07-13)만, 과거 행 제외
    codes = [i["corp_code"] for i in body["items"]]
    # 25.0 → 95.0 → null(판단불가 마지막)
    assert codes == ["00000001", "00000002", "00000003"]
    # 목표·실제·갭 동결값 노출
    assert body["items"][0]["roe_gap"] == -7.0
    # washing null은 null 그대로(false 강제 금지)
    assert body["items"][2]["washing_flag"] is None


def test_washing_ranking_only_true(client) -> None:
    """AC2: washing_flag=true만 — 판단불가(null)·근거없음(false) 제외."""
    r = client.get("/valueup/washing-ranking")
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["corp_code"] == "00000001"
    assert body["items"][0]["washing_flag"] is True


def test_filters_market_and_min_progress(client) -> None:
    """AC3: market·min_progress 필터."""
    r = client.get("/valueup/gap-analysis", params={"market": "KOSDAQ"})
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000003"]
    r2 = client.get("/valueup/gap-analysis", params={"min_progress": 0.5})
    assert {i["corp_code"] for i in r2.json()["items"]} == {"00000001", "00000002"}


def test_corp_code_filter(client) -> None:
    """[3.4] 상세화면 단건 조회 — corp_code 정확일치 필터."""
    r = client.get("/valueup/gap-analysis", params={"corp_code": "00000001"})
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["corp_code"] == "00000001"
    assert body["items"][0]["roe_gap"] == -7.0
    r2 = client.get("/valueup/gap-analysis", params={"corp_code": "00000099"})
    assert r2.json()["total"] == 0  # 존재하지 않는 종목 → 빈 결과(404 아님)


def test_explicit_as_of(client) -> None:
    """AC3: as_of 명시 조회(과거 스냅샷)."""
    r = client.get("/valueup/gap-analysis", params={"as_of": "2025-12-31"})
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000004"]


def test_empty_scores_returns_empty_envelope(engine, monkeypatch) -> None:
    """스코어 미적재 → 빈 봉투(500 아님)."""
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    r = TestClient(fastapi_app).get("/valueup/gap-analysis")
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0, "page": 1, "size": 20}


def test_invalid_as_of_is_422_not_empty_200(client) -> None:
    """[일괄리뷰 Med] 달력상 무효/쓰레기 as_of는 422 — 빈 200으로 세탁 금지."""
    assert client.get("/valueup/gap-analysis", params={"as_of": "2026-02-30"}).status_code == 422
    assert client.get("/valueup/gap-analysis", params={"as_of": "garbage"}).status_code == 422

```

### `tests/test_mna_api.py`

```python
"""Story 2.5 — M&A 타겟 랭킹 API 검증 (SQLite in-memory + TestClient)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Company, MnaScore


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:", future=True,
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    return eng


def _seed(s: Session) -> None:
    for code, name, market, sector in (
        ("00000001", "저평가매력", "KOSPI", "26100"),   # 반도체
        ("00000002", "보통", "KOSPI", "26200"),
        ("00000003", "산출불가금융", "KOSPI", "64110"),  # 금융(엄격 null)
        ("00000004", "코스닥유통", "KOSDAQ", "47000"),
        ("00000005", "과거스냅샷", "KOSPI", None),
    ):
        s.add(Company(corp_code=code, corp_name=name, market=market, sector=sector))
    s.add(MnaScore(
        corp_code="00000001", as_of="2026-07-13",
        mna_target_score=82.5, valuation_score=0.9, capacity_score=0.8,
        ownership_score=0.7, macro_score=0.6, population_basis="sector:26",
    ))
    s.add(MnaScore(
        corp_code="00000002", as_of="2026-07-13",
        mna_target_score=41.0, valuation_score=0.4, capacity_score=0.4,
        ownership_score=0.5, macro_score=0.6, population_basis="sector:26",
    ))
    s.add(MnaScore(  # 엄격 null(요소 산출 불가 → 총점 null)
        corp_code="00000003", as_of="2026-07-13",
        mna_target_score=None, valuation_score=None, capacity_score=None,
        ownership_score=0.9, macro_score=0.6, population_basis=None,
    ))
    s.add(MnaScore(
        corp_code="00000004", as_of="2026-07-13",
        mna_target_score=60.0, valuation_score=0.6, capacity_score=0.6,
        ownership_score=0.6, macro_score=0.6, population_basis="market_fallback",
    ))
    s.add(MnaScore(  # 다른 as_of(과거) — 최신 기본 조회에서 제외돼야
        corp_code="00000005", as_of="2025-12-31",
        mna_target_score=99.0, valuation_score=1.0, capacity_score=1.0,
        ownership_score=1.0, macro_score=1.0, population_basis="market",
    ))
    s.commit()


@pytest.fixture()
def client(engine, monkeypatch):
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    return TestClient(fastapi_app)


def test_ranking_envelope_desc_null_last(client) -> None:
    """AC1/2: 봉투 + mna_target_score 내림차순(null last) + 기본 as_of=최신 + 요소별 분해."""
    r = client.get("/mna/ranking")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "total", "page", "size"}
    assert body["total"] == 4  # 최신 as_of만, 과거(00000005) 제외
    codes = [i["corp_code"] for i in body["items"]]
    # 82.5 → 60.0 → 41.0 → null(산출 불가 마지막)
    assert codes == ["00000001", "00000004", "00000002", "00000003"]
    top = body["items"][0]
    # 요소별 분해 + population_basis 노출
    assert top["valuation_score"] == 0.9
    assert top["capacity_score"] == 0.8
    assert top["ownership_score"] == 0.7
    assert top["macro_score"] == 0.6
    assert top["population_basis"] == "sector:26"


def test_null_score_returned_as_null(client) -> None:
    """AC3: 엄격 null — 총점 null은 null 그대로(0점 강제 금지), 산출된 요소는 노출."""
    r = client.get("/mna/ranking")
    last = r.json()["items"][-1]
    assert last["corp_code"] == "00000003"
    assert last["mna_target_score"] is None
    assert last["ownership_score"] == 0.9  # 산출된 요소는 그대로


def test_filters_market_and_sector_prefix(client) -> None:
    """AC2: market 필터 + sector는 KSIC prefix 매칭."""
    r = client.get("/mna/ranking", params={"market": "KOSDAQ"})
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000004"]
    r2 = client.get("/mna/ranking", params={"sector": "26"})  # 26100·26200 모두
    assert [i["corp_code"] for i in r2.json()["items"]] == ["00000001", "00000002"]
    r3 = client.get("/mna/ranking", params={"sector": "26100"})  # 세분류 정확 매칭도 동작
    assert [i["corp_code"] for i in r3.json()["items"]] == ["00000001"]


def test_corp_code_filter(client) -> None:
    """[3.4] 상세화면 단건 조회 — corp_code 정확일치 필터."""
    r = client.get("/mna/ranking", params={"corp_code": "00000001"})
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["corp_code"] == "00000001"
    assert body["items"][0]["mna_target_score"] == 82.5
    r2 = client.get("/mna/ranking", params={"corp_code": "00000099"})
    assert r2.json()["total"] == 0  # 존재하지 않는 종목 → 빈 결과(404 아님)


def test_explicit_as_of_and_pagination(client) -> None:
    """AC2/5: as_of 스냅샷 + 페이지네이션 + 무효 날짜 422."""
    r = client.get("/mna/ranking", params={"as_of": "2025-12-31"})
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000005"]
    r2 = client.get("/mna/ranking", params={"page": 2, "size": 2})
    body = r2.json()
    assert body["total"] == 4 and body["page"] == 2
    assert [i["corp_code"] for i in body["items"]] == ["00000002", "00000003"]
    assert client.get("/mna/ranking", params={"as_of": "2026-02-30"}).status_code == 422
    assert client.get("/mna/ranking", params={"as_of": "garbage"}).status_code == 422


def test_blank_filters_are_rejected(client) -> None:
    """[GPT 리뷰 Med] 빈 문자열 필터는 '필터 없음'으로 확대되지 않고 422."""
    assert client.get("/mna/ranking?market=").status_code == 422
    assert client.get("/mna/ranking?sector=").status_code == 422
    # 빈 sector가 있어도 다른 유효 필터와 함께면 여전히 422(부분 적용 금지)
    assert client.get("/mna/ranking?market=KOSPI&sector=").status_code == 422
    # sector는 숫자 KSIC 코드만(2~5자리)
    assert client.get("/mna/ranking", params={"sector": "abc"}).status_code == 422


def test_validation_error_contract(client) -> None:
    """[GPT 리뷰 Med] 422 본문이 AD-6 에러 계약 {detail, code}를 따른다."""
    r = client.get("/mna/ranking", params={"as_of": "2026-02-30"})
    assert r.status_code == 422
    body = r.json()
    assert set(body) == {"detail", "code"}
    assert body["code"] == "VALIDATION_ERROR"


def test_huge_page_is_rejected(client) -> None:
    """[GPT 리뷰 Med] OFFSET 오버플로(500)로 새지 않도록 page 상한 초과는 422."""
    r = client.get("/mna/ranking", params={"page": "100000000000000000000"})
    assert r.status_code == 422


def test_empty_scores_returns_empty_envelope(engine, monkeypatch) -> None:
    """AC5: 스코어 미적재 → 빈 봉투(500 아님)."""
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    r = TestClient(fastapi_app).get("/mna/ranking")
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0, "page": 1, "size": 20}

```

### `dashboard/src/api/detail.ts`

```ts
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "./client";
import type { Page } from "./screening";

// 2.4 GapAnalysisOut 스키마와 1:1.
export interface GapDetail {
  corp_code: string;
  corp_name: string | null;
  market: string | null;
  as_of: string;
  target_roe: number | null;
  actual_roe: number | null;
  roe_gap: number | null;
  achievement_rate: number | null;
  progress_rate: number | null;
  execution_score: number | null;
  washing_flag: boolean | null;
  buyback_status: string | null;
}

// 3.4: /valueup/gap-analysis를 corp_code 필터+size=1로 재사용(신규 엔드포인트 회피).
export function useGapDetail(corpCode: string | undefined) {
  return useQuery({
    queryKey: ["gap-detail", corpCode],
    queryFn: () => apiGet<Page<GapDetail>>("/valueup/gap-analysis", { corp_code: corpCode, size: 1 }),
    enabled: !!corpCode,
    select: (page) => page.items[0] ?? null,
  });
}

// 2.5 MnaRankingOut 스키마와 1:1.
export interface MnaDetail {
  corp_code: string;
  corp_name: string | null;
  market: string | null;
  sector: string | null;
  as_of: string;
  mna_target_score: number | null;
  valuation_score: number | null;
  capacity_score: number | null;
  ownership_score: number | null;
  macro_score: number | null;
  population_basis: string | null;
}

// 3.4: /mna/ranking을 corp_code 필터+size=1로 재사용.
export function useMnaDetail(corpCode: string | undefined) {
  return useQuery({
    queryKey: ["mna-detail", corpCode],
    queryFn: () => apiGet<Page<MnaDetail>>("/mna/ranking", { corp_code: corpCode, size: 1 }),
    enabled: !!corpCode,
    select: (page) => page.items[0] ?? null,
  });
}

// 1.7 MetricOut 스키마와 1:1(분기별 시계열, 이미 존재하는 단건조회 경로 — 변경 없음).
export interface MetricPoint {
  corp_code: string;
  corp_name: string | null;
  market: string | null;
  sector: string | null;
  year: number;
  quarter: number;
  roe: number | null;
  roa: number | null;
  pbr: number | null;
  per: number | null;
  ev_ebitda: number | null;
  debt_ratio: number | null;
  payout_ratio: number | null;
  net_cash: number | null;
  ebitda_margin: number | null;
  yoy_revenue_growth: number | null;
  yoy_income_growth: number | null;
}

export function useMetricsByCorp(corpCode: string | undefined) {
  return useQuery({
    queryKey: ["metrics-by-corp", corpCode],
    queryFn: () => apiGet<MetricPoint[]>(`/metrics/${corpCode}`),
    enabled: !!corpCode,
  });
}

```

### `dashboard/src/api/screening.ts`

```ts
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { apiGet } from "./client";

// 2.6 ScreeningOut 스키마와 1:1. null 계약이 타입에 그대로 드러난다.
export interface ScreeningRow {
  corp_code: string;
  corp_name: string | null;
  market: string | null;
  sector: string | null;
  as_of: string;
  roe: number | null; // 핵심지표(AC3) — null=지표 없음
  pbr: number | null;
  execution_score: number | null;
  washing_flag: boolean | null; // true=워싱의심 / false=근거없음 / null=판단불가
  buyback_status: string | null;
  buyback_executed: boolean | null;
  mna_target_score: number | null; // null=산출불가(엄격 게이팅)
  population_basis: string | null; // sector:{KSIC} / market_fallback / market
  has_valueup_score: boolean; // false=엔진 미집계(산출불가와 구분)
  has_mna_score: boolean;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}

export type ScoreMode = "valueup" | "mna";

export interface ScreeningParams {
  corp_code?: string; // 3.4 상세화면 단건 조회용
  market?: string;
  sector?: string;
  min_execution_score?: number;
  max_execution_score?: number;
  min_mna_score?: number;
  max_mna_score?: number;
  // 지표 범위 필터(AC2, 3.3 리뷰 반영)
  min_roe?: number;
  max_pbr?: number;
  max_ev_ebitda?: number;
  max_debt_ratio?: number;
  // 시총구간(KRW 원)
  min_market_cap?: number;
  max_market_cap?: number;
  washing_only?: boolean;
  buyback_executed?: boolean;
  sort?: string; // field / -field
  page?: number;
  size?: number;
}

export function useScreening(params: ScreeningParams) {
  return useQuery({
    queryKey: ["screening", params],
    queryFn: () => apiGet<Page<ScreeningRow>>("/screening", params as Record<string, unknown>),
    placeholderData: keepPreviousData, // 필터 변경 시 깜빡임 방지
  });
}

// 상세화면 헤더용 단건 조회(3.4) — 목록 API를 corp_code 필터+size=1로 재사용(신규
// 엔드포인트 회피). 종목이 스코어 미보유일 수 있어 total=0(빈 결과)이 정상 케이스.
export function useScreeningDetail(corpCode: string | undefined) {
  return useQuery({
    queryKey: ["screening-detail", corpCode],
    queryFn: () => apiGet<Page<ScreeningRow>>("/screening", { corp_code: corpCode, size: 1 }),
    enabled: !!corpCode,
    select: (page) => page.items[0] ?? null,
  });
}

```

### `dashboard/src/lib/investmentTags.ts`

```ts
import type { GapDetail } from "../api/detail";
import type { MnaDetail } from "../api/detail";
import type { MetricPoint } from "../api/detail";

export interface Tag {
  label: string;
  group: "valueup" | "mna";
}

// AC5 자동 태깅 — 순수 함수(입력 데이터만으로 판정, 부수효과 없음). 근거 지표가 null이면
// 태그를 만들지 않는다(추측으로 태그 생성 금지 — API가 지킨 null 정직성을 화면 마지막
// 단계에서 깨지 않기 위함). 임계치는 이 스토리의 표시 로직 상수(config.py의 스코어링
// 가중치와는 별개 — 스코어 산식이 아니라 "셀링포인트로 부를 만한가"의 프론트 판단).
const VALUEUP_HIGH_ROE = 10; // %
const VALUEUP_LOW_PBR = 1.0; // x
const MNA_STRONG_FACTOR = 0.7; // 0~1 스케일 상위 30% 근사

export function valueupTags(latestMetric: MetricPoint | undefined, gap: GapDetail | null): Tag[] {
  const tags: Tag[] = [];
  if (latestMetric?.roe !== undefined && latestMetric?.roe !== null && latestMetric.roe >= VALUEUP_HIGH_ROE) {
    tags.push({ label: `고ROE (${latestMetric.roe.toFixed(1)}%)`, group: "valueup" });
  }
  if (latestMetric?.pbr !== undefined && latestMetric?.pbr !== null && latestMetric.pbr <= VALUEUP_LOW_PBR) {
    tags.push({ label: `저PBR (${latestMetric.pbr.toFixed(2)}x)`, group: "valueup" });
  }
  // buyback_status가 null(엔진 미실행/미보유)이면 태그 없음 — "retired"일 때만
  if (gap?.buyback_status === "retired") {
    tags.push({ label: "자사주 실이행 (소각 확인)", group: "valueup" });
  }
  return tags;
}

export function mnaTags(mna: MnaDetail | null): Tag[] {
  if (!mna) return [];
  const tags: Tag[] = [];
  // capacity_score는 부채비율뿐 아니라 순현금·마진도 섞인 복합 지표라 "저부채"는 근사
  // 라벨(2.3 산식 자체가 그렇게 설계됨 — 3.4 스토리 스코프의 기록된 한계).
  if (mna.valuation_score !== null && mna.valuation_score >= MNA_STRONG_FACTOR) {
    tags.push({ label: "저평가", group: "mna" });
  }
  if (mna.capacity_score !== null && mna.capacity_score >= MNA_STRONG_FACTOR) {
    tags.push({ label: "저부채", group: "mna" });
  }
  if (mna.ownership_score !== null && mna.ownership_score >= MNA_STRONG_FACTOR) {
    tags.push({ label: "낮은 지분율", group: "mna" });
  }
  return tags;
}

```

### `dashboard/src/lib/investmentTags.test.ts`

```ts
import { describe, expect, it } from "vitest";
import { mnaTags, valueupTags } from "./investmentTags";
import type { GapDetail, MetricPoint, MnaDetail } from "../api/detail";

function metric(partial: Partial<MetricPoint>): MetricPoint {
  return {
    corp_code: "00000000", corp_name: null, market: null, sector: null,
    year: 2025, quarter: 3, roe: null, roa: null, pbr: null, per: null,
    ev_ebitda: null, debt_ratio: null, payout_ratio: null, net_cash: null,
    ebitda_margin: null, yoy_revenue_growth: null, yoy_income_growth: null,
    ...partial,
  };
}

function gap(partial: Partial<GapDetail>): GapDetail {
  return {
    corp_code: "00000000", corp_name: null, market: null, as_of: "2026-07-13",
    target_roe: null, actual_roe: null, roe_gap: null, achievement_rate: null,
    progress_rate: null, execution_score: null, washing_flag: null, buyback_status: null,
    ...partial,
  };
}

function mna(partial: Partial<MnaDetail>): MnaDetail {
  return {
    corp_code: "00000000", corp_name: null, market: null, sector: null, as_of: "2026-07-13",
    mna_target_score: null, valuation_score: null, capacity_score: null,
    ownership_score: null, macro_score: null, population_basis: null,
    ...partial,
  };
}

describe("valueupTags — null이면 태그 미생성", () => {
  it("roe·pbr·buyback_status 전부 null이면 태그 없음", () => {
    expect(valueupTags(metric({}), gap({}))).toEqual([]);
  });
  it("roe=10(경계값)은 고ROE — 임계 이상 포함", () => {
    const tags = valueupTags(metric({ roe: 10 }), gap({}));
    expect(tags).toEqual([{ label: "고ROE (10.0%)", group: "valueup" }]);
  });
  it("roe=9.9는 고ROE 아님", () => {
    expect(valueupTags(metric({ roe: 9.9 }), gap({}))).toEqual([]);
  });
  it("pbr=1.0(경계값)은 저PBR — 임계 이하 포함", () => {
    const tags = valueupTags(metric({ pbr: 1.0 }), gap({}));
    expect(tags).toEqual([{ label: "저PBR (1.00x)", group: "valueup" }]);
  });
  it("buyback_status='unknown'(판단불가)은 태그 없음 — retired일 때만", () => {
    expect(valueupTags(metric({}), gap({ buyback_status: "unknown" }))).toEqual([]);
    expect(valueupTags(metric({}), gap({ buyback_status: "retired" }))).toEqual([
      { label: "자사주 실이행 (소각 확인)", group: "valueup" },
    ]);
  });
  it("latestMetric 자체가 undefined(지표 없음)여도 크래시 없이 빈 배열", () => {
    expect(valueupTags(undefined, gap({ buyback_status: "retired" }))).toEqual([
      { label: "자사주 실이행 (소각 확인)", group: "valueup" },
    ]);
  });
  it("전 조건 충족 시 3개 태그", () => {
    const tags = valueupTags(metric({ roe: 15, pbr: 0.8 }), gap({ buyback_status: "retired" }));
    expect(tags).toHaveLength(3);
  });
});

describe("mnaTags — null이면 태그 미생성, 산출불가(mna=null)는 완전 빈 배열", () => {
  it("mna 자체가 null(산출 불가)이면 빈 배열", () => {
    expect(mnaTags(null)).toEqual([]);
  });
  it("요소 전부 null이면 태그 없음(총점은 있어도 요소가 null일 수 있는 이론상 케이스 방어)", () => {
    expect(mnaTags(mna({ mna_target_score: 50 }))).toEqual([]);
  });
  it("valuation_score=0.7(경계)은 저평가 포함", () => {
    expect(mnaTags(mna({ valuation_score: 0.7 }))).toEqual([{ label: "저평가", group: "mna" }]);
  });
  it("valuation_score=0.69는 저평가 아님", () => {
    expect(mnaTags(mna({ valuation_score: 0.69 }))).toEqual([]);
  });
  it("3요소 전부 강함이면 3개 태그", () => {
    const tags = mnaTags(mna({ valuation_score: 0.9, capacity_score: 0.8, ownership_score: 0.75 }));
    expect(tags).toHaveLength(3);
    expect(tags.map((t) => t.label)).toEqual(["저평가", "저부채", "낮은 지분율"]);
  });
});

```

### `dashboard/src/components/detail/MetricsChart.tsx`

```tsx
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { MetricPoint } from "../../api/detail";

// UX-DR3 지표 분기 시계열(3.2 시안 재현) — ROE 분기별 바차트.
export function MetricsChart({ metrics }: { metrics: MetricPoint[] }) {
  const data = metrics
    .filter((m) => m.roe !== null)
    .map((m) => ({ label: `${String(m.year).slice(2)}Q${m.quarter}`, roe: m.roe }));

  if (data.length === 0) {
    return <p className="py-8 text-center text-sm text-gray-400">ROE 시계열 데이터가 없습니다</p>;
  }

  return (
    <div className="h-[180px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <XAxis dataKey="label" tick={{ fontSize: 10, fill: "#9ca3af" }} axisLine={false} tickLine={false} />
          <YAxis hide />
          <Tooltip
            formatter={(v) => [`${Number(v).toFixed(1)}%`, "ROE"]}
            contentStyle={{ fontSize: 12, borderRadius: 8 }}
          />
          <Bar dataKey="roe" radius={[4, 4, 0, 0]}>
            {data.map((_, i) => (
              <Cell key={i} fill={i === data.length - 1 ? "#0e9f6e" : "#a7f3d0"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

```

### `dashboard/src/components/detail/GapCard.tsx`

```tsx
import type { GapDetail } from "../../api/detail";
import { WashingBadge } from "../badges";

// UX-DR3 "계획 vs 실제" 갭 카드(3.2 시안 재현). null 계약은 리스트와 동일 —
// washing_flag=판단불가 배지 재사용, 지표 null은 "—"(0 표시 금지).
export function GapCard({ gap }: { gap: GapDetail | null }) {
  if (!gap) {
    return (
      <div className="rounded-xl border border-gray-100 bg-white p-5 text-sm text-gray-400">
        밸류업 계획 데이터가 없습니다(엔진 미집계)
      </div>
    );
  }

  const fmt = (v: number | null, unit = "%") => (v === null ? "—" : `${v.toFixed(1)}${unit}`);

  return (
    <div className="rounded-xl border border-gray-100 bg-white p-5">
      <h3 className="mb-4 text-sm font-bold text-gray-900">계획 vs 실제 (밸류업 이행)</h3>
      <div className="flex items-center gap-0">
        <Stat label="목표 ROE" value={fmt(gap.target_roe)} color="#6b7280" />
        <span className="px-2 text-lg text-gray-300">→</span>
        <Stat label="실제 ROE" value={fmt(gap.actual_roe)} color="#0e9f6e" />
        <Stat
          label="갭"
          value={gap.roe_gap === null ? "—" : `${gap.roe_gap >= 0 ? "+" : ""}${gap.roe_gap.toFixed(1)}%p`}
          color={gap.roe_gap !== null && gap.roe_gap >= 0 ? "#0e9f6e" : "#dc2626"}
        />
      </div>
      <div className="mt-4 flex gap-3">
        <MiniStat label="달성률" value={fmt(gap.achievement_rate ? gap.achievement_rate * 100 : null)} />
        <MiniStat label="진척률" value={fmt(gap.progress_rate ? gap.progress_rate * 100 : null)} />
        <MiniStat label="자사주" value={buybackLabel(gap.buyback_status)} />
      </div>
      <div className="mt-3 flex items-center gap-2 text-xs text-gray-500">
        워싱 판정: <WashingBadge flag={gap.washing_flag} />
      </div>
    </div>
  );
}

function buybackLabel(status: string | null): string {
  switch (status) {
    case "retired":
      return "소각 이행";
    case "purchased_only":
      return "매입만·미소각";
    case "none":
      return "미실행";
    default:
      return "판단 불가";
  }
}

function Stat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="flex flex-1 flex-col gap-1">
      <span className="text-[11px] font-semibold text-gray-500">{label}</span>
      <span className="text-2xl font-bold" style={{ color }}>
        {value}
      </span>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-1 flex-col gap-1 rounded-lg bg-gray-50 px-3.5 py-3">
      <span className="text-[10px] font-semibold text-gray-500">{label}</span>
      <span className="text-base font-bold text-gray-900">{value}</span>
    </div>
  );
}

```

### `dashboard/src/components/detail/MnaBreakdown.tsx`

```tsx
import type { MnaDetail } from "../../api/detail";
import { PopulationBasisChip } from "../badges";

// UX-DR3/UX-DR4 M&A 4요소 분해(3.2 시안 재현). null 계약은 리스트와 동일 —
// mna_target_score null=산출 불가, population_basis chip 재사용.
const FACTORS: Array<{ key: keyof MnaDetail; label: string; weight: string }> = [
  { key: "valuation_score", label: "저평가 (valuation)", weight: "가중 0.35" },
  { key: "capacity_score", label: "인수여력 (capacity)", weight: "가중 0.25" },
  { key: "ownership_score", label: "지배구조 (ownership)", weight: "가중 0.25" },
  { key: "macro_score", label: "매크로 (macro)", weight: "가중 0.15" },
];

function factorColor(v: number): string {
  if (v >= 0.7) return "#65a30d";
  if (v >= 0.4) return "#ca8a04";
  return "#dc2626";
}

export function MnaBreakdown({ mna }: { mna: MnaDetail | null }) {
  if (!mna) {
    return (
      <div className="rounded-xl border border-gray-100 bg-white p-5 text-sm text-gray-400">
        M&A 스코어 데이터가 없습니다(엔진 미집계)
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-gray-100 bg-white p-5">
      <h3 className="mb-1 text-sm font-bold text-gray-900">M&A 4요소 분해</h3>
      <div className="mb-3">
        <PopulationBasisChip basis={mna.population_basis} />
      </div>
      {mna.mna_target_score === null && (
        <p className="mb-3 text-xs text-gray-400">총점 산출 불가 — 요소 지표 결측(0점/최하위 아님)</p>
      )}
      <div className="flex flex-col gap-3">
        {FACTORS.map((f) => {
          const v = mna[f.key] as number | null;
          return (
            <div key={f.key}>
              <div className="mb-1.5 flex items-center gap-2">
                <span className="flex-1 text-xs font-semibold text-gray-700">{f.label}</span>
                <span className="text-[9px] text-gray-400">{f.weight}</span>
                <span className="text-xs font-bold" style={{ color: v === null ? "#9ca3af" : factorColor(v) }}>
                  {v === null ? "—" : v.toFixed(2)}
                </span>
              </div>
              <div className="h-2 w-full rounded-full bg-gray-100">
                {v !== null && (
                  <div
                    className="h-2 rounded-full"
                    style={{ width: `${v * 100}%`, background: factorColor(v) }}
                  />
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

```

### `dashboard/src/components/detail/InvestmentPoints.tsx`

```tsx
import type { Tag } from "../../lib/investmentTags";

// UX-DR4 투자 포인트 카드 — 자동 태깅 결과 표시(순수 로직은 lib/investmentTags.ts).
export function InvestmentPoints({ tags }: { tags: Tag[] }) {
  const valueup = tags.filter((t) => t.group === "valueup");
  const mna = tags.filter((t) => t.group === "mna");

  if (tags.length === 0) {
    return (
      <div className="rounded-xl border border-gray-100 bg-white p-5 text-sm text-gray-400">
        자동 태깅할 만한 셀링포인트가 없습니다(근거 지표 부족)
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-gray-100 bg-white p-5">
      <h3 className="mb-3 text-sm font-bold text-gray-900">투자 포인트 (자동 태깅)</h3>
      {valueup.length > 0 && (
        <>
          <span className="text-[10px] font-bold text-emerald-600">밸류업</span>
          <div className="mb-3 mt-1.5 flex flex-col gap-1.5">
            {valueup.map((t) => (
              <TagRow key={t.label} label={t.label} color="emerald" />
            ))}
          </div>
        </>
      )}
      {mna.length > 0 && (
        <>
          <span className="text-[10px] font-bold text-indigo-600">M&A</span>
          <div className="mt-1.5 flex flex-col gap-1.5">
            {mna.map((t) => (
              <TagRow key={t.label} label={t.label} color="indigo" />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function TagRow({ label, color }: { label: string; color: "emerald" | "indigo" }) {
  const bg = color === "emerald" ? "#f0fdf4" : "#eef2ff";
  const fg = color === "emerald" ? "#166534" : "#4338ca";
  return (
    <div className="flex items-center gap-2 rounded-lg px-3 py-2.5" style={{ background: bg }}>
      <span className="h-2 w-2 rounded-full" style={{ background: fg }} />
      <span className="text-xs font-semibold" style={{ color: fg }}>
        {label}
      </span>
    </div>
  );
}

```

### `dashboard/src/pages/CompanyDetail.tsx`

```tsx
import { Link, useParams } from "react-router-dom";
import { useGapDetail, useMetricsByCorp, useMnaDetail } from "../api/detail";
import { useScreeningDetail } from "../api/screening";
import { GapCard } from "../components/detail/GapCard";
import { MetricsChart } from "../components/detail/MetricsChart";
import { MnaBreakdown } from "../components/detail/MnaBreakdown";
import { InvestmentPoints } from "../components/detail/InvestmentPoints";
import { MarketPill } from "../components/badges";
import { mnaTags, valueupTags } from "../lib/investmentTags";

// UX-DR3/UX-DR4 종목 상세 화면(3.2 Screen 2 시안). 4개 API 병렬 호출(AD-11 REST만):
// /screening(헤더) · /valueup/gap-analysis(갭카드) · /mna/ranking(4요소) · /metrics/{corp}(시계열).
export default function CompanyDetail() {
  const { corpCode } = useParams<{ corpCode: string }>();

  const { data: header } = useScreeningDetail(corpCode);
  const { data: gap, isLoading: gapLoading } = useGapDetail(corpCode);
  const { data: mna, isLoading: mnaLoading } = useMnaDetail(corpCode);
  const { data: metrics, isLoading: metricsLoading } = useMetricsByCorp(corpCode);

  const latestMetric = metrics?.[metrics.length - 1];
  const tags = [...valueupTags(latestMetric, gap ?? null), ...mnaTags(mna ?? null)];

  return (
    <div className="min-h-screen bg-[#f5f6f8] p-7">
      <Link to="/" className="mb-4 inline-block text-xs font-semibold text-emerald-600">
        ← 리스트로
      </Link>

      <header className="mb-5 flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl font-bold text-gray-900">{header?.corp_name ?? corpCode}</h1>
            <MarketPill market={header?.market ?? null} />
            <span className="text-xs text-gray-400">
              {corpCode} · {header?.sector ?? "—"}
            </span>
          </div>
          <p className="mt-1 text-[11px] text-gray-400">
            {header?.as_of ? `as_of ${header.as_of}` : "…"}
          </p>
        </div>
        <div className="flex gap-3">
          <ScoreChip
            label="실행점수"
            value={header?.execution_score ?? null}
            color="#0e9f6e"
          />
          <ScoreChip
            label="M&A 타겟"
            value={header?.mna_target_score ?? null}
            color="#65a30d"
          />
        </div>
      </header>

      <div className="flex gap-5">
        <div className="flex flex-1 flex-col gap-5">
          <div className="rounded-xl border border-gray-100 bg-white p-5">
            <h3 className="mb-3 text-sm font-bold text-gray-900">지표 분기 시계열 · ROE</h3>
            {metricsLoading ? (
              <p className="py-8 text-center text-sm text-gray-400">불러오는 중…</p>
            ) : (
              <MetricsChart metrics={metrics ?? []} />
            )}
          </div>
          {gapLoading ? <LoadingCard /> : <GapCard gap={gap ?? null} />}
        </div>
        <div className="flex w-[420px] shrink-0 flex-col gap-5">
          {mnaLoading ? <LoadingCard /> : <MnaBreakdown mna={mna ?? null} />}
          <InvestmentPoints tags={tags} />
        </div>
      </div>
    </div>
  );
}

function ScoreChip({ label, value, color }: { label: string; value: number | null; color: string }) {
  return (
    <div className="rounded-xl border border-gray-100 bg-white px-4 py-3">
      <div className="text-[10px] font-semibold text-gray-500">{label}</div>
      <div className="flex items-center gap-1">
        <span className="text-xl font-bold" style={{ color: value === null ? "#9ca3af" : color }}>
          {value === null ? "—" : value.toFixed(0)}
        </span>
        <span className="text-[10px] text-gray-400">/100</span>
      </div>
    </div>
  );
}

function LoadingCard() {
  return (
    <div className="rounded-xl border border-gray-100 bg-white p-5 text-sm text-gray-400">
      불러오는 중…
    </div>
  );
}

```

### `dashboard/src/pages/ScreenerList.tsx`

```tsx
import { useFilters, toParams } from "../state/filters";
import { useScreening } from "../api/screening";
import { FilterPanel } from "../components/FilterPanel";
import { ScreenerTable } from "../components/ScreenerTable";

export default function ScreenerList() {
  const filters = useFilters();
  const params = toParams(filters);
  // isPlaceholderData: keepPreviousData가 새 필터 응답 도착 전까지 이전 결과를 제공 —
  // 그대로 두면 "새 조건 라벨 아래 이전 결과"가 보인다(재리뷰 #4). 오버레이로 명시.
  const { data, isFetching, isPlaceholderData, error } = useScreening(params);

  return (
    <div className="flex min-h-screen">
      <FilterPanel />
      <main className="flex-1 p-7">
        <header className="mb-4 flex items-center justify-between">
          <div>
            <h1 className="text-lg font-bold text-gray-900">종목 리스트</h1>
            <p className="text-xs text-gray-500">
              {/* 재리뷰(3차) 반영: placeholder 중엔 total을 표시하지 않는다 — 이전 조건의
                  개수를 새 필터 결과인 것처럼 보여주면 안 됨(정직성 원칙, 이 프로젝트의
                  null 계약과 동일한 이유). */}
              {isPlaceholderData ? "새 조건 계산 중…" : data ? `${data.total}개 종목` : "…"} ·{" "}
              {filters.scoreMode === "valueup" ? "Value-up" : "M&A"} 모드
            </p>
          </div>
          <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs font-semibold text-gray-700">
            정렬: {filters.sort}
          </div>
        </header>
        {/* 배너는 opacity 래퍼 밖 — 흐려지지 않고 또렷하게 보여야 함(재리뷰 반영) */}
        {isPlaceholderData && (
          <div className="mb-2 rounded-lg bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-700">
            새 조건으로 다시 계산 중 — 아래는 이전 조건의 결과입니다
          </div>
        )}
        <div className={isPlaceholderData ? "pointer-events-none opacity-50" : ""}>
          <ScreenerTable
            rows={data?.items ?? []}
            total={data?.total ?? 0}
            loading={isFetching}
            error={error}
          />
        </div>
      </main>
    </div>
  );
}

```

### `dashboard/src/App.tsx`

```tsx
import { Route, Routes } from "react-router-dom";
import ScreenerList from "./pages/ScreenerList";
import CompanyDetail from "./pages/CompanyDetail";

// AC6: /company/:corpCode 딥링크. 리스트 필터 상태(zustand)는 전역 스토어라
// 라우트 전환에도 언마운트되지 않고 그대로 보존된다(뒤로가기 시 필터 유지).
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<ScreenerList />} />
      <Route path="/company/:corpCode" element={<CompanyDetail />} />
    </Routes>
  );
}

```

### `dashboard/src/main.tsx`

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./App.tsx";
import "./index.css";

// 서버 상태 전담(AD-11). UI 상태(필터·모드)는 zustand로 별도 관리.
const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);

```

### `dashboard/src/components/ScreenerTable.tsx`

```tsx
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import type { ScreeningRow } from "../api/screening";
import { useFilters } from "../state/filters";
import { MarketPill, MnaCell, ValueUpCell, WashingBadge } from "./badges";
import { ApiRequestError } from "../api/client";

const col = createColumnHelper<ScreeningRow>();

// 정렬 가능한 헤더 — 클릭 시 sort 토글(백엔드 field/-field 규약, AD-6)
function SortableHeader({ label, field, align }: { label: string; field?: string; align?: "right" }) {
  const { sort, setSort } = useFilters();
  if (!field) return <span>{label}</span>;
  const active = sort === field || sort === `-${field}`;
  const desc = sort === `-${field}`;
  return (
    <button
      onClick={() => setSort(desc ? field : `-${field}`)}
      className={`flex items-center gap-1 ${align === "right" ? "justify-end" : ""} ${
        active ? "text-gray-900" : "text-gray-500"
      }`}
    >
      {label}
      {active && <span>{desc ? "↓" : "↑"}</span>}
    </button>
  );
}

export function ScreenerTable({
  rows,
  total,
  loading,
  error,
}: {
  rows: ScreeningRow[];
  total: number;
  loading: boolean;
  error: unknown;
}) {
  const { scoreMode, page, size, setPage } = useFilters();
  const navigate = useNavigate(); // AC1/AC6: 행 클릭 → /company/:corpCode 딥링크 라우트

  const columns = useMemo(
    () => [
      col.accessor("corp_name", {
        header: () => <span>종목명</span>,
        cell: (c) => (
          <div className="flex flex-col">
            <span className="text-[13px] font-semibold text-gray-900">{c.getValue() ?? "—"}</span>
            <span className="text-[10px] text-gray-400">{c.row.original.corp_code}</span>
          </div>
        ),
      }),
      col.accessor("market", {
        header: () => <span>시장</span>,
        cell: (c) => <MarketPill market={c.getValue()} />,
      }),
      col.display({
        id: "valueup",
        header: () => <SortableHeader label="Value-up" field="execution_score" align="right" />,
        cell: (c) => (
          <div className="text-right">
            <ValueUpCell row={c.row.original} />
          </div>
        ),
      }),
      col.display({
        id: "mna",
        header: () => <SortableHeader label="M&A" field="mna_target_score" align="right" />,
        cell: (c) => (
          <div className="flex justify-end">
            <MnaCell row={c.row.original} />
          </div>
        ),
      }),
      // 핵심지표(AC3, 3.3 리뷰 반영) — null=지표 없음("—", 0으로 표시 금지)
      col.accessor("roe", {
        header: () => <span className="block text-right">ROE</span>,
        cell: (c) => {
          const v = c.getValue();
          return (
            <div className="text-right text-xs text-gray-700">
              {v === null ? <span className="text-gray-300">—</span> : `${v.toFixed(1)}%`}
            </div>
          );
        },
      }),
      col.accessor("pbr", {
        header: () => <span className="block text-right">PBR</span>,
        cell: (c) => {
          const v = c.getValue();
          return (
            <div className="text-right text-xs text-gray-700">
              {v === null ? <span className="text-gray-300">—</span> : `${v.toFixed(2)}x`}
            </div>
          );
        },
      }),
      col.accessor("washing_flag", {
        header: () => <span>워싱</span>,
        cell: (c) => <WashingBadge flag={c.getValue()} />,
      }),
    ],
    [],
  );

  const table = useReactTable({ data: rows, columns, getCoreRowModel: getCoreRowModel() });
  const totalPages = Math.max(1, Math.ceil(total / size));

  // AC6 강조 컬럼(재리뷰 #6): 활성 스코어 모드의 컬럼 전체를 배경 틴트로 강조
  const highlightedCol = scoreMode === "valueup" ? "valueup" : "mna";
  const highlightClass = (colId: string) =>
    colId === highlightedCol ? (scoreMode === "valueup" ? "bg-emerald-50/70" : "bg-indigo-50/70") : "";

  if (error) {
    const msg =
      error instanceof ApiRequestError
        ? `${error.code ?? error.status}: ${typeof error.detail === "string" ? error.detail : "요청 오류"}`
        : "데이터를 불러오지 못했습니다";
    return (
      <div className="rounded-xl border border-red-100 bg-red-50 p-6 text-sm text-red-700">{msg}</div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
      <table className="w-full">
        <thead>
          <tr className="border-b border-gray-100 bg-gray-50">
            {table.getHeaderGroups()[0].headers.map((h) => (
              <th
                key={h.id}
                className={`px-4 py-3 text-[11px] font-semibold text-gray-500 ${
                  h.id === "valueup" || h.id === "mna" ? "text-right" : "text-left"
                } ${highlightClass(h.id)}`}
              >
                {flexRender(h.column.columnDef.header, h.getContext())}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && !loading && (
            <tr>
              <td colSpan={7} className="px-4 py-10 text-center text-sm text-gray-400">
                조건에 맞는 종목이 없습니다
              </td>
            </tr>
          )}
          {table.getRowModel().rows.map((r) => (
            <tr
              key={r.id}
              onClick={() => navigate(`/company/${r.original.corp_code}`)}
              className="cursor-pointer border-b border-gray-50 hover:bg-gray-50/70"
              style={{ background: r.original.washing_flag === true ? "#fffbfa" : undefined }}
            >
              {r.getVisibleCells().map((cell) => (
                <td key={cell.id} className={`px-4 py-3.5 align-middle ${highlightClass(cell.column.id)}`}>
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>

      <div className="flex items-center justify-between border-t border-gray-100 px-4 py-3 text-xs text-gray-500">
        <span>
          총 {total}종목 · {scoreMode === "valueup" ? "Value-up" : "M&A"} 모드
          {loading && <span className="ml-2 text-gray-400">불러오는 중…</span>}
        </span>
        <div className="flex items-center gap-2">
          <button
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
            className="rounded border border-gray-200 px-2 py-1 disabled:opacity-40"
          >
            이전
          </button>
          <span>
            {page} / {totalPages}
          </span>
          <button
            disabled={page >= totalPages}
            onClick={() => setPage(page + 1)}
            className="rounded border border-gray-200 px-2 py-1 disabled:opacity-40"
          >
            다음
          </button>
        </div>
      </div>
    </div>
  );
}

```

### `dashboard/src/components/badges.tsx`

```tsx
import type { ScreeningRow } from "../api/screening";

// 3.2 Figma 범례(node 11:2)의 null 시각 언어를 그대로 구현.
// 원칙: null을 빈칸·0·"아니오"로 뭉개지 않는다(2.4~2.6 API 계약 승계).

function Pill({ text, bg, fg, dashed }: { text: string; bg?: string; fg: string; dashed?: boolean }) {
  return (
    <span
      className="inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-semibold"
      style={{
        background: bg ?? "transparent",
        color: fg,
        border: dashed ? "1px dashed #d1d5db" : undefined,
      }}
    >
      {text}
    </span>
  );
}

export function WashingBadge({ flag }: { flag: boolean | null }) {
  if (flag === true) return <Pill text="⚠ 워싱 의심" bg="#fee4e2" fg="#b42318" />;
  if (flag === false) return <span className="text-xs text-gray-400">근거 없음</span>;
  return <Pill text="판단 불가" fg="#6b7280" dashed />; // null
}

function scoreColor(v: number): string {
  if (v >= 70) return "#0e9f6e";
  if (v >= 50) return "#65a30d";
  if (v >= 30) return "#ca8a04";
  return "#dc2626";
}

export function ValueUpCell({ row }: { row: ScreeningRow }) {
  if (!row.has_valueup_score) return <Pill text="미집계" fg="#9ca3af" dashed />;
  if (row.execution_score === null) return <span className="text-xs text-gray-400">—</span>;
  return (
    <span className="text-[15px] font-bold" style={{ color: scoreColor(row.execution_score) }}>
      {row.execution_score.toFixed(0)}
    </span>
  );
}

// 은행·보험 등 M&A 스코어가 구조적으로 산출 불가한 업종(KSIC 64~66 금융·보험)
function isUnsupportedSector(sector: string | null): boolean {
  if (!sector) return false;
  const p = sector.slice(0, 2);
  return p === "64" || p === "65" || p === "66";
}

export function MnaCell({ row }: { row: ScreeningRow }) {
  if (!row.has_mna_score) return <Pill text="미집계" fg="#9ca3af" dashed />;
  if (row.mna_target_score === null) {
    if (isUnsupportedSector(row.sector)) {
      return (
        <div className="flex flex-col items-end gap-0.5">
          <Pill text="미지원 업종" bg="#f3f4f6" fg="#6b7280" />
          <span className="text-[9px] text-gray-400">은행·보험</span>
        </div>
      );
    }
    return (
      <div className="flex flex-col items-end gap-0.5">
        <span className="text-[15px] font-bold text-gray-400">—</span>
        <span className="text-[10px] text-gray-400">산출 불가</span>
      </div>
    );
  }
  return (
    <div className="flex flex-col items-end gap-0.5">
      <span className="text-[15px] font-bold" style={{ color: scoreColor(row.mna_target_score) }}>
        {row.mna_target_score.toFixed(1)}
      </span>
      <PopulationBasisChip basis={row.population_basis} />
    </div>
  );
}

export function PopulationBasisChip({ basis }: { basis: string | null }) {
  if (!basis) return null;
  let label = "전체시장";
  if (basis.startsWith("sector:")) label = `업종 내 (KSIC ${basis.slice(7)})`;
  else if (basis === "market_fallback") label = "전체시장 폴백";
  return <span className="text-[9px] text-gray-400">{label}</span>;
}

export function MarketPill({ market }: { market: string | null }) {
  if (!market) return <span className="text-xs text-gray-400">—</span>;
  const kospi = market === "KOSPI";
  return <Pill text={market} bg={kospi ? "#eff6ff" : "#f5f3ff"} fg={kospi ? "#1d4ed8" : "#6d28d9"} />;
}

```
