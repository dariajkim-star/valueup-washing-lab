# Tableau 대시보드 구성 스펙 (Story 3.5)

Tableau Public에서 아래 순서대로 조립한다. 데이터 소스는 `exports/tableau/*.csv`
(생성: `python -m app.export.tableau`, 갱신 시 재실행 후 Tableau에서 Data → Refresh).
모든 CSV는 UTF-8 BOM이라 한글 종목명이 그대로 열린다.

공통 규칙
- **null = 빈 셀**은 "판단 불가/미집계"다. 0으로 읽지 말 것 — 집계 시 Tableau 기본이
  null 제외라 그대로 두면 되고, 색·라벨로 표시할 땐 회색(#9ca3af) 중립 처리(3.2 Figma
  null 시각언어·3.4 프론트와 동일).
- `washing_flag`는 `"true"/"false"/빈칸` 3값 — 필터 생성 시 빈칸을 "판정불가"로 별도 표기.
- `sector`는 DART induty 코드(예: 24213) — 표시용 업종명 매핑은 프로젝트 스코프 밖
  (API도 코드 그대로 반환). 필요하면 Tableau 별칭(Aliases)으로 수동 지정.
- 모든 스코어 계열 CSV는 **단일 as_of**(파일 내 `as_of` 컬럼)로 뽑혀 있다 —
  대시보드 제목에 as_of를 표기해 기준일을 못 박을 것.

## 뷰 1 — 밸류업 점수 (valueup_scores.csv)

- 차트: 가로 막대(종목별 execution_score 내림차순).
- 행: corp_name / 열: execution_score.
- 색: washing_flag (true=경고색 #dc2626, false=기본 #2563eb, 빈칸=회색).
- 툴팁: achievement_rate·progress_rate·buyback_status.
- 필터: market, sector, washing_flag.

## 뷰 2 — 업종별 저평가 맵 (sector_valuation_map.csv)

- 차트: 트리맵. 그룹: sector → corp_name.
- 크기: mna_target_score (빈칸 종목은 자동 제외됨 — 별도 목록으로 "미산정 N종목" 캡션 권장).
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

- 차트: 이중축 콤보. 열: year(불연속) / 행 1: SUM(dividend_total) 막대 /
  행 2: buyback_amount+buyback_retired_amount 라인(또는 누적 막대).
- 색: buyback_status (retired=진초록, purchased_only=연두, none=회색 — 워싱 신호 위계).
- 필터: corp_name(단일 선택 권장 — 종목별 환원 추이 뷰), sector.
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

- 뷰 1 종목 수 = valueup_scores.csv 행수(26, 2026-07-13 기준).
- 워싱 비율 = `/stats/summary`의 washing_ratio와 일치(패리티는 export 시점에 코드로 검증됨).
- 매크로 최신값 4종 = `/stats/macro` 응답과 일치.
