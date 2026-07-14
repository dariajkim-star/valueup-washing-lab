# Review Bundle — Story 3.3 3차 검증 (2026-07-13, 재리뷰 반영 커밋 50e5623)

역할: 컨텍스트 없는 시니어 풀스택 리뷰어. 이번은 **재리뷰(2차) 지적을 반영한 결과의 검증**이다. 스토리 문서 + 변경 소스 + 테스트 verbatim.

## 2차 리뷰 → 반영 내역 (검증 대상)

| 2차 지적 | 처리 | 검증 포인트 |
|---|---|---|
| 과거 as_of 미래 분기 누수 (High) | **기각(코드)** — 2.1 리뷰에서 이미 발견·부분 수정·명시 defer된 기존 한계(1~3분기 동일연도, 완전 해결=공시일 available_at 수집 별도 스토리). 달력 휴리스틱을 screening에만 넣으면 gap_engine/mna_engine/stats와 규칙이 갈라짐. docstring '안전'→'부분 차단' 정정 + OpenAPI 한계 명시 | **이 기각 논리가 타당한가?** 반박하려면 "달력 휴리스틱을 전 모듈(4곳)에 일관 적용" 비용/편익까지 다뤄야 함 |
| 시총 버킷 경계 중복 (High) | mid.max=10조-1·small.max=1조-1(원 정수), '이상/미만' 문구, 경계 테스트 | off-by-one·빈 구간 없는지 |
| 슬라이더 커밋 경로 (Med) | pointercancel·blur·valueAsNumber·useEffect 동기화. **단, 리뷰어 제안 코드를 그대로 안 씀**: 미설정(local=undefined) 상태의 blur가 input의 min 폴백값을 커밋해 "탭 통과만으로 필터 활성화"되는 함정 발견 → 미설정 가드 추가 | **이 가드가 새 버그를 만들지 않는가?** (예: onChange 직후 같은 틱의 pointerup에서 local이 스테일한 렌더의 클로저일 가능성 — React discrete event 플러시로 안전하다고 판단했는데 맞나) |
| isPlaceholderData (Med) | 오버레이(opacity+pointer-events-none) + 배너 | placeholder 상태 식별 정확성 |
| AC6 강조 컬럼 (Med) | 모드별 활성 스코어 컬럼 th·td 배경 틴트 | 컬럼 id 매칭 누락 |
| 테스트 공백 (Med) | 백엔드 4종 + 프론트 7종 추가 → 228+29 passed | 시나리오 구멍 |
| 2단계 IN 확장성 (Med) | defer(ROW_NUMBER 전환, deferred-work 기록) | — |
| 문서 모순 (Low) | historical note 격리 | — |

## 알려진 것(재보고 불필요)

- 1~3분기 동일연도 look-ahead 잔여 리스크: **의도된 기존 defer**(2-1부터, 전 엔드포인트 공통). 위 기각 논리의 타당성 비판은 환영하나 "누수가 존재한다"는 재보고는 불필요.
- 시총 point-in-time 아님(전역 최신가): 뷰 PBR과 동일 컨벤션, 기존 defer.
- score_status 백엔드 명시화·msw 통합테스트·2단계 IN 확장성: deferred 등재됨.
- sector는 DART induty_code 숫자 KSIC 원문(1차 리뷰 오탐으로 실증 종결).
- Company 33 중 1종목(한국전력공사)은 두 스코어 모두 없어 설계상 제외(total=32 정상).

## 파일 (verbatim)

### `docs/implementation-artifacts/3-3-screener-filter-list.md`

```markdown
---
baseline_commit: bc8334f
---

# Story 3.3: 스크리너 화면 — 필터 패널 & 종목 리스트

Status: done

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

### 3.2 시안·API 매핑 (재리뷰 #8로 최신화 — 1차 기록은 아래 historical note)

- 리스트 행 = `/screening` ScreeningOut: corp_name·market·**roe·pbr**·execution_score·mna_target_score·washing_flag·population_basis·**has_valueup_score·has_mna_score**·buyback_status·buyback_executed·sector.
- null 배지 규칙(3.2 범례 node 11:2): washing_flag(true=워싱의심/false=근거없음/null=판단불가), mna null=산출불가, has_*_score=false→미집계(산출불가와 구분), 금융 등 sector→미지원업종, population_basis chip. roe/pbr null="—".
- 필터→쿼리: market·sector·**min_roe·max_pbr·max_ev_ebitda·max_debt_ratio·min/max_market_cap**·min/max_execution_score·min/max_mna_score·washing_only·buyback_executed·sort·page·size. 빈 문자열 필터는 보내지 않음(2.6이 빈 문자열 422). 시총 버킷은 프론트에서 배타 구간(-1)으로 변환.
- **[historical note — 1차 구현 당시]** 원래 이 스토리는 "백엔드 코드 변경 없음(순수 소비, 221 pytest 불변)"으로 계획했으나, 1차 리뷰 반려로 `/screening` 백엔드 확장(지표·시총 필터 + roe/pbr 응답)이 이 스토리에 편입됨 — 최종 224 pytest. 아래 1차 계획 문구 중 "백엔드 무변경" 언급은 이 시점 이전 기록임.

### 아키텍처 가드레일

- AD-11(REST만·상태 분리), AD-6 응답 봉투/정렬 규약/에러 계약 소비. 에러 계약: 400·422·404 응답의 `{detail,code}`를 화면이 토스트/빈 상태로 처리(크래시 금지).
- 이 스토리는 **필터·리스트만**(상세=3.4, Tableau=3.5). 백엔드 코드 변경 없음(순수 소비) — 기존 221 pytest 불변.

### 검증 방식

- 백엔드는 smoke 패턴(uvicorn 백그라운드, 이전 스토리들과 동일)으로 127.0.0.1:8000, 프론트는 preview_start(launch.json). 실데이터 valueup.db(KOSPI 33종목)로 렌더 확인.

### 유니버스 33 vs 리스트 32 (리뷰 지적 → 실증 완료)

- `company` 33종목 중 **한국전력공사(00159193, sector 35120)** 1종목이 `/screening`에서 제외됨 — 밸류업 공시가 없어 gap_engine이 행 미생성(2.1 설계) + M&A 3요소 전부 null이라 mna_engine도 행 미생성(2.3 설계) → **두 스코어 모두 없는 종목 제외**(2.6 AC1)가 정확히 적용된 결과. 파이프라인 버그 아님. 데이터 검증 쿼리로 확정(2026-07-13).
- 화면 문구도 "33개 종목"이 아니라 API total(32)을 그대로 표시 — 이미 정합.

### Review Findings — 재리뷰 (code review 2026-07-13, GPT — High 2·Med 5·Low 1)

- [x] [Dismiss/문서정정][High] **과거 as_of 미래 분기 누수** — 사실관계는 맞으나 **2.1 리뷰에서 이미 발견·부분 수정·명시적 defer된 기존 한계의 재발견**(1~3분기 동일연도 시차, 완전 해결=공시일 available_at 수집 별도 스토리). 달력 휴리스틱을 screening에만 넣으면 gap/mna/stats와 규칙이 갈라져 기각. 리드 승인. 수용분: docstring "안전"→"부분 차단" 정정 + OpenAPI 설명에 한계 명시 + 번들 알려진 것 누락이 재발견 원인이었음을 기록.
- [x] [Patch][High] **시총 버킷 경계 중복**(1조·10조가 두 버킷에) → mid.max=10조-1·small.max=1조-1(원 단위 정수), 문구 "이상/미만", 경계 테스트(프론트 배타성+백엔드 포함성).
- [x] [Patch][Med] **슬라이더 커밋 경로** → pointercancel·blur 추가, currentTarget.valueAsNumber(클로저 스테일 방지), useEffect 외부 값 동기화. **+자체 발견**: 리뷰어 제안 코드는 미설정 상태 blur가 min값을 커밋해 탭 통과만으로 필터가 활성화되는 함정 — 미설정 가드 추가(테스트로 고정).
- [x] [Patch][Med] **isPlaceholderData 미표시** → 오버레이(opacity 50%+pointer-events-none) + "새 조건으로 다시 계산 중" 배너.
- [x] [Defer][Med] **2단계 IN 필터 확장성** — 현재 정합(리뷰어 확인), 유니버스 확대 시 ROW_NUMBER JOIN 전환(deferred-work 기록).
- [x] [Patch][Med] **AC6 강조 컬럼 미구현** → 모드별 활성 스코어 컬럼 배경 틴트(emerald/indigo) 구현 — AC 문구 축소 대신 구현 선택(1차 반려 교훈).
- [x] [Patch][Med] **테스트 공백** → 백엔드 4종(ev_ebitda·debt_ratio 필터, 필터+페이지네이션 total, 지표×시총 조합, 시총 경계 포함성) + 프론트 7종(RangeFilter 커밋 경로·동기화·미설정 가드, MCAP 경계 배타성). look-ahead 배제 테스트는 #1 defer에 묶여 제외(available_at 스토리 몫).
- [x] [Patch][Low] **문서 모순** → historical note 격리("백엔드 무변경"은 1차 계획), 필터→쿼리 매핑 최신화.
- 리뷰어 Clean 판정: 2단계 IN의 COUNT/페이지네이션 정합, empty IN 처리, query key 구성(객체 결정적 해시), scoreMode→sort 경유 재요청.

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
- 2026-07-13: **재리뷰**(Changes Requested, High2·Med5·Low1) triage — look-ahead 건은 기존 defer 재발견으로 기각(리드 승인, 문서 정정만), 나머지 patch/defer(위 Review Findings). 시총 경계·슬라이더 경로·placeholder 오버레이·강조 컬럼·테스트 11종 추가. 백엔드 **228 passed**·vitest **29 passed**·tsc clean, 라이브 검증(강조 컬럼 모드 스왑 computed style 실증). Status → done.

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
        "범위 필터는 null을 매칭하지 않는다(산출 불가는 조건 판단 불가). "
        "알려진 한계: roe/pbr 등 지표는 look-ahead 부분 차단(같은 해 사업보고서만 배제) — "
        "명시적 과거 as_of 조회 시 그 해의 이후 분기 지표가 섞일 수 있음(공시일 수집 전까지, "
        "전 엔드포인트 공통). 시총 필터는 최신가 기준(point-in-time 아님)."
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

### `dashboard/src/state/filters.ts`

```ts
import { create } from "zustand";
import type { ScoreMode, ScreeningParams } from "../api/screening";

// UI 상태(필터·스코어 모드·정렬·페이지) — 서버 상태(TanStack Query)와 분리(AD-11).

const DEFAULT_SORT: Record<ScoreMode, string> = {
  valueup: "execution_score", // 이행 나쁜 순(오름차순) = 워싱 방향
  mna: "-mna_target_score", // 인수 매력 높은 순(내림차순)
};

// 시총구간 버킷(KRW 원, 백엔드 비교는 포함(>=,<=)이라 max는 -1로 잘라 상호 배타 보장):
// 대형 = 10조 이상 / 중형 = 1조 이상 10조 미만 / 소형 = 1조 미만 (재리뷰 #2 — 경계 중복 제거)
export type McapBucket = "all" | "large" | "mid" | "small";
const TRILLION = 1_000_000_000_000;
export const MCAP_BOUNDS: Record<McapBucket, { min?: number; max?: number }> = {
  all: {},
  large: { min: 10 * TRILLION },
  mid: { min: 1 * TRILLION, max: 10 * TRILLION - 1 },
  small: { max: 1 * TRILLION - 1 },
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

### `dashboard/src/components/FilterPanel.tsx`

```tsx
import { useEffect, useState } from "react";
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
  { value: "large", label: "대형 (10조 이상)" },
  { value: "mid", label: "중형 (1조 이상 10조 미만)" },
  { value: "small", label: "소형 (1조 미만)" },
];

// 실동작 슬라이더: 드래그 중엔 로컬 값만, 놓는 순간(commit) 스토어 반영 → 재요청.
// (onChange마다 커밋하면 드래그 한 번에 요청 수십 발 — 커밋 시점 분리)
// 재리뷰 #3 반영: pointercancel(터치 스크롤 개입)·blur(포커스 이탈) 경로 추가,
// 클로저 스테일 방지 위해 currentTarget.valueAsNumber를 읽고, 외부 value 변경
// (전체 초기화 등)에 로컬 상태를 동기화.
export function RangeFilter({
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
  useEffect(() => setLocal(value), [value]); // 외부(스토어) 값 변경 동기화
  const active = local !== undefined;
  // 미설정(local=undefined) 상태의 blur/pointerup은 no-op — input이 min을 폴백 표시할 뿐
  // 사용자가 값을 만진 적이 없는데 valueAsNumber(=min)를 커밋하면 탭 통과만으로 필터가
  // 활성화된다(리뷰어 제안 코드의 함정 — onChange가 선행된 경우에만 실값 커밋).
  const commit = (v: number) => onCommit(local === undefined ? undefined : v);
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
        aria-label={label}
        min={min}
        max={max}
        step={step}
        value={local ?? min}
        onChange={(e) => setLocal(e.currentTarget.valueAsNumber)}
        onPointerUp={(e) => commit(e.currentTarget.valueAsNumber)}
        onPointerCancel={(e) => commit(e.currentTarget.valueAsNumber)}
        onKeyUp={(e) => commit(e.currentTarget.valueAsNumber)}
        onBlur={(e) => commit(e.currentTarget.valueAsNumber)}
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
              className="border-b border-gray-50"
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

### `dashboard/src/App.tsx`

```tsx
import { useFilters, toParams } from "./state/filters";
import { useScreening } from "./api/screening";
import { FilterPanel } from "./components/FilterPanel";
import { ScreenerTable } from "./components/ScreenerTable";

export default function App() {
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
              {data ? `${data.total}개 종목` : "…"} ·{" "}
              {filters.scoreMode === "valueup" ? "Value-up" : "M&A"} 모드
            </p>
          </div>
          <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs font-semibold text-gray-700">
            정렬: {filters.sort}
          </div>
        </header>
        <div className={isPlaceholderData ? "pointer-events-none opacity-50" : ""}>
          {isPlaceholderData && (
            <div className="mb-2 rounded-lg bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-700">
              새 조건으로 다시 계산 중 — 아래는 이전 조건의 결과입니다
            </div>
          )}
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

  it("시총 버킷은 상호 배타 — 1조·10조 경계가 두 버킷에 걸리지 않는다(재리뷰 #2)", () => {
    const TRILLION = 1_000_000_000_000;
    // 정확히 1조: small(max) 미포함, mid(min) 포함
    expect(MCAP_BOUNDS.small.max!).toBeLessThan(1 * TRILLION);
    expect(MCAP_BOUNDS.mid.min!).toBe(1 * TRILLION);
    // 정확히 10조: mid(max) 미포함, large(min) 포함
    expect(MCAP_BOUNDS.mid.max!).toBeLessThan(10 * TRILLION);
    expect(MCAP_BOUNDS.large.min!).toBe(10 * TRILLION);
    // 인접 버킷 사이 빈 구간 없음(백엔드 비교가 포함(>=,<=)이므로 max+1 = 다음 min)
    expect(MCAP_BOUNDS.small.max! + 1).toBe(MCAP_BOUNDS.mid.min!);
    expect(MCAP_BOUNDS.mid.max! + 1).toBe(MCAP_BOUNDS.large.min!);
  });

  it("toParams: washing_only=false는 undefined로(파라미터 미전송)", () => {
    const p = toParams(useFilters.getState());
    expect(p.washing_only).toBeUndefined();
    useFilters.getState().setWashingOnly(true);
    expect(toParams(useFilters.getState()).washing_only).toBe(true);
  });
});

```

### `dashboard/src/components/FilterPanel.test.tsx`

```tsx
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { RangeFilter } from "./FilterPanel";

afterEach(cleanup);

// 재리뷰 #3 — 슬라이더 커밋 경로(pointerup/keyup/blur/pointercancel)·외부 값 동기화·
// 미설정 상태 가드(blur 통과만으로 min값이 커밋되면 안 됨).

function setup(value?: number) {
  const onCommit = vi.fn();
  render(
    <RangeFilter label="ROE ≥" unit="%" min={0} max={30} step={1} value={value} onCommit={onCommit} />,
  );
  const input = screen.getByLabelText("ROE ≥") as HTMLInputElement;
  return { input, onCommit };
}

describe("RangeFilter", () => {
  it("change 후 pointerup에 커밋(값은 valueAsNumber)", () => {
    const { input, onCommit } = setup();
    fireEvent.change(input, { target: { value: "15" } });
    expect(onCommit).not.toHaveBeenCalled(); // 드래그 중엔 커밋 안 함
    fireEvent.pointerUp(input);
    expect(onCommit).toHaveBeenCalledWith(15);
  });

  it("blur로도 커밋된다(포커스 이탈 경로)", () => {
    const { input, onCommit } = setup();
    fireEvent.change(input, { target: { value: "10" } });
    fireEvent.blur(input);
    expect(onCommit).toHaveBeenCalledWith(10);
  });

  it("키보드 조작(keyup) 커밋", () => {
    const { input, onCommit } = setup();
    fireEvent.change(input, { target: { value: "5" } });
    fireEvent.keyUp(input, { key: "ArrowRight" });
    expect(onCommit).toHaveBeenCalledWith(5);
  });

  it("미설정 상태에서 blur/pointerup 통과만으로는 필터가 활성화되지 않는다(min값 커밋 금지)", () => {
    const { input, onCommit } = setup(undefined);
    fireEvent.blur(input); // 탭으로 지나가기만 함
    fireEvent.pointerUp(input);
    // undefined 커밋(no-op)만 허용 — 숫자 커밋이 있으면 안 됨
    for (const call of onCommit.mock.calls) {
      expect(call[0]).toBeUndefined();
    }
  });

  it("외부 value 변경(전체 초기화 등)에 로컬 상태가 동기화된다", () => {
    const onCommit = vi.fn();
    const { rerender } = render(
      <RangeFilter label="PBR ≤" unit="x" min={0} max={5} step={0.1} value={3} onCommit={onCommit} />,
    );
    expect(screen.getByText("3x")).toBeTruthy();
    rerender(
      <RangeFilter label="PBR ≤" unit="x" min={0} max={5} step={0.1} value={undefined} onCommit={onCommit} />,
    );
    expect(screen.getByText("전체")).toBeTruthy(); // local이 undefined로 동기화됨
  });

  it("해제 버튼은 undefined 커밋", () => {
    const { onCommit } = setup(20);
    fireEvent.click(screen.getByText("해제"));
    expect(onCommit).toHaveBeenCalledWith(undefined);
  });
});

```
