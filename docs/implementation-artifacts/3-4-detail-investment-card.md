---
baseline_commit: d1a5788
---

# Story 3.4: 종목 상세 & 투자 포인트 카드

Status: done

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

### Review Findings (code review 2026-07-13, GPT — High 3·Med 3·Low 2, 수용 7.5/기각 0.5)

- [x] [Patch][High] **as_of 시점 혼합** — 4개 API가 각자의 최신일로 조회돼 서로 다른 기준일 데이터가 한 화면·한 태그 세트에 합성될 수 있었음. **리뷰어 처방(전 API as_of 스레딩+/metrics 확장) 대신 더 싼 해법 채택**: ① 태그의 roe/pbr을 /metrics 시계열 마지막 행이 아니라 **/screening 행(헤더와 동일 as_of, 3.3의 look-ahead 부분차단 값)에서 취득** — 3.3이 만든 단일 소스를 두고 중복 소스를 쓴 설계 실수 교정 ② gap·mna 쿼리를 `header.as_of`로 체이닝(두 API 모두 as_of 파라미터 기존재 — **백엔드 무변경**). 화면 전체가 단일 기준일로 수렴, 시계열 차트만 예외(본질이 역사). 라이브 네트워크 로그로 as_of 전달 실증.
- [x] [Patch][High] **0 falsy → "—" 세탁** — `gap.achievement_rate ? ...*100 : null`이 정상값 0%를 판단불가로 표시(1.8부터 지킨 null≠0 계약의 프론트 위반, 가장 뼈아픈 지적). 명시적 null 비교로 교체 + 0% 렌더 회귀 테스트.
- [x] [Patch][High] **API 실패를 미집계로 세탁** — 4개 쿼리의 isError 미소비로 500이 "엔진 미집계/데이터 없음"으로 보였음(2.6의 예외 세탁 지적과 같은 계열). 카드별 4상태(로딩/요청오류/성공+빈결과/성공+null포함) 분리, "미집계"는 성공+빈결과에서만.
- [x] [Patch][Med] **미지원 업종 미구분(상세)** — `isUnsupportedSector`를 badges.tsx에서 export해 MnaBreakdown 공유, 문구 분기 + 테스트.
- [x] [Patch][Med] **InvestmentPoints 상태 뭉갬** — 3상태 분리(계산중/데이터부족 판단불가/기준미충족), `hasTagBasis` 순수함수 + 테스트.
- [x] [기각 반+수용 반][Med] **딥링크 미검증 주장** — 사실관계 반박: 브라우저 navigate는 SPA 내부 이동이 아니라 주소창 풀 페이지 로드였고 Vite dev는 SPA fallback 내장(제 "새로고침 없이" 문구가 오해 유발 — 정정). 이번 라운드에 강력 새로고침 + 직접 진입 재검증 완료. 수용분: **운영 정적 호스팅의 rewrite 설정은 실재 공백** → 배포 스토리(아키텍처 Deferred "배포 envelope") 체크리스트로 기록.
- [x] [Patch][Low] **corp_code 8글자≠8자리 숫자** — `pattern=^\d{8}$` 3개 라우터 + 비숫자 422 테스트 6종. (반영 중 sed가 백슬래시를 삼켜 `^d{8}$`가 되는 사고를 즉시 발견·수정 — 정규식 sed 주의.)
- [x] [Patch][Low] **null 갭 빨간색** — null은 중립 회색(#9ca3af), 부정 신호로 오독 방지 + 색상 테스트.

### 2차 검증 (리뷰 반영 후 — 라이브 valueup.db)

- 신한금융지주(00382199) 딥링크 직접 진입 + **강력 새로고침** → 정상 렌더(리뷰어 #6 필수 검증).
- **미지원 업종 문구 상세 표시**: "미지원 업종 — 현재 M&A 스코어 산식 적용 대상이 아닙니다(은행·보험 등)".
- **as_of 체이닝 네트워크 실증**: `gap-analysis?corp_code=00382199&as_of=2026-07-13`·`mna/ranking?...&as_of=2026-07-13` — 헤더 기준일이 명시 전달됨.
- 태그 정확성: 신한은 roe/pbr null → 저PBR 태그 미생성, buyback retired만 태깅(null 미태깅 원칙 실증).
- corp_code=abcdefgh → 422 {detail,code} 라이브 확인.
- 백엔드 **231 passed**(테스트 강화, 수량 불변), 프론트 vitest **56 passed**(+12), tsc clean.

## Dev Agent Record

### Agent Model Used

claude-sonnet-5 (bmad-create-story + 인라인 구현) / claude-fable-5 (리뷰 triage·반영)

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
- 2026-07-13: **GPT 리뷰**(Changes Requested, High3·Med3·Low2) triage·반영 — as_of 시점 혼합은 리뷰어 처방(전 API 스레딩+/metrics 확장) 대신 백엔드 무변경 해법(태그 소스를 /screening으로 단일화 + gap/mna를 header.as_of 체이닝) 채택. 0 falsy 세탁·에러 세탁·미지원업종 구분·3상태·corp_code 숫자 패턴·null 색상 전부 patch, 딥링크 미검증 주장은 사실관계 반박(운영 rewrite는 배포 defer 기록). 백엔드 231·프론트 56 passed, 라이브 재검증(강력 새로고침·as_of 네트워크 실증·미지원 문구). Status → done.
