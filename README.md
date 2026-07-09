# 밸류업 워싱 탐지 대시보드 — API 명세서

- 버전: v0.1
- Base URL: `http://localhost:8000/api/v1`
- 포맷: JSON (UTF-8)
- 인증: v1 없음 (내부 도구). v2에서 API Key 헤더 예정.
- 자동 문서: `/docs` (Swagger), `/redoc`

---

## 0. 공통 규약

### 응답 봉투
목록형 응답은 페이지네이션 메타를 포함한다.

```json
{
  "items": [ ... ],
  "total": 718,
  "page": 1,
  "size": 20
}
```

### 공통 쿼리 파라미터 (목록)
| 파라미터 | 타입 | 기본 | 설명 |
|---|---|---|---|
| `page` | int | 1 | 페이지 번호 (1-base) |
| `size` | int | 20 | 페이지 크기 (max 100) |
| `sort` | string | - | `field` 또는 `-field`(내림차순). 예: `-execution_score` |

### 에러 포맷
```json
{ "detail": "company not found", "code": "NOT_FOUND" }
```
| HTTP | code | 상황 |
|---|---|---|
| 400 | `BAD_REQUEST` | 잘못된 파라미터 |
| 404 | `NOT_FOUND` | 리소스 없음 |
| 422 | `VALIDATION_ERROR` | 스키마 검증 실패 (FastAPI 기본) |
| 500 | `INTERNAL` | 서버 오류 |

---

## 1. 데이터 스키마 (엔티티)

### Company
| 필드 | 타입 | 설명 |
|---|---|---|
| `corp_code` | string(8) | DART 고유 기업코드 (PK) |
| `stock_code` | string(6) | 종목코드 |
| `corp_name` | string | 회사명 |
| `market` | enum | `KOSPI` \| `KOSDAQ` |
| `sector` | string | 업종 |
| `market_cap` | int | 시가총액(원) |
| `has_valueup_plan` | bool | 밸류업 계획 공시 여부 |

### ValueupPlan
| 필드 | 타입 | 설명 |
|---|---|---|
| `plan_id` | int | PK |
| `corp_code` | string(8) | FK → Company |
| `disclosure_date` | date | 공시일 |
| `target_roe` | float\|null | 목표 ROE(%) |
| `target_payout_ratio` | float\|null | 목표 배당성향(%) |
| `target_pbr` | float\|null | 목표 PBR(배) |
| `period_start` | date\|null | 목표 기간 시작 |
| `period_end` | date\|null | 목표 기간 종료 |
| `buyback_planned` | bool | 자사주 매입/소각 계획 명시 |
| `raw_text` | string | 공시 원문 발췌 |

### Financial (원천 재무제표 — 테이블 `financials`)
| 필드 | 타입 | 설명 |
|---|---|---|
| `corp_code` | string(8) | FK |
| `year` | int | 사업연도 |
| `quarter` | int | 1~4 |
| `revenue` | int\|null | 매출액 |
| `net_income` | int\|null | 당기순이익 |
| `equity` | int\|null | 자본총계 |
| `total_assets` | int\|null | 자산총계 |
| `total_liabilities` | int\|null | 부채총계 |
| `dividend_total` | int\|null | 배당총액 |
| `buyback_amount` | int\|null | 자사주 매입액 |

### ValuationMetric (파생 지표 — **SQL VIEW** `valuation_metrics`, 조회 시 즉석 계산)
| 필드 | 타입 | 산식 |
|---|---|---|
| `corp_code` | string(8) | FK |
| `year` / `quarter` | int | 기준 분기 |
| `roe` | float\|null | 당기순이익 / 자본총계 |
| `roa` | float\|null | 당기순이익 / 자산총계 |
| `pbr` | float\|null | 시가총액 / 자본총계 |
| `per` | float\|null | 시가총액 / 순이익(TTM) |
| `debt_ratio` | float\|null | 부채총계 / 자본총계 |
| `payout_ratio` | float\|null | 배당총계 / 순이익 |
| `yoy_revenue_growth` | float\|null | 매출 전년동기 대비 성장률 |
| `yoy_income_growth` | float\|null | 순이익 전년동기 대비 성장률 |

### ValueupScore (분석 산출 — 테이블 `valueup_score`)
| 필드 | 타입 | 설명 |
|---|---|---|
| `corp_code` | string(8) | FK |
| `as_of` | date | 산출 기준일 |
| `achievement_rate` | float | 목표 대비 달성률(0~1+) |
| `progress_rate` | float | 목표기간 경과 대비 진척률(0~1) |
| `washing_flag` | bool | 워싱 의심 여부 |
| `execution_score` | float | 밸류업 실행 점수(0~100) |
| `buyback_executed` | bool | 실제 자사주 이행 여부 |

---

## 2. 엔드포인트

### 2.1 기업 (Companies)

#### `GET /companies`
기업 목록/필터.

쿼리: `market`, `sector`, `has_valueup_plan`(bool), `q`(회사명 검색) + 공통.

```json
// 200
{
  "items": [
    {
      "corp_code": "00126380",
      "stock_code": "005930",
      "corp_name": "삼성전자",
      "market": "KOSPI",
      "sector": "반도체",
      "market_cap": 450000000000000,
      "has_valueup_plan": true
    }
  ],
  "total": 718, "page": 1, "size": 20
}
```

#### `GET /companies/{corp_code}`
기업 상세 (계획 + 최근 실적 + 갭스코어 포함).

```json
// 200
{
  "corp_code": "00126380",
  "corp_name": "삼성전자",
  "market": "KOSPI",
  "valueup_plan": { "target_roe": 15.0, "target_payout_ratio": 35.0, "buyback_planned": true, "period_end": "2027-12-31" },
  "latest_financial": { "year": 2026, "quarter": 1, "actual_roe": 11.2, "actual_payout_ratio": 28.0 },
  "gap_score": { "achievement_rate": 0.75, "progress_rate": 0.40, "washing_flag": false, "execution_score": 72.5 }
}
// 404 NOT_FOUND
```

---

### 2.2 밸류업 분석 (Valueup) — 프로젝트 핵심

#### `GET /valueup/plans`
공시된 밸류업 계획 목록. 쿼리: `market`, `buyback_planned`, `disclosed_from`, `disclosed_to`.

#### `GET /valueup/gap-analysis`
**핵심 API.** 기업별 계획 대비 실제 이행 갭.

쿼리:
| 파라미터 | 타입 | 설명 |
|---|---|---|
| `market` | enum | 시장 필터 |
| `metric` | enum | `roe` \| `payout` \| `pbr` (기준 지표) |
| `min_progress` | float | 최소 목표기간 진척률 (예 0.5 = 절반 이상 경과) |

```json
// 200
{
  "items": [
    {
      "corp_code": "00111722",
      "corp_name": "신세계",
      "market": "KOSPI",
      "target_roe": 10.0,
      "actual_roe": 6.1,
      "achievement_rate": 0.61,
      "progress_rate": 0.55,
      "gap": -3.9,
      "washing_flag": true
    }
  ],
  "total": 200, "page": 1, "size": 20
}
```

#### `GET /valueup/washing-ranking`
**"말만 하고 안 하는 기업" 랭킹.** 워싱 스코어 높은 순.

쿼리: `market`, `min_progress`(기본 0.5), `size`.

```json
// 200
{
  "items": [
    {
      "rank": 1,
      "corp_code": "00111722",
      "corp_name": "○○기업",
      "target_roe": 12.0,
      "actual_roe": 4.5,
      "achievement_rate": 0.375,
      "progress_rate": 0.70,
      "buyback_planned": true,
      "buyback_executed": false,
      "washing_flag": true,
      "execution_score": 21.0
    }
  ],
  "total": 50, "page": 1, "size": 20
}
```

#### `GET /valueup/screening`
다중 조건 스크리닝 (밸류업 후보/워싱 양방향).

쿼리:
| 파라미터 | 타입 | 설명 |
|---|---|---|
| `market` | enum | 시장 |
| `min_execution_score` | float | 실행 점수 하한 |
| `max_execution_score` | float | 실행 점수 상한 |
| `washing_only` | bool | 워싱 플래그만 |
| `buyback_executed` | bool | 자사주 실이행 여부 |
| `sort` | string | 기본 `-execution_score` |

---

### 2.3 재무 & 지표 (Financials / Metrics)

#### `GET /financials/{corp_code}`
분기 원천 재무 시계열. 쿼리: `from_year`, `to_year`.

```json
// 200
{
  "corp_code": "00126380",
  "items": [
    { "year": 2026, "quarter": 1, "revenue": 70000000000000, "net_income": 8000000000000, "equity": 300000000000000, "buyback_amount": 3000000000000 }
  ]
}
```

#### `GET /metrics`
계산된 밸류에이션 지표 목록/필터 — **애널리스트 스크리너의 기준 데이터**.

쿼리: `market`, `sector`, `max_pbr`, `min_roe`, `max_debt_ratio`, `min_payout_ratio` + 공통.

```json
// 200
{
  "items": [
    {
      "corp_code": "00126380", "corp_name": "삼성전자", "market": "KOSPI", "sector": "반도체",
      "roe": 11.2, "roa": 7.4, "pbr": 1.5, "per": 14.2,
      "debt_ratio": 42.0, "payout_ratio": 28.0,
      "yoy_revenue_growth": 12.3, "yoy_income_growth": 25.1
    }
  ],
  "total": 718, "page": 1, "size": 20
}
```

#### `GET /metrics/{corp_code}`
종목별 지표 시계열(Tableau ROE-PBR 산점도·상세 차트용).

---

### 2.4 통계 (Stats) — Tableau/Figma 피드용

#### `GET /stats/market-comparison`
시장(KOSPI/KOSDAQ)·시총구간별 평균 지표 집계. (아이디어 #3 확장 훅)

```json
// 200
{
  "as_of": "2026-06-30",
  "groups": [
    { "market": "KOSPI", "avg_roe": 9.8, "avg_pbr": 1.4, "washing_ratio": 0.18, "n": 480 },
    { "market": "KOSDAQ", "avg_roe": 6.2, "avg_pbr": 0.9, "washing_ratio": 0.41, "n": 238 }
  ]
}
```

#### `GET /stats/summary`
전체 대시보드 헤드라인 카드용 KPI.

```json
// 200
{
  "total_companies": 718,
  "washing_count": 142,
  "avg_execution_score": 58.3,
  "buyback_execution_ratio": 0.63
}
```

---

### 2.5 수집/운영 (Ingest)

#### `POST /ingest/run`
수동 데이터 수집 트리거 (관리자용).

```json
// 요청
{ "source": "dart", "target": "financials", "year": 2026, "quarter": 1 }
// 202 Accepted
{ "job_id": "ing_20260708_01", "status": "queued" }
```

#### `GET /ingest/status/{job_id}`
수집 잡 상태. `queued` \| `running` \| `done` \| `failed`.

---

## 3. 갭 스코어 산식 (정의)

```
달성률   achievement_rate = actual_metric / target_metric      (target>0)
진척률   progress_rate    = (today - period_start) / (period_end - period_start)   [0,1] 클램프
갭       gap              = actual_metric - target_metric

워싱 플래그 washing_flag = (progress_rate >= 0.5)
                        AND (achievement_rate < 0.6)
                        AND (buyback_planned == true AND buyback_executed == false)
                        # ↑ 절반 이상 시간 지났는데 목표 60% 미달 + 약속한 자사주 미이행

실행점수 execution_score = 100 * clamp(
                        0.5 * min(achievement_rate, 1.0)
                      + 0.3 * (buyback_executed ? 1 : 0)
                      + 0.2 * min(actual_payout/target_payout, 1.0)
                      , 0, 1)
```

> 임계치(0.5, 0.6)·가중치(0.5/0.3/0.2)는 설정값(`config.py`)으로 노출해 튜닝 가능.

---

## 4. 데이터 소스 매핑

| 데이터 | 소스 | 라이브러리 |
|---|---|---|
| 기업 기본정보·재무제표 | DART 전자공시 OpenAPI | `dart-fss` |
| 밸류업 계획 공시 | DART "기업가치제고계획" 공시 | `dart-fss` + 파서 |
| 주가·시가총액 | KRX | `pykrx` |
| 배당·상장기업 재무 보강 | 금융위 **금융공공데이터** 개방 API | `requests` |
| 지표(ROE/ROA/PBR/PER/부채비율/배당성향/YoY) | `financials`×`prices` SQL 계산 | (내부 뷰) |

API Key는 `.env`의 `DART_API_KEY`, `FINDATA_API_KEY`로 주입.
