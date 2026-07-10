---
id: SPEC-valueup-washing
companions:
  - db-schema.md
  - scoring.md
  - stack.md
sources:
  - ../../../valueup-washing-lab/DEV_PLAN.md
  - ../../../valueup-washing-lab/API_SPEC.md
  - ../../../ob_storage/밸류업_워싱_스크리너/03_DB스키마_지표산식.md
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only.

# 밸류업 워싱 탐지 스크리너

## Why

2026년 한국 밸류업 공시 참여 기업은 718개사로 급증해 사실상 의무화됐지만, **공시(말) ≠ 이행(행동)**이다. 코스닥은 저PBR 해소 진입 단계에 머물고, 목표 ROE·배당·자사주를 공시만 하고 실행하지 않는 "워싱" 기업이 존재한다. 기관투자자·의결권 자문·애널리스트가 실제로 원하는 것은 **계획 대비 실제 이행 갭의 정량화**다. 이 프로젝트는 그 갭을 데이터로 계량화해 워싱 기업을 걸러내고 저평가 우량주를 스크리닝한다. 나아가 같은 데이터 기반 위에서 **M&A 타겟 스코어**(저평가·인수여력·지배구조·매크로)를 산출해, "스스로 가치를 올리나"(밸류업)와 "남이 사갈 만한가"(M&A)라는 상반된 IB 관점을 한 플랫폼에서 본다 — 동시에 SQL 역량을 드러내는 포트폴리오 산출물이다.

## Capabilities

- **CAP-1** 밸류업 계획공시 수집·정규화
  - **intent:** DART "기업가치제고계획" 공시에서 목표 ROE·배당성향·PBR·목표기간·자사주 계획을 추출해 `valueup_plan`에 적재한다.
  - **success:** 한 종목의 공시를 넣으면 목표 지표들이 구조화 컬럼으로 저장되고, 수치 추출 실패 필드는 `null`로 남는다.

- **CAP-2** 재무·시세 원천 데이터 수집
  - **intent:** DART 재무제표(EBITDA·순부채·배당·자사주 매입액·**자사주 소각액** 포함), KRX 시세/시가총액/거래대금을 수집해 `company`·`financials`·`prices`에 적재한다.
  - **success:** 대상 종목의 분기 재무·일별 시세가 DB에 존재하고, 소스별 코드 체계(6자리 종목 ↔ 8자리 corp_code)가 매핑돼 조인된다. 시가총액 단일원천은 `prices`(company에 market_cap 미보유).

- **CAP-3** 밸류에이션 지표 SQL VIEW 계산
  - **intent:** ROE·ROA·PBR·PER·**EV/EBITDA**·부채비율·배당성향·YoY 성장률을 `valuation_metrics` **SQL VIEW**로 계산한다.
  - **success:** 뷰를 조회하면 최신 주가 기준으로 지표가 즉석 계산되어 반환되고, EV/EBITDA=(시총+순부채)/EBITDA, YoY는 전년동기(LAG 4분기) 대비로 산출된다.

- **CAP-4** 계획 vs 실적 갭 스코어링
  - **intent:** 목표 대비 실제 달성률·목표기간 진척률·실행점수(0~100)를 산출해 `valueup_score`에 적재한다.
  - **success:** 종목별 `achievement_rate`·`progress_rate`·`execution_score`가 계산되고, 임계치·가중치를 바꾸면 결과가 그에 따라 변한다.

- **CAP-5** 워싱 플래그 판정 (자사주 매입 vs 소각 구분)
  - **intent:** 자사주를 공시(planned)·매입(executed)·소각(retired) 3단계로 구분하고, "진척률 ≥ 0.5 & 달성률 < 0.6 & 약속했으나 **소각(retired) 미이행**"인 종목을 워싱으로 표시한다(2026 의무소각 반영).
  - **success:** 조건을 만족하는 종목만 `washing_flag=true`가 되고, `buyback_status`(retired/purchased_only/none)가 함께 제공되어 "매입만 하고 미소각"이 별도 신호로 드러난다.

- **CAP-6** 스크리닝·랭킹 REST API
  - **intent:** 갭 분석·워싱 랭킹·다중조건 스크리닝·지표 목록을 REST로 제공한다(`/valueup/gap-analysis`, `/valueup/washing-ranking`, `/valueup/screening`, `/metrics`).
  - **success:** 시장·업종·지표 필터와 정렬·페이지네이션이 동작하고, OpenAPI 문서(`/docs`)가 자동 생성된다.

- **CAP-7** 시장 비교 통계 API
  - **intent:** 시장(KOSPI/KOSDAQ)·시총구간별 평균 지표와 워싱 비율, 매크로 지표, 헤드라인 KPI를 집계해 제공한다(`/stats/market-comparison`, `/stats/summary`, `/stats/macro`).
  - **success:** Tableau가 물릴 수 있는 집계 JSON이 반환되고, 코스피/코스닥 양극화와 매크로 국면이 수치로 드러난다.

- **CAP-8** ECOS 매크로 지표 수집
  - **intent:** ECOS에서 기준금리·국고채3년·원달러환율·경기선행지수를 수집해 `macro_indicator`에 시계열 적재한다.
  - **success:** 지표별 시계열이 DB에 존재하고, upsert 자연키(indicator+date)로 재수집 시 중복이 없다.

- **CAP-9** 지분구조 수집
  - **intent:** DART 지분공시에서 최대주주 지분율·자사주 비중을 수집해 `ownership`에 적재한다.
  - **success:** 종목별 최대주주 지분율·자사주 비중이 저장되고, 미공시 종목은 null로 남는다.

- **CAP-10** M&A Target Score 산출
  - **intent:** 저평가·인수여력·지배구조·매크로 4요소를 시장 내 백분위로 정규화·가중합해 M&A 타겟 점수(0~100)를 `mna_score`에 적재한다.
  - **success:** 종목별 mna_target_score와 요소별 분해가 계산되고, 가중치를 config에서 바꾸면 결과가 그에 따라 변한다.

## Constraints

- 밸류에이션 지표 계산은 애플리케이션 코드가 아니라 **DB SQL VIEW**로 수행한다(포폴 SQL 역량 어필이 목적). 대용량 전환 시 `MATERIALIZED VIEW`로 승격 가능. → 상세 `db-schema.md`
- 0으로 나누기는 `NULLIF`로 방어하고 지표 `null`을 허용한다. 밸류업 목표치가 정성적(서술형)이라 파싱 실패 시 `null` + 수동 보정 테이블로 병행한다.
- 워싱 임계치(진척 0.5 / 달성 0.6)·Value-up 가중치(0.5/0.3/0.2)·M&A 가중치(0.35/0.25/0.25/0.15)는 `config.py`로 노출해 재현·튜닝 가능해야 한다. → 산식 `scoring.md`
- 데이터 소스는 DART·KRX·ECOS 3종으로 고정하며(금융공공데이터 미사용), API 키는 `.env`(`DART_API_KEY`, `ECOS_API_KEY`)로 주입한다.

## Non-goals

- v1에서 사용자 인증·계정 관리는 하지 않는다(내부 분석 도구).
- 실시간 시세 스트리밍은 하지 않는다(일배치 수집으로 충분).
- 공시 원문 LLM 요약·자연어 해석은 하지 않는다(v2 백로그).
- 매매·주문·자금이체 등 실행 기능은 범위 밖(분석 전용).

## Success signal

한 애널리스트가 스크리너에서 "코스피 · 진척률 50%+ · 자사주 미이행" 필터를 걸면, 밸류업을 공시만 하고 실행하지 않은 워싱 기업이 `execution_score` 낮은 순으로 즉시 랭킹되어 나오고, 스코어 모드를 M&A로 바꾸면 "저평가·저부채·낮은 지분율" 인수 타겟이 `mna_target_score` 높은 순으로 정렬된다 — 즉 말과 행동의 갭, 그리고 인수 매력이 한 화면에서 정렬된다.

## Assumptions

- v1은 인증 없는 내부 도구이며, 데이터 수집은 일배치, 공시 LLM 요약은 범위에서 제외한다(입력 문서 기준 추정).

## Open Questions

- 밸류업 목표치가 범위·서술형으로 공시된 경우의 정규화 규칙(중앙값? 하한? 수동 태깅?)을 어떻게 확정할 것인가 — CAP-1의 파싱 정확도에 영향.
- 분기 실적 발표 시차를 진척률(`progress_rate`)에 어떻게 반영할지 — `as_of` 기준일 정의가 필요.
