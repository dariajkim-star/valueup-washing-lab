---
stepsCompleted: [step-01-validate-prerequisites, step-02-design-epics, step-03-create-stories, step-04-final-validation]
inputDocuments:
  - ../specs/spec-valueup-washing/SPEC.md
  - ../specs/spec-valueup-washing/db-schema.md
  - ../specs/spec-valueup-washing/scoring.md
  - ../specs/spec-valueup-washing/stack.md
  - ./architecture/architecture-valueup-washing-2026-07-08/ARCHITECTURE-SPINE.md
---

# 밸류업 워싱 스크리너 - Epic Breakdown

## Overview

이 문서는 밸류업 워싱 스크리너의 에픽·스토리 분해다. PRD 대신 **SPEC**(CAP-1~7)과 **아키텍처 스파인**(AD-1~9)을 입력으로, 구현 가능한 스토리로 나눈다. UX는 Figma MCP로 연동(UX-DR1~5).

> **FR 번호 주의** (F-1): 이 문서의 `FR1~10`은 **SPEC CAP 매핑 기준**이다. PRD의 `FR-1~12`와는 1:1이 아니며, 크로스워크는 `prds/.../addendum.md`의 매핑표 참조.

> **개발 순서 ≠ 발표 순서** (확정)
> - **개발(빌드) 순서**: Epic 1 → 2 → 3 (데이터 → 스코어 → UI, 의존성 순). BMAD 에픽 번호는 이 순서.
> - **발표(포폴·면접) 순서**: Epic 3 → 2 → 1 (스크리너 화면 → 워싱/M&A 차별점 → SQL·데이터 원리, 결과부터).

> **2026-07-08 범위 확장 (확정)**: 데이터 소스에 **ECOS**(금리/환율/경기지표) 추가, 지표에 **EV/EBITDA** 추가, 두 번째 스코어 **M&A Target Score**(4요소) 추가, DART **지분구조** 수집 추가. 배당은 DART에서 수집(금융공공데이터 어댑터 제거) → 소스 3종(DART·KRX·ECOS). 배당성향은 내부 계산 유지.

## Requirements Inventory

### Functional Requirements

FR1: (CAP-1) DART 밸류업 계획공시에서 목표 ROE·배당성향·PBR·목표기간·자사주계획을 추출해 `valueup_plan`에 적재. 실패 필드 null, 원문 `raw_text` 보존.
FR2: (CAP-2) DART 재무제표(EBITDA·순부채·배당 포함)·KRX 시세/시총/거래대금을 수집해 `company`·`financials`·`prices`에 적재.
FR3: (CAP-3) ROE·ROA·PBR·PER·**EV/EBITDA**·부채비율·배당성향·YoY 성장률을 `valuation_metrics` SQL VIEW로 계산(최신 주가 반영).
FR4: (CAP-4) 목표 대비 달성률·진척률·Value-up 실행점수(0~100)를 산출해 `valueup_score`에 적재.
FR5: (CAP-5) 자사주 3단계(공시/매입/소각) 구분, "진척률 ≥ 0.5 & 달성률 < 0.6 & 소각 미이행(NOT buyback_retired)" 종목을 washing_flag=true로 판정(2026 의무소각 반영). buyback_status로 '매입만·미소각' 약한신호 별도.
FR6: (CAP-6) 갭분석·워싱랭킹·M&A랭킹·스크리닝·지표 REST API. 필터·정렬·페이지네이션·OpenAPI.
FR7: (CAP-7) 시장·시총구간별 평균지표·워싱비율·매크로·헤드라인 KPI 집계 API.
FR8: (신규) ECOS에서 기준금리·국고채3년·원달러환율·경기선행지수를 수집해 `macro_indicator`에 시계열 적재.
FR9: (신규) DART 지분공시에서 최대주주 지분율·자사주 비중을 수집해 `ownership`에 적재.
FR10: (신규) M&A Target Score(저평가·인수여력·지배구조·매크로 4요소 가중합, 0~100)를 산출해 `mna_score`에 적재.

### NonFunctional Requirements

NFR1: 밸류에이션 지표는 앱 코드가 아니라 DB SQL VIEW로만 계산한다(AD-1). 파이썬 지표 계산 금지.
NFR2: 0 나눗셈은 NULLIF로 방어하고 지표 null을 허용한다.
NFR3: 워싱 임계치(0.5/0.6)·Value-up 가중치(0.5/0.3/0.2)·M&A 가중치(0.35/0.25/0.25/0.15)는 config.py로 노출해 튜닝 가능해야 한다.
NFR4: 데이터소스는 **DART·KRX·ECOS 3종**. API 키는 .env(DART_API_KEY, ECOS_API_KEY).
NFR5: v1 비목표 — 인증 없음, 실시간 스트리밍 없음(일배치), 공시 LLM 요약 없음, 매매·주문 기능 없음.

### Additional Requirements

- (AD-2) 레이어 의존 단방향: routers→services→repositories→models/DB. 라우터·서비스 SQL 직접 실행 금지.
- (AD-3) 원천 테이블 writer는 소스 어댑터 하나씩. 어댑터는 공통 인터페이스 fetch()→normalize()→upsert() 구현. (어댑터: dart / krx / ecos)
- (AD-4) `valueup_score` writer는 gap_engine 하나. **(AD-10 신규)** `mna_score` writer는 mna_engine 하나. 입력은 valuation_metrics 뷰 + ownership + macro_indicator.
- (AD-5) corp_code(8자리)가 전 테이블 정식 키·FK. stock_code(6자리)는 company 속성.
- (AD-6) API 목록응답 {items,total,page,size} 봉투, 에러 {detail,code}.
- (AD-7) 수집 적재는 자연키 멱등 upsert(financials=corp_code+year+quarter, prices=corp_code+date, valueup_plan=corp_code+disclosure_date, macro_indicator=indicator+date, ownership=corp_code+as_of).
- (AD-8) valueup_score·mna_score에 as_of 컬럼, progress_rate는 as_of를 today로 사용.
- (AD-9) company writer=dart_adapter, 시가총액 단일원천=prices(KRX).
- (Stack) FastAPI 0.139.0, SQLAlchemy 2.0.51, PostgreSQL 17, alembic, APScheduler.

### UX Design Requirements

**전달 방식**: UX는 **Figma MCP로 연동**해 "증권사 애널리스트용 스크리너" UI를 실제 금융 플랫폼처럼 인터랙티브 프로토타입으로 디자인·구현한다.

UX-DR1: 필터 패널 — 시장·업종·시총구간, ROE·PBR·EV/EBITDA·부채비율 슬라이더, 워싱 토글, **스코어 모드 전환(Value-up ↔ M&A)**. 변경 시 리스트 즉시 반영.
UX-DR2: 종목 리스트 — Value-up 점수·M&A 점수·핵심지표 컬럼, 워싱 배지, 정렬·페이지네이션(AD-6 정합).
UX-DR3: 종목 상세 — 지표 분기 시계열, "계획 vs 실제" 갭 카드, M&A 4요소 분해.
UX-DR4: 투자 포인트 카드 — "고ROE·저PBR·자사주 실이행"(밸류업) / "저평가·저부채·낮은 지분율"(M&A) 자동 태깅.
UX-DR5: Tableau 4개 뷰 + 매크로 레이어 — 밸류업 점수·업종 저평가 맵·ROE-PBR 산점도·배당/자사주 + ECOS 금리/환율 컨텍스트.

### FR Coverage Map

FR1: Epic 1 — 밸류업 공시 수집 → valueup_plan
FR2: Epic 1 — DART 재무·KRX 시세 수집 → company/financials/prices
FR3: Epic 1 — valuation_metrics SQL VIEW (EV/EBITDA 포함)
FR4: Epic 2 — Value-up 갭 스코어링 → valueup_score
FR5: Epic 2 — 워싱 플래그 판정
FR6: Epic 2 — 갭/워싱/M&A 랭킹·스크리닝 API
FR7: Epic 3 — 시장·매크로 통계 API
FR8: Epic 1 — ECOS 매크로 수집 → macro_indicator
FR9: Epic 1 — DART 지분구조 수집 → ownership
FR10: Epic 2 — M&A Target Score → mna_score
UX-DR1~5: Epic 3 — Figma 스크리너 UI + Tableau/매크로 연계

## Epic List

### Epic 1: 데이터 기반 & 지표 조회
애널리스트가 상장사 재무·시세·매크로·지분구조와 밸류에이션 지표(EV/EBITDA 포함)를 조회할 수 있다.
**FRs covered:** FR1, FR2, FR3, FR8, FR9

### Epic 2: 밸류업 워싱 & M&A 타겟 스코어 (핵심 차별점)
애널리스트가 워싱 기업(밸류업 미이행)과 M&A 타겟(인수 매력)을 두 스코어로 랭킹한다.
**FRs covered:** FR4, FR5, FR6, FR10

### Epic 3: 시장 인사이트 & 스크리너 UI
애널리스트가 화면에서 필터링하고 시장 양극화·매크로 인사이트를 본다.
**FRs covered:** FR7
**UX-DR covered:** UX-DR1~5

---

## Epic 1: 데이터 기반 & 지표 조회

애널리스트가 상장사 재무·시세·매크로·지분구조와 밸류에이션 지표를 조회할 수 있다. (FR1·FR2·FR3·FR8·FR9)

### Story 1.1: 프로젝트 스캐폴딩 & DB 연결

As a 개발자,
I want FastAPI 앱 골격과 PostgreSQL 연결·설정(config) 기반을 갖추는 것,
So that 이후 수집·지표·스코어링 스토리가 올라갈 토대가 생긴다.

**Acceptance Criteria:**

**Given** 빈 저장소와 확정된 스택(FastAPI 0.139 / SQLAlchemy 2.0.51 / PostgreSQL 17)
**When** 앱을 실행하면
**Then** `/health` 200과 `/docs`가 뜨고
**And** `config.py`가 `.env`에서 DB URL·DART_API_KEY·ECOS_API_KEY와 워싱 임계치·Value-up/M&A 가중치를 로드하며(NFR3), alembic이 초기화된다.

### Story 1.2: 재무제표 수집 (DART, EBITDA·순부채·배당 포함)

As a 애널리스트,
I want DART에서 기본정보와 분기 재무제표(EBITDA·순부채·배당 항목 포함)가 적재되는 것,
So that ROE·EV/EBITDA·배당성향 계산의 원천이 준비된다.

**Acceptance Criteria:**

**Given** `dart_adapter`와 corp_code
**When** 수집을 실행하면
**Then** `company`와 `financials`(revenue, net_income, equity, total_assets, total_liabilities, **operating_income, depreciation, cash, total_debt, dividend_total, buyback_amount(취득 수량, 1.8), buyback_retired_amount(소각 수량, 1.8)**)가 적재되고(AD-3·AD-9)
**And** 자연키(corp_code+year+quarter) 멱등 upsert로 중복이 없다(AD-7). 배당은 DART에서 수집한다(금융공공데이터 미사용).

### Story 1.3: 시세·시가총액·거래대금 수집 (KRX)

As a 애널리스트,
I want KRX에서 종가·거래량·거래대금·시가총액이 적재되는 것,
So that PBR·PER·EV 계산과 유동성 필터가 가능해진다.

**Acceptance Criteria:**

**Given** `krx_adapter`와 종목코드(6자리)
**When** 수집을 실행하면
**Then** `prices`(corp_code, date, close, volume, **trading_value**, market_cap)가 적재되고 stock_code↔corp_code 매핑으로 조인된다(AD-5)
**And** 시총 단일원천은 prices이며(AD-9), upsert 자연키는 corp_code+date다(AD-7).

### Story 1.4: 매크로 지표 수집 (ECOS)

As a 애널리스트,
I want ECOS에서 금리·환율·경기지표가 시계열로 적재되는 것,
So that 매크로 컨텍스트와 M&A 타이밍 신호를 얻는다.

**Acceptance Criteria:**

**Given** `ecos_adapter`와 ECOS_API_KEY
**When** 수집을 실행하면
**Then** `macro_indicator`(indicator, date, value)에 기준금리·국고채3년·원달러환율·경기선행지수가 적재되고
**And** upsert 자연키는 indicator+date이며(AD-7), 결측 구간은 null로 남는다.

### Story 1.5: 밸류업 계획공시 수집 (DART)

As a 애널리스트,
I want DART "기업가치제고계획" 공시의 목표치가 구조화 저장되는 것,
So that 계획 대비 실적 갭을 잴 수 있다.

**Acceptance Criteria:**

**Given** `dart_adapter`의 밸류업 공시 파서
**When** 공시를 수집하면
**Then** `valueup_plan`(target_roe, target_payout_ratio, target_pbr, period_start, period_end, buyback_planned)이 적재되고
**And** 실패 필드 null, 원문 `raw_text` 보존, upsert 자연키는 corp_code+disclosure_date다.

### Story 1.6: 지분구조 수집 (DART 지분공시)

As a 애널리스트,
I want DART에서 최대주주 지분율과 자사주 비중이 적재되는 것,
So that M&A 타겟의 지배구조 취약성을 판정할 수 있다.

**Acceptance Criteria:**

**Given** `dart_adapter`의 최대주주·자기주식 현황 수집
**When** 수집을 실행하면
**Then** `ownership`(corp_code, as_of, largest_shareholder_pct, treasury_stock_pct)이 적재되고
**And** upsert 자연키는 corp_code+as_of이며(AD-7), 미공시 종목은 null로 남는다.

### Story 1.7: valuation_metrics SQL VIEW + 지표 조회 API

As a 애널리스트,
I want ROE·ROA·PBR·PER·EV/EBITDA·부채비율·배당성향·YoY를 조회하는 것,
So that 종목을 정량 비교할 수 있다.

**Acceptance Criteria:**

**Given** 적재된 `financials`·`prices`
**When** `valuation_metrics` 뷰나 `/metrics`를 호출하면
**Then** 지표가 최신 주가 기준으로 계산되어 반환되고(AD-1: 뷰 전용), **EV/EBITDA = (시총 + 순부채) / EBITDA**, EBITDA = 영업이익 + 감가상각비, **net_cash(현금−차입금)·ebitda_margin(EBITDA/매출)도 뷰가 노출(M&A 엔진 입력, F-4)**
**And** YoY는 LAG(4분기)·TTM은 SUM OVER, 0 나눗셈은 NULLIF, 목록 응답은 {items,total,page,size} 봉투를 따른다(AD-6).

### Story 1.8: 자기주식 취득/소각 수집 (DART 자기주식 취득/처분현황)

> **추가 경위 (2026-07-10, Epic 1 회고 액션아이템 #3)**: 1-2 재무제표(`fnlttSinglAcntAll`)에는 자사주 취득/소각 라인이 없어 `financials.buyback_amount`·`buyback_retired_amount`가 **구조적으로 100% null**이었다. 그런데 2.1이 이 두 필드에서 `buyback_executed`·`buyback_retired`·`buyback_status`를 도출하고 2.2 워싱 플래그가 `NOT buyback_retired`에 의존한다 → 데이터 없이 엔진을 붙이면 워싱 판정이 조용히 상수로 고정된다. 정밀 출처 `tesstkAcqsDspsSttus`(자기주식 취득/처분현황)를 별도 수집 스토리로 확보한다. 수집 스토리라 Epic 1 테마('데이터 기반')에 배치(Epic 2는 순수 계산 유지).

As a 애널리스트,
I want DART 자기주식 취득/처분현황에서 취득 수량과 소각 수량이 적재되는 것,
So that 워싱 판정의 '진짜 소각(NOT buyback_retired)' 신호를 실데이터로 잴 수 있다.

**Acceptance Criteria:**

**Given** `dart_adapter`의 자기주식 취득/처분현황(`tesstkAcqsDspsSttus`) 수집
**When** 수집을 실행하면
**Then** 기존 `financials`의 `buyback_amount`(취득 수량(주))·`buyback_retired_amount`(소각 수량(주))가 corp_code+year+quarter로 채워지고(기존 재무 upsert에 병합, 별도 테이블 신설 없음, AD-7)
**And** 취득/소각 구분은 자기주식 처분사유(소각·이익소각 → retired, 매입·취득 → amount)로 매핑하며, 미공시·애매값은 null(0 아님)로 남겨 2.1의 `buyback_status` 도출이 실데이터에 근거한다(NFR2 "null > 틀린 값").

### Story 1.9: 배당총액 수집 (DART 배당에 관한 사항)

> **추가 경위 (2026-07-13, 드레스 리허설 발견 1)**: `financials.dividend_total`이 구조적 100% null(1.2가 best-effort로 남긴 채 수집 경로 미구현 — 1.8 buyback과 동일 병) → execution_score 전 종목 0%. 정밀 출처 `alotMatter.json`(배당에 관한 사항)로 해소.

As a 애널리스트,
I want DART 배당에 관한 사항의 현금배당금총액이 적재되는 것,
So that 실행점수의 배당 항(0.2 가중)과 payout_ratio가 실데이터로 계산된다.

**Acceptance Criteria:**

**Given** `dart_adapter`의 `alotMatter.json` 수집(재무제표와 동일 params)
**When** 수집을 실행하면
**Then** `financials.dividend_total`이 "현금배당금총액(백만원)" 행 × 1,000,000(KRW)으로 채워지고(기존 재무 upsert 병합, AD-7)
**And** 라벨 정확일치·단위 스케일 명시, 미공시·애매값은 null, 보조 원천 실패는 재무 수집을 막지 않는다(1.8 격리 패턴, NFR2).

### Story 1.10: 밸류업 공시 파서 튜닝 (실샘플 기반)

> **추가 경위 (2026-07-13, 드레스 리허설 발견 3)**: 실공시 79건에서 target_roe 24%·payout 14%·period 13% 파싱률 확인. 1.5가 "실샘플 확보 후 튜닝"으로 미룬 조건이 충족됨(raw_text 79건 보존). deferred-work의 1.5 항목(F9 이행현황 매칭 등) 일괄 처리.

As a 애널리스트,
I want 밸류업 계획공시의 목표치 파싱률이 실샘플 기준으로 개선되는 것,
So that 갭 스코어(achievement_rate) 커버리지가 실사용 가능한 수준이 된다.

**Acceptance Criteria:**

**Given** 저장된 raw_text 실샘플과 1.5 파서
**When** report_nm 부정 필터(이행현황·철회 제외, 정정 유지)와 정규식 개선을 적용해 재파싱하면
**Then** 계획 아닌 공시가 valueup_plan에서 배제되고 목표 필드 파싱률이 측정 가능하게 개선되며(before/after 리포트)
**And** raw_text 보존·전체교체 upsert로 재파싱이 파괴 없이 수행된다(1.5 원칙).

---

## Epic 2: 밸류업 워싱 & M&A 타겟 스코어 (핵심 차별점)

애널리스트가 워싱 기업과 M&A 타겟을 두 스코어로 랭킹한다. (FR4·FR5·FR6·FR10)

### Story 2.1: Value-up 갭 스코어링 엔진

As a 애널리스트,
I want 계획 대비 달성률·진척률·실행점수가 산출되는 것,
So that 밸류업 이행 정도를 비교할 수 있다.

**Acceptance Criteria:**

**Given** `valueup_plan`·`valuation_metrics` 뷰·`financials`(자사주 취득·소각 수량(주), >0 신호)(AD-4)
**When** `gap_engine`을 특정 as_of로 실행하면
**Then** `valueup_score`(achievement_rate, progress_rate, execution_score, as_of, **buyback_executed, buyback_retired, buyback_status**)가 적재되고(gap_engine이 유일 writer)
**And** **buyback_executed = (buyback_amount>0), buyback_retired = (buyback_retired_amount>0), buyback_status = retired/purchased_only/none로 도출**되며, progress_rate는 as_of 기준(AD-8), 임계치·가중치는 config 주입(NFR3).

### Story 2.2: 워싱 플래그 판정

> **2026-07-10: 별도 구현 없이 완료 처리** — 이 AC 전부가 Story 2.1(gap_engine)의 산출물에 이미 포함됨(washing_flag 계산, buyback_status=purchased_only 노출, config 임계치 연동). 설계 단계부터 2.1·2.2가 "같은 엔진·같은 테이블"이라 스토리만 분리돼 있었음. 별도 구현 시도 없이 sprint-status만 done으로 갱신.

As a 애널리스트,
I want 공시만 하고 이행 안 한 기업이 자동 표시되는 것,
So that 워싱 기업을 걸러낼 수 있다.

**Acceptance Criteria:**

**Given** `valueup_score`의 자사주 3단계(planned/executed/retired)
**When** 워싱 판정을 실행하면
**Then** "progress_rate ≥ 0.5 AND achievement_rate < 0.6 AND (buyback_planned AND NOT **buyback_retired**)"인 종목만 washing_flag=true가 되고(FR5, 소각까지 안 하면 미이행)
**And** `buyback_status=purchased_only`(매입만·미소각)는 약한 워싱 신호로 별도 노출되며, config 임계치를 바꾸면 판정이 변한다.

### Story 2.3: M&A Target Score 엔진

As a 애널리스트,
I want 인수 매력도가 4요소 점수로 산출되는 것,
So that M&A 타겟 후보를 발굴할 수 있다.

**Acceptance Criteria:**

**Given** `valuation_metrics` 뷰·`ownership`·`macro_indicator`(AD-10: mna_engine이 유일 writer)
**When** `mna_engine`을 as_of로 실행하면
**Then** `mna_score`(mna_target_score 0~100, 요소별 점수: valuation·capacity·ownership·macro)가 적재되고
**And** 저평가(EV/EBITDA·PBR)·인수여력(부채비율·순현금)·지배구조(최대주주 지분율·자사주)·매크로(기준금리)를 시장 내 백분위로 정규화해 가중합(0.35/0.25/0.25/0.15, config)한다.

### Story 2.4: 갭분석 & 워싱 랭킹 API

As a 애널리스트,
I want 갭 분석과 워싱 랭킹을 API로 받는 것,
So that 이행 갭이 큰 기업을 상위부터 본다.

**Acceptance Criteria:**

**Given** 적재된 `valueup_score`
**When** `/valueup/gap-analysis`, `/valueup/washing-ranking`을 호출하면
**Then** 목표·실제·갭·washing_flag가 execution_score 낮은 순으로 반환되고
**And** market·min_progress 필터·페이지네이션이 동작하며 응답 봉투를 따른다(AD-6).

### Story 2.5: M&A 타겟 랭킹 API

As a 애널리스트,
I want M&A 타겟 점수 랭킹을 API로 받는 것,
So that 인수 매력 높은 종목을 상위부터 본다.

**Acceptance Criteria:**

**Given** 적재된 `mna_score`
**When** `/mna/ranking`을 호출하면
**Then** mna_target_score 높은 순으로 요소별 분해와 함께 반환되고
**And** market·업종 필터·페이지네이션이 동작한다(AD-2·AD-6).

### Story 2.6: 다중조건 스크리닝 API

As a 애널리스트,
I want 여러 조건을 조합해 종목을 걸러내는 것,
So that 워싱·저평가·M&A 후보를 양방향으로 스크리닝한다.

**Acceptance Criteria:**

**Given** 지표·두 스코어가 준비된 상태
**When** `/screening`을 실행점수·mna_score 범위, washing_only, buyback_executed 필터로 호출하면
**Then** 조건에 맞는 종목이 정렬·페이지네이션되어 반환되고(FR6)
**And** 라우터는 repository를 통해서만 조회한다(AD-2).

### Story 2.7: M&A 스코어 sector peer-group 백분위

> **추가 경위 (2026-07-10, 리드 스코프 분리 결정)**: 2.3의 전종목 통합 백분위는 finance 관점에서 업종 간 비교가능성이 깨진다(은행·금융은 레버리지가 사업모델이라 EV/EBITDA·부채비율 백분위가 무의미, 리츠는 FFO 기반 등). 2.3은 `_build_populations` grouping seam만 확보하고, 실제 sector-relative 랭킹은 이 스토리로 분리. 업종별 **변수 세트 교체**(금융=P/B·ROE, 산업재=EV/EBITDA 등, 레벨 2)는 finance 도메인 리서치가 선행돼야 해서 이 스토리 범위 밖(후속 후보로만 기록).

As a 애널리스트,
I want M&A 스코어의 저평가·인수여력 백분위가 같은 업종 peer 안에서 매겨지는 것,
So that 은행과 반도체가 같은 자로 줄 세워지는 왜곡 없이 "업종 내에서 싼 회사"를 찾는다.

**Acceptance Criteria:**

**Given** `company.sector`(DART induty_code)와 2.3의 grouping seam(`_build_populations`)
**When** 업종코드→peer 버킷 택소노미 매핑을 적용해 mna_engine을 실행하면
**Then** valuation_score·capacity_score의 백분위 모집단이 같은 버킷 종목으로 제한되고(ownership_score·macro_score는 업종 무관 유지)
**And** 버킷 peer 수가 최소 임계(config) 미만이면 전체시장 모집단으로 폴백하며(small-N 노이즈 방어), 어느 모집단을 썼는지 식별 가능하다.

---

## Epic 3: 시장 인사이트 & 스크리너 UI

애널리스트가 화면에서 필터링하고 시장 양극화·매크로 인사이트를 본다. (FR7·UX-DR1~5)

### Story 3.1: 시장·매크로 통계 API

As a 애널리스트,
I want 시장·시총구간별 평균 지표·워싱 비율과 매크로 지표를 받는 것,
So that 코스피-코스닥 양극화와 매크로 국면을 파악한다.

**Acceptance Criteria:**

**Given** 지표·스코어·매크로가 적재된 상태
**When** `/stats/market-comparison`, `/stats/summary`, `/stats/macro`를 호출하면
**Then** 시장별 avg_roe·avg_pbr·avg_ev_ebitda·washing_ratio·n과 전체 KPI, 최신 매크로 지표가 반환되고(FR7)
**And** Tableau가 물릴 집계 JSON 형태다.

### Story 3.2: Figma 애널리스트 스크리너 UI 디자인

As a 디자이너/개발자,
I want Figma MCP로 실제 금융 플랫폼 같은 스크리너를 디자인하는 것,
So that 클릭 흐름을 가진 프로토타입 기준 시안이 생긴다.

**Acceptance Criteria:**

**Given** Figma MCP 연동과 UX-DR1~4
**When** `/figma-generate-design`으로 화면을 생성하면
**Then** 필터 패널·종목 리스트·종목 상세·투자 포인트 카드 프레임과 스코어 모드(Value-up↔M&A) 전환이 만들어지고
**And** 데이터 요소가 API 필드(execution_score, mna_target_score, washing_flag 등)와 매핑되며 클릭 흐름(리스트→상세) 프로토타입이 연결된다.

### Story 3.3: 스크리너 화면 — 필터 패널 & 종목 리스트

As a 애널리스트,
I want 화면에서 조건을 걸어 종목 리스트를 보는 것,
So that 원하는 종목군을 좁혀 탐색한다.

**Acceptance Criteria:**

**Given** `/screening`·`/metrics` API와 Figma 시안(UX-DR1, UX-DR2), React 19+Vite 스캐폴딩
**When** 시장·업종·시총구간과 ROE·PBR·EV/EBITDA·부채비율 슬라이더, 워싱 토글, 스코어 모드를 조작하면
**Then** 리스트(TanStack Table)가 즉시 필터링되어 Value-up·M&A 점수·핵심지표·워싱 배지로 표시되고
**And** 서버상태는 TanStack Query로, API로만 데이터 접근(AD-11), 정렬·페이지네이션이 응답 봉투와 정합하게 동작한다.

### Story 3.4: 종목 상세 & 투자 포인트 카드

As a 애널리스트,
I want 종목을 눌러 상세 지표·스코어 분해·투자 포인트를 보는 것,
So that 개별 종목의 밸류업 이행과 인수 매력을 판단한다.

**Acceptance Criteria:**

**Given** 종목별 지표 시계열·`valueup_score`·`mna_score`·`valueup_plan`(UX-DR3, UX-DR4)
**When** 리스트에서 종목을 선택하면
**Then** 지표 시계열·"계획 vs 실제" 갭 카드·M&A 4요소 분해가 표시되고
**And** "고ROE·저PBR·자사주 실이행"(밸류업)/"저평가·저부채·낮은 지분율"(M&A) 셀링포인트가 자동 태깅된다.

### Story 3.5: Tableau 대시보드 연계

As a 애널리스트,
I want Tableau에서 시장·매크로 대시보드를 보는 것,
So that 발표·리포트용 시각 자료를 얻는다.

**Acceptance Criteria:**

**Given** `/stats/*`와 지표·스코어·매크로 데이터(UX-DR5)
**When** Tableau를 PostgreSQL에 연결하면
**Then** 밸류업 점수·업종별 저평가 맵·ROE-PBR 산점도·배당/자사주 4개 뷰와 ECOS 매크로 레이어가 구성되고
**And** 각 뷰가 API/DB 뷰를 소스로 갱신된다.
