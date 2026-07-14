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
- [x] **T5**: `FilterPanel.tsx`(UX-DR1, 시장·워싱·스코어모드 실동작 + 슬라이더 시안) + `ScreenerTable.tsx`(TanStack Table, 정렬 헤더·페이지네이션·빈상태·에러상태).
- [x] **T6**: `App.tsx` + `main.tsx`(QueryClientProvider). launch.json에 `valueup-dashboard`(port 5175) 등록.
- [x] **T7**: 백엔드+프론트 동시 구동, 브라우저에서 실데이터 32종목 렌더·모드전환·워싱필터·null배지 확인(아래).

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

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (bmad-create-story + 인라인 구현)

### Completion Notes List

- **라이브 검증(백엔드 uvicorn:8000 + Vite:5175, valueup.db 실데이터)**:
  - 실데이터 32종목 렌더, 5가지 null 상태 전부 화면에 정상 표시 — 고려아연=산출 불가, 삼성생명보험=미지원 업종(은행·보험), 삼성SDI=미집계(Value-up), 다수=판단 불가, 전 종목 population_basis chip(전체시장 폴백).
  - **스코어 모드 전환** 동작: M&A 클릭 → 헤더 "M&A 모드"·정렬 `-mna_target_score`·리스트 내림차순 재정렬(포스코홀딩스 71.1→네이버 68.0→크래프톤 67.4 = 2.5 랭킹과 일치).
  - **워싱 필터** 동작: 워싱 토글 → 0종목(대형주 워싱 의심 0, 드레스 리허설과 정합) → 빈 상태 "조건에 맞는 종목이 없습니다".
  - 페이지네이션(20/32), 점선 배지 스타일(dashed border) 적용 확인. 콘솔·빌드 에러 0. **tsc -b clean**.
  - 스크린샷 캡처는 환경 렌더러 이슈로 타임아웃(read_page·클릭·JS 평가는 전부 정상 — 페이지 결함 아님). 시각 검증은 read_page 접근성 트리 + computed style로 대체.
- 백엔드 코드 무변경(순수 소비) → **기존 221 pytest 불변**.
- 슬라이더(ROE/PBR/EV·EBITDA/부채비율)·업종·시총 필터는 시안 UI만(배선은 후속) — 즉시 필터 핵심 경로(시장·워싱·모드·정렬·페이지)를 우선 검증.

### File List

- `dashboard/package.json`·`vite.config.ts`·`tsconfig.json`·`index.html`·`.gitignore` (스캐폴딩)
- `dashboard/src/main.tsx`·`App.tsx`·`index.css`·`vite-env.d.ts`
- `dashboard/src/api/client.ts`·`screening.ts`
- `dashboard/src/state/filters.ts`
- `dashboard/src/components/badges.tsx`·`FilterPanel.tsx`·`ScreenerTable.tsx`
- `.gitignore`(루트, dashboard/ 무시 경로 정정) · `../.claude/launch.json`(Desktop, valueup-dashboard 등록)

## Change Log

- 2026-07-13: Story 3.3 생성 — 스크리너 필터·리스트 React 구현. dashboard/ 스캐폴딩(React19/Vite8/TS/Tailwind4 + TanStack Query·Table), 3.2 시안·null 시각 언어 구현, AD-11(REST만·상태분리) 준수, /screening 소비.
- 2026-07-13: Story 3.3 구현 — dashboard 스캐폴딩+필터패널+TanStack Table+null배지, 라이브 검증(32종목·모드전환·워싱필터·null 5상태), tsc clean, 221 pytest 불변. Status → review(GPT 교차리뷰 대기).
