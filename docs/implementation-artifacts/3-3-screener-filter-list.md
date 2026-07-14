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
- 이 스토리는 **필터·리스트만**(상세=3.4, Tableau=3.5). [재리뷰 정정] 1차 계획은 "백엔드 무변경(순수 소비)"이었으나 1차 리뷰 반려로 `/screening` 확장이 편입됨 — 최종적으로 백엔드도 변경됨. pytest 이력: 1차 구현 221(불변, 계획대로) → 2차(1차 리뷰 반영) 224 → 3차(재리뷰 반영) 228.

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

### Review Findings — 3차 검증 (code review 2026-07-13, GPT — High 0·Med 3·Low 2, Dismiss/Accept 4)

- [x] [Accept] **look-ahead defer 유지 논리 타당** — GPT가 명시적으로 동의(달력 휴리스틱을 screening에만 넣으면 gap/mna/stats와 규칙 분기, 완전 해결은 available_at 수집). 잔여 지적 1건 반영: `repositories/screening.py` 응답 조립부에 남아있던 "look-ahead 안전 최신 지표" 주석을 "부분 차단"으로 정정(docstring은 이미 정정했었으나 인라인 주석 1곳 누락).
- [x] [Patch][Med] **미설정 슬라이더 가드가 완전한 no-op이 아니었음** — 2차 수정(`local===undefined?undefined:v`)이 여전히 `onCommit(undefined)`를 호출해 부모의 `patch()`가 아무것도 안 건드렸는데 `page`를 1로 리셋시킴. `interacted` ref로 재설계: change 이벤트 없이는 커밋 함수가 **호출 자체를 스킵**(undefined 커밋조차 안 함). 테스트를 `call[0] toBeUndefined`(느슨, 호출 자체는 허용)에서 `not.toHaveBeenCalled()`(엄격)로 교체.
- [x] [Patch][Med] **미설정 상태에서 슬라이더 최솟값을 명시 선택 불가** — `interacted` ref가 "change로 실제 조작했는가"를 값 자체와 분리해 판별하므로 동일 수정으로 해소(값이 이미 min과 같아도 change가 발생했다면 interacted=true → 커밋됨). 마우스만으로 값 이동 없이 정확히 min 위치를 클릭하는 극단적 경우는 여전히 onChange 자체가 안 뜨는 브라우저 네이티브 한계(GPT 제안 코드도 동일 한계) — 키보드(화살표)로는 항상 가능.
- [x] [Patch][Med] **pointerup 이후 blur로 중복 커밋** — `interacted` ref를 커밋 직후 즉시 false로 리셋해 동일 상호작용의 후속 종료 이벤트(blur 등)가 재커밋하지 않도록 함. 테스트로 고정(pointerup→blur 시퀀스가 정확히 1회만 커밋).
- [x] [Patch][Low] **pointercancel 미테스트** — 구현은 있었으나 테스트 누락. 추가.
- [x] [Patch][Low] **placeholder 배너가 opacity 아래 흐려짐 + 헤더 total이 이전 조건 값 유지** — 배너를 opacity 래퍼 밖으로 이동(또렷하게 유지), 헤더는 `isPlaceholderData`일 때 total 대신 "새 조건 계산 중…" 표시(이전 조건 숫자를 새 조건 결과처럼 보여주지 않음 — 이 프로젝트의 null 정직성 원칙과 동일 이유).
- [x] [Patch][Low] **문서 잔여 모순** — "백엔드 무변경·221 불변" 문구가 활성 섹션(아키텍처 가드레일·1차 Completion Notes)에 그대로 남아있던 것을 정정 + pytest 이력 명시(1차 221→2차 224→3차 228).
- 리뷰어 Accept 판정(추가 조치 불필요): 시총 버킷 경계(중복·빈구간 없음), 2단계 IN 필터의 COUNT/페이지네이션 정합, query key 구성, AC6 강조 컬럼 컬럼id 매칭.
- **라이브 재검증**: 미설정 슬라이더 2개를 Tab으로 통과 → 네트워크 요청 0건 추가(완전 no-op 실증). 정상 슬라이더 조작(min_roe=15) → 요청 1건만 발생.

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
- [1차 시점 기준] 백엔드 코드 무변경(순수 소비) → 기존 221 pytest 불변. **(이후 갱신됨 — 위 [재리뷰 정정] 배너 및 아키텍처 가드레일 섹션 참조: 최종 228 pytest, 백엔드도 변경됨)**
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
- 2026-07-13: **3차 검증**(Changes Requested, High0·Med3·Low2, Accept4) — look-ahead defer 유지 논리는 명시적으로 Accept(잔여 주석 1곳만 정정). 슬라이더 재설계(`interacted` ref로 완전 no-op·최솟값 명시선택·중복커밋 3건 동시 해소 — 근본원인이 같아 한 번에 수정), placeholder 배너/헤더 정합(배너는 opacity 밖, 헤더는 계산중 표시로 이전값 은폐 방지), pointercancel 테스트 추가, 문서 잔여 모순 정정. vitest **32 passed**·백엔드 228 유지(주석만 변경)·tsc clean. 라이브 재검증: 미설정 슬라이더 Tab 통과 시 네트워크 요청 0건(완전 no-op 실증). Status: done 유지.
