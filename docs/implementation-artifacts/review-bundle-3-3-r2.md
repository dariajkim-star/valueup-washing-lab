# Review Bundle — Story 3.3 재리뷰 (2026-07-13, 1차 반려 반영 후)

역할: 컨텍스트 없는 시니어 풀스택(FastAPI+React/TS) 리뷰어. 이번 번들은 **스토리 문서 + 백엔드/프론트 소스 + 테스트 전부 verbatim**(1차 리뷰가 문서만 보고 이뤄져 소스 기반 오탐 1건이 있었음 — 이번엔 코드 라인 단위 검증 가능).

## 1차 반려 사유와 반영 내역
1. [BLOCKER] AC2 필터 미배선 → 백엔드 /screening에 min_roe·max_pbr·max_ev_ebitda·max_debt_ratio·min/max_market_cap 추가(뷰 미매핑이라 2단계: 통과 corp 집합→IN 조건, COUNT/페이지네이션 SQL 유지) + 프론트 업종 select·시총 select·슬라이더 4종 실배선(커밋 시점 분리).
2. [High] ROE/PBR 컬럼 → ScreeningOut에 roe/pbr(look-ahead 안전 최신) + 테이블 컬럼(null="—").
3. [High] 33vs32 → 실증: 한국전력공사 1종목이 두 스코어 모두 없어 2.6 설계("두 스코어 모두 없으면 제외")대로 제외 — 문서화 완료, 버그 아님.
4. [High] KSIC 판정 → 기각(sector는 DART induty_code 숫자 KSIC 원문임을 데이터로 실증, 예: "64992"·"65121"). 백엔드 명시 score_status는 deferred.
5. [Med] 프론트 테스트 → vitest 22종(filters/client/badges).
6. [Med] 체크박스 과대계상 → 스토리 상태·체크박스·노트 정정 완료.

## 재리뷰 관점(요청)
- 지표 필터의 2단계(IN 조건) 방식에 페이지네이션/COUNT 정합 깨지는 케이스가 있는가.
- 시총 필터의 "전역 최신가" 컨벤션(뷰 PBR과 동일, point-in-time은 기존 defer)이 명시 as_of 조회와 조합될 때 오해 소지 — 알려진 한계로 수용 가능한가.
- 슬라이더 커밋(onPointerUp/onKeyUp) 방식의 빠뜨린 이벤트 경로(터치·폼 리셋 등).
- query key와 필터 상태의 동기화 누락.

## 알려진 것(재보고 불필요)
- 스크린샷 캡처 불가는 환경 이슈(접근성 트리·네트워크 로그로 검증 대체).
- score_run 메타데이터(latest_as_of 오염)·가격 point-in-time — 기존 defer.
- msw 통합테스트 — deferred(단위테스트로 1차 방어).

## 파일 (verbatim)

### `docs/implementation-artifacts/3-3-screener-filter-list.md`

```markdown
---
baseline_commit: bc8334f
---

# Story 3.3: 스크리너 화면 — 필터 패널 & 종목 리스트

Status: review

## Story

As a 애널리스트,
I want 화면에서 조건을 걸어 종목 리스트를 보는 것,
so that 원하는 종목군을 좁혀 탐색한다.

## Acceptance Criteria

1. **Given** React 19 + Vite 스캐폴딩이 `dashboard/`에 서고, **When** 앱을 구동하면, **Then** 3.2 Figma 시안(Screen 1)을 옮긴 필터 패널 + 종목 리스트 레이아웃이 렌더된다.
2. **Given** 필터 조작(시장·업종·시총구간·ROE/PBR/EV·EBITDA/부채비율 슬라이더·워싱 토글·스코어 모드), **When** 값을 바꾸면, **Then** 리스트가 즉시 필터링된다(필터→쿼리 파라미터→재요청).
3. **Given** 리스트(TanStack Table), **Then** Value-up 점수·M&A 점수·핵심지표(ROE·PBR)·워싱 배지 컬럼이 표시되고, 3.2에서 확정한 **null 시각 언어**(판단불가·산출불가·미집계·미지원업종·population_basis)가 배지 컴포넌트로 구현된다.
4. **Given** 서버 상태, **Then** TanStack Query로 `/screening` API만 호출(AD-11: DB·아티팩트 직접 접근 없음), UI 상태(필터·스코어 모드)는 로컬로 분리한다.
5. **Given** 정렬·페이지네이션, **Then** `/screening`의 `sort`(field/-field)·`page`/`size`와 응답 봉투(`{items,total,page,size}`)에 정합하게 동작하고, 400(INVALID_SORT)·422(빈 필터)·404 등 에러 계약을 화면이 깨지지 않게 처리한다.
6. **Given** 스코어 모드 전환(Value-up↔M&A), **Then** 강조 컬럼·기본 정렬(execution_score ↑ ↔ mna_target_score ↓)이 바뀐다(UI 상태, 서버 재요청).
7. **Given** 검증, **Then** FastAPI 백엔드 + Vite dev 서버를 함께 띄워 실데이터(valueup.db 33종목)로 리스트가 렌더되고 필터·정렬·null 배지가 동작함을 브라우저에서 확인한다.

## Tasks / Subtasks

- [x] **T1**: `dashboard/` 스캐폴딩 — React 19.2 + Vite 8.1 + TS 6 + Tailwind 4.3 + TanStack Query·Table + zustand. Vite dev proxy `/api → 127.0.0.1:8000`(AD-11). npm install 43패키지 clean.
- [x] **T2**: `src/api/client.ts`(fetch 래퍼, 미선택 파라미터 제거, ApiRequestError로 에러계약 파싱) + `src/api/screening.ts`(ScreeningRow 2.6 스키마 1:1 + `useScreening` 훅, keepPreviousData).
- [x] **T3**: `src/state/filters.ts`(zustand) — 스코어 모드 전환 시 기본 sort 스왑(valueup→execution_score / mna→-mna_target_score) + page 1 리셋.
- [x] **T4**: `src/components/badges.tsx` — WashingBadge·ValueUpCell·MnaCell·PopulationBasisChip·MarketPill. 3.2 범례 6상태 그대로(미지원업종=KSIC 64~66 판정 포함).
- [x] **T5**: `FilterPanel.tsx`(UX-DR1) — [리뷰 반려 → 재작업 완료] **전 필터 실배선**: 시장·워싱·스코어모드 + 업종 select(KSIC prefix)·시총구간 select(대/중/소 버킷→min/max_market_cap)·ROE/PBR/EV·EBITDA/부채비율 실동작 슬라이더(드래그 중 로컬, 놓을 때 커밋 — 요청 폭주 방지).
- [x] **T6**: `App.tsx` + `main.tsx`(QueryClientProvider). launch.json에 `valueup-dashboard`(port 5175) 등록.
- [x] **T7**: [재검증 완료] 전 필터 라이브 조작 검증 — 아래 2차 검증 노트.
- [x] **T8[리뷰 추가]**: 백엔드 `/screening` 확장 — 지표 범위 필터 4종 + 시총 필터 + 응답 roe·pbr. 뷰는 ORM 미매핑이라 2단계(통과 corp 집합→IN 조건, COUNT·페이지네이션은 SQL 유지). pytest 3종 추가 → **224 passed**.
- [x] **T9[리뷰 추가]**: vitest 단위테스트 22종 — filters(page 리셋·sort 스왑·버킷 변환), client(빈 파라미터 제거·0/false 보존·에러 계약 파싱·detail 배열·비JSON 응답), badges(null 상태 우선순위: 미집계>미지원업종>산출불가>값, sector null 오판 방지).
- [x] **T10[리뷰 추가]**: 33 vs 32 사유 문서화 완료(Dev Notes) — 한국전력공사 1종목, 2.6 설계대로 제외(버그 아님).

## Dev Notes

### 스택·위치 결정

- **위치 `dashboard/`** — 아키텍처 AD-9/AD-11이 명명한 프론트 경계. 저장소 루트 하위 별도 npm 프로젝트(백엔드 .venv와 독립).
- **스택** — React 19.2 / Vite 8.1 / TS / Tailwind 4.3(flood-escape-lab과 계열 일관) + TanStack Query(서버상태)·Table(리스트). shadcn-ui는 이 스토리에선 미도입(필요 최소 — 커스텀 경량 컴포넌트로 시안 재현, 과설치 회피). Recharts는 3.4(상세 시계열)에서.
- **AD-11 준수** — 데이터는 `/screening` REST만. Vite dev proxy로 `/api` 프리픽스를 FastAPI(127.0.0.1:8000)에 넘겨 CORS·하드코딩 URL 회피. 서버상태=TanStack Query, UI상태(필터·모드)=zustand 로컬 — 두 관심사 분리.

### 3.2 시안·API 매핑 (그대로 구현)

- 리스트 행 = `/screening` ScreeningOut: corp_name·market·execution_score·mna_target_score·washing_flag·population_basis·**has_valueup_score·has_mna_score**·buyback_status·buyback_executed·sector.
- null 배지 규칙(3.2 범례 node 11:2): washing_flag(true=워싱의심/false=근거없음/null=판단불가), mna null=산출불가, has_*_score=false→미집계(산출불가와 구분), 금융 등 sector→미지원업종, population_basis chip.
- 필터→쿼리: market·sector·min/max_execution_score·min/max_mna_score·washing_only·buyback_executed·sort·page·size. 빈 문자열 필터는 보내지 않음(2.6이 빈 문자열 422 — 프론트가 미선택을 빈 문자열로 보내지 않게).

### 아키텍처 가드레일

- AD-11(REST만·상태 분리), AD-6 응답 봉투/정렬 규약/에러 계약 소비. 에러 계약: 400·422·404 응답의 `{detail,code}`를 화면이 토스트/빈 상태로 처리(크래시 금지).
- 이 스토리는 **필터·리스트만**(상세=3.4, Tableau=3.5). 백엔드 코드 변경 없음(순수 소비) — 기존 221 pytest 불변.

### 검증 방식

- 백엔드는 smoke 패턴(uvicorn 백그라운드, 이전 스토리들과 동일)으로 127.0.0.1:8000, 프론트는 preview_start(launch.json). 실데이터 valueup.db(KOSPI 33종목)로 렌더 확인.

### 유니버스 33 vs 리스트 32 (리뷰 지적 → 실증 완료)

- `company` 33종목 중 **한국전력공사(00159193, sector 35120)** 1종목이 `/screening`에서 제외됨 — 밸류업 공시가 없어 gap_engine이 행 미생성(2.1 설계) + M&A 3요소 전부 null이라 mna_engine도 행 미생성(2.3 설계) → **두 스코어 모두 없는 종목 제외**(2.6 AC1)가 정확히 적용된 결과. 파이프라인 버그 아님. 데이터 검증 쿼리로 확정(2026-07-13).
- 화면 문구도 "33개 종목"이 아니라 API total(32)을 그대로 표시 — 이미 정합.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (bmad-create-story + 인라인 구현)

### Completion Notes List

> **[2026-07-13 리뷰 반려 정정]** 아래 1차 노트의 "라이브 검증"은 시장·워싱·스코어모드·정렬·페이지네이션만 동작 검증한 것이다. 업종·시총·ROE·PBR·EV/EBITDA·부채비율 필터는 당시 미구현(가짜 컨트롤)이었고, AC2 충족 전까지 이 스토리는 완료 처리하지 않는다. 체크박스를 AC보다 후하게 친 것이 반려 사유 — 재작업 후 재검증한다.

- **라이브 검증(1차, 부분 — 백엔드 uvicorn:8000 + Vite:5175, valueup.db 실데이터)**:
  - 실데이터 32종목 렌더, 5가지 null 상태 전부 화면에 정상 표시 — 고려아연=산출 불가, 삼성생명보험=미지원 업종(은행·보험), 삼성SDI=미집계(Value-up), 다수=판단 불가, 전 종목 population_basis chip(전체시장 폴백).
  - **스코어 모드 전환** 동작: M&A 클릭 → 헤더 "M&A 모드"·정렬 `-mna_target_score`·리스트 내림차순 재정렬(포스코홀딩스 71.1→네이버 68.0→크래프톤 67.4 = 2.5 랭킹과 일치).
  - **워싱 필터** 동작: 워싱 토글 → 0종목(대형주 워싱 의심 0, 드레스 리허설과 정합) → 빈 상태 "조건에 맞는 종목이 없습니다".
  - 페이지네이션(20/32), 점선 배지 스타일(dashed border) 적용 확인. 콘솔·빌드 에러 0. **tsc -b clean**.
  - 스크린샷 캡처는 환경 렌더러 이슈로 타임아웃(read_page·클릭·JS 평가는 전부 정상 — 페이지 결함 아님). 시각 검증은 read_page 접근성 트리 + computed style로 대체.
- 백엔드 코드 무변경(순수 소비) → **기존 221 pytest 불변**.
- 슬라이더(ROE/PBR/EV·EBITDA/부채비율)·업종·시총 필터는 시안 UI만(배선은 후속) — 즉시 필터 핵심 경로(시장·워싱·모드·정렬·페이지)를 우선 검증.

### 2차 검증 (리뷰 반영 후, 2026-07-13 — 라이브 valueup.db)

- **네트워크 실증**(요청 로그 원문): `sector=64` 전송 → 해제 시 빈 문자열 없이 파라미터 제거 → `min_roe=15`(슬라이더 커밋) → `min_roe=15&min_market_cap=10000000000000`(AND 조합). 매 요청 `page=1` 리셋.
- 업종=금융(64) → 금융지주 5종목, 전부 "미지원 업종/은행·보험" 배지 + ROE/PBR 값은 정상 표시(KB 8.4%·1.12x — 금융주도 ROE/PBR은 유효, EV/EBITDA만 무의미. 배지-지표 공존이 정확).
- ROE≥15 슬라이더 → 32→4종목(기아 17.5% 등). 시총 대형(10조↑) 조합 → 4종목 유지(고ROE 대형주).
- ROE/PBR 컬럼 라이브 표시(기아 17.5%·1.05x), 지표 없는 종목 "—".
- 백엔드 pytest **224 passed**(지표/시총 필터 + roe/pbr 응답 3종 추가), vitest **22 passed**, tsc clean.

### File List

- `dashboard/package.json`·`vite.config.ts`·`tsconfig.json`·`index.html`·`.gitignore` (스캐폴딩)
- `dashboard/src/main.tsx`·`App.tsx`·`index.css`·`vite-env.d.ts`
- `dashboard/src/api/client.ts`·`screening.ts`
- `dashboard/src/state/filters.ts`
- `dashboard/src/components/badges.tsx`·`FilterPanel.tsx`·`ScreenerTable.tsx`
- `.gitignore`(루트, dashboard/ 무시 경로 정정) · `../.claude/launch.json`(Desktop, valueup-dashboard 등록)

## Change Log

- 2026-07-13: Story 3.3 생성 — 스크리너 필터·리스트 React 구현. dashboard/ 스캐폴딩(React19/Vite8/TS/Tailwind4 + TanStack Query·Table), 3.2 시안·null 시각 언어 구현, AD-11(REST만·상태분리) 준수, /screening 소비.
- 2026-07-13: Story 3.3 구현(1차) — dashboard 스캐폴딩+필터패널+TanStack Table+null배지, 부분 검증. Status → review.
- 2026-07-13: **GPT 리뷰 반려**(Changes Requested) — AC2 필터 미배선(BLOCKER)·ROE/PBR 컬럼 부재(High)·33vs32 미설명(High)·프론트 테스트 부재(Med)·체크박스 과대계상(Med). KSIC 판정 건은 전제 오류(sector=KSIC 코드 실증)로 기각, 백엔드 명시 status는 defer. Status → in-progress.
- 2026-07-13: 리뷰 반영 재작업 — ① 백엔드 /screening 확장(지표 4종+시총 필터, roe/pbr 응답, 224 passed) ② 전 필터 실배선(업종·시총 select, 슬라이더 4종 커밋 방식) ③ ROE/PBR 컬럼 ④ vitest 22종 ⑤ 33vs32 문서화(한전 1종목, 설계대로) ⑥ 라이브 재검증(네트워크 로그 실증). Status → review(재리뷰 대기).

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
    """corp별 look-ahead 안전 최신 지표(roe·pbr·ev_ebitda·debt_ratio) — 3.3 리뷰 반영.

    2.1/2.3/3.1과 동일한 사업보고서 배제 규칙 + Python dedupe(DISTINCT ON 회피, 이식성).
    look-ahead 패턴 4번째 사용처 — 시그니처(선택 컬럼·조인)가 소비자마다 달라 억지 공통화
    대신 명시적 반복을 유지(deferred-work의 공통 헬퍼 항목에 기록).
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
            # 핵심지표(AC3, 3.3 리뷰 반영): look-ahead 안전 최신 지표. 없으면 null.
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
        "범위 필터는 null을 매칭하지 않는다(산출 불가는 조건 판단 불가)."
    ),
)
def screening_list(
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
        "market": market, "sector": sector,
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

### `app/schemas.py`

```python
"""API 응답 pydantic 스키마."""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """목록 응답 봉투 (AD-6)."""

    items: list[T]
    total: int
    page: int
    size: int


class MetricOut(BaseModel):
    """valuation_metrics 뷰 + company 조인 결과."""

    corp_code: str
    corp_name: str | None = None
    market: str | None = None
    sector: str | None = None
    year: int
    quarter: int
    roe: float | None = None
    roa: float | None = None
    pbr: float | None = None
    per: float | None = None
    ev_ebitda: float | None = None
    debt_ratio: float | None = None
    payout_ratio: float | None = None
    net_cash: int | None = None
    ebitda_margin: float | None = None
    yoy_revenue_growth: float | None = None
    yoy_income_growth: float | None = None


class ScreeningOut(BaseModel):
    """company + valueup_score + mna_score outer join 결과 (2.6 다중조건 스크리닝).

    null 계약 승계: washing_flag null=판단 불가(빈칸/아니오 표시 금지, 2.4),
    mna_target_score null=산출 불가(0점/최하위 표시 금지, 2.5).
    has_valueup_score/has_mna_score: 엔진 실행 여부(score row 존재) — "row 없음(미실행)"과
    "row는 있으나 전부 null(엄격 게이팅 산출 불가)"은 필드값만으론 구분 불가라 명시 노출.
    """

    corp_code: str
    corp_name: str | None = None
    market: str | None = None
    sector: str | None = None
    as_of: str
    # 핵심지표(AC3, 3.3 리뷰 반영) — look-ahead 안전 최신값, null=지표 없음
    roe: float | None = None
    pbr: float | None = None
    has_valueup_score: bool
    has_mna_score: bool
    execution_score: float | None = None
    washing_flag: bool | None = None
    buyback_status: str | None = None
    buyback_executed: bool | None = None
    mna_target_score: float | None = None
    population_basis: str | None = None


class MnaRankingOut(BaseModel):
    """mna_score + company 조인 결과 (2.5 M&A 타겟 랭킹).

    mna_target_score 계약: **null=산출 불가**(요소 하나라도 입력 데이터 부족이면 총점
    null — 2.3 엄격 null 정책). UI에서 0점이나 최하위로 표시 금지, "산출 불가"로 표시.
    population_basis: 백분위 모집단 식별(sector:{KSIC2} / market_fallback / market, 2.7).
    """

    corp_code: str
    corp_name: str | None = None
    market: str | None = None
    sector: str | None = None
    as_of: str
    mna_target_score: float | None = None
    valuation_score: float | None = None
    capacity_score: float | None = None
    ownership_score: float | None = None
    macro_score: float | None = None
    population_basis: str | None = None


class MarketComparisonOut(BaseModel):
    """시장별(KOSPI/KOSDAQ) 헤드라인 통계 (3.1). n=as_of 시점 최신 지표 보유 종목 수,
    washing_ratio 분모는 n_judged(washing_flag가 null이 아닌 종목) — n과 다른 모집단.
    market은 이 스토리가 다루는 KOSPI/KOSDAQ로 한정(repository가 이미 필터하지만
    스키마에서도 계약을 좁혀 방어)."""

    market: Literal["KOSPI", "KOSDAQ"]
    n: int
    avg_roe: float | None = None
    avg_pbr: float | None = None
    avg_ev_ebitda: float | None = None
    n_judged: int
    n_washing: int
    washing_ratio: float | None = None


class StatsSummaryOut(BaseModel):
    """시장 구분 없는 전체 헤드라인 KPI (3.1)."""

    as_of: str
    n_companies: int
    n_metrics: int
    avg_roe: float | None = None
    avg_pbr: float | None = None
    avg_ev_ebitda: float | None = None
    n_judged: int
    n_washing: int
    washing_ratio: float | None = None


class MacroSnapshotOut(BaseModel):
    """매크로 지표 스냅샷 (3.1). date/value null = 아직 관측 없음(지표 자리는 항상 보장)."""

    indicator: str
    date: str | None = None
    value: float | None = None


class GapAnalysisOut(BaseModel):
    """valueup_score + company 조인 결과 (2.4 갭분석/워싱랭킹).

    washing_flag 계약: true=워싱 의심 / false=워싱 근거 없음 / **null=판단 불가**
    (입력 데이터 부족 — UI에서 빈칸이나 '아니오'로 표시 금지, "판단 불가"로 표시할 것).
    """

    corp_code: str
    corp_name: str | None = None
    market: str | None = None
    as_of: str
    target_roe: float | None = None
    actual_roe: float | None = None
    roe_gap: float | None = None
    achievement_rate: float | None = None
    progress_rate: float | None = None
    execution_score: float | None = None
    washing_flag: bool | None = None
    buyback_status: str | None = None

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
    # 지표·시총(3.3 리뷰 반영): 00000001=고ROE(20%)·저PBR, 00000002=저ROE(5%)·고PBR.
    # 00000003/4는 지표 없음(roe/pbr null — 범위 필터 불통과 검증용).
    s.execute(text(
        "INSERT INTO financials (corp_code, year, quarter, revenue, net_income, equity, "
        "total_assets, total_liabilities, operating_income) VALUES "
        "('00000001', 2025, 3, 1000, 200, 1000, 3000, 1000, 220), "
        "('00000002', 2025, 3, 1000, 50, 1000, 3000, 1000, 60)"
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

### `dashboard/vite.config.ts`

```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// AD-11: 프론트는 REST API로만 데이터 접근. dev proxy로 /api → FastAPI(127.0.0.1:8000)에
// 넘겨 CORS·하드코딩 URL을 피한다. 프로덕션은 리버스 프록시가 동일 경로를 담당.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: {
    environment: "jsdom",
  },
  server: {
    port: 5175,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});

```

### `dashboard/src/api/client.ts`

```ts
// REST 접근 단일 지점(AD-11). /api 프리픽스는 Vite dev proxy가 FastAPI로 넘긴다.

export interface ApiError {
  detail: unknown;
  code?: string;
  status: number;
}

export class ApiRequestError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly detail: unknown;
  constructor(e: ApiError) {
    super(typeof e.detail === "string" ? e.detail : `HTTP ${e.status}`);
    this.status = e.status;
    this.code = e.code;
    this.detail = e.detail;
  }
}

export async function apiGet<T>(path: string, params?: Record<string, unknown>): Promise<T> {
  const qs = new URLSearchParams();
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      // 미선택(undefined/null/"")은 아예 보내지 않는다 — 2.6이 빈 문자열 필터를 422로
      // 거부하므로, 프론트는 미선택을 빈 파라미터로 흘려보내지 않는다.
      if (v === undefined || v === null || v === "") continue;
      qs.append(k, String(v));
    }
  }
  const url = `/api${path}${qs.toString() ? `?${qs}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) {
    let body: { detail?: unknown; code?: string } = {};
    try {
      body = await res.json();
    } catch {
      /* 본문 없는 에러 */
    }
    throw new ApiRequestError({ detail: body.detail ?? res.statusText, code: body.code, status: res.status });
  }
  return (await res.json()) as T;
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

```

### `dashboard/src/state/filters.ts`

```ts
import { create } from "zustand";
import type { ScoreMode, ScreeningParams } from "../api/screening";

// UI 상태(필터·스코어 모드·정렬·페이지) — 서버 상태(TanStack Query)와 분리(AD-11).

const DEFAULT_SORT: Record<ScoreMode, string> = {
  valueup: "execution_score", // 이행 나쁜 순(오름차순) = 워싱 방향
  mna: "-mna_target_score", // 인수 매력 높은 순(내림차순)
};

// 시총구간 버킷(KRW 원): 대형 ≥10조 / 중형 1~10조 / 소형 <1조
export type McapBucket = "all" | "large" | "mid" | "small";
const TRILLION = 1_000_000_000_000;
export const MCAP_BOUNDS: Record<McapBucket, { min?: number; max?: number }> = {
  all: {},
  large: { min: 10 * TRILLION },
  mid: { min: 1 * TRILLION, max: 10 * TRILLION },
  small: { max: 1 * TRILLION },
};

export interface FilterState {
  scoreMode: ScoreMode;
  market?: string; // "KOSPI" | "KOSDAQ" | undefined(전체)
  sector?: string; // KSIC prefix
  mcapBucket: McapBucket;
  minRoe?: number; // %
  maxPbr?: number; // x
  maxEvEbitda?: number; // x
  maxDebtRatio?: number; // %
  washingOnly: boolean;
  buybackExecuted?: boolean;
  sort: string;
  page: number;
  size: number;
  setScoreMode: (m: ScoreMode) => void;
  setMarket: (m?: string) => void;
  setSector: (s?: string) => void;
  setMcapBucket: (b: McapBucket) => void;
  setWashingOnly: (v: boolean) => void;
  setSort: (s: string) => void;
  setPage: (p: number) => void;
  patch: (p: Partial<FilterState>) => void; // 필터류 일괄 갱신(page 1 리셋)
}

export const useFilters = create<FilterState>((set) => ({
  scoreMode: "valueup",
  mcapBucket: "all",
  washingOnly: false,
  sort: DEFAULT_SORT.valueup,
  page: 1,
  size: 20,
  // 스코어 모드 전환 시 기본 정렬을 그 모드의 관점으로 스왑 + 1페이지로(AC6)
  setScoreMode: (m) => set({ scoreMode: m, sort: DEFAULT_SORT[m], page: 1 }),
  setMarket: (market) => set({ market, page: 1 }),
  setSector: (sector) => set({ sector, page: 1 }),
  setMcapBucket: (mcapBucket) => set({ mcapBucket, page: 1 }),
  setWashingOnly: (washingOnly) => set({ washingOnly, page: 1 }),
  setSort: (sort) => set({ sort, page: 1 }),
  setPage: (page) => set({ page }),
  patch: (p) => set({ ...p, page: 1 }),
}));

// 스토어 상태 → API 파라미터(미선택은 client.ts가 걸러냄)
export function toParams(s: FilterState): ScreeningParams {
  const mcap = MCAP_BOUNDS[s.mcapBucket];
  return {
    market: s.market,
    sector: s.sector,
    min_roe: s.minRoe,
    max_pbr: s.maxPbr,
    max_ev_ebitda: s.maxEvEbitda,
    max_debt_ratio: s.maxDebtRatio,
    min_market_cap: mcap.min,
    max_market_cap: mcap.max,
    washing_only: s.washingOnly || undefined,
    buyback_executed: s.buybackExecuted,
    sort: s.sort,
    page: s.page,
    size: s.size,
  };
}

export { DEFAULT_SORT };

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

### `dashboard/src/components/FilterPanel.tsx`

```tsx
import { useState } from "react";
import { useFilters, type McapBucket } from "../state/filters";

// UX-DR1: 시장·업종·시총구간·지표 슬라이더·워싱 토글·스코어 모드 전환 — 전부 실배선
// (3.3 리뷰 반영: 가짜 컨트롤 금지, 모든 조작이 /screening 재요청으로 이어진다).

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2.5">
      <div className="text-[11px] font-semibold text-gray-500">{title}</div>
      {children}
    </div>
  );
}

// KSIC 2자리 prefix 옵션(sector = DART induty_code 원문, 2.7 버킷 택소노미와 동일 단위)
const SECTOR_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "", label: "전체" },
  { value: "20", label: "화학 (20)" },
  { value: "21", label: "제약 (21)" },
  { value: "24", label: "금속 (24)" },
  { value: "26", label: "전자·반도체 (26)" },
  { value: "30", label: "자동차 (30)" },
  { value: "35", label: "전기·가스 (35)" },
  { value: "58", label: "출판·게임 (58)" },
  { value: "63", label: "정보서비스 (63)" },
  { value: "64", label: "금융 (64)" },
  { value: "65", label: "보험 (65)" },
];

const MCAP_OPTIONS: Array<{ value: McapBucket; label: string }> = [
  { value: "all", label: "전체" },
  { value: "large", label: "대형 (10조↑)" },
  { value: "mid", label: "중형 (1~10조)" },
  { value: "small", label: "소형 (1조↓)" },
];

// 실동작 슬라이더: 드래그 중엔 로컬 값만, 놓는 순간(commit) 스토어 반영 → 재요청.
// (onChange마다 커밋하면 드래그 한 번에 요청 수십 발 — 커밋 시점 분리)
function RangeFilter({
  label,
  unit,
  min,
  max,
  step,
  value,
  onCommit,
}: {
  label: string;
  unit: string;
  min: number;
  max: number;
  step: number;
  value?: number;
  onCommit: (v?: number) => void;
}) {
  const [local, setLocal] = useState<number | undefined>(value);
  const active = local !== undefined;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-gray-700">{label}</span>
        <span className="flex items-center gap-1.5 text-[11px] text-gray-500">
          {active ? `${local}${unit}` : "전체"}
          {active && (
            <button
              onClick={() => {
                setLocal(undefined);
                onCommit(undefined);
              }}
              className="text-gray-400 underline"
            >
              해제
            </button>
          )}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={local ?? min}
        onChange={(e) => setLocal(Number(e.target.value))}
        onPointerUp={() => onCommit(local)}
        onKeyUp={() => onCommit(local)}
        className="h-1 w-full accent-emerald-600"
      />
    </div>
  );
}

export function FilterPanel() {
  const f = useFilters();

  return (
    <aside className="flex w-[300px] shrink-0 flex-col gap-5 bg-white p-5">
      <div>
        <div className="text-base font-bold leading-tight">밸류업 워싱</div>
        <div className="text-base font-bold leading-tight">스크리너</div>
        <div className="mt-0.5 text-[11px] text-gray-400">KOSPI · 애널리스트용</div>
      </div>

      {/* 스코어 모드 전환(UX-DR1 핵심) */}
      <Section title="스코어 모드">
        <div className="flex gap-0.5 rounded-lg bg-gray-100 p-0.5">
          {(["valueup", "mna"] as const).map((m) => (
            <button
              key={m}
              onClick={() => f.setScoreMode(m)}
              className={`flex-1 rounded-md py-2 text-xs font-semibold transition ${
                f.scoreMode === m ? "bg-emerald-600 text-white" : "text-gray-500"
              }`}
            >
              {m === "valueup" ? "Value-up" : "M&A"}
            </button>
          ))}
        </div>
      </Section>

      <Section title="시장">
        {(["KOSPI", "KOSDAQ"] as const).map((mk) => {
          const active = f.market === mk;
          return (
            <label key={mk} className="flex cursor-pointer items-center gap-2">
              <input
                type="radio"
                name="market"
                checked={active}
                onChange={() => f.setMarket(active ? undefined : mk)}
                className="accent-emerald-600"
              />
              <span className="text-[13px] text-gray-700">{mk}</span>
            </label>
          );
        })}
        <button onClick={() => f.setMarket(undefined)} className="self-start text-[11px] text-gray-400 underline">
          전체
        </button>
      </Section>

      <Section title="업종">
        <select
          value={f.sector ?? ""}
          onChange={(e) => f.setSector(e.target.value || undefined)}
          className="rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-[13px] text-gray-700"
        >
          {SECTOR_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </Section>

      <Section title="시총 구간">
        <select
          value={f.mcapBucket}
          onChange={(e) => f.setMcapBucket(e.target.value as McapBucket)}
          className="rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-[13px] text-gray-700"
        >
          {MCAP_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </Section>

      <RangeFilter label="ROE ≥" unit="%" min={0} max={30} step={1} value={f.minRoe} onCommit={(v) => f.patch({ minRoe: v })} />
      <RangeFilter label="PBR ≤" unit="x" min={0} max={5} step={0.1} value={f.maxPbr} onCommit={(v) => f.patch({ maxPbr: v })} />
      <RangeFilter label="EV/EBITDA ≤" unit="x" min={0} max={50} step={1} value={f.maxEvEbitda} onCommit={(v) => f.patch({ maxEvEbitda: v })} />
      <RangeFilter label="부채비율 ≤" unit="%" min={0} max={300} step={10} value={f.maxDebtRatio} onCommit={(v) => f.patch({ maxDebtRatio: v })} />

      {/* 워싱 토글(실동작) */}
      <button
        onClick={() => f.setWashingOnly(!f.washingOnly)}
        className="flex items-center justify-between rounded-lg px-3 py-3 text-left"
        style={{ background: f.washingOnly ? "#fee4e2" : "#fef3f2" }}
      >
        <span className="text-xs font-semibold text-red-700">⚠ 워싱 의심만 보기</span>
        <span
          className="relative h-5 w-9 rounded-full transition"
          style={{ background: f.washingOnly ? "#b42318" : "#d1d5db" }}
        >
          <span
            className="absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all"
            style={{ left: f.washingOnly ? 18 : 2 }}
          />
        </span>
      </button>
    </aside>
  );
}

```

### `dashboard/src/components/ScreenerTable.tsx`

```tsx
import { useMemo } from "react";
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
                }`}
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
              className="border-b border-gray-50"
              style={{ background: r.original.washing_flag === true ? "#fffbfa" : undefined }}
            >
              {r.getVisibleCells().map((cell) => (
                <td key={cell.id} className="px-4 py-3.5 align-middle">
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

### `dashboard/src/App.tsx`

```tsx
import { useFilters, toParams } from "./state/filters";
import { useScreening } from "./api/screening";
import { FilterPanel } from "./components/FilterPanel";
import { ScreenerTable } from "./components/ScreenerTable";

export default function App() {
  const filters = useFilters();
  const params = toParams(filters);
  const { data, isFetching, error } = useScreening(params);

  return (
    <div className="flex min-h-screen">
      <FilterPanel />
      <main className="flex-1 p-7">
        <header className="mb-4 flex items-center justify-between">
          <div>
            <h1 className="text-lg font-bold text-gray-900">종목 리스트</h1>
            <p className="text-xs text-gray-500">
              {data ? `${data.total}개 종목` : "…"} ·{" "}
              {filters.scoreMode === "valueup" ? "Value-up" : "M&A"} 모드
            </p>
          </div>
          <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs font-semibold text-gray-700">
            정렬: {filters.sort}
          </div>
        </header>
        <ScreenerTable
          rows={data?.items ?? []}
          total={data?.total ?? 0}
          loading={isFetching}
          error={error}
        />
      </main>
    </div>
  );
}

```

### `dashboard/src/state/filters.test.ts`

```ts
import { beforeEach, describe, expect, it } from "vitest";
import { DEFAULT_SORT, MCAP_BOUNDS, toParams, useFilters } from "./filters";

// zustand 스토어는 모듈 전역 — 테스트마다 초기 상태로 리셋
const initial = useFilters.getState();
beforeEach(() => useFilters.setState(initial, true));

describe("filters store (3.3 리뷰 반영)", () => {
  it("시장 변경 시 page=1 리셋", () => {
    useFilters.getState().setPage(3);
    useFilters.getState().setMarket("KOSDAQ");
    expect(useFilters.getState().page).toBe(1);
    expect(useFilters.getState().market).toBe("KOSDAQ");
  });

  it("스코어 모드 전환 시 기본 sort 스왑 + page 리셋 (AC6)", () => {
    useFilters.getState().setPage(2);
    useFilters.getState().setScoreMode("mna");
    const s = useFilters.getState();
    expect(s.sort).toBe(DEFAULT_SORT.mna); // -mna_target_score
    expect(s.page).toBe(1);
    useFilters.getState().setScoreMode("valueup");
    expect(useFilters.getState().sort).toBe(DEFAULT_SORT.valueup); // execution_score
  });

  it("사용자 정렬 후 모드 전환하면 기본 정렬로 덮인다(모드 관점 우선)", () => {
    useFilters.getState().setSort("-execution_score");
    useFilters.getState().setScoreMode("mna");
    expect(useFilters.getState().sort).toBe("-mna_target_score");
  });

  it("patch(지표 필터)도 page=1 리셋", () => {
    useFilters.getState().setPage(5);
    useFilters.getState().patch({ minRoe: 10 });
    const s = useFilters.getState();
    expect(s.page).toBe(1);
    expect(s.minRoe).toBe(10);
  });

  it("toParams: 시총 버킷 → min/max_market_cap 변환", () => {
    useFilters.getState().setMcapBucket("mid");
    const p = toParams(useFilters.getState());
    expect(p.min_market_cap).toBe(MCAP_BOUNDS.mid.min);
    expect(p.max_market_cap).toBe(MCAP_BOUNDS.mid.max);
  });

  it("toParams: washing_only=false는 undefined로(파라미터 미전송)", () => {
    const p = toParams(useFilters.getState());
    expect(p.washing_only).toBeUndefined();
    useFilters.getState().setWashingOnly(true);
    expect(toParams(useFilters.getState()).washing_only).toBe(true);
  });
});

```

### `dashboard/src/api/client.test.ts`

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { apiGet, ApiRequestError } from "./client";

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: `HTTP ${status}`,
    json: () => Promise.resolve(body),
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("apiGet (3.3 리뷰 반영)", () => {
  it("undefined/null/빈 문자열 파라미터는 전송하지 않는다(2.6 빈 필터 422 계약)", async () => {
    const fn = mockFetch(200, { items: [] });
    await apiGet("/screening", {
      market: "", // 빈 문자열 → 제거
      sector: undefined, // → 제거
      washing_only: null, // → 제거
      min_roe: 10,
      page: 1,
    });
    const url = fn.mock.calls[0][0] as string;
    expect(url).toBe("/api/screening?min_roe=10&page=1");
    expect(url).not.toContain("market");
    expect(url).not.toContain("sector");
  });

  it("숫자 0과 false는 유효값으로 전송된다(빈 값과 구분)", async () => {
    const fn = mockFetch(200, {});
    await apiGet("/x", { min_roe: 0, washing_only: false });
    const url = fn.mock.calls[0][0] as string;
    expect(url).toContain("min_roe=0");
    expect(url).toContain("washing_only=false");
  });

  it("에러 계약 {detail, code} 파싱 → ApiRequestError", async () => {
    mockFetch(400, { detail: "invalid sort field: 'x'", code: "INVALID_SORT" });
    try {
      await apiGet("/screening", { sort: "x" });
      expect.unreachable("should throw");
    } catch (e) {
      expect(e).toBeInstanceOf(ApiRequestError);
      const err = e as ApiRequestError;
      expect(err.status).toBe(400);
      expect(err.code).toBe("INVALID_SORT");
      expect(err.message).toContain("invalid sort field");
    }
  });

  it("FastAPI 422의 detail 배열(비문자열)도 크래시 없이 처리", async () => {
    mockFetch(422, {
      detail: [{ type: "date_from_datetime_parsing", loc: ["query", "as_of"] }],
      code: "VALIDATION_ERROR",
    });
    try {
      await apiGet("/screening", { as_of: "2026-02-30" });
      expect.unreachable("should throw");
    } catch (e) {
      const err = e as ApiRequestError;
      expect(err.status).toBe(422);
      expect(err.code).toBe("VALIDATION_ERROR");
      expect(Array.isArray(err.detail)).toBe(true);
      expect(err.message).toBe("HTTP 422"); // 비문자열 detail은 메시지로 캐스팅하지 않음
    }
  });

  it("본문 없는 에러(HTML 502 등)도 안전하게 throw", async () => {
    const fn = vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      statusText: "Bad Gateway",
      json: () => Promise.reject(new SyntaxError("not json")),
    });
    vi.stubGlobal("fetch", fn);
    await expect(apiGet("/x")).rejects.toBeInstanceOf(ApiRequestError);
  });
});

```

### `dashboard/src/components/badges.test.tsx`

```tsx
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

// vitest globals 미사용 시 testing-library 자동 cleanup이 비활성 — 명시적 cleanup
afterEach(cleanup);
import { MnaCell, ValueUpCell, WashingBadge } from "./badges";
import type { ScreeningRow } from "../api/screening";

// null 시각 언어(3.2 범례)의 상태 우선순위 검증 — 금칙: 빈칸·0·"아니오"로 뭉개기.

function row(partial: Partial<ScreeningRow>): ScreeningRow {
  return {
    corp_code: "00000000",
    corp_name: "테스트",
    market: "KOSPI",
    sector: "26100",
    as_of: "2026-07-13",
    roe: null,
    pbr: null,
    execution_score: null,
    washing_flag: null,
    buyback_status: null,
    buyback_executed: null,
    mna_target_score: null,
    population_basis: null,
    has_valueup_score: true,
    has_mna_score: true,
    ...partial,
  };
}

describe("WashingBadge — 3상태", () => {
  it("true → 워싱 의심", () => {
    render(<WashingBadge flag={true} />);
    expect(screen.getByText(/워싱 의심/)).toBeTruthy();
  });
  it("false → 근거 없음(강조 없음)", () => {
    render(<WashingBadge flag={false} />);
    expect(screen.getByText("근거 없음")).toBeTruthy();
  });
  it('null → "판단 불가"(빈칸/"아니오" 금지)', () => {
    render(<WashingBadge flag={null} />);
    expect(screen.getByText("판단 불가")).toBeTruthy();
    expect(screen.queryByText("아니오")).toBeNull();
  });
});

describe("ValueUpCell — 미집계 vs 산출불가 vs 값", () => {
  it("has_valueup_score=false → 미집계(점수 null이어도 산출불가 아님)", () => {
    render(<ValueUpCell row={row({ has_valueup_score: false, execution_score: null })} />);
    expect(screen.getByText("미집계")).toBeTruthy();
  });
  it("row 있음 + score null → — (0으로 표시 금지)", () => {
    render(<ValueUpCell row={row({ execution_score: null })} />);
    expect(screen.getByText("—")).toBeTruthy();
    expect(screen.queryByText("0")).toBeNull();
  });
  it("값 있으면 숫자 표시", () => {
    render(<ValueUpCell row={row({ execution_score: 85 })} />);
    expect(screen.getByText("85")).toBeTruthy();
  });
});

describe("MnaCell — 상태 우선순위: 미집계 > 미지원업종 > 산출불가 > 값", () => {
  it("has_mna_score=false가 최우선(금융주라도 미집계)", () => {
    render(<MnaCell row={row({ has_mna_score: false, sector: "64110" })} />);
    expect(screen.getByText("미집계")).toBeTruthy();
    expect(screen.queryByText("미지원 업종")).toBeNull();
  });
  it("KSIC 64~66 + null → 미지원 업종(개별 산출불가가 아니라 업종 안내)", () => {
    render(<MnaCell row={row({ sector: "65121", mna_target_score: null })} />);
    expect(screen.getByText("미지원 업종")).toBeTruthy();
  });
  it("비금융 + null → 산출 불가(0점/최하위 금지)", () => {
    render(<MnaCell row={row({ sector: "26100", mna_target_score: null })} />);
    expect(screen.getByText("산출 불가")).toBeTruthy();
    expect(screen.queryByText("0.0")).toBeNull();
  });
  it("값 있으면 점수 + population_basis chip", () => {
    render(<MnaCell row={row({ mna_target_score: 71.1, population_basis: "market_fallback" })} />);
    expect(screen.getByText("71.1")).toBeTruthy();
    expect(screen.getByText("전체시장 폴백")).toBeTruthy();
  });
  it("sector null(미분류) + null → 산출 불가(미지원으로 오판하지 않음)", () => {
    render(<MnaCell row={row({ sector: null, mna_target_score: null })} />);
    expect(screen.getByText("산출 불가")).toBeTruthy();
  });
});

```
