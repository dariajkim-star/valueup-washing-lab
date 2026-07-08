# 밸류업 워싱 탐지 대시보드 — 개발계획서

> **한 줄 정의**: 상장사의 밸류업 *계획 공시*(목표 ROE·배당성향·자사주 등)와 *실제 실적*을 DB에서 대조해,
> "말만 하고 안 지키는" 기업을 정량 스코어링·랭킹하는 스크리닝 대시보드.

- 문서 버전: v0.1
- 작성일: 2026-07-08
- 담당: daria.j.kim

---

## 1. 배경 & 문제정의

- 밸류업 공시 참여 기업은 2024.5 3개사 → **2026.4말 718개사**로 급증, 사실상 의무화 단계.
- 그러나 **공시 ≠ 이행**. 코스닥은 "저PBR 해소 진입 단계"에 머물고, 더벨 리뷰에서도 "ROE 개선 지연"(신세계 등) 사례가 반복 지적됨.
- 기관투자자·의결권 자문·애널리스트가 실제로 원하는 인사이트 = **계획 대비 실제 이행 갭(gap)의 정량화**.

**핵심 질문**: 어떤 기업이 밸류업을 *실행*하고 있고, 어떤 기업이 *워싱(washing)*만 하는가?

---

## 2. 목표 & 비목표

### 목표 (v1)
- DART 밸류업 공시 + 분기 재무 + KRX 주가/PBR을 하나의 DB로 통합.
- 계획-실적 **갭 스코어**(달성률·진척률·워싱 플래그) 자동 산출.
- REST API로 스크리닝/랭킹/기업 상세 제공.
- Tableau·Figma 대시보드가 물릴 수 있는 정제 데이터 뷰 노출.

### 비목표 (v1 제외)
- 실시간 시세 스트리밍 (일배치로 충분).
- 자연어 공시 원문 요약/LLM 해석 (v2 백로그).
- 사용자 인증/계정 (내부 분석 도구로 시작).

---

## 3. 성공 지표 (분석 산출물 기준)

| 지표 | 정의 |
|---|---|
| **달성률(Achievement)** | 실제 ROE / 목표 ROE (배당성향·PBR 동일) |
| **진척률(Progress)** | (경과 기간 대비) 목표 궤도 도달 정도 |
| **워싱 플래그** | 목표기간 50%+ 경과 & 달성률 < 임계치(예 60%) & 자사주/배당 실이행 없음 |
| **밸류업 실행 점수** | 위 지표 가중합 0~100 |

---

## 4. 아키텍처

```
[DART OpenAPI]   [KRX / pykrx]        ← 외부 데이터 소스
       │               │
       ▼               ▼
   ┌───────────────────────┐
   │  Ingestion (수집기)    │  APScheduler 일배치 + 수동 트리거
   └──────────┬────────────┘
              ▼
   ┌───────────────────────┐
   │  DB (PostgreSQL)      │  기업 / 계획공시 / 분기실적 / 주가 / 갭스코어
   └──────────┬────────────┘
              ▼
   ┌───────────────────────┐
   │  Analysis (갭 엔진)    │  pandas 계산 → gap_score 테이블 적재
   └──────────┬────────────┘
              ▼
   ┌───────────────────────┐
   │  FastAPI (REST)       │  스크리닝 / 랭킹 / 상세 / 통계
   └──────────┬────────────┘
              ▼
     Tableau  /  Figma UI
```

### 기술 스택
- **Backend**: FastAPI + Uvicorn
- **ORM/DB**: SQLAlchemy 2.0 + PostgreSQL (개발은 SQLite 폴백)
- **데이터 수집**: `dart-fss`(전자공시 재무제표), `pykrx`(KRX 시세·PBR), 금융위 **금융공공데이터** 개방 API(`requests`)
- **분석**: pandas, numpy
- **배치**: APScheduler
- **검증/설정**: pydantic v2, pydantic-settings
- **테스트**: pytest, httpx

---

## 5. 데이터 모델 (애널리스트 스크리너 5테이블 + 밸류업 확장)

증권사 애널리스트 스크리너 표준 구조(`company / financials / prices / valuation_metrics / valueup_score`)를 채택하되,
본 프로젝트의 차별점인 **밸류업 계획 공시**(`valueup_plan`)를 추가해 "계획 vs 실적" 워싱 탐지를 가능케 한다.
**원천(raw) → 파생(계산) → 스코어**로 관심사를 분리한다.

| 테이블 | 성격 | 핵심 컬럼 | 소스 |
|---|---|---|---|
| `company` | 원천 | corp_code, stock_code, corp_name, market(KOSPI/KOSDAQ), sector, market_cap | DART/KRX |
| `financials` | 원천 | corp_code, year, quarter, net_income, equity, **total_assets, total_liabilities**, revenue, dividend_total, buyback_amount | DART 재무제표 + 금융공공데이터 |
| `prices` | 원천 | corp_code, date, close, volume, market_cap | KRX |
| `valueup_plan` | 원천 | plan_id, corp_code, disclosure_date, target_roe, target_payout_ratio, target_pbr, period_start, period_end, buyback_planned | DART 밸류업 공시 |
| `valuation_metrics` | **SQL VIEW (즉석 계산)** | corp_code, year, quarter, **roe, roa, pbr, per, debt_ratio, payout_ratio, yoy_revenue_growth, yoy_income_growth** | financials×prices 조인 계산 |
| `valueup_score` | 스코어 | corp_code, as_of, achievement_rate, progress_rate, washing_flag, execution_score, buyback_executed | 분석 산출 |

### SQL 계산 지표 정의 (valuation_metrics)
| 지표 | 산식 |
|---|---|
| ROE | 당기순이익 / 자본총계 |
| ROA | 당기순이익 / 자산총계 |
| PBR | 시가총액 / 자본총계 |
| PER | 시가총액 / 당기순이익(TTM) |
| 부채비율 | 부채총계 / 자본총계 |
| 배당성향 | 배당총계 / 당기순이익 |
| YoY 성장률 | (당기 − 전년동기) / 전년동기 · 매출·순이익 각각 |

> **설계 결정**: `valuation_metrics`는 물리 테이블이 아니라 **SQL VIEW**로 구현한다.
> 조회 시점에 항상 최신 주가로 즉석 계산되며, **윈도우 함수(YoY `LAG`)·CTE·다중 조인**을 활용해 SQL 역량을 직접 드러내는 포트폴리오 핵심 산출물이다.
> (데모 규모에서 성능 이슈 없음. 대용량 전환 시 `MATERIALIZED VIEW`로 승격 가능.)
> 전체 스키마·엔드포인트는 `API_SPEC.md`, 실제 뷰 DDL은 옵시디언 `03_DB스키마_지표산식` 참조.

---

## 6. 마일스톤 (4주 스프린트 가정)

### Week 1 — 데이터 파이프라인
- [ ] DART OpenAPI 키 발급, `dart-fss` 연결 검증
- [ ] `company`·`financials`·`prices` 스키마 확정 및 적재 스크립트
- [ ] KRX 주가/시총 수집(pykrx) + 금융공공데이터 배당 연동
- [ ] DB 마이그레이션(alembic) 초기화

### Week 2 — 지표 계산 & 밸류업 갭 엔진
- [ ] `valuation_metrics` SQL 계산(ROE/ROA/PBR/PER/부채비율/배당성향/YoY)
- [ ] 밸류업 계획 공시 파싱 → `valueup_plan` 적재
- [ ] `valueup_score` 산식 구현(달성률/진척률/워싱 플래그) + 단위 테스트

### Week 3 — API
- [ ] FastAPI 엔드포인트 구현(지표/스크리닝/랭킹/상세/통계)
- [ ] pydantic 응답 스키마 + OpenAPI 문서 자동화
- [ ] 필터·정렬·페이지네이션

### Week 4 — 시각화 & 마감
- [ ] Tableau 정제 뷰: 밸류업 점수·업종별 저평가 맵·ROE-PBR 산점도·배당/자사주 현황
- [ ] Figma "애널리스트 스크리너" UI: 필터 패널·종목 상세·투자 포인트 카드
- [ ] README·데모 데이터·발표 스토리라인 정리

---

## 7. 리스크 & 대응

| 리스크 | 대응 |
|---|---|
| 밸류업 목표치가 정성적(범위·서술형)이라 정규화 어려움 | 파서에서 수치 추출 실패 시 `null` + 수동 보정 테이블 병행 |
| DART API 레이트리밋 | 배치 시 sl-eep/재시도, 수집분 캐시 |
| 종목 코드 체계(6자리 종목 vs 8자리 corp_code) 불일치 | `company`에 매핑 컬럼 두고 조인 |
| 분기 실적 발표 시차 | `as_of` 기준일 명시, 진척률에 반영 |

---

## 8. 폴더 구조 (예정)

```
valueup-washing-lab/
├── app/
│   ├── main.py            # FastAPI 엔트리
│   ├── config.py          # 설정(pydantic-settings)
│   ├── db.py              # 세션/엔진
│   ├── models.py          # SQLAlchemy 모델
│   ├── schemas.py         # pydantic 응답 스키마
│   ├── routers/           # companies / metrics / valueup / financials / stats
│   ├── ingest/            # dart.py, krx.py, findata.py(금융공공데이터), scheduler.py
│   └── analysis/          # metrics_engine.py, gap_engine.py
├── alembic/               # 마이그레이션
├── tests/
├── API_SPEC.md
├── DEV_PLAN.md
├── requirements.txt
└── README.md
```

---

## 9. 시각화 & 산출물 (Tableau · Figma)

### Tableau 대시보드 (4개 뷰)
| 뷰 | 내용 | 물리는 API/뷰 |
|---|---|---|
| **밸류업 점수** | 종목별 execution_score 랭킹·워싱 플래그 하이라이트 | `/valueup/washing-ranking`, `valueup_score` |
| **업종별 저평가 맵** | 업종×시장 PBR 히트맵, 저PBR 우량주 탐지 | `/stats/market-comparison` |
| **ROE-PBR 산점도** | 사분면 분석(고ROE-저PBR = 저평가 후보) | `valuation_metrics` |
| **배당/자사주 현황** | 배당성향·자사주 매입 실이행 트래킹 | `financials`, `valueup_score.buyback_executed` |

### Figma — 증권사 애널리스트용 스크리너 UI
- **필터 패널**: 시장/업종/시총구간, ROE·PBR·부채비율 슬라이더, 워싱 여부 토글
- **종목 리스트**: 밸류업 점수·핵심 지표 컬럼, 워싱 배지
- **종목 상세**: 지표 시계열, 계획 vs 실제 갭 카드
- **투자 포인트 카드**: "고ROE·저PBR·자사주 실이행" 등 자동 태깅된 셀링포인트

### 면접 어필 포인트
> "한국 증시 저평가와 밸류업 정책을 **데이터로 계량화**했다."
> - 공시(말) vs 실적(행동)의 갭을 정량 스코어링 → 워싱 탐지
> - 애널리스트 스크리너 관점의 DB 설계 + SQL 지표 계산(ROE/ROA/PBR/PER/부채비율/배당성향/YoY)
> - DART·KRX·금융공공데이터 3소스 통합 파이프라인 구축
