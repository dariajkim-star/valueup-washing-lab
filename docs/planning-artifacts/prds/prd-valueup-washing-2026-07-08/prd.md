---
title: 밸류업 워싱 스크리너
status: final
created: 2026-07-08
updated: 2026-07-08
---

# PRD: 밸류업 워싱 스크리너
*Working title — confirm.*

## 0. Document Purpose

이 PRD는 PM·다운스트림 워크플로우(아키텍처·에픽·개발) 소유자를 위한 요구사항 문서다. 이 프로젝트는 이미 **SPEC**(`specs/spec-valueup-washing/SPEC.md`, CAP-1~10), **아키텍처 스파인**(`.../ARCHITECTURE-SPINE.md`, AD-1~10), **에픽·스토리**(`planning-artifacts/epics.md`, 3에픽/18스토리)를 갖고 있으며, 본 PRD는 그것들을 **중복하지 않고 정합되게** 상위 요구사항으로 정리한다. 기술 구현(HOW)은 아키텍처 스파인과 `addendum.md`에 있다. FR은 전역 번호(FR-1~12)로 안정 참조되며, 용어는 §3 Glossary를 정확히 따른다.

## 1. Vision

한국 밸류업 공시는 2026년 718개사로 급증해 사실상 의무화됐지만, **공시(말)와 이행(행동)은 다르다.** 목표 ROE·배당·자사주를 공시만 하고 실행하지 않는 "워싱" 기업이 존재하고, 코스닥은 저PBR 해소 초기 단계에 머문다. 기관투자자·의결권 자문·애널리스트가 실제로 원하는 것은 **계획 대비 실제 이행 갭의 정량화**다.

밸류업 워싱 스크리너는 상장사 재무·시세·매크로 데이터를 DB에 모아 SQL로 지표를 계산하고, 두 개의 상반된 IB 관점 스코어를 산출한다 — **Value-up Score**("이 회사가 스스로 가치를 올리나")와 **M&A Target Score**("남이 사갈 만한가"). 애널리스트는 화면에서 필터를 걸어 워싱 기업, 저평가 우량주, M&A 타겟을 즉시 랭킹으로 본다.

동시에 이 프로젝트는 **SQL·DB·금융 해석·시각화 역량을 계량화해 보여주는 포트폴리오 산출물**이다 — 코리아 디스카운트와 밸류업 정책을 데이터로 다뤘다고 말할 수 있는.

## 2. Target User

### 2.1 Jobs To Be Done
- (기능) 밸류업을 공시만 하고 이행하지 않는 워싱 기업을 빠르게 걸러낸다.
- (기능) 고ROE·저PBR 저평가 우량주와 M&A 인수 타겟 후보를 발굴한다.
- (기능) 코스피-코스닥 양극화와 매크로 국면을 한눈에 파악한다.
- (사회/경력) "한국 증시 저평가·밸류업 정책을 데이터로 계량화했다"를 포폴·면접에서 증명한다.

### 2.2 Non-Users (v1)
- 일반 개인투자자용 매매 도구가 아니다(매매·주문 기능 없음).
- 실시간 트레이더 대상 아님(일배치 데이터).

### 2.3 Key User Journeys

- **UJ-1. 애널리스트 민준, 워싱 기업을 걸러낸다.**
  - **페르소나+맥락:** 증권사 리서치 담당 민준, 밸류업 공시 기업 중 실제 이행 여부를 검증해야 한다.
  - **경로:** 스크리너에서 "코스피 · 진척률 50%+ · 자사주 미이행" 필터 → 종목 리스트가 Value-up Score 낮은 순으로 정렬 → 워싱 배지 종목 클릭 → "계획 vs 실제" 갭 카드 확인.
  - **클라이맥스:** 목표 ROE를 공시하고 절반 이상 기간이 지났는데 60% 미달·자사주 미이행인 기업이 상위에 뜬다.
  - **결과:** 워싱 의심 리스트를 리포트에 담는다. Realizes FR-7, FR-9.

- **UJ-2. 민준, 스코어 모드를 M&A로 바꿔 인수 타겟을 찾는다.**
  - **경로:** 스코어 모드를 Value-up→M&A로 전환 → "저평가·저부채·낮은 지분율" 필터 → M&A Target Score 높은 순 정렬 → 종목 상세에서 4요소(저평가·인수여력·지배구조·매크로) 분해 확인.
  - **클라이맥스:** EV/EBITDA 낮고 순현금 많고 최대주주 지분 낮은 기업이 상위에 뜬다.
  - **결과:** M&A 타겟 후보군을 도출한다. Realizes FR-8, FR-9.

## 3. Glossary

- **밸류업 공시** — 상장사가 DART에 제출하는 "기업가치제고계획"(목표 ROE·배당성향·PBR·목표기간·자사주계획).
- **워싱(washing)** — 밸류업을 공시했으나 실제 이행하지 않는 상태. 판정: 진척률 ≥ 0.5 & 달성률 < 0.6 & 자사주 미이행.
- **Value-up Score** — 밸류업 계획 대비 실제 이행 정도를 0~100으로 나타낸 실행점수(execution_score).
- **M&A Target Score** — 인수 매력도를 저평가·인수여력·지배구조·매크로 4요소 가중합으로 0~100 산출한 점수.
- **달성률(achievement_rate)** — 실제 지표 / 목표 지표.
- **진척률(progress_rate)** — 목표기간 경과 비율(as_of 기준), 0~1.
- **EV/EBITDA** — (시가총액 + 순부채) / (영업이익 + 감가상각비).
- **corp_code** — DART 8자리 기업 고유코드. 전 데이터의 정식 엔티티 키.
- **as_of** — 스코어 산출 기준일. 진척률 계산의 "오늘".

## 4. Features

### 4.1 데이터 파이프라인 (수집·적재)
**Description:** DART·KRX·ECOS 3개 소스에서 상장사 재무·시세·공시·지분구조와 매크로 지표를 수집해 PostgreSQL에 멱등 적재한다. 소스별 어댑터가 각자 맡은 원천 테이블만 기록한다. Realizes UJ-1, UJ-2.

**Functional Requirements:**

#### FR-1: 밸류업 계획공시 수집
애널리스트는 DART 밸류업 공시의 목표치를 구조화 데이터로 확보할 수 있다.
**Consequences (testable):**
- 공시를 넣으면 목표 ROE·배당성향·PBR·목표기간·자사주계획이 컬럼으로 저장된다.
- 수치 추출 실패 필드는 null, 공시 원문은 보존된다.

#### FR-2: 재무·시세 수집
애널리스트는 분기 재무제표(EBITDA·순부채·배당 포함)와 일별 시세(종가·거래량·거래대금·시총)를 확보할 수 있다.
**Consequences (testable):**
- 재무는 (corp_code, year, quarter), 시세는 (corp_code, date) 자연키로 멱등 적재된다.
- 시가총액 단일원천은 시세 데이터다.

#### FR-3: 매크로 지표 수집 (ECOS)
애널리스트는 기준금리·국고채3년·원달러환율·경기선행지수를 시계열로 확보할 수 있다.
**Consequences (testable):**
- (indicator, date) 자연키로 시계열 적재되고, 결측 구간은 null이다.

#### FR-4: 지분구조 수집
애널리스트는 최대주주 지분율·자사주 비중을 확보할 수 있다.
**Consequences (testable):**
- (corp_code, as_of) 자연키로 적재되고, 미공시 종목은 null이다.

**Notes:** `[NOTE FOR PM]` 밸류업 목표치가 범위·서술형으로 공시된 경우 정규화 규칙 미확정(§8 Open Q1).

### 4.2 밸류에이션 지표 (SQL 계산)
**Description:** 수집된 원천 데이터로 밸류에이션 지표를 **DB SQL VIEW**로 즉석 계산한다. 애플리케이션 코드가 아니라 SQL이 지표를 계산한다(포폴 SQL 역량 핵심).

**Functional Requirements:**

#### FR-5: 밸류에이션 지표 계산
애널리스트는 ROE·ROA·PBR·PER·EV/EBITDA·부채비율·배당성향·YoY 성장률을 조회할 수 있다.
**Consequences (testable):**
- 뷰 조회 시 최신 주가 기준으로 지표가 계산되어 반환된다.
- YoY는 전년동기(4분기 전) 대비, EV/EBITDA는 (시총+순부채)/EBITDA로 산출되고, 0 나눗셈은 방어된다.

### 4.3 스코어링 (Value-up + M&A)
**Description:** 상반된 두 관점의 스코어를 산출한다. Value-up은 밸류업 이행 갭, M&A는 인수 매력. 임계치·가중치는 설정으로 튜닝 가능. Realizes UJ-1, UJ-2.

**Functional Requirements:**

#### FR-6: Value-up 갭 스코어링
애널리스트는 계획 대비 달성률·진척률·실행점수(0~100)를 확보할 수 있다.
**Consequences (testable):**
- as_of 기준으로 종목별 execution_score가 산출된다.
- 가중치를 설정에서 바꾸면 점수가 그에 따라 변한다.

#### FR-7: 워싱 플래그 판정
애널리스트는 공시만 하고 이행하지 않은 기업을 식별할 수 있다. Realizes UJ-1.
**Consequences (testable):**
- "진척률 ≥ 0.5 & 달성률 < 0.6 & 자사주 미이행"인 종목만 워싱으로 표시된다.

#### FR-8: M&A Target Score 산출
애널리스트는 인수 매력도를 4요소 점수로 확보할 수 있다. Realizes UJ-2.
**Consequences (testable):**
- 저평가·인수여력·지배구조·매크로를 시장 내 백분위로 정규화·가중합(0.35/0.25/0.25/0.15)해 0~100으로 산출된다.
- 요소별 점수 분해가 함께 제공된다.

### 4.4 스크리너 API
**Description:** 지표·스코어를 필터·정렬·페이지네이션 가능한 REST API로 제공한다. 목록 응답은 일관된 봉투 형식을 따른다.

**Functional Requirements:**

#### FR-9: 랭킹·스크리닝 API
애널리스트는 갭분석·워싱랭킹·M&A랭킹·다중조건 스크리닝을 API로 받을 수 있다. Realizes UJ-1, UJ-2.
**Consequences (testable):**
- 시장·업종·지표·스코어 범위 필터와 정렬·페이지네이션이 동작한다.
- OpenAPI 문서가 자동 생성된다.

#### FR-10: 시장·매크로 통계 API
애널리스트는 시장·시총구간별 평균지표·워싱비율·매크로 지표·헤드라인 KPI를 받을 수 있다.
**Consequences (testable):**
- 시장(KOSPI/KOSDAQ)별 집계와 최신 매크로 지표가 반환된다.

### 4.5 시각화 UX (Figma · Tableau)
**Description:** 실제 금융 플랫폼처럼 인터랙티브한 애널리스트 스크리너를 Figma로 디자인·구현하고, Tableau로 시장 인사이트 대시보드를 제작한다.

**Functional Requirements:**

#### FR-11: 애널리스트 스크리너 UI
애널리스트는 화면에서 필터링하고 종목 상세·투자 포인트를 볼 수 있다. Realizes UJ-1, UJ-2.
**Consequences (testable):**
- 필터 패널·종목 리스트·종목 상세·투자 포인트 카드가 동작하고, 스코어 모드(Value-up↔M&A)를 전환할 수 있다.
- 리스트→상세 클릭 흐름이 프로토타입으로 연결된다.

#### FR-12: Tableau 대시보드
애널리스트는 밸류업 점수·업종별 저평가 맵·ROE-PBR 산점도·배당/자사주 현황과 매크로 레이어를 볼 수 있다.
**Consequences (testable):**
- Tableau가 PostgreSQL에 연결되어 4개 뷰 + 매크로 레이어가 구성된다.

## 5. Non-Goals (Explicit)
- 사용자 인증·계정 관리를 하지 않는다(내부 도구).
- 실시간 시세 스트리밍을 하지 않는다(일배치).
- 공시 원문 LLM 요약·자연어 해석을 하지 않는다(v2 백로그).
- 매매·주문·자금이체 등 실행 기능을 하지 않는다(분석 전용).

## 6. MVP Scope

### 6.1 In Scope
- DART·KRX·ECOS 수집 파이프라인, SQL VIEW 지표, Value-up·M&A 스코어, 스크리너 API, Figma UI, Tableau 대시보드.

### 6.2 Out of Scope for MVP
- 인증/권한 — 내부 도구라 불필요. `[NOTE FOR PM]` 외부 공개 시 재검토.
- 공시 목표치 정성 텍스트의 LLM 해석 — v2.
- 실시간/장중 데이터 — 일배치로 충분.

## 7. Success Metrics

**Primary**
- **SM-1**: 워싱 탐지 동작성 — "진척률 50%+ & 자사주 미이행" 필터가 워싱 종목을 execution_score 낮은 순으로 정확히 랭킹한다. Validates FR-7, FR-9.
- **SM-2**: SQL 계량화 증명 — ROE·PBR·EV/EBITDA·YoY가 SQL VIEW(윈도우 함수)로 계산되어 `/metrics`로 조회된다. Validates FR-5.

**Secondary**
- **SM-3**: 두 스코어 공존 — 같은 데이터에서 Value-up·M&A 스코어가 모두 산출되고 화면에서 모드 전환된다. Validates FR-6, FR-8, FR-11.
- **SM-4**: 시각화 완성 — Figma 인터랙티브 프로토타입 + Tableau 대시보드가 실제 데이터에 물린다. Validates FR-11, FR-12.

**Counter-metrics (do not optimize)**
- **SM-C1**: 지표 커버리지를 늘리려 데이터 정확도를 희생하지 말 것 — 결측은 null로 두고 억지 추정 금지. Counterbalances SM-2.
- **SM-C2**: 워싱 탐지율을 높이려 임계치를 과하게 낮춰 오탐을 늘리지 말 것. Counterbalances SM-1.

## 8. Open Questions
1. 밸류업 목표치가 범위·서술형으로 공시된 경우 정규화 규칙(중앙값? 하한? 수동 태깅?) — FR-1 파싱 정확도에 영향.
2. 분기 실적 발표 시차를 진척률(as_of)에 어떻게 반영할지 — FR-6.
3. M&A Score의 시장 내 백분위 정규화 기준(전체 시장 vs 업종 내) 확정 — FR-8.

## 9. Assumptions Index
- §2.1 — 주 사용자는 단일 애널리스트 롤(멀티 스테이크홀더 아님).
- §7 — 성공지표는 상용 KPI가 아니라 포폴/데모 동작성 기준.
- §4.5 — Figma는 디자인+인터랙티브 프로토타입, 코드 프론트 연동까지 범위.
