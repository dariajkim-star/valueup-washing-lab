---
stepsCompleted: [step-01-document-discovery, step-02-prd-analysis, step-03-epic-coverage-validation, step-04-ux-alignment, step-05-epic-quality-review, step-06-final-assessment]
documentsAssessed:
  - planning-artifacts/prds/prd-valueup-washing-2026-07-08/prd.md
  - planning-artifacts/prds/prd-valueup-washing-2026-07-08/addendum.md
  - specs/spec-valueup-washing/SPEC.md
  - specs/spec-valueup-washing/db-schema.md
  - specs/spec-valueup-washing/scoring.md
  - specs/spec-valueup-washing/stack.md
  - planning-artifacts/architecture/architecture-valueup-washing-2026-07-08/ARCHITECTURE-SPINE.md
  - planning-artifacts/epics.md
---

# Implementation Readiness Assessment Report

**Date:** 2026-07-08
**Project:** 밸류업 워싱 스크리너

## Step 1 — Document Discovery (재실행, PRD 포함)

| 문서 유형 | 파일 | 상태 |
|---|---|---|
| PRD | planning-artifacts/prds/prd-valueup-washing-2026-07-08/prd.md (+ addendum.md) | ✅ |
| SPEC | specs/spec-valueup-washing/SPEC.md (+ db-schema, scoring, stack) | ✅ |
| Architecture | planning-artifacts/architecture/architecture-valueup-washing-2026-07-08/ARCHITECTURE-SPINE.md | ✅ |
| Epics & Stories | planning-artifacts/epics.md (3에픽/18스토리) | ✅ |
| UX | Figma MCP 연동 (UX-DR1~5는 epics.md·PRD FR-11에 내장) | ✅ |

**중복 문서:** 없음 (whole+sharded 충돌 없음, sharded 문서 없음).
**누락:** 없음 — PRD·SPEC·아키텍처·에픽 4종 완비. UX는 Figma MCP 연동 방식으로 PRD FR-11/12에 반영.

## Step 2 — PRD Analysis

### Functional Requirements (12개)
- FR-1 밸류업 계획공시 수집 (목표 ROE·배당성향·PBR·목표기간·자사주, 실패 null·원문 보존)
- FR-2 재무·시세 수집 (EBITDA·순부채·배당 / 종가·거래량·거래대금·시총, 멱등 upsert)
- FR-3 매크로 지표 수집 (ECOS 기준금리·국고채3년·환율·경기선행지수)
- FR-4 지분구조 수집 (최대주주 지분율·자사주 비중)
- FR-5 밸류에이션 지표 계산 (ROE·ROA·PBR·PER·EV/EBITDA·부채비율·배당성향·YoY, SQL VIEW)
- FR-6 Value-up 갭 스코어링 (달성률·진척률·실행점수 0~100)
- FR-7 워싱 플래그 판정 (진척≥0.5 & 달성<0.6 & 자사주 미이행)
- FR-8 M&A Target Score (저평가·인수여력·지배구조·매크로 4요소 가중합)
- FR-9 랭킹·스크리닝 API (갭분석·워싱랭킹·M&A랭킹·다중조건)
- FR-10 시장·매크로 통계 API
- FR-11 애널리스트 스크리너 UI (필터·리스트·상세·투자포인트, 스코어 모드 전환)
- FR-12 Tableau 대시보드 (4개 뷰 + 매크로 레이어)
**Total FRs: 12**

### Non-Functional Requirements (PRD 제약·비목표 + SPEC 도출)
- NFR1 지표 계산은 DB SQL VIEW 전용 (앱 계산 금지, AD-1)
- NFR2 0 나눗셈 NULLIF 방어, 지표 null 허용
- NFR3 워싱 임계치·Value-up/M&A 가중치는 config.py 튜닝 가능
- NFR4 데이터 소스 DART·KRX·ECOS 3종, 키는 .env
- NFR5 v1: 인증 없음(내부도구), 일배치(실시간 없음), LLM요약 없음, 매매 없음
**Total NFRs: 5**

### Additional Requirements
- 통합/의존: DART·KRX·ECOS 외부 API 연동, Tableau→PostgreSQL 연결, Figma MCP UX.
- 제약: corp_code(8자리) 정식 키, API 응답 봉투 {items,total,page,size}.

### PRD Completeness Assessment
PRD는 Vision·Target User(UJ 2)·Glossary·Features(FR-1~12)·Non-Goals·MVP·성공지표(+카운터메트릭)·오픈퀘스천·가정인덱스를 완비. NFR은 별도 섹션 대신 SPEC 제약·PRD 비목표에 분산 — 추적 가능. addendum에 FR↔CAP↔스토리 매핑표 존재. 완성도 양호.

## Step 3 — Epic Coverage Validation

### Coverage Matrix (PRD FR → 에픽 스토리)

| PRD FR | 요구 | 에픽 스토리 | 상태 |
|---|---|---|---|
| FR-1 | 밸류업 공시 수집 | Story 1.5 | ✓ Covered |
| FR-2 | 재무·시세 수집 | Story 1.2, 1.3 | ✓ Covered |
| FR-3 | 매크로 수집(ECOS) | Story 1.4 | ✓ Covered |
| FR-4 | 지분구조 수집 | Story 1.6 | ✓ Covered |
| FR-5 | 지표 계산(SQL VIEW) | Story 1.7 | ✓ Covered |
| FR-6 | Value-up 스코어링 | Story 2.1 | ✓ Covered |
| FR-7 | 워싱 판정 | Story 2.2 | ✓ Covered |
| FR-8 | M&A Target Score | Story 2.3 | ✓ Covered |
| FR-9 | 랭킹·스크리닝 API | Story 2.4, 2.5, 2.6 | ✓ Covered |
| FR-10 | 통계 API | Story 3.1 | ✓ Covered |
| FR-11 | 스크리너 UI | Story 3.2, 3.3, 3.4 | ✓ Covered |
| FR-12 | Tableau 대시보드 | Story 3.5 | ✓ Covered |

### Missing Requirements
- 없음 — 12/12 전부 스토리 커버.
- 역방향(에픽에 있으나 PRD에 없음): Story 1.1(스캐폴딩)은 PRD FR에 대응 없음 — 정상(인프라 셋업, 요구사항 아님).

### ⚠️ Finding F-1 (Minor, 추적성): FR 번호 체계 불일치
- **문제**: PRD는 `FR-1~12`, epics.md는 `FR1~10`(SPEC CAP 매핑 기준) — 두 문서의 FR 번호가 1:1이 아니다.
- **영향**: 개발자가 "FR6"을 볼 때 PRD의 FR-6(Value-up)인지 epics의 FR6(스크리닝 API)인지 혼동 가능.
- **완화**: addendum.md에 PRD FR ↔ SPEC CAP ↔ 스토리 크로스워크표가 이미 존재.
- **권고**: epics.md 상단에 "epics의 FR 번호는 SPEC CAP 기준, PRD FR-N과는 addendum 크로스워크 참조" 주석 1줄 추가.

### Coverage Statistics
- Total PRD FRs: 12
- FRs covered in epics: 12
- **Coverage: 100%**

## Step 4 — UX Alignment Assessment

### UX Document Status
독립 UX 문서 **없음**. 단, UI는 명백히 함의됨(PRD FR-11 스크리너 UI, FR-12 Tableau, UJ-1/UJ-2 사용자 흐름, UX-DR1~5, Figma MCP 연동). UX 요구는 PRD·epics에 내장.

### UX ↔ PRD 정합
- ✓ FR-11/12가 스크리너 UI·Tableau를 커버, UJ-1(워싱)·UJ-2(M&A)가 사용자 흐름 서술. 정합.

### UX ↔ Architecture 정합
- ✓ 백엔드는 API 계약(AD-6 응답 봉투)으로 UI에 데이터 공급 — 프론트가 API 소비하는 구조는 성립.
- ⚠️ 프론트엔드 **앱 구조 자체는 아키텍처 스파인에 없음**(Deferred). API 계약까지만 설계됨.

### ⚠️ Finding F-2 (Medium): 프론트엔드 전달 방식 미정
- **문제**: Story 3.3/3.4는 "프론트 구현"·"화면에서 조작 시 필터링"을 요구하나, **코딩된 SPA인지 Figma 인터랙티브 프로토타입인지** 전달 방식이 확정 안 됨. 아키텍처에 프론트 스택(React 등)·상태관리 결정 없음.
- **영향**: Story 3.3/3.4 착수 시 "무엇으로 만드나"가 열려 있어 구현 경로가 모호. Story 3.2(Figma)와 3.3(구현)의 경계 불명확.
- **권고**: 프론트 범위를 명시 — (a) Figma 클릭 프로토타입까지(코드 프론트 없음) 또는 (b) 경량 코딩 SPA(스택 지정). 포폴 목적이면 (a)+간단 데모 SPA 조합이 현실적. 확정 후 아키텍처 Deferred 항목 갱신 또는 프론트 미니 스파인 추가.

### Warnings
- W-1: 독립 UX 스펙(bmad-ux DESIGN/EXPERIENCE) 부재 — Figma MCP가 대체하나, 디자인 토큰·접근성 기준은 Story 3.2 수행 시 Figma에서 확정 필요.

## Step 5 — Epic Quality Review (엄격 검토)

### 에픽 구조 (가치·독립성)
| 에픽 | 사용자 가치 | 독립성 | 판정 |
|---|---|---|---|
| E1 데이터 기반 & 지표 조회 | "지표 조회 가능"(FR-5 /metrics로 완결) | standalone | ✓ (데이터 중심이나 조회 능력으로 가치 성립) |
| E2 워싱+M&A 스코어 | 두 스코어 랭킹 | E1만 사용 | ✓ |
| E3 시장인사이트+UI | 화면 탐색 | E1·E2 사용 | ✓ |
- 기술 레이어 에픽("DB 셋업"/"API 개발") 없음. 순환·전방 에픽 의존 없음.

### 스토리 품질·의존성
- 전방 의존 **없음**(각 스토리는 앞 스토리 산출물만 사용). AC는 전부 Given/When/Then·테스트 가능.
- 테이블은 필요 스토리에서 생성(1.2 company/financials, 1.3 prices, 1.4 macro, 1.5 valueup_plan, 1.6 ownership, 2.1 valueup_score, 2.3 mna_score). 선행 일괄생성 없음.
- Story 1.1(스캐폴딩)은 사용자 가치 없으나 **그린필드 셋업 스토리로 승인됨**(아키텍처가 스타터 템플릿 미지정 → 자체 스캐폴딩 정당). 위반 아님.

### ✅ Finding F-3 (Major) — RESOLVED (2026-07-08)
- **원문제**: Story 2.2(워싱 판정)가 `buyback_executed`를 입력으로 쓰나 산출 주체 미지정.
- **해소 + 강화**: 자사주를 **3단계(planned/executed/retired)**로 정교화. Story 1.2가 `buyback_retired_amount`(소각액) 추가 수집, Story 2.1 AC가 buyback_executed/buyback_retired/buyback_status 도출을 명시, Story 2.2 워싱 판정은 "NOT buyback_retired"(소각까지 안 하면 미이행)로 강화 — 2026 자사주 의무소각 정책 반영. SPEC CAP-5·scoring.md·db-schema 동기화 완료.

### 🟡 Finding F-4 (Minor): M&A 엔진 입력 지표 뷰 미노출
- **문제**: scoring.md의 M&A 산식은 `net_cash`·`ebitda_margin`을 쓰지만, `valuation_metrics` 뷰(Story 1.7)는 이 둘을 노출하지 않음(ev_ebitda·debt_ratio만).
- **영향**: Story 2.3(M&A 엔진)이 참조할 파생값이 뷰에 없어 엔진에서 재계산하거나 뷰 보강 필요 — 계산 위치 불명확(AD-1 "지표는 뷰에서" 원칙과 마찰 가능).
- **권고**: Story 1.7 뷰에 `net_cash`(cash−total_debt)·`ebitda_margin`(EBITDA/revenue) 컬럼 추가, 또는 2.3 AC에 "엔진이 원천에서 계산" 명시.

### Best Practices Compliance
- [x] 에픽 사용자 가치 · [x] 에픽 독립 · [x] 스토리 사이징 · [x] 전방 의존 없음 · [x] 테이블 적시 생성 · [x] AC 명확 · [x] FR 추적성(단, F-1 번호체계 주의)

## Summary and Recommendations

### Overall Readiness Status
**READY** (2026-07-08 갱신) — 발견 이슈 4건 전부 해소. 문서 4종(PRD·SPEC·아키텍처·에픽) 정합, FR 커버리지 100%, 프론트 스택 확정. 개발 착수 가능.

### 발견 이슈 종합 (4건 → 전부 Resolved)
| ID | 심각도 | 요약 | 상태 |
|---|---|---|---|
| F-3 | 🔴 Major | 자사주 산출 스토리 미지정 → 3단계(매입/소각) 정교화, buyback_retired·의무소각 반영 | ✅ Resolved |
| F-2 | 🟠 Medium | 프론트 전달방식 미정 → **코딩 SPA(React 19+Vite 8)** 확정, AD-11 편입 | ✅ Resolved |
| F-4 | 🟡 Minor | M&A 입력 뷰 미노출 → valuation_metrics 뷰에 net_cash·ebitda_margin 추가 | ✅ Resolved |
| F-1 | 🟡 Minor | FR 번호체계 불일치 → epics.md 상단에 크로스워크 주석 추가 | ✅ Resolved |

### Critical Issues Requiring Immediate Action
- **F-3만 실질 블로커성**: 워싱 판정(핵심 차별점)이 계산 못 하는 필드에 의존. Story 2.1 AC에 buyback_executed 도출 규칙 한 줄 추가로 해소.

### Recommended Next Steps
1. **F-3 해소**: Story 2.1 AC에 "financials.buyback_amount>0 → buyback_executed=true" 추가 (에픽 문서 1줄 수정).
2. **F-4 해소**: Story 1.7 뷰에 net_cash·ebitda_margin 컬럼 추가 (M&A 입력을 뷰로 일원화, AD-1 정합).
3. **F-2 결정**: 프론트 범위 확정 — 포폴이면 "Figma 인터랙티브 프로토타입 + 경량 데모 SPA" 권장. 아키텍처 Deferred 갱신.
4. **F-1 정리**: epics.md 상단에 FR 번호 크로스워크 주석 1줄. (선택)
5. 이후 **스프린트 계획(SP) → Story 1.1 개발** 진행.

### Final Note
이 평가는 3개 카테고리에서 **4개 이슈**를 식별했다. F-3(Major) 하나만 실질적으로 개발 흐름을 막을 수 있고, 나머지는 해당 스토리 착수 시점에 처리 가능하다. F-1~F-4는 모두 **에픽 문서 소폭 수정**으로 닫히며, 전면 재설계는 불필요하다.

**Assessor:** BMAD Implementation Readiness (Claude) · **Date:** 2026-07-08
