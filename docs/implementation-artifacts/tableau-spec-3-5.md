# Tableau 대시보드 구성 스펙 (Story 3.5)

Tableau Public에서 아래 순서대로 조립한다. 데이터 소스는 `exports/tableau/*.csv`
(생성: `python -m app.export.tableau`, 갱신 시 재실행 후 Tableau에서 Data → Refresh).
모든 CSV는 UTF-8 BOM이라 한글 종목명이 그대로 열린다.

공통 규칙
- **manifest.json이 스냅숏의 신원이다**: export는 5개 CSV+manifest를 원자적으로
  교체하므로, Tableau에 물리기 전 manifest의 `as_of`·`generated_at`·행수를 확인하고
  대시보드 제목의 기준일과 일치시킬 것. manifest가 없거나 행수가 다르면 그 디렉터리는
  깨진/오래된 스냅숏이다 — 사용 금지.
- **null = 빈 셀**은 "판단 불가/미집계"다. 0으로 읽지 말 것 — 집계 시 Tableau 기본이
  null 제외라 그대로 두면 되고, 색·라벨로 표시할 땐 회색(#9ca3af) 중립 처리(3.2 Figma
  null 시각언어·3.4 프론트와 동일).
- `washing_flag`는 `"true"/"false"/빈칸` 3값 — 필터 생성 시 빈칸을 "판정불가"로 별도 표기.
- `sector`는 DART induty 코드(예: 24213) — 표시용 업종명 매핑은 프로젝트 스코프 밖
  (API도 코드 그대로 반환). 필요하면 Tableau 별칭(Aliases)으로 수동 지정.
- 모든 스코어 계열 CSV는 **두 엔진이 모두 실행된 공통 as_of**로 뽑혀 있다(교집합이
  없으면 export 자체가 실패) — 대시보드 제목에 as_of를 표기해 기준일을 못 박을 것.

**데이터 타입 강제(연결 직후 필수 — Tableau 자동 추론을 믿지 말 것)**
| 필드 | 타입 | 이유 |
|---|---|---|
| `corp_code` | **String** | 숫자 추론 시 선행 0 소실(`00155319`→`155319`) — 관계·URL 전부 깨짐 |
| `sector` | **String** | 숫자형 KSIC 코드라 동일 위험 |
| `as_of`, `date` | Date | |
| `metrics_year`·`metrics_quarter`·`year`·`quarter` | Whole Number(불연속) | |
| `washing_flag`·`period_buyback_status` | String | 3값(true/false/빈칸)·4값 유지 |
| 스코어·지표 전부 | Number (decimal) | |

## 뷰 1 — 밸류업 점수 (valueup_scores.csv)

- 차트: 가로 막대(종목별 execution_score 내림차순).
- 행: corp_name / 열: execution_score.
- 색: washing_flag (true=경고색 #dc2626, false=기본 #2563eb, 빈칸=회색).
- 툴팁: achievement_rate·progress_rate·buyback_status.
- 필터: market, sector, washing_flag.

## 뷰 2 — 업종별 저평가 맵 (sector_valuation_map.csv)

- 차트: 트리맵. 그룹: sector → corp_name.
- 크기: mna_target_score. **주의: 크기가 null인 종목은 트리맵에서 통째로 사라진다** —
  CSV가 지킨 null 정직성이 화면에서 깨지는 지점이므로 아래 "미산정 시트"가 **필수**다.
- **[필수] 미산정 시트**: `COUNT(IF ISNULL([mna_target_score]) THEN 1 END)` 계산식으로
  "M&A 산출 N / 미산정·미지원 M" KPI 텍스트 시트를 만들어 트리맵 바로 아래 배치하고,
  미산정 종목명 목록(corp_name, sector)을 툴팁 또는 하단 텍스트 테이블로 노출.
  뷰 3 산점도도 동일 — 한 축(roe/pbr)이 null이면 mark가 안 생기므로 같은 KPI에
  "산점도 표시 N / 좌표 결측 M"을 함께 표기.
- 색: pbr 연속 그라디언트(낮을수록 진하게 = 저평가 강조), 중앙값 1.0 기준 diverging.
- 툴팁: per·ev_ebitda·valuation_score·population_basis(모집단이 sector인지
  market_fallback인지 — 2.7의 small-N 폴백 식별 계약을 화면까지 노출).
- 필터: market.

## 뷰 3 — ROE-PBR 산점도 (roe_pbr_scatter.csv)

- 차트: 산점도. 열: roe / 행: pbr.
- 색: execution_score 연속(빈칸=회색). 모양: washing_flag.
- 참조선: pbr=1.0 (저평가 기준선), roe=8% (시장 평균 근방 — /stats/summary avg_roe 참고).
- 레이블: corp_name (겹침 시 상위 execution_score만).
- 우하단(고ROE·저PBR) 사분면이 "밸류업 스토리 후보" — 대시보드 주석으로 표기.
- 필터: market, sector.

## 뷰 4 — 배당/자사주 (dividend_buyback.csv)

- 차트: 이중축 콤보 — **단위가 다르므로 두 축을 절대 합산·동일축 처리하지 말 것**:
  - 왼쪽 축(막대): SUM(dividend_total) — **금액(KRW)**. 축 제목 "배당총액(원)".
  - 오른쪽 축(라인 2개): buyback_amount·buyback_retired_amount — **주식 수(주)**.
    축 제목 "취득/소각 주식 수(주)". 소각량이 취득량의 부분집합일 수 있어
    **둘을 더하면 중복 계산** — 반드시 별도 라인으로 유지.
- 색: `period_buyback_status` — **그 연도의 원천 수량에서 계산된 기간별 상태**
  (retired=진초록, purchased_only=연두, none=회색, 빈칸=무관측 점선/회색).
  현재 스냅숏 상태(valueup_scores.csv의 buyback_status)와 다른 값이다 —
  과거 연도에 현재 상태를 칠하면 "그때도 소각했다"로 오독되므로 시계열엔
  이 컬럼만 쓸 것. 현재 상태는 뷰 1 툴팁/별도 KPI로만.
- 필터: corp_name(단일 선택 권장 — 종목별 환원 추이 뷰), market, sector.
- 주의: dividend_total은 best-effort 수집(없으면 빈칸) — 빈 해를 "배당 0"으로 읽지 말 것.

## 매크로 레이어 (macro_layer.csv)

- 차트: 지표별 라인 4장(base_rate·bond_3y·usd_krw·leading_index), 열: date(연속) / 행: value.
- 대시보드에서 뷰 1~4 하단에 가로 스트립으로 배치 — "매크로 국면 컨텍스트"(UX-DR5).
- frequency(M/D)가 달라 축 밀도가 다름 — 지표별 개별 시트로 만들고 y축 독립.

## 대시보드 배치

```
┌─────────────────────────────────────────────┐
│ 밸류업 워싱 스크리너 — as_of 2026-07-13     │
├──────────────────────┬──────────────────────┤
│ 뷰3 ROE-PBR 산점도   │ 뷰2 업종 저평가 맵    │
├──────────────────────┼──────────────────────┤
│ 뷰1 밸류업 점수      │ 뷰4 배당/자사주       │
├──────────────────────┴──────────────────────┤
│ 매크로 스트립: 기준금리·국고3y·환율·선행지수 │
└─────────────────────────────────────────────┘
```

- 전역 필터(market·sector)를 뷰 1~4에 적용(매크로 스트립은 종목 무관이라 제외).
- 게시: Tableau Public → 워크북 저장(로컬 CSV extract가 함께 업로드됨).
  데이터 갱신 시 export 재실행 → Tableau에서 extract refresh → 재게시.

## 검증 기준 (조립 후 확인)

- 각 뷰 종목/행 수 = **manifest.json의 views 행수**와 일치(뷰 1은 26, 2026-07-13 기준).
- `corp_code`가 선행 0 포함 8자리 문자열로 표시되는지(예: `00155319` — `155319`로
  보이면 타입 강제 누락).
- 워싱 비율 = `/stats/summary`의 washing_ratio와 일치(패리티는 export 시점에 코드로 검증됨).
- 매크로 최신값 4종 = `/stats/macro` 응답과 일치.
- 뷰 2/3의 미산정 KPI 시트가 존재하고, 산출+미산정 합계 = manifest 행수.
