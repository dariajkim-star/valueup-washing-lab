# Review Bundle — Story 5-1 + 5-2 (2026-07-22)

v2 P1-1 커버리지 확대(백엔드)와 그 결과를 화면에 드러내는 스토리(프론트)를 **합본**으로 냅니다.
5-2는 5-1이 만든 값을 소비할 뿐이라 따로 보면 판단이 반쪽이 됩니다.

PR: #8(5-1, main `c402812`) · #9(5-2, main `fb7c203`).

## 이 스토리들이 바꾼 계약

**`execution_score`는 이제 "기업이 공시한 약속에 대해서만" 채점됩니다.** 이전에는 ROE·자사주·
배당 세 항목 중 하나라도 없으면 전체 null이었습니다. 이 변경은 NFR2("null > 틀린 값")를
건드리므로 **리드 결정으로 진행**했고, 그 판단이 이 리뷰의 1순위 검토 대상입니다.

근거: null에 서로 다른 두 상태가 섞여 있었습니다.
- **판단 불가** — 목표는 공시했는데 실적을 모른다 → 진짜 null
- **약속한 게 없음** — 애초에 ROE 목표를 공시하지 않았다 → 판단할 대상이 없다

후자를 null로 두면 배당·자사주는 약속하고 지킨 기업까지 "이행 판단 불가"가 되어 **오히려
정보를 지웁니다**. (4-2에서 `complete`/`publishable`을 나눈 것과 같은 구조의 오류로 봤습니다.)

## 착수 전 측정 — 백로그 전제가 틀렸다

v2 백로그는 P1-1의 원인을 "배당 커버리지 병목(수집)", 선행 조건을 "없음"으로 적었는데
실데이터로 분해하니 둘 다 아니었습니다.

| 입력 (계획 보유 26종목) | 가용 | |
|---|---|---|
| actual_roe / actual_payout / buyback | 20 / 18 / 19 | 수집 정상 |
| **target_roe / target_payout** | **11 / 4** | ← 병목 |

`target_payout` 4/26의 이유는 파싱 실패가 아니라 **의미 불일치**였습니다 — 기업들은
`배당성향`이 아니라 **`주주환원율`(배당+자사주매입)/순이익**으로 약속합니다
(공시 60건: 배당성향만 18 / 주주환원율만 9 / 둘 다 8 / 언급 없음 25).

도달 가능 커버리지(완료 기준 8종목+):

| 경로 | 도달 |
|---|---|
| ① 현재 | 1 |
| ② 주주환원율 별도 필드만 추가(엄격 AND 유지) | 3 (미달) |
| ③ ② + 공시한 항목만으로 채점 ← **채택** | **12** |

②가 막힌 이유는 ROE 목표를 아예 공시하지 않는 기업이 다수라(원문 언급조차 없는 공시 29/60)
엄격 AND의 천장이 9였기 때문입니다.

## AC 요약

**5-1**: 주주환원율 별도 파싱 / 뷰 `total_return_ratio` / 공시 항목만 채점 + 가중치 재정규화 /
`score_basis` 기록 / 약속 없으면 null 유지 / **약속했는데 실적 미상이면 그 항목을 빼지 않고
전체 null**(빼면 점수가 부풀려짐) / 커버리지 1 → 8종목+.

**5-2**: `/screening`·`/valueup/gap-analysis`에 `score_basis` 노출 / 리스트·상세에 근거 표시 /
단일 항목은 시각 구분 / `total_return`과 `payout`을 다른 라벨로 / 점수 null은 "판단 불가" /
**라이브 배선 실증**(프론트 DoD).

## 아키텍처 제약

- **AD-1**: 지표는 SQL VIEW 전용 — 실적 총주주환원율은 뷰에서 계산(엔진이 아님).
- **AD-4**: `valueup_score`의 유일 writer는 `gap_engine`.
- **AD-11**: 프론트는 REST API로만 접근(직접 DB 접근 없음).
- **NFR2 / SM-C1**: null > 틀린 값 / 억지 추정 금지.

## 설계상 의도된 선택 (재보고 불필요)

1. **공시 항목만 채점(가중치 재정규화)** — 리드 결정. 없는 값을 만드는 게 아니라 기업이 실제로
   한 약속에 대해서만 채점하므로 SM-C1 위반이 아니라고 봤습니다. *근거 자체가 틀렸다*는
   반박은 환영합니다.
2. **비교 가능성 약화는 인지하고 `score_basis`로 완화** — mna의 `population_basis` 선례.
3. **환원 항목은 총주주환원율 우선**(둘 다 공시 시). 더 포괄적인 약속이고, 두 지표는 정의가
   다르므로 섞지 않습니다.
4. **파서에 목표 표지 요구** — 아래 "구현 중 잡은 오독" 참조. 보수적으로 놓치는 쪽을 택했습니다.
5. **재파싱은 저장된 `raw_text`로 수행**(네트워크 미사용). 1.5의 raw_text 보존 계약 덕분입니다.
6. **null의 두 원인을 화면에서 나누지 않음** — API가 구분하지 않으므로 추정해서 나누지 않고
   둘 다 "판단 불가"로 둡니다.

## 알려진 것 (재보고 불필요)

- **단일 항목 채점 8종목**(`buyback` 6, `roe` 2). 자사주 단독은 이진값이라 0/100뿐입니다.
  `score_basis`로 드러나 있고, **랭킹 정렬 정책은 미해결로 명시 인계**했습니다.
- **`washing_flag` 불변**(None 7 / False 19 / True 0) — 이 판정은 `execution_score`를 쓰지
  않아 이번 변경 밖입니다. 백로그의 "19→25"는 달성되지 않았고 별도 원인 분해가 필요합니다.
- **Tableau CSV·워크북에 `score_basis` 미반영**.
- **P1-2(수동 태깅)는 PRD OQ-1 리드 확정 대기**로 별도.
- **스크린샷 환경 이슈**로 시각 증빙은 접근성 트리 + computed style + 네트워크 로그로 대체.

## 구현 중 잡은 오독 (참고 — 이미 고침)

주주환원율을 라벨+숫자로만 뽑으니 **13건 중 5건이 과거 실적**이었습니다. 계획 공시는 목표와
이행 실적을 같은 문서에 싣습니다.

| 오독 | 원문 |
|---|---|
| 고려아연 268.0% | `'25년 총 주주환원율 268.0%` |
| KT&G 108.9% | `[현금환원] … -> 총주주환원율 108.9%` |
| HMM 72.8% | `자기주식 취득 및 소각완료 … 총주주환원율 72.8%` |

268%를 목표로 저장했다면 달성률이 터무니없이 낮게 나와 워싱 판정을 오염시켰을 것입니다.
값 뒤 짧은 구간에 목표 표지(목표·지향·이상·확대·원칙·수준·계획)를 요구하도록 조였고
(PBR의 '배' 단위 요구와 같은 계열), 손 라벨링 13건 대조에서 **오독 0 / 보수적 놓침 1**입니다.

## 특히 봐주셨으면 하는 것

1. **채점 계약 변경의 타당성.** "약속한 게 없음"과 "판단 불가"를 나눈 것이 정말 정직성을
   높이는가, 아니면 점수를 후하게 만드는 합리화인가. 특히 **자사주 단독 100점**이 리스트에서
   기아의 3항목 100점과 같은 정렬 위치를 차지하는 현 상태를 어떻게 보시는지.
2. **`_execution_score`의 null 규칙이 새는 곳.** "약속했는데 실적 미상 → 전체 null"이
   모든 경로에서 지켜지는지(특히 `buyback_committed` 판정이 `buyback_planned is True`인 것,
   즉 None을 약속으로 치지 않는 처리).
3. **파서의 목표 표지 규칙이 과/소 차단하는 케이스.** 12자 창(`.{0,12}?`)과 표지 목록이
   실제 공시 문형을 얼마나 놓치는지. 정규식이 다른 지표의 목표 표지를 훔쳐올 여지는 없는지.
4. **뷰의 `total_return_ratio` 정의** — 자사주매입액 null이면 전체 null로 둔 판단
   (0으로 메우면 환원 과소평가). 분모 `net_income > 0` 조건이 적자 기업을 어떻게 다루는지.
5. **프론트 시각 언어가 3.2 범례와 충돌하지 않는지** — 앰버를 "워싱 의심" pill에 쓰고 있는데
   여기서는 캡션에 썼습니다. 형태가 달라 구분된다고 봤으나 사용자 혼동 가능성은 봐주세요.

## 검증 결과

- **백엔드 289 passed** (284 → +5) · **프론트 63 passed** (56 → +7) · `tsc -b --noEmit` exit 0
- 라이브: `execution_score` non-null **1 → 12/26종목(46%)**, 완료 기준 8종목+ 상회
- `score_basis` 분포: 미채점 14 / buyback 6 / roe 2 / roe+payout 1 /
  roe+buyback+total_return 1 / roe+buyback+payout 1 / buyback+total_return 1
- 프론트 라이브 배선: `GET /api/screening → 200`(Vite 프록시), 칩 12개 렌더,
  단일=앰버 `rgb(180,83,9)` / 다항목=회색 `rgb(156,163,175)`, 콘솔 오류 0

## 파일 (verbatim)

### `docs/implementation-artifacts/5-1-execution-score-coverage.md` (161행)

스토리 문서 (5-1)

````markdown
# Story 5-1 — execution_score 커버리지 확대 (v2 P1-1)

- **에픽**: 5 v2 커버리지 개선
- **상태**: review (구현·라이브 검증 완료)
- **작성일**: 2026-07-22
- **근거**: [v2-backlog](v2-backlog.md) P1-1 · [cx-analysis](../cx-analysis-2026-07-16.md)(3방법론 수렴)
- **선행**: 없음(4-2 교차리뷰 반영 완료, main `2a30bc9`)

## 착수 전 측정 — 백로그의 전제가 틀렸다

백로그는 P1-1의 원인을 **"배당 커버리지 병목"(수집)** 으로 적고 선행 조건을 "없음"으로 뒀다.
실데이터로 분해하니 둘 다 사실이 아니었다.

계획 보유 26종목 기준 입력 가용성:

| 입력 | 가용 | |
|---|---|---|
| actual_roe | 20 | 수집 정상 |
| actual_payout | 18 | 수집 정상 |
| buyback_amount | 19 | 수집 정상 |
| **target_roe** | **11** | ← 병목 |
| **target_payout** | **4** | ← 병목 |

**병목은 수집이 아니라 목표 필드다.** 그리고 `target_payout`이 4/26인 이유는 파싱 실패가
아니라 **의미 불일치**였다 — 기업들은 `배당성향`이 아니라 **`주주환원율`(배당+자사주매입)/순이익**
으로 약속한다. 공시 60건 분포: 배당성향만 18 / 주주환원율만 9 / 둘 다 8 / 언급 없음 25.

파서(`app/ingest/dart_valueup.py`)는 이미 이 구분을 알고 있었다 — 주석에
"주주환원율은 다른 지표라 target_payout_ratio에 넣지 않음"이라고 명시돼 있다. 의미 판단은
처음부터 옳았고, 빠진 것은 **받아줄 별도 필드**였다(deferred-work의 "주주환원율 별도 필드").

(파싱된 8건이 과거 실적을 목표로 오독한 건 아닌지도 확인했다 — "배당성향 최소 25%" 같은
진짜 목표였다. 오독 없음.)

## 도달 가능 커버리지 (26종목 기준, 완료 기준 8종목+)

| 경로 | 도달 | |
|---|---|---|
| ① 현재 | 1 | 미달 |
| ② 주주환원율 별도 필드만 추가(엄격 AND 유지) | 3 | **미달** |
| ③ ② + 공시한 항목만으로 채점 | **11** | 달성 |

②가 막히는 이유는 `target_roe`다 — **ROE 목표를 아예 공시하지 않는 기업이 많다**(원문에 언급
자체가 없는 공시 29/60). 세 항목 엄격 AND를 유지하는 한 천장이 9종목이고, 파싱이나 수동
태깅으로는 뚫을 수 없다(원문에 없는 값을 만들어낼 수는 없으므로).

## 결정 (리드, 2026-07-22)

**③ 채택** — 주주환원율 별도 필드 + **기업이 공시한 항목만으로 채점**(가중치 재정규화) +
`score_basis` 노출.

### 왜 이것이 NFR2("null > 틀린 값") 위반이 아닌가

지금 `execution_score`의 null에는 **두 개념이 섞여 있다**.

- **"판단 불가"** — 목표는 공시했는데 실적을 모른다 → 진짜 null이 맞다.
- **"약속한 게 없음"** — 애초에 ROE 목표를 공시하지 않았다 → 판단할 대상이 없는 것이지,
  판단에 실패한 것이 아니다.

후자를 null로 두는 것은 정직한 게 아니라 **오히려 정보를 지우는 쪽**이다. 배당·자사주는
약속하고 지켰는데 ROE를 약속하지 않았다는 이유로 "이행 점수 판단 불가"가 되면, 그 기업이
자기 약속을 지켰는지에 대한 판단을 포기하는 것이다. 이는 4-2에서 `complete`(실행 성공)와
`publishable`(게시 가능)을 분리한 것과 **같은 구조의 오류** — 서로 다른 두 상태를 한 null에
담고 있었다.

억지 추정(SM-C1)과도 구분된다: 없는 값을 만들어내는 것이 아니라, **기업이 실제로 한 약속에
대해서만 채점**한다.

### 대가와 완화

가중치 기반이 종목마다 달라 **점수의 종목 간 비교 가능성이 약해진다**. 이는 mna의
population 문제와 같은 계열이므로 같은 방식으로 완화한다 — **`score_basis`에 어떤 항목으로
채점됐는지 기록·노출**(`population_basis` 선례). 랭킹·UI는 이 값을 함께 보여줘야 한다.

## 범위

- `valueup_plan.target_total_return_ratio` 신규 컬럼 + 파서 추출
- `valuation_metrics` 뷰에 `total_return_ratio` = (배당총액+자사주매입액)/당기순이익
- `_execution_score` 재작성: 공시 항목만으로 가중치 재정규화, `score_basis` 반환
- `valueup_score.score_basis` 신규 컬럼 + API 응답 노출
- 마이그레이션 0012

**비범위**: 프론트 표시(`score_basis` 시각 언어) → 후속 스토리. P1-2(수동 태깅 레이어)는
PRD OQ-1 리드 확정 대기로 별도.

## 인수 조건

- **AC1** 주주환원율 목표가 `target_total_return_ratio`로 파싱된다(배당성향과 섞이지 않는다).
- **AC2** 뷰가 `total_return_ratio` 실적을 산출한다.
- **AC3** `execution_score`가 공시한 항목만으로 채점되고, 가중치는 그 항목들에 재정규화된다.
- **AC4** `score_basis`에 채점에 쓰인 항목이 기록된다(예: `payout+buyback`).
- **AC5** 약속 항목이 하나도 없으면 여전히 null(진짜 판단 불가는 보존).
- **AC6** 목표는 있는데 실적이 없으면 그 항목은 제외가 아니라 **null 전파**(판단 불가 유지).
- **AC7** 실데이터 커버리지 1종목 → 8종목 이상.
- **AC8** 기존 테스트 전건 통과(284) + 신규.

## 검증 계획

- 단위: 재정규화 산식(항목 조합별), AC5/AC6 경계
- 통합: SQLite in-memory + 뷰
- 라이브: 실 DB 재계산 후 커버리지 측정(1 → ?), `score_basis` 분포 확인

## 검증 결과 (2026-07-22)

**AC7 달성** — execution_score non-null **1 → 12종목 / 26 (46%)**. 완료 기준(8종목+) 상회.

```
score_basis 분포
  (미채점)                   14
  buyback                    6
  roe                        2
  roe+payout                 1
  roe+buyback+total_return   1
  roe+buyback+payout         1
  buyback+total_return       1
```

**289 passed** (284 → +5). 재파싱은 네트워크 없이 저장된 `raw_text`에 새 파서를 적용해 수행했다
(`parse_targets`가 공개 함수라 가능 — raw_text 보존 계약이 여기서 값을 했다).

### 구현 중 잡은 오독 — 목표와 실적이 한 문서에 있다

주주환원율을 라벨+숫자만으로 뽑으니 **13건 중 5건이 과거 실적**이었다. 계획 공시는 목표와
이행 실적을 같은 문서에 싣기 때문이다.

| 오독 사례 | 실제 의미 |
|---|---|
| 고려아연 268.0% | `'25년 총 주주환원율 268.0%` — 실적 |
| 고려아연 113.1% | `'25년 상반기 기준 … 113.1% 기록` — 실적 |
| KT&G 108.9% | `[현금환원] 1조 1,874억원 -> 총주주환원율 108.9%` — 실적 |
| HMM 72.8% | `자기주식 취득 및 소각완료 … 총주주환원율 72.8%` — 실적 |
| 셀트리온 78% | `주주환원 현황('22~'24 3년 평균 … 78%)` — 실적 |

268%를 목표로 저장했다면 달성률이 터무니없이 낮게 나와 워싱 판정을 오염시켰을 것이다.
**값 뒤 짧은 구간에 목표 표지(목표·지향·이상·확대·원칙·수준·계획)를 요구**하도록 조였고,
PBR이 '배' 단위를 요구하는 것과 같은 계열의 방어다.

손으로 라벨링한 13건 정답 대조: **오독 0건 / 보수적 놓침 1건**(신한 plan 38 — 목표 표지가
값보다 앞 문장에 있어 놓침. 같은 기업의 다른 공시가 잡히므로 실효 손실 없음). 놓침은
NFR2상 허용이고 오독은 아니다.

한 문서에 실적과 목표가 함께 있으면 **목표 쪽을 집는지**도 확인했다(셀트리온: 현황 78%를
건너뛰고 목표 40% 채택). 이 케이스는 처음에 내가 정답 라벨을 "실적"으로 잘못 달았다가
원문을 다시 읽고 정정한 것이다 — 파서가 옳고 내 라벨이 틀렸다.

### 부수로 드러난 결함

`latest_metrics`가 `SELECT roe, payout_ratio`로 **컬럼을 명시 선택**하고 있어, 뷰에 새 컬럼을
추가해도 엔진까지 오지 않았다(신한·셀트리온·메리츠는 뷰에 값이 있는데 basis에 `total_return`이
한 번도 안 나타남). 컬럼 추가 시 이 지점을 함께 봐야 한다.

### 남는 한계

- **단일 항목 채점 8종목**(`buyback` 6, `roe` 2). 특히 `buyback` 단독은 이진값이라 점수가
  0 또는 100뿐이다 — `score_basis`로 드러나 있으나, 랭킹에서 단일 항목 점수를 다항목 점수와
  나란히 세우는 것이 타당한지는 UI 스토리에서 다뤄야 한다.
- **`washing_flag`는 불변**(None 7 / False 19 / True 0). 이 판정은 `progress_rate`·
  `achievement_rate`·자사주에 의존하고 execution_score를 쓰지 않으므로 이번 변경의 영향 밖이다.
  백로그의 "washing_flag 19→25" 목표는 이 스토리로 달성되지 않는다 — 별도 원인 분해 필요.
- 프론트는 `score_basis`를 아직 표시하지 않는다(비범위) — 기준이 다른 점수를 같은 척도처럼
  보이게 두는 기간이 생긴다. **후속 스토리 우선순위 높음**.
````

### `docs/implementation-artifacts/5-2-score-basis-frontend.md` (99행)

스토리 문서 (5-2)

````markdown
# Story 5-2 — score_basis 프론트 표시

- **에픽**: 5 v2 커버리지 개선
- **상태**: review (구현·라이브 배선 실증 완료)
- **작성일**: 2026-07-22
- **선행**: [5-1](5-1-execution-score-coverage.md)(main `c402812`)

## 왜 곧바로 이어서 하는가

5-1로 백엔드는 정직해졌지만 **화면이 따라가지 않은 상태**였다. `execution_score`는 이제
기업이 공시한 약속에 대해서만 채점되므로 가중치 기반이 종목마다 다른데, 리스트에는 숫자만
떠서 기준이 다른 점수가 **같은 척도처럼** 보였다. 실데이터가 이 문제를 그대로 보여준다:

| 종목 | 점수 | 실제 근거 |
|---|---|---|
| 기아 | 100 | `roe+buyback+payout` — 세 약속 모두 이행 |
| 삼성전자 | 100 | `buyback` 단독 — 자사주 하나만 공시했고 실행함 |

같은 100점이지만 의미가 전혀 다르다. 자사주 단독은 이진값이라 **0 또는 100뿐**이다.
이 간극을 두는 것은 3.2에서 정한 "null을 빈칸·0으로 뭉개지 않는다"와 같은 종류의 위반이다 —
값을 왜곡하진 않지만 **비교 가능성에 대한 정보를 지운다**.

## 결정

**`population_basis` 선례를 그대로 따른다.** 점수 옆에 근거를 항상 붙이고, 별도 클릭 없이
읽히게 한다(툴팁 뒤에 숨기지 않는다 — 숨기면 안 본다).

**단일 항목은 시각적으로 구분한다.** 다항목은 회색 캡션(`#9ca3af`)으로 조용히,
단일 항목은 앰버(`#b45309`) + `~만` 표기로 주의를 준다. 3.2의 앰버는 "워싱 의심"에 쓰이지만
여기서는 pill이 아닌 캡션이라 형태가 달라 혼동되지 않는다.

**라벨은 지표 이름 그대로**: `roe`→ROE, `buyback`→자사주, `payout`→배당성향,
`total_return`→**주주환원**. 배당성향과 주주환원율을 다른 말로 적는 것이 이 스토리의 핵심 —
5-1에서 둘을 별도 필드로 나눈 이유가 화면에서도 유지돼야 한다.

**점수 null 표시 개선**: 기존엔 `—`만 떴다. `판단 불가` 캡션을 함께 붙인다(2.4 API 계약이
요구하는 문구이자 3.2 시각 언어의 상태 중 하나인데 이 셀에만 빠져 있었다). 다만 null의 두
원인("약속 자체가 없음" vs "약속은 있으나 실적 미상")은 API가 구분하지 않으므로 **추정해서
나누지 않는다** — 둘 다 "판단 불가"로 정직하게 둔다.

## 범위

- `ScreeningOut`·`GapAnalysisOut`에 `score_basis` 노출 + screening 리포지토리 선택
- 프론트 타입 2종, `ScoreBasisChip` 신규, `ValueUpCell`·상세 `ScoreChip` 배선
- 백엔드/프론트 테스트

**비범위**: 랭킹에서 단일 항목 점수를 다항목과 같은 정렬에 세우는 문제(정렬 정책 변경은
별도 결정 — 지금은 "보이게 하기"까지). Tableau 쪽 표시.

## 인수 조건

- **AC1** `/screening`·`/valueup/gap-analysis` 응답에 `score_basis`가 포함된다.
- **AC2** 리스트에서 점수와 근거가 함께 보인다.
- **AC3** 단일 항목 근거는 다항목과 시각적으로 구분된다.
- **AC4** `total_return`이 "주주환원"으로, `payout`이 "배당성향"으로 **다르게** 표시된다.
- **AC5** 점수 null은 `—` + "판단 불가"로 표시된다.
- **AC6** 상세 화면 실행점수 칩에도 근거가 붙는다.
- **AC7** 기존 테스트 전건 통과 + 신규.
- **AC8** **라이브 배선 실증**(네트워크 로그 + 실제 렌더 확인) — 프론트 DoD.

## 검증 결과 (2026-07-22)

**백엔드 289 passed · 프론트 63 passed**(56 → +7). `tsc -b --noEmit` exit 0.

### 라이브 배선 실증 (AC8)

백엔드 `uvicorn:8000` + Vite `:5175`, 실 DB 32종목.

**네트워크**: `GET /api/screening?sort=execution_score&page=1&size=20 → 200`
(Vite 프록시 경유 — 목업 아님)

**응답에 필드 존재**:
```
기아(주)     execution_score=100.0  score_basis="roe+buyback+payout"
삼성전자(주)  execution_score=100.0  score_basis="buyback"
```

**실제 렌더**(computed style로 확인 — 접근성 트리는 `title` 속성을 읽으므로 별도 검증):

| 표시 텍스트 | 색 | |
|---|---|---|
| `ROE·자사주·배당성향` | `rgb(156,163,175)` | 다항목 = 회색 |
| `ROE·자사주·주주환원` | `rgb(156,163,175)` | **주주환원 라벨 동작**(AC4) |
| `자사주만` | `rgb(180,83,9)` | 단일 = 앰버(AC3) |
| `ROE만` | `rgb(180,83,9)` | |

총 12개 칩 렌더, 전부 `visible: true`. 콘솔 오류 0건.

**상세 화면**(삼성전자): `실행점수 100/100 자사주만` — AC6 확인.

스크린샷은 환경 이슈로 타임아웃(기존에 기록된 제약)이라, 접근성 트리 + computed style +
네트워크 로그로 대체 증빙했다.

## 인계

- **랭킹 정렬 정책은 미해결**. 지금은 `buyback` 단독 100점이 `roe+buyback+payout` 100점과
  같은 정렬 위치를 차지한다. 보이게는 했으나 **정렬은 여전히 두 값을 동일 취급**한다 —
  단일 항목을 후순위로 밀지, 별도 구간으로 나눌지, 그대로 둘지는 별도 결정이 필요하다.
- Tableau CSV·워크북에는 `score_basis`가 아직 없다(5-1 export 미반영).
````

### `app/analysis/gap_engine.py` (371행)

**핵심 변경** — `_execution_score` 재작성

```python
"""Value-up 갭 스코어링 엔진 (writer = 이 모듈, AD-4).

Epic 1(수집)과 다른 새 패턴: HTTP 어댑터가 아니라 **순수 계산**. 입력은 이미 DB에 있다
(valuation_metrics 뷰 + valueup_plan + financials.buyback_*). 산식은 scoring.md 참조.

null 전파가 핵심 계약(2026-07-10 코드리뷰로 scoring.md 강화): 입력이 애매/누락이면
0이나 False로 강제하지 않고 해당 스코어도 null로 전파한다(NFR2 "null > 틀린 값").
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.repositories import valueup_score as repo

logger = logging.getLogger(__name__)

_AS_OF_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class InvalidAsOfError(ValueError):
    """as_of 입력이 잘못됐다 — **사용법 오류**이지 엔진 실패가 아니다.

    CLI가 "사용법 오류(종료 코드 2)"와 "엔진 실행 실패(종료 코드 1)"를 구분하려면 전용 타입이
    필요하다(코드리뷰 2026-07-22 High). 이전엔 CLI가 맨 `ValueError`를 잡아 종료 코드 2로
    번역했는데, 엔진 깊은 곳에서 올라온 무관한 ValueError까지 사용법 오류로 세탁됐다.
    ValueError를 상속해 기존 호출자(`pytest.raises(ValueError)` 포함)와의 호환은 유지한다.
    """


def _validate_as_of(as_of: str) -> None:
    """as_of가 zero-padded YYYY-MM-DD **이자 달력상 유효**한지 fail-fast.

    정규식만으론 2025-02-30이 통과(코드리뷰 2026-07-10 Med) — 세 입력원(metrics 연도,
    ownership·macro 문자열 비교)이 무효 날짜를 서로 다르게 해석하는 것을 진입점에서 차단.
    gap_engine·mna_engine 공용(중복 정의 금지).
    """
    if not _AS_OF_RE.match(as_of):
        raise InvalidAsOfError(f"as_of는 YYYY-MM-DD 형식이어야 합니다: {as_of!r}")
    try:
        date.fromisoformat(as_of)
    except ValueError:
        raise InvalidAsOfError(f"as_of가 달력상 유효한 날짜가 아닙니다: {as_of!r}") from None


def _safe_ratio(actual: float | None, target: float | None) -> float | None:
    """target이 없거나 0 이하면 계산 불가(0 나눗셈·역설 방어) → None."""
    if actual is None or target is None or target <= 0:
        return None
    return actual / target


def _progress_rate(
    period_start: str | None, period_end: str | None, as_of: date
) -> float | None:
    """계획기간 대비 진척률, [0,1] 클램프. **일 단위 정밀도**(코드리뷰 2026-07-21 결정 B).

    scoring.md 원식은 `(today - period_start) / (period_end - period_start)` — 처음부터
    날짜 기반이었고, 이전 연 단위 구현이 스펙 이탈이었다(연도가 바뀌는 1/1에 진척률이
    1/(end-start)만큼 점프 → washing_flag 임계 0.5를 하루 사이에 넘는 종목 발생).

    입력이 연도 문자열뿐이므로 경계 규약: 시작 = 시작연도 1/1, 종료 = 종료연도 12/31.
    end <= start는 계속 None — 0나눗셈은 이제 아니지만(단년 계획도 분모 364일), 단년 계획
    수용은 AC3 계약("null·end<=start 무효") 변경이라 별도 결정으로 defer(deferred-work.md).
    """
    if period_start is None or period_end is None:
        return None
    try:
        start, end = int(period_start), int(period_end)
    except (TypeError, ValueError):
        return None
    if end <= start:
        return None
    period_begin = date(start, 1, 1)
    period_close = date(end, 12, 31)
    raw = (as_of - period_begin).days / (period_close - period_begin).days
    return max(0.0, min(1.0, raw))


def _achievement_rate(actual_roe: float | None, target_roe: float | None) -> float | None:
    """achievement_rate = 실제 ROE / 목표 ROE. ROE 단독(배당은 execution_score에서 별도 가중,
    이중반영 방지 — 2026-07-10 리드 결정). target_pbr은 산식 미사용."""
    return _safe_ratio(actual_roe, target_roe)


def _buyback_signals(
    amount: int | None, retired_amount: int | None
) -> tuple[bool | None, bool | None, str]:
    """(buyback_executed, buyback_retired, buyback_status). 수량 null=unknown, 0=확정 없음.

    음수는 수량 도메인에 없음(1.8 `_parse_quantity`가 상류에서 이미 걸러 DB엔 안 들어오지만,
    이 함수는 DB 값을 그대로 믿지 않고 자체 방어— 코드리뷰 High, GPT). 음수도 unknown 취급.
    """
    executed = None if amount is None or amount < 0 else amount > 0
    retired = None if retired_amount is None or retired_amount < 0 else retired_amount > 0
    if executed is None or retired is None:
        status = "unknown"
    elif retired:
        status = "retired"
    elif executed:
        status = "purchased_only"
    else:
        status = "none"
    return executed, retired, status


def _execution_score(
    achievement_rate: float | None,
    buyback_executed: bool | None,
    actual_payout: float | None,
    target_payout: float | None,
    w_achievement: float,
    w_buyback: float,
    w_payout: float,
    *,
    roe_committed: bool = True,
    buyback_committed: bool = True,
    actual_total_return: float | None = None,
    target_total_return: float | None = None,
) -> tuple[float | None, str | None]:
    """(execution_score, score_basis) — **기업이 공시한 약속에 대해서만** 채점(5-1, 리드 결정).

    이전엔 세 항 중 하나라도 없으면 전체 null이었다. 그런데 그 null에는 서로 다른 두 상태가
    섞여 있었다(4-2에서 complete/publishable을 나눈 것과 같은 구조의 오류):

    - **판단 불가** — 목표는 공시했는데 실적을 모른다 → 진짜 null이 맞다.
    - **약속한 게 없음** — 애초에 ROE 목표를 공시하지 않았다 → 판단할 대상이 없는 것이지
      판단에 실패한 것이 아니다. 이걸 null로 두면 배당·자사주는 약속하고 지킨 기업까지
      "이행 판단 불가"가 되어 **오히려 정보를 지운다**.

    그래서 약속한 항목만 골라 그 항목들에 가중치를 재정규화한다. 없는 값을 만들어내는 것이
    아니므로 "억지 추정 금지"(SM-C1)와도 어긋나지 않는다 — 실데이터에서 ROE 목표를 아예
    공시하지 않는 기업이 다수라(원문 언급조차 없는 공시 29/60) 엄격 AND는 천장이 낮았다.

    **대가**: 가중치 기반이 종목마다 달라 점수의 종목 간 비교 가능성이 약해진다. 그래서
    어떤 항목으로 채점했는지를 `score_basis`로 함께 돌려준다(mna의 population_basis와 같은
    이유 — 기준이 다른 값을 같은 척도처럼 쓰는 것을 막는다).

    환원 항목은 **배당성향과 총주주환원율 중 기업이 약속한 쪽**을 쓴다(둘 다면 총주주환원율
    우선 — 자사주까지 포함하는 더 포괄적인 약속이다). 두 지표는 정의가 다르므로 섞지 않는다.

    약속했는데 실적을 모르면 그 항목을 **빼지 않고 전체를 null로 만든다**(AC6) — 빼면 모르는
    항목을 유리하게 무시한 셈이 되어 점수가 부풀려진다.
    """
    parts: list[tuple[str, float, float]] = []  # (basis명, 가중치, 0~1 달성도)

    if roe_committed:
        if achievement_rate is None:
            return None, None  # 약속했는데 실적 미상 → 판단 불가
        parts.append(("roe", w_achievement, min(achievement_rate, 1.0)))

    if buyback_committed:
        if buyback_executed is None:
            return None, None
        parts.append(("buyback", w_buyback, 1.0 if buyback_executed else 0.0))

    # 총주주환원율 우선(더 포괄적인 약속) — 둘의 정의가 다르므로 하나만 쓴다
    if target_total_return is not None:
        ratio = _safe_ratio(actual_total_return, target_total_return)
        if ratio is None:
            return None, None
        parts.append(("total_return", w_payout, min(ratio, 1.0)))
    elif target_payout is not None:
        ratio = _safe_ratio(actual_payout, target_payout)
        if ratio is None:
            return None, None
        parts.append(("payout", w_payout, min(ratio, 1.0)))

    if not parts:
        return None, None  # 공시된 약속이 하나도 없다 — 채점할 대상 자체가 없음(AC5)

    total_w = sum(w for _, w, _ in parts)
    if total_w <= 0:  # 설정 이상(가중치 0) — 0나눗셈 방어
        return None, None
    raw = sum(w * v for _, w, v in parts) / total_w
    basis = "+".join(name for name, _, _ in parts)
    return 100 * max(0.0, min(1.0, raw)), basis


def _washing_flag(
    progress_rate: float | None,
    achievement_rate: float | None,
    buyback_planned: bool | None,
    buyback_retired: bool | None,
    progress_min: float,
    achievement_max: float,
) -> bool | None:
    """3치(Kleene) AND. 네 항 중 하나라도 **확정 False**면 나머지가 unknown이어도 전체 False
    (예: 소각이 확정 이뤄졌으면[buyback_retired=True] 진척률을 몰라도 워싱 아님이 확정된다).
    확정 False가 없고 하나라도 None이면 None(판단 불가). 전부 확정 True면 True.

    (코드리뷰 2026-07-10 Med, GPT) 이전엔 "하나라도 None→전체 None"이라 과잉보수적이었다
    — false positive는 없었지만 확정 가능한 케이스까지 불필요하게 '판단 불가'로 만들었다.
    scoring.md·AC6도 이 3치 논리로 함께 갱신(2026-07-10).
    """
    terms = (
        None if progress_rate is None else progress_rate >= progress_min,
        None if achievement_rate is None else achievement_rate < achievement_max,
        buyback_planned,
        None if buyback_retired is None else not buyback_retired,
    )
    if any(term is False for term in terms):
        return False
    if any(term is None for term in terms):
        return None
    return True


@dataclass
class ScoreRunResult:
    """run()의 결과. 부분 성공을 허용하므로 '몇 건'뿐 아니라 '무엇이 실패했는지'를 함께 싣는다.

    수집 레이어의 IngestResult(app/ingest/run.py)와 동형 — 두 레이어의 트랜잭션 정책이
    같으므로 결과 표현도 같게 유지한다(코드리뷰 2026-07-21).
    """

    scored: int = 0  # upsert된 종목 수
    deleted: int = 0  # 근거(plan)를 잃어 정리된 종목 수
    succeeded: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (corp_code, reason)

    @property
    def complete(self) -> bool:
        """실패 0건 = **이번 실행이 대상으로 삼은 종목**이 모두 저장됐다.

        False면 valueup_score의 해당 as_of에는 이번 실행분과 이전 실행분이 **섞여 있다**.
        게시·비교 용도로 쓰기 전에 반드시 확인할 것(트레이드오프는 아래 run() docstring).

        주의(코드리뷰 2026-07-22 High): 이것은 "전 종목이 동일 시점"을 뜻하지 **않는다**.
        corp_codes 부분집합 실행이면 대상 밖 종목은 이전 실행분 그대로이므로,
        complete=True여도 스냅숏 전체는 여전히 부분적이다. 두 개념을 섞지 말 것.
        """
        return not self.failed


def _score_one(session: Session, corp_code: str, as_of: str, as_of_date: date) -> bool:
    """한 종목의 스코어를 계산·저장. upsert면 True, 근거 없어 정리했으면 False.

    호출자(run)가 종목당 트랜잭션을 소유한다 — 이 함수는 커밋하지 않는다.
    """
    plan = repo.latest_valueup_plan(session, corp_code, as_of)
    if plan is None:
        repo.delete_valueup_score(session, corp_code, as_of)
        return False

    metrics = repo.latest_metrics(session, corp_code, as_of)
    buyback = repo.latest_financial_buyback(session, corp_code, as_of)
    actual_roe = metrics.get("roe") if metrics else None
    actual_payout = metrics.get("payout_ratio") if metrics else None
    actual_total_return = metrics.get("total_return_ratio") if metrics else None
    amount = buyback.get("buyback_amount") if buyback else None
    retired_amount = buyback.get("buyback_retired_amount") if buyback else None

    progress_rate = _progress_rate(plan["period_start"], plan["period_end"], as_of_date)
    # AC3: 계획기간이 무효(null·end<=start)면 achievement_rate도 계산하지 않고 null로
    # 명시한다(코드리뷰 High, GPT — 이전 구현은 progress_rate만 null이 되고 achievement_rate는
    # 별개로 계산돼 AC3를 위반했다). execution_score는 achievement_rate가 None이면 이미 null.
    achievement_rate = (
        None if progress_rate is None
        else _achievement_rate(actual_roe, plan["target_roe"])
    )
    executed, retired, status = _buyback_signals(amount, retired_amount)
    # 어떤 항목을 "약속했는가"의 판정(5-1): 목표를 공시했는지 여부다. ROE는 target_roe 존재,
    # 자사주는 buyback_planned가 확정 True일 때만(None=언급 불명은 약속으로 치지 않는다 —
    # _washing_flag가 buyback_planned를 3치로 다루는 것과 같은 기준).
    execution_score, score_basis = _execution_score(
        achievement_rate, executed, actual_payout, plan["target_payout_ratio"],
        settings.score_w_achievement, settings.score_w_buyback, settings.score_w_payout,
        roe_committed=plan["target_roe"] is not None,
        buyback_committed=plan["buyback_planned"] is True,
        actual_total_return=actual_total_return,
        target_total_return=plan["target_total_return_ratio"],
    )
    washing_flag = _washing_flag(
        progress_rate, achievement_rate, plan["buyback_planned"], retired,
        settings.washing_progress_min, settings.washing_achievement_max,
    )

    # 목표·실제·갭 동결(2.4 표시용): 엔진이 고른 값 그대로 저장(AC3 게이팅과 무관한 원값)
    target_roe = plan["target_roe"]
    roe_gap = (
        actual_roe - target_roe
        if actual_roe is not None and target_roe is not None
        else None
    )
    repo.upsert_valueup_score(
        session,
        {
            "corp_code": corp_code,
            "as_of": as_of,
            "target_roe": target_roe,
            "actual_roe": actual_roe,
            "roe_gap": roe_gap,
            "achievement_rate": achievement_rate,
            "progress_rate": progress_rate,
            "execution_score": execution_score,
            "washing_flag": washing_flag,
            "buyback_executed": executed,
            "buyback_retired": retired,
            "buyback_status": status,
            "score_basis": score_basis,
        },
    )
    return True


def run(
    as_of: str,
    corp_codes: Sequence[str] | None = None,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> ScoreRunResult:
    """as_of 기준으로 corp별 valueup_score를 계산·upsert. ScoreRunResult 반환.

    트랜잭션 정책(결정, 코드리뷰 2026-07-21): **종목별 커밋 + 실패 목록**. 한 종목의
    계산·저장 실패가 이미 성공한 다른 종목의 결과를 되돌리지 않도록 부분 성공을 허용한다.
    수집 레이어(app/ingest/run.py)와 동일한 정책·동일한 결과 표현(IngestResult)을 쓴다 —
    두 레이어가 다른 규칙을 가지면 읽는 사람이 매번 어느 쪽인지 확인해야 한다.

    트레이드오프(명시): 부분 성공은 같은 as_of 안에 **이번 실행분과 이전 실행분이 섞일 수**
    있다는 뜻이다. 전량 원자성(하나 실패 시 전량 롤백)은 이 섞임을 없애지만, 실패한 종목이
    무엇이었는지도 함께 지운다. 섞임을 없애는 대신 **숨기지 않는** 쪽을 택했다 —
    `ScoreRunResult.complete`가 False면 그 스냅샷은 불완전하다(게시 전 확인 필요).

    세션은 이 함수가 소유한다(종목당 짧은 트랜잭션). 호출자가 세션을 넘기지 않는 것은
    의도된 설계 — 넘겨받은 세션에 커밋을 걸면 호출자의 다른 미저장 작업까지 함께 커밋된다.
    테스트는 session_factory로 자체 엔진을 주입한다.

    valueup_plan이 없는 종목은 목표가 없어 갭을 정의할 수 없으므로 행을 만들지 않는다
    (1-6 no-data 교훈과 동일 원칙). 이전에 plan이 있어 score가 생성됐다가 이후 plan이
    삭제/정정된 경우, 근거를 잃은 기존 score도 함께 정리한다(코드리뷰 High, GPT: gap_engine이
    valueup_score의 유일 writer(AD-4)이므로 정합성 유지 책임도 이 모듈에 있음).

    as_of는 YYYY-MM-DD 형식만 허용(fail-fast) — 비표준 포맷은 disclosure_date와의 문자열
    비교(사전식)를 실제 날짜 비교와 어긋나게 만들 수 있다(코드리뷰 High, GPT).
    """
    _validate_as_of(as_of)
    # 기본 인자로 두면 정의 시점에 객체가 고정돼 테스트가 모듈 속성만 바꿔선 못 막는다
    # (코드리뷰 2026-07-22 Med — 실 DB 오염 사고의 구조적 원인).
    session_factory = session_factory or SessionLocal
    as_of_date = date.fromisoformat(as_of)  # _validate_as_of 통과 직후라 안전

    if corp_codes is None:
        with session_factory() as session:
            corp_codes = repo.list_all_corp_codes(session)

    result = ScoreRunResult()
    for corp_code in corp_codes:
        try:
            with session_factory() as session, session.begin():  # 종목당 짧은 트랜잭션
                upserted = _score_one(session, corp_code, as_of, as_of_date)
        except Exception as e:  # noqa: BLE001 (부분성공 정책 — ingest/run.py와 동일)
            logger.warning(
                "스코어 계산 실패 corp_code=%s: %s", corp_code, type(e).__name__
            )
            result.failed.append((corp_code, str(e)))
            continue
        if upserted:
            result.scored += 1
        else:
            result.deleted += 1
        result.succeeded.append(corp_code)
    return result
```

### `app/ingest/dart_valueup.py` (429행)

**핵심 변경** — 주주환원율 파싱 + 목표 표지 규칙

```python
"""DART 밸류업 계획공시 어댑터 — valueup_plan의 writer (AD-3, source="dart").

"기업가치 제고 계획"은 구조화 재무 API가 없는 **자유서식 공시**라 2단계로 수집한다:
  1) list.json(공시검색, JSON)  → report_nm 매칭으로 밸류업 공시 발견(다중·다중페이지)
  2) document.xml(ZIP 바이너리) → 압축 해제·태그 스트립으로 원문 raw_text 확보

정확성 계약의 핵심 = **raw_text 보존 + 멱등 upsert**. 목표 필드(ROE·배당성향·PBR·기간·자사주)는
best-effort 정규식이며 **애매하면 null**(틀린 non-null 값 금지 — 코드리뷰 반영).

설계 규약(코드리뷰 반영):
- **문서별 격리**: 한 문서/후반 페이지 실패가 그 종목의 이미 모은 공시를 날리지 않는다.
- **성공/실패 구분**: 유효 문서를 파싱한 결과만 upsert(권위) → repository가 목표필드를 null 포함
  전체 교체. 문서 fetch 실패(비ZIP·HTTP오류·빈 응답)는 upsert하지 않아 기존 레코드를 보존한다.
- ⚠️ document.xml은 ZIP 바이너리 → dart.py의 `_get`(resp.json) 재사용 금지. `_fetch_document`는
  `resp.content`를 쓰고, 실패는 DartDocumentError로 격리. HTTP 하드닝·키 미노출은 dart.py 재사용.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from sqlalchemy.orm import Session
from urllib3.util.retry import Retry

from app.config import settings
from app.ingest.base import SourceAdapter
from app.ingest.dart import (
    _BASE,
    _MIN_INTERVAL,
    _TIMEOUT,
    DartAdapterError,
    _RateLimiter,
)
from app.repositories.valueup_plan import upsert_valueup_plan

# report_nm 매칭(공백 제거 후 부분일치). pblntf_ty로 좁히지 않는다(과대필터 방지).
_REPORT_KEYWORD = "기업가치제고계획"
# 계획이 아닌 공시 제외(1.10, F9 실증): 이행현황(사후보고)·철회는 목표 공시가 아님.
# 정정([기재정정] 등)은 유지 — 최신 정정이 권위 있는 목표(2.1 최신공시 채택 규칙과 정합).
_REPORT_EXCLUDE = ("이행현황", "철회")


def _is_plan_report(report_nm: str | None) -> bool:
    """report_nm이 '계획' 공시인지 판정(공백 제거 부분일치 + 부정 키워드 제외)."""
    compact = str(report_nm or "").replace(" ", "")
    if _REPORT_KEYWORD not in compact:
        return False
    return not any(kw in compact for kw in _REPORT_EXCLUDE)
_MAX_PAGES = 50  # 페이지네이션 상한(과대 total_page 방어)
_MAX_ZIP_BYTES = 20 * 1024 * 1024  # 문서 ZIP 원본 크기 상한
_MAX_MEMBER_BYTES = 10 * 1024 * 1024  # 멤버 압축해제 크기 상한(zip-bomb 방어)
_MAX_TOTAL_BYTES = 50 * 1024 * 1024  # 누적 압축해제 상한(일괄리뷰 Med: 멤버별 한도 우회 방어)
_MAX_MEMBERS = 200  # 텍스트 멤버 수 상한
_TEXT_EXTS = (".xml", ".html", ".htm", ".txt")  # 텍스트 멤버만(바이너리 오탐 방지)
_PBR_MAX = 100.0  # 현실적 PBR 상한(연도·페이지번호 오탐 배제)

# ── best-effort 파싱 패턴 ──
# 값 뒤에 p/P/포(인트)가 오면 '퍼센트포인트'(증감)라 절대목표 아님 → 제외.
_PCT = r"(\d+(?:\.\d+)?)\s*%(?![pP포])"
# ROE 별칭(1.10, 실샘플 6건: '자기자본이익률' 표기).
_ROE_LABEL = r"(?:ROE|자기자본이익률)"
# 경쟁 지표 라벨(일괄리뷰 2026-07-13 High): gap이 다른 지표를 가로질러 그 지표의 %를
# 훔쳐오는 오탐 차단 — 라벨별로 "자신이 아닌" 지표들을 배제한다.
_OTHERS_FOR_ROE = r"배당성향|주주환원|PBR|영업이익|부채비율"
_OTHERS_FOR_PAYOUT = r"ROE|자기자본이익률|주주환원|PBR|영업이익|부채비율"
# 주주환원율 라벨이 자기 자신이므로 배제 목록에서 빼고, 배당성향을 경쟁 지표로 넣는다.
_OTHERS_FOR_RETURN = r"ROE|자기자본이익률|배당성향|PBR|영업이익|부채비율"


def _plain_gap(others: str) -> str:
    """라벨-값 gap: 개행·숫자·%·경쟁 지표 금지 + 괄호 한정어 1개 허용.

    괄호 안은 숫자·백틱 허용(실샘플 `목표(\\`24~\\`30년 평균)`)하되 **%·경쟁 지표는 금지**
    (일괄리뷰 High: `ROE(2024년 5%) 배당성향 30%`가 30을 ROE로 훔치던 오탐 차단).
    """
    pre = rf"(?:(?!{others})[^0-9%\n(]){{0,15}}"
    paren = rf"(?:\((?:(?!%|{others})[^)\n]){{0,25}}\)\s*[:：]?\s*)?"
    tail = rf"(?:(?!{others})[^0-9%\n]){{0,10}}?"
    return pre + paren + tail


_ROE_RE = re.compile(_ROE_LABEL + _plain_gap(_OTHERS_FOR_ROE) + _PCT, re.IGNORECASE)
# '배당성향'만 매칭(주주환원율은 다른 지표라 target_payout_ratio에 넣지 않음).
_PAYOUT_RE = re.compile(r"배당성향" + _plain_gap(_OTHERS_FOR_PAYOUT) + _PCT)
# 총주주환원율(배당+자사주매입)/순이익 — **배당성향과 다른 지표**라 별도 필드로 받는다(5-1).
# 이 구분은 처음부터 의도된 것이었고(위 주석), 빠져 있던 건 받아줄 필드였다.
_RETURN_LABEL = r"(?:총\s*주주환원율|주주환원율|총주주환원)"
# **목표 표지 필수**(5-1 실샘플 검증). 주주환원율은 계획 공시에서 목표만큼이나 자주
# *이행 실적*으로 등장한다 — "'25년 총 주주환원율 268.0%", "총주주환원율 72.8%",
# "3년 평균 주주환원율 78%(현황)". 라벨+숫자만 보면 13건 중 5건이 과거 실적이었다.
# 값 뒤 짧은 구간에 목표를 뜻하는 말이 와야만 채택한다(같은 절 안 — 개행은 넘지 않는다).
# 보수적으로 놓치는 쪽을 택한다: 애매하면 null(NFR2).
_TARGET_MARK = r"(?=.{0,12}?(?:목표|지향|이상|확대|원칙|수준|계획))"
_RETURN_RE = re.compile(
    _RETURN_LABEL + _plain_gap(_OTHERS_FOR_RETURN) + _PCT + _TARGET_MARK
)


def _arrow_tail(others: str) -> str:
    """"현재 X% → 목표 Y%" 화살표 체인(우변 채택). 좌변 gap은 숫자 허용(연도 서술 통과)
    하되 **경쟁 지표 라벨은 금지**(일괄리뷰 High: 남의 화살표를 훔치던 오탐 차단), 개행 금지."""
    seg_l = rf"(?:(?!{others})[^%\n]){{0,30}}?"
    seg_m = rf"(?:(?!{others})[^\n%]){{0,25}}?"
    return (
        seg_l + r"(\d+(?:\.\d+)?)\s*%"
        + seg_m + r"(?:→|⇒|➔)\s*" + seg_m + r"(\d+(?:\.\d+)?)\s*%(?![pP포])"
    )


_ROE_ARROW_RE = re.compile(_ROE_LABEL + _arrow_tail(_OTHERS_FOR_ROE), re.IGNORECASE)
_PAYOUT_ARROW_RE = re.compile(r"배당성향" + _arrow_tail(_OTHERS_FOR_PAYOUT))
_RETURN_ARROW_RE = re.compile(_RETURN_LABEL + _arrow_tail(_OTHERS_FOR_RETURN) + _TARGET_MARK)
# PBR은 '배' 단위 **필수**(연도·페이지번호를 PBR로 오탐하는 것 차단).
_PBR_RE = re.compile(r"PBR[^0-9\n]{0,15}?(\d+(?:\.\d+)?)\s*배", re.IGNORECASE)
_PERIOD_RE = re.compile(r"(20\d{2})\s*년?\s*[~\-–∼]\s*(20\d{2})")
# 1.10: 백틱/따옴표 표식이 붙은 2자리 연도 범위(실샘플 `24~`30년) → 20xx 확장.
# 표식·'년' 필수(24~26개월 같은 비연도 오탐 방지).
_PERIOD2_RE = re.compile(r"[`'‘’]\s*(\d{2})\s*[~\-–∼]\s*[`'‘’]?\s*(\d{2})\s*년")
# 기간 후보 선택 앵커(일괄리뷰 Med: 과거 비교기간을 계획기간으로 오인 방지).
# '기간'은 제외 — "비교기간"에도 들어가 과거 범위를 앵커시키는 역효과.
_PERIOD_CTX_RE = re.compile(r"(계획|목표|향후|중장기)")


def _select_period(text: str) -> tuple[str | None, str | None]:
    """문서 내 모든 연도범위 후보 중 계획 문맥에 앵커된 것을 선택(일괄리뷰 Med).

    규칙: (1) 후보 직전 20자에 계획·목표·향후·중장기가 있으면 그 첫 후보,
    (2) 앵커 없고 후보가 전부 같은 범위면 그 값(단일 후보 포함 — 기존 recall 유지),
    (3) 앵커 없이 상이한 범위 다수면 애매 → null(NFR2).
    """
    cands: list[tuple[int, str, str]] = []
    for m in _PERIOD_RE.finditer(text):
        if int(m.group(1)) <= int(m.group(2)):
            cands.append((m.start(), m.group(1), m.group(2)))
    for m in _PERIOD2_RE.finditer(text):
        start, end = f"20{m.group(1)}", f"20{m.group(2)}"
        if int(start) <= int(end):
            cands.append((m.start(), start, end))
    if not cands:
        return None, None
    cands.sort()
    anchored = [
        c for c in cands
        if _PERIOD_CTX_RE.search(text[max(0, c[0] - 20): c[0]])
    ]
    if anchored:
        return anchored[0][1], anchored[0][2]
    if len({(s, e) for _, s, e in cands}) == 1:
        return cands[0][1], cands[0][2]
    return None, None
_BUYBACK_RE = re.compile(r"(자기주식|자사주)[^\n]{0,15}?(취득|매입|소각)")
# 부정·과거(계획 아님) 문맥 → False 판정.
_BUYBACK_NEG_RE = re.compile(r"(없음|없이|아니|않|미실시|미계획|계획\s*없|완료|기실시)")


class DartDocumentError(DartAdapterError):
    """문서(document.xml) 다운로드/해제 실패 — 종목 전체가 아니라 그 문서만 격리."""


def _safe_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _parse_date(yyyymmdd: str | None) -> str | None:
    """YYYYMMDD → ISO YYYY-MM-DD. strptime으로 엄격 검증, 무효면 None(적재 제외용)."""
    s = (yyyymmdd or "").strip()
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return datetime.strptime(s, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _strip_tags(s: str) -> str:
    """DART 전용 XML 마크업 태그 제거. 태그 자리를 **개행으로 치환**해 셀/문단 경계를 보존한다
    (라벨과 인접 지표 값이 한 줄로 뭉쳐 오탐되는 것 방지)."""
    text = re.sub(r"<[^>]+>", "\n", s)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)  # 공백류만 축약(개행은 유지)
    text = re.sub(r"\n[ \t]*", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _zip_to_text(content: bytes) -> str:
    """document.xml ZIP → 평문. 비ZIP/빈/추출실패는 DartDocumentError(성공값과 구분).

    텍스트 멤버(.xml/.html/.txt)만, 사이즈 상한으로 읽는다(바이너리 오탐·zip-bomb 방어).
    """
    if not content:
        raise DartDocumentError("빈 문서 응답")
    if len(content) > _MAX_ZIP_BYTES:
        raise DartDocumentError("문서 ZIP 크기 상한 초과")
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        # 비ZIP = DART 오류 HTML/XML 응답 → 실패로 격리(빈 원문으로 오인 금지)
        raise DartDocumentError("ZIP 아님(오류 응답 가능)") from None
    parts: list[str] = []
    total_bytes = 0
    members = 0
    with zf:
        for info in zf.infolist():
            if not info.filename.lower().endswith(_TEXT_EXTS):
                continue
            if info.file_size > _MAX_MEMBER_BYTES:
                continue
            members += 1
            total_bytes += info.file_size
            if members > _MAX_MEMBERS or total_bytes > _MAX_TOTAL_BYTES:
                raise DartDocumentError("문서 누적 압축해제 상한 초과(멤버 수/총 크기)")
            parts.append(_decode(zf.read(info)))
    text = _strip_tags("\n".join(parts))
    if not text:
        raise DartDocumentError("문서에서 텍스트 추출 실패")
    return text


def parse_targets(raw_text: str | None) -> dict[str, Any]:
    """유효 문서 원문에서 목표 필드 best-effort 추출. 못 찾으면 해당 필드 None.

    보수적: 애매하면 null(틀린 non-null 값 금지). 값 뒤 p(포인트)·단위없는 PBR·범위이상·부정 자사주 배제.
    """
    text = raw_text or ""

    def _num(rx: re.Pattern[str]) -> float | None:
        m = rx.search(text)
        return float(m.group(1)) if m else None

    def _num_with_arrow(arrow_rx: re.Pattern[str], plain_rx: re.Pattern[str]) -> float | None:
        """화살표 체인(현재→목표)은 우변(목표) 채택 — 단 **문서 내 위치가 앞선 쪽 우선**
        (일괄리뷰 Med: 앞의 명시 목표가 뒤쪽 과거실적 표의 화살표에 밀리지 않게).
        같은 위치(같은 clause)에서 화살표가 있으면 화살표 우변이 목표."""
        am = arrow_rx.search(text)
        pm = plain_rx.search(text)
        if am is not None and (pm is None or am.start() <= pm.start()):
            return float(am.group(2))
        return float(pm.group(1)) if pm else None

    pbr = _num(_PBR_RE)
    if pbr is not None and not (0 < pbr <= _PBR_MAX):
        pbr = None  # 연도·비현실적 값 배제

    # 기간: 전체 후보 중 계획 문맥 앵커 우선(일괄리뷰 Med — 과거 비교기간 오인 방지)
    period_start, period_end = _select_period(text)

    buyback: bool | None = None
    bm = _BUYBACK_RE.search(text)
    if bm:
        window = text[max(0, bm.start() - 10) : bm.end() + 15]
        buyback = False if _BUYBACK_NEG_RE.search(window) else True

    return {
        "target_roe": _num_with_arrow(_ROE_ARROW_RE, _ROE_RE),
        "target_payout_ratio": _num_with_arrow(_PAYOUT_ARROW_RE, _PAYOUT_RE),
        "target_total_return_ratio": _num_with_arrow(_RETURN_ARROW_RE, _RETURN_RE),
        "target_pbr": pbr,
        "period_start": period_start,
        "period_end": period_end,
        "buyback_planned": buyback,
    }


class DartValueupAdapter(SourceAdapter):
    source = "dart"

    def __init__(self) -> None:
        self._session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        self._session.mount("https://", HTTPAdapter(max_retries=retry))
        self._limiter = _RateLimiter(_MIN_INTERVAL)

    # ── fetch (라이브, 키 필요) ──
    def fetch(self, corp_code: str, bgn_de: str, end_de: str) -> dict[str, Any]:
        key = settings.dart_api_key.get_secret_value()
        if not key:
            raise DartAdapterError(
                "DART_API_KEY가 설정되지 않았습니다. .env에 DART_API_KEY를 넣으세요."
            )
        plans: list[dict[str, Any]] = []
        failed: list[tuple[str | None, str]] = []
        page_no = 1
        while page_no <= _MAX_PAGES:
            try:
                data = self._get_json(
                    "list.json",
                    {
                        "crtfc_key": key,
                        "corp_code": corp_code,
                        "bgn_de": bgn_de,
                        "end_de": end_de,
                        "page_no": page_no,
                        "page_count": 100,
                    },
                    allow_no_data=True,
                )
            except DartAdapterError as e:
                # 후반 페이지 실패 시 이미 모은 plan은 보존하고 중단(부분결과 보존)
                failed.append((f"list.json#p{page_no}", type(e).__name__))
                break
            page_items = data.get("list")
            if page_items is None:
                page_items = []
            if not isinstance(page_items, list):  # 형태 이탈 → 페이지 실패로 격리
                failed.append((f"list.json#p{page_no}", "list 형태 오류"))
                break
            for item in page_items:
                if not isinstance(item, Mapping):  # malformed 항목 격리(일괄리뷰 High)
                    continue
                report_nm = str(item.get("report_nm") or "")
                if not _is_plan_report(report_nm):  # 1.10: 이행현황·철회 제외(F9)
                    continue
                disclosure_date = _parse_date(item.get("rcept_dt"))
                rcept_no = item.get("rcept_no")
                if disclosure_date is None:
                    failed.append((rcept_no, "무효 rcept_dt"))
                    continue
                if not rcept_no:
                    failed.append((None, "rcept_no 없음"))
                    continue
                try:
                    raw_text = self._fetch_document(key, rcept_no)  # 문서별 격리
                except DartDocumentError as e:
                    failed.append((rcept_no, type(e).__name__))
                    continue
                plans.append(
                    {
                        "disclosure_date": disclosure_date,
                        "report_nm": report_nm,
                        "raw_text": raw_text,
                    }
                )
            total_page = _safe_int(data.get("total_page"), 1)
            if page_no >= total_page:
                break
            page_no += 1
        return {"corp_code": corp_code, "plans": plans, "failed": failed}

    def _get_json(
        self, endpoint: str, params: Mapping[str, Any], allow_no_data: bool = False
    ) -> dict[str, Any]:
        """list.json 등 JSON 엔드포인트. dart.py `_get`과 동일한 status 처리. 키 미노출."""
        self._limiter.acquire()
        try:
            resp = self._session.get(
                f"{_BASE}/{endpoint}", params=params, timeout=_TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            # ValueError=비JSON 200(dart.py `_get`과 동일 처리, 일괄리뷰 High)
            raise DartAdapterError(
                f"DART 요청 실패: endpoint={endpoint} ({type(e).__name__})"
            ) from None
        if not isinstance(data, dict):
            # 비-dict JSON(list/str)이 AttributeError로 누출되면 페이지 격리 계약이
            # 깨진다(DartAdapterError만 부분결과 보존 경로를 탄다, 일괄리뷰 High)
            raise DartAdapterError(f"DART 응답 형태 오류: endpoint={endpoint}")
        status = data.get("status")
        if status == "000":
            return data
        if allow_no_data and status == "013":  # 조회된 데이터 없음
            return {"list": []}
        raise DartAdapterError(
            f"DART API 오류: endpoint={endpoint}, status={status}, "
            f"msg={data.get('message')}"
        )

    def _fetch_document(self, key: str, rcept_no: str) -> str:
        """document.xml(ZIP 바이너리) 다운로드 → 평문. 실패는 DartDocumentError로 격리."""
        self._limiter.acquire()
        try:
            resp = self._session.get(
                f"{_BASE}/document.xml",
                params={"crtfc_key": key, "rcept_no": rcept_no},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            content = resp.content  # 바이너리(ZIP) — resp.json 금지
        except requests.RequestException as e:
            raise DartDocumentError(
                f"문서 다운로드 실패 ({type(e).__name__})"
            ) from None
        return _zip_to_text(content)  # 비ZIP/빈/추출실패 → DartDocumentError

    # ── normalize (순수, 테스트 가능) ──
    def normalize(self, raw: Mapping[str, Any]) -> list[dict[str, Any]]:
        corp_code = raw["corp_code"]
        recs: list[dict[str, Any]] = []
        for plan in raw.get("plans", []):
            rec: dict[str, Any] = {
                "corp_code": corp_code,
                "disclosure_date": plan["disclosure_date"],
                "raw_text": plan.get("raw_text"),
            }
            rec.update(parse_targets(plan.get("raw_text")))
            recs.append(rec)
        return recs

    # ── upsert (멱등, 유효 문서 기반 전체 교체) ──
    def upsert(self, session: Session, records: Sequence[dict[str, Any]]) -> int:
        for rec in records:
            upsert_valueup_plan(session, rec)
        session.flush()
        return len(records)
```

### `app/sql_views.py` (56행)

뷰 — `total_return_ratio` 정의

```python
"""SQL VIEW 정의 (마이그레이션·테스트 공용).

valuation_metrics: 지표를 앱코드가 아니라 DB VIEW로 계산(AD-1).
이식성: SQLite(개발)·PostgreSQL(운영) 모두 동작하도록 작성.
  - 최신 주가: DISTINCT ON(PG전용) 대신 상관 서브쿼리(MAX(date)).
  - float: *100.0 / *1.0 로 정수나눗셈 방지, NULLIF로 0방어.
  - YoY: LAG 윈도우 함수(연간 데이터 → 전년).
"""

from __future__ import annotations

VALUATION_METRICS_VIEW = "valuation_metrics"

CREATE_VALUATION_METRICS = f"""
CREATE VIEW {VALUATION_METRICS_VIEW} AS
SELECT
    f.corp_code,
    f.year,
    f.quarter,
    -- 음수/0 분모는 무의미(자본잠식·적자) → NULL. NULLIF(0)만으론 '음수 분모'가 통과해
    -- 지표 부호가 뒤집히고 스크리너를 오염(예: min_roe가 자본잠식 기업을 우량으로 통과)한다.
    -- 그래서 분모 > 0 조건을 CASE로 명시한다(GPT 교차검증 반영).
    ROUND(CASE WHEN f.equity > 0 THEN f.net_income * 100.0 / f.equity END, 2)      AS roe,
    ROUND(CASE WHEN f.total_assets > 0 THEN f.net_income * 100.0 / f.total_assets END, 2) AS roa,
    ROUND(CASE WHEN f.equity > 0 THEN lp.market_cap * 1.0 / f.equity END, 2)       AS pbr,
    ROUND(CASE WHEN f.net_income > 0 THEN lp.market_cap * 1.0 / f.net_income END, 2) AS per,
    -- EBITDA = 영업이익 + 감가상각비(없으면 COALESCE로 EBIT 근사). EBITDA > 0일 때만.
    ROUND(CASE WHEN (f.operating_income + COALESCE(f.depreciation, 0)) > 0
               THEN (lp.market_cap + f.total_debt - f.cash) * 1.0
                    / (f.operating_income + COALESCE(f.depreciation, 0)) END, 2)   AS ev_ebitda,
    ROUND(CASE WHEN f.equity > 0 THEN f.total_liabilities * 100.0 / f.equity END, 2) AS debt_ratio,
    ROUND(CASE WHEN f.net_income > 0 THEN f.dividend_total * 100.0 / f.net_income END, 2) AS payout_ratio,
    -- 총주주환원율 = (배당총액 + 자사주매입액)/순이익 (5-1). 배당성향과 **다른 지표**다 —
    -- 기업 다수가 이쪽으로 목표를 공시하므로 목표와 같은 정의의 실적이 필요하다.
    -- 자사주매입액이 null이면 0으로 메우지 않는다(그러면 환원을 과소평가) → 전체 null.
    ROUND(CASE WHEN f.net_income > 0 AND f.buyback_amount IS NOT NULL
               THEN (f.dividend_total + f.buyback_amount) * 100.0 / f.net_income END, 2)
                                                                               AS total_return_ratio,
    (f.cash - f.total_debt)                                                        AS net_cash,
    -- 매출 > 0에서만. EBITDA 자체는 음수 가능(음수 마진은 유의미)이라 분자 부호는 유지.
    ROUND(CASE WHEN f.revenue > 0
               THEN (f.operating_income + COALESCE(f.depreciation, 0)) * 100.0 / f.revenue END, 2) AS ebitda_margin,
    ROUND((f.revenue - LAG(f.revenue) OVER w) * 100.0
          / NULLIF(LAG(f.revenue) OVER w, 0), 2)                                   AS yoy_revenue_growth,
    ROUND((f.net_income - LAG(f.net_income) OVER w) * 100.0
          / NULLIF(LAG(f.net_income) OVER w, 0), 2)                                AS yoy_income_growth
FROM financials f
LEFT JOIN prices lp
       ON lp.corp_code = f.corp_code
      AND lp.date = (SELECT MAX(p2.date) FROM prices p2 WHERE p2.corp_code = f.corp_code)
-- YoY: 같은 분기끼리 전년 대비(PARTITION BY quarter). 연간(quarter=4만) 데이터에선
-- LAG(1)=전년으로 기존과 동일하고, 분기 데이터가 섞여도 QoQ 오표기 없이 전년 동분기와 비교.
WINDOW w AS (PARTITION BY f.corp_code, f.quarter ORDER BY f.year)
""".strip()

DROP_VALUATION_METRICS = f"DROP VIEW IF EXISTS {VALUATION_METRICS_VIEW}"
```

### `app/repositories/valueup_score.py` (202행)

`latest_metrics` 컬럼 선택(부수 결함 수정 포함)

```python
"""valueup_score 입력 조회 + 멱등 upsert 저장소 (AD-2: SQL은 여기서만).

gap_engine(app/analysis/gap_engine.py)의 유일한 DB 접근 지점. 세 가지 읽기(공시 목표·
실적 지표·자사주 원천)와 한 가지 쓰기(스코어 upsert)로 구성. gap_engine 자체는 dict/스칼라만
다루고 SQL을 직접 실행하지 않는다(AD-2).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import Session

from app.models import Company, Financial, ValueupPlan, ValueupScore


def list_all_corp_codes(session: Session) -> list[str]:
    """전 종목 corp_code 목록(run()의 corp_codes 기본값). SQL은 여기서만(AD-2)."""
    return list(session.scalars(select(Company.corp_code)).all())


def latest_valueup_plan(
    session: Session, corp_code: str, as_of: str
) -> dict[str, Any] | None:
    """as_of 이전(포함) 최신 valueup_plan 1건. 여러 공시 중 as_of 직전 최신 것을 target으로 채택
    (2026-07-10 리드 결정 A: 기간-포함 판정 대신 단순·재현 가능한 규칙).

    동일 disclosure_date(원공시+정정공시 등) tie-break은 plan_id 내림차순(코드리뷰 Med,
    GPT) — 접수번호 등 진짜 우선순위 필드가 없어 "나중에 적재된 것"을 결정적으로 채택.
    """
    stmt = (
        select(ValueupPlan)
        .where(
            ValueupPlan.corp_code == corp_code,
            ValueupPlan.disclosure_date <= as_of,
        )
        .order_by(ValueupPlan.disclosure_date.desc(), ValueupPlan.plan_id.desc())
        .limit(1)
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        return None
    return {
        "target_roe": obj.target_roe,
        "target_payout_ratio": obj.target_payout_ratio,
        "target_total_return_ratio": obj.target_total_return_ratio,
        "target_pbr": obj.target_pbr,  # 계산 미사용, 참고 보관만(리드 결정)
        "period_start": obj.period_start,
        "period_end": obj.period_end,
        "buyback_planned": obj.buyback_planned,
    }


def latest_metrics(session: Session, corp_code: str, as_of: str) -> dict[str, Any] | None:
    """as_of 이전 최신 (year,quarter) valuation_metrics 행. look-ahead 부분 차단(코드리뷰 High,
    GPT): 같은 연도의 **사업보고서(quarter=4)는 그 해 안에 공시될 수 없음**(결산 후 통상 90일
    이내 = 다음 해)이므로 무조건 제외 — `year<as_of_year OR (year=as_of_year AND quarter<4)`.
    1~3분기 보고서의 동일연도 내 공시시차는 실제 공시일 데이터가 없어 잔여 리스크로 defer
    (deferred-work.md 2-1 섹션). AD-1: 뷰가 계산한 값을 읽기만.
    """
    as_of_year = int(as_of[:4])
    row = session.execute(
        text(
            "SELECT roe, payout_ratio, total_return_ratio FROM valuation_metrics "
            "WHERE corp_code = :cc AND (year < :yr OR (year = :yr AND quarter < 4)) "
            "ORDER BY year DESC, quarter DESC LIMIT 1"
        ),
        {"cc": corp_code, "yr": as_of_year},
    ).mappings().one_or_none()
    return dict(row) if row is not None else None


def latest_financial_buyback(
    session: Session, corp_code: str, as_of: str
) -> dict[str, Any] | None:
    """as_of 이전 최신 (year,quarter) financials의 buyback 수량 필드.
    look-ahead 부분 차단은 latest_metrics와 동일 규칙(사업보고서 동일연도 제외)."""
    as_of_year = int(as_of[:4])
    stmt = (
        select(Financial)
        .where(
            Financial.corp_code == corp_code,
            or_(
                Financial.year < as_of_year,
                and_(Financial.year == as_of_year, Financial.quarter < 4),
            ),
        )
        .order_by(Financial.year.desc(), Financial.quarter.desc())
        .limit(1)
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        return None
    return {
        "buyback_amount": obj.buyback_amount,
        "buyback_retired_amount": obj.buyback_retired_amount,
    }


def upsert_valueup_score(session: Session, rec: dict[str, Any]) -> ValueupScore:
    """(corp_code, as_of) 자연키 기준 valueup_score upsert(AD-7 확장 패턴).

    gap_engine 산출값은 항상 그 as_of의 '권위 있는 재계산 결과'이므로 null 포함 전체
    교체한다(valueup_plan upsert와 동일 원칙 — 재계산 시 과거 오탐이 null로 정정되게).
    `rec[field]`(직접 인덱싱, 코드리뷰 Med, GPT): 키 누락은 프로그래밍 오류이므로
    `.get()`으로 조용히 None 넘기지 않고 KeyError로 즉시 드러낸다.
    """
    stmt = select(ValueupScore).where(
        ValueupScore.corp_code == rec["corp_code"],
        ValueupScore.as_of == rec["as_of"],
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        obj = ValueupScore(corp_code=rec["corp_code"], as_of=rec["as_of"])
        session.add(obj)
    for field in (
        "target_roe", "actual_roe", "roe_gap",
        "achievement_rate", "progress_rate", "execution_score", "washing_flag",
        "buyback_executed", "buyback_retired", "buyback_status", "score_basis",
    ):
        setattr(obj, field, rec[field])
    return obj


def latest_as_of(session: Session) -> str | None:
    """valueup_score의 최신 as_of(기본 조회 기준일, 2.4). 없으면 None."""
    from sqlalchemy import func

    return session.scalar(select(func.max(ValueupScore.as_of)))


def list_scores(
    session: Session, filters: dict[str, Any], page: int, size: int
) -> tuple[list[dict[str, Any]], int]:
    """갭분석/워싱랭킹 서빙 조회(2.4). company 조인 + 필터 + execution_score 오름차순.

    null 정렬은 방언(SQLite NULLS FIRST/PG NULLS LAST 기본 차이)을 타지 않도록
    명시적 2단 키(`IS NULL` 우선순위 → 값)로 처리(1.7 defer 교훈). 동순위는 corp_code로
    안정 정렬(페이지네이션 결정성).
    """
    from sqlalchemy import func

    from app.models import Company

    conds = [ValueupScore.as_of == filters["as_of"]]
    if filters.get("corp_code") is not None:  # 3.4 상세화면 단건 조회용(정확일치)
        conds.append(Company.corp_code == filters["corp_code"])
    # `is not None`: 빈 문자열이 "필터 없음"으로 새지 않게(2-5 리뷰 패리티 — 1차 방어는
    # 라우터 min_length=1의 422)
    if filters.get("market") is not None:
        conds.append(Company.market == filters["market"])
    if filters.get("min_progress") is not None:
        conds.append(ValueupScore.progress_rate >= filters["min_progress"])
    if filters.get("washing_only"):
        conds.append(ValueupScore.washing_flag.is_(True))

    base = select(ValueupScore, Company).join(
        Company, Company.corp_code == ValueupScore.corp_code
    ).where(*conds)

    total = session.scalar(
        select(func.count()).select_from(base.subquery())
    ) or 0
    rows = session.execute(
        base.order_by(
            ValueupScore.execution_score.is_(None),  # null last(명시적)
            ValueupScore.execution_score.asc(),
            ValueupScore.corp_code.asc(),
        ).limit(size).offset((page - 1) * size)
    ).all()

    items = []
    for score, company in rows:
        items.append({
            "corp_code": score.corp_code,
            "corp_name": company.corp_name,
            "market": company.market,
            "as_of": score.as_of,
            "target_roe": score.target_roe,
            "actual_roe": score.actual_roe,
            "roe_gap": score.roe_gap,
            "achievement_rate": score.achievement_rate,
            "progress_rate": score.progress_rate,
            "execution_score": score.execution_score,
            "washing_flag": score.washing_flag,
            "buyback_status": score.buyback_status,
            "score_basis": score.score_basis,
        })
    return items, total


def delete_valueup_score(session: Session, corp_code: str, as_of: str) -> None:
    """plan이 사라진 (corp_code, as_of)의 오래된 score를 정리(코드리뷰 High, GPT: 정합성
    reconciliation). gap_engine이 valueup_score의 유일 writer(AD-4)이므로 근거가 사라진
    행을 제거할 책임도 이 모듈에 있다. 없으면 no-op(멱등)."""
    stmt = select(ValueupScore).where(
        ValueupScore.corp_code == corp_code, ValueupScore.as_of == as_of,
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is not None:
        session.delete(obj)
```

### `tests/test_gap_engine.py` (582행)

채점 계약 테스트(기존 5건 대체 + 신규)

```python
"""Story 2.1 — Value-up 갭 스코어링 엔진 검증 (순수 함수 + 통합, DB는 SQLite in-memory)."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.analysis.gap_engine import (
    _achievement_rate,
    _buyback_signals,
    _execution_score,
    _progress_rate,
    _safe_ratio,
    _washing_flag,
    run,
)
from app.models import Base, Company, Financial, ValueupPlan, ValueupScore
from app.repositories import valueup_score as repo
from app.sql_views import CREATE_VALUATION_METRICS


# ── T3: 순수 함수 단위 테스트 (DB 미접촉) ──

def test_safe_ratio_normal() -> None:
    assert _safe_ratio(8.0, 10.0) == 0.8


def test_safe_ratio_target_zero_or_negative_is_none() -> None:
    assert _safe_ratio(8.0, 0.0) is None
    assert _safe_ratio(8.0, -5.0) is None


def test_safe_ratio_missing_input_is_none() -> None:
    assert _safe_ratio(None, 10.0) is None
    assert _safe_ratio(8.0, None) is None


def test_progress_rate_mid_period_day_precision() -> None:
    """[결정 B, 2026-07-21] 일 단위 정밀도(scoring.md 원식 `today` 기반 정합화).
    2024~2027 계획(2024-01-01~2027-12-31, 1460일)의 2025-12-31 시점 = 730일 = 정확히 0.5."""
    assert _progress_rate("2024", "2027", date(2025, 12, 31)) == pytest.approx(0.5)


def test_progress_rate_no_new_year_jump() -> None:
    """[결정 B 핵심 회귀] 12/31→1/1 사이 진척률이 점프하지 않는다 — 연 단위 구현은
    같은 구간에서 1/3→2/3으로 +0.33 점프해 washing 임계(0.5)를 하루 만에 넘겼다."""
    before = _progress_rate("2024", "2027", date(2025, 12, 31))
    after = _progress_rate("2024", "2027", date(2026, 1, 1))
    assert after - before == pytest.approx(1 / 1460)  # 정확히 하루치


def test_progress_rate_before_start_clamps_zero() -> None:
    assert _progress_rate("2024", "2027", date(2023, 6, 1)) == 0.0


def test_progress_rate_after_end_clamps_one() -> None:
    assert _progress_rate("2024", "2027", date(2030, 1, 1)) == 1.0


def test_progress_rate_invalid_period_is_none() -> None:
    d = date(2025, 12, 31)
    assert _progress_rate(None, "2027", d) is None
    assert _progress_rate("2024", None, d) is None
    assert _progress_rate("2027", "2024", d) is None  # end<start
    # end==start: 0나눗셈은 일 단위 전환으로 사라졌지만(분모 364일) AC3 계약("end<=start
    # 무효") 유지 — 단년 계획 수용은 별도 결정(deferred-work.md 2026-07-21).
    assert _progress_rate("2024", "2024", d) is None
    assert _progress_rate("abc", "2027", d) is None  # 파싱 실패


def test_achievement_rate_normal() -> None:
    assert _achievement_rate(8.0, 10.0) == pytest.approx(0.8)


def test_achievement_rate_target_missing_or_nonpositive_is_none() -> None:
    assert _achievement_rate(8.0, None) is None
    assert _achievement_rate(8.0, 0.0) is None
    assert _achievement_rate(None, 10.0) is None


def test_buyback_signals_retired() -> None:
    executed, retired, status = _buyback_signals(3_000_000, 1_000_000)
    assert executed is True
    assert retired is True
    assert status == "retired"


def test_buyback_signals_purchased_only() -> None:
    executed, retired, status = _buyback_signals(3_000_000, 0)
    assert executed is True
    assert retired is False
    assert status == "purchased_only"


def test_buyback_signals_none_activity() -> None:
    executed, retired, status = _buyback_signals(0, 0)
    assert executed is False
    assert retired is False
    assert status == "none"


def test_buyback_signals_unknown_when_either_missing() -> None:
    assert _buyback_signals(None, 0)[2] == "unknown"
    assert _buyback_signals(3_000_000, None)[2] == "unknown"
    assert _buyback_signals(None, None) == (None, None, "unknown")


def test_execution_score_normal() -> None:
    # 세 항목 모두 약속 → 가중치 그대로. achievement=0.8(0.5)+buyback=1(0.3)+payout=1.0(0.2)
    score, basis = _execution_score(
        achievement_rate=0.8, buyback_executed=True,
        actual_payout=35.0, target_payout=30.0,  # 초과달성 → min(,1.0)=1.0
        w_achievement=0.5, w_buyback=0.3, w_payout=0.2,
    )
    assert score == pytest.approx(90.0)
    assert basis == "roe+buyback+payout"


def test_execution_score_caps_overachievement() -> None:
    """achievement_rate 150%여도 min(,1.0)으로 캡."""
    score, _ = _execution_score(
        achievement_rate=1.5, buyback_executed=True,
        actual_payout=30.0, target_payout=30.0,
        w_achievement=0.5, w_buyback=0.3, w_payout=0.2,
    )
    assert score == pytest.approx(100.0)


# ── 5-1: 공시한 약속에 대해서만 채점 ──

def test_execution_score_null_when_committed_but_actual_missing() -> None:
    """AC6: 약속했는데 실적을 모르면 그 항목을 빼지 않고 **전체 null**(판단 불가 보존).

    빼버리면 모르는 항목을 유리하게 무시한 셈이라 점수가 부풀려진다.
    """
    for kwargs in (
        dict(achievement_rate=None, buyback_executed=True),   # ROE 약속·실적 미상
        dict(achievement_rate=0.8, buyback_executed=None),    # 자사주 약속·실행 미상
    ):
        score, basis = _execution_score(
            actual_payout=30.0, target_payout=30.0,
            w_achievement=0.5, w_buyback=0.3, w_payout=0.2, **kwargs,
        )
        assert score is None and basis is None


def test_execution_score_skips_uncommitted_and_renormalizes() -> None:
    """AC3/AC4: ROE를 공시하지 않은 기업은 나머지 항목만으로 채점하고 가중치를 재정규화한다.

    이전엔 target_roe가 없다는 이유만으로 전체 null이었다 — 배당·자사주는 약속하고 지킨
    기업까지 '판단 불가'가 되어 오히려 정보를 지웠다.
    """
    score, basis = _execution_score(
        achievement_rate=None, buyback_executed=True,
        actual_payout=30.0, target_payout=30.0,
        w_achievement=0.5, w_buyback=0.3, w_payout=0.2,
        roe_committed=False,  # ROE 목표를 공시하지 않음
    )
    # 남은 가중치 0.3+0.2=0.5에 재정규화 → (0.3*1 + 0.2*1)/0.5 = 1.0
    assert score == pytest.approx(100.0)
    assert basis == "buyback+payout"


def test_execution_score_partial_renormalization_value() -> None:
    """재정규화가 '남은 항목 안에서의 비율'로 계산되는지 값으로 확인."""
    score, basis = _execution_score(
        achievement_rate=None, buyback_executed=False,  # 자사주 미실행 → 0점
        actual_payout=15.0, target_payout=30.0,         # 배당 50% 달성
        w_achievement=0.5, w_buyback=0.3, w_payout=0.2,
        roe_committed=False,
    )
    # (0.3*0.0 + 0.2*0.5) / 0.5 = 0.2 → 20점
    assert score == pytest.approx(20.0)
    assert basis == "buyback+payout"


def test_execution_score_total_return_preferred_over_payout() -> None:
    """주주환원율과 배당성향은 다른 지표 — 둘 다 공시했으면 더 포괄적인 주주환원율을 쓴다."""
    score, basis = _execution_score(
        achievement_rate=None, buyback_executed=None,
        actual_payout=30.0, target_payout=30.0,
        w_achievement=0.5, w_buyback=0.3, w_payout=0.2,
        roe_committed=False, buyback_committed=False,
        actual_total_return=25.0, target_total_return=50.0,  # 50% 달성
    )
    assert basis == "total_return"
    assert score == pytest.approx(50.0)  # 단독 항목이라 재정규화 후 그 달성도 자체


def test_execution_score_none_when_nothing_committed() -> None:
    """AC5: 약속이 하나도 없으면 채점 대상 자체가 없다 → null(진짜 판단 불가 보존)."""
    score, basis = _execution_score(
        achievement_rate=0.8, buyback_executed=True,
        actual_payout=30.0, target_payout=None,
        w_achievement=0.5, w_buyback=0.3, w_payout=0.2,
        roe_committed=False, buyback_committed=False,
    )
    assert score is None and basis is None


def test_washing_flag_true_case() -> None:
    assert _washing_flag(
        progress_rate=0.6, achievement_rate=0.4, buyback_planned=True,
        buyback_retired=False, progress_min=0.5, achievement_max=0.6,
    ) is True


def test_washing_flag_false_case_achievement_high() -> None:
    assert _washing_flag(
        progress_rate=0.6, achievement_rate=0.9, buyback_planned=True,
        buyback_retired=False, progress_min=0.5, achievement_max=0.6,
    ) is False


def test_washing_flag_false_when_retired_true() -> None:
    assert _washing_flag(
        progress_rate=0.6, achievement_rate=0.4, buyback_planned=True,
        buyback_retired=True, progress_min=0.5, achievement_max=0.6,
    ) is False


def test_washing_flag_none_when_all_unknown_no_confirmed_false() -> None:
    """확정 False가 없고 unknown만 있으면 None(판단 불가) — Kleene 3치의 두 번째 경우."""
    assert _washing_flag(
        progress_rate=None, achievement_rate=0.4, buyback_planned=True,
        buyback_retired=False, progress_min=0.5, achievement_max=0.6,
    ) is None  # progress unknown, 나머지 True 방향이라 확정 False 없음


# ── 코드리뷰 회귀 테스트 (2026-07-10, GPT 교차검증) ──

def test_washing_flag_kleene_retired_true_dominates() -> None:
    """[High] 소각이 확정(retired=True)되면 나머지가 unknown이어도 washing은 확정 False —
    이전 구현("하나라도 None→전체 None")은 이 케이스도 None으로 냈다(과잉보수적)."""
    assert _washing_flag(
        progress_rate=None, achievement_rate=None, buyback_planned=True,
        buyback_retired=True, progress_min=0.5, achievement_max=0.6,
    ) is False


def test_washing_flag_kleene_buyback_not_planned_dominates() -> None:
    """[High] buyback_planned=False가 확정 False 항이면 나머지 unknown이어도 전체 False."""
    assert _washing_flag(
        progress_rate=None, achievement_rate=None, buyback_planned=False,
        buyback_retired=None, progress_min=0.5, achievement_max=0.6,
    ) is False


def test_washing_flag_buyback_planned_none_is_unknown_term() -> None:
    """[코드리뷰 2026-07-21] buyback_planned는 파싱 실패 시 DB에 null로 들어온다
    (ValueupPlan.buyback_planned: bool|None, 자유서식 best-effort). _washing_flag에서
    래핑 없이 raw로 들어가는 것은 의도 — 이미 3치(bool|None)라 변환이 불필요하며,
    None은 Kleene unknown으로 처리된다. 이 테스트가 그 계약을 고정한다."""
    assert _washing_flag(
        progress_rate=0.6, achievement_rate=0.4, buyback_planned=None,
        buyback_retired=False, progress_min=0.5, achievement_max=0.6,
    ) is None  # 확정 False 없음 + unknown 있음 → 판단 불가


def test_washing_flag_buyback_planned_none_still_dominated_by_retired() -> None:
    """[코드리뷰 2026-07-21] planned가 unknown이어도 소각 확정(retired=True)이면 전체
    확정 False — unknown 항이 확정 False 항의 지배를 막지 않는다."""
    assert _washing_flag(
        progress_rate=0.6, achievement_rate=0.4, buyback_planned=None,
        buyback_retired=True, progress_min=0.5, achievement_max=0.6,
    ) is False


def test_washing_flag_kleene_progress_below_min_dominates() -> None:
    """[High] progress_rate가 확정으로 임계 미달이면 나머지 unknown이어도 전체 False."""
    assert _washing_flag(
        progress_rate=0.1, achievement_rate=None, buyback_planned=True,
        buyback_retired=None, progress_min=0.5, achievement_max=0.6,
    ) is False


def test_buyback_signals_negative_quantity_is_unknown() -> None:
    """[High] 음수 수량(도메인에 없는 값)은 확정 False/True가 아니라 unknown 취급.
    1.8의 _parse_quantity가 상류에서 이미 음수를 걸러 DB엔 안 들어오지만, gap_engine 자체도
    방어(다른 writer 경로·수동 DB 편집 등에 대한 belt-and-suspenders)."""
    from app.analysis.gap_engine import _buyback_signals

    assert _buyback_signals(-5, 0)[0] is None  # executed
    assert _buyback_signals(-5, 0)[2] == "unknown"
    assert _buyback_signals(3_000_000, -1)[1] is None  # retired
    assert _buyback_signals(3_000_000, -1)[2] == "unknown"


def test_run_rejects_malformed_as_of(engine) -> None:
    """[High] as_of가 YYYY-MM-DD가 아니면 fail-fast — 문자열 날짜 비교가 실제 날짜 비교와
    어긋나는 입력(예: zero-pad 없는 월)을 사전에 차단."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        run(as_of="2025-7-1", session_factory=Session_)
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        run(as_of="not-a-date", session_factory=Session_)


def test_run_ac3_invalid_period_nulls_achievement_and_execution(engine) -> None:
    """[High] AC3: period_start가 없으면 progress_rate뿐 아니라 achievement_rate·
    execution_score도 null이어야 한다(이전 구현은 achievement_rate를 별도 계산해 AC3 위반)."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        s.add(Company(corp_code="00000005", corp_name="기간불명"))
        s.add(Financial(
            corp_code="00000005", year=2024, quarter=4,
            net_income=80, equity=1000, revenue=1000,
            operating_income=100, depreciation=10, total_assets=2000,
            total_liabilities=1000, cash=100, total_debt=200, dividend_total=24,
        ))
        s.add(ValueupPlan(
            corp_code="00000005", disclosure_date="2024-01-01",
            target_roe=10.0, target_payout_ratio=30.0,
            period_start=None, period_end=None,  # 파싱 실패로 기간 불명
            buyback_planned=True,
        ))
        s.commit()
        run(as_of="2025-12-31", corp_codes=["00000005"], session_factory=Session_)
        row = s.scalars(select(ValueupScore)).one()
        assert row.progress_rate is None
        assert row.achievement_rate is None  # actual_roe=8.0, target_roe=10.0로 계산 가능했었지만 null
        assert row.execution_score is None


def test_run_deletes_stale_score_when_plan_removed(engine) -> None:
    """[High] plan이 있어 score가 생성된 뒤 plan이 삭제되면, 같은 as_of 재실행 시 근거를
    잃은 기존 score도 함께 정리된다(정합성 reconciliation)."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
        run(as_of="2025-12-31", session_factory=Session_)
        assert s.scalar(select(ValueupScore)) is not None  # score 생성 확인

        plan = s.scalars(select(ValueupPlan).where(ValueupPlan.corp_code == "00000001")).one()
        s.delete(plan)
        s.commit()

        result = run(as_of="2025-12-31", session_factory=Session_)
        assert s.scalar(select(ValueupScore)) is None  # 정리됨
        assert result.scored == 0 and result.deleted == 1


def test_run_excludes_same_year_annual_report_lookahead(engine) -> None:
    """[High] look-ahead 부분차단: 같은 연도의 사업보고서(quarter=4)는 그 해 안에 공시될 수
    없으므로(통상 다음해 3월) as_of가 같은 해면 사용하지 않는다. 다음 해로 넘어가면 사용됨."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        s.add(Company(corp_code="00000006", corp_name="당해사업보고서"))
        s.add(Financial(
            corp_code="00000006", year=2025, quarter=4,  # FY2025 사업보고서
            net_income=80, equity=1000, revenue=1000,
            operating_income=100, depreciation=10, total_assets=2000,
            total_liabilities=1000, cash=100, total_debt=200, dividend_total=24,
        ))
        s.add(ValueupPlan(
            corp_code="00000006", disclosure_date="2024-01-01",
            target_roe=10.0, period_start="2024", period_end="2027",
            buyback_planned=True,
        ))
        s.commit()

        run(as_of="2025-12-31", corp_codes=["00000006"], session_factory=Session_)
        row_same_year = s.scalars(
            select(ValueupScore).where(ValueupScore.as_of == "2025-12-31")
        ).one()
        assert row_same_year.achievement_rate is None  # 같은 해 → 아직 못 봄
        s.commit()  # run()이 자체 세션을 열기 전에 커넥션을 놓아준다(StaticPool 공유)

        run(as_of="2026-06-30", corp_codes=["00000006"], session_factory=Session_)
        row_next_year = s.scalars(
            select(ValueupScore).where(ValueupScore.as_of == "2026-06-30")
        ).one()
        assert row_next_year.achievement_rate == pytest.approx(0.8)  # 다음 해 → 이제 보임


def test_latest_valueup_plan_tie_break_is_structurally_unreachable(engine) -> None:
    """[Med, GPT 지적 재검증] "동일 disclosure_date 2건" 시나리오는 valueup_plan의
    UniqueConstraint(corp_code, disclosure_date)(1.5, AD-7)가 DB 레벨에서 이미 차단한다 —
    같은 날짜에 정정공시가 겹쳐도 자연키 충돌로 두 번째 insert가 실패하므로 tie-break 자체가
    발생할 수 없다(GPT 원 지적은 스키마 확인 없이 나온 것으로 재검증 후 반례 확인, REFUTED).
    plan_id 보조 정렬키는 그래도 무해한 방어코드로 유지(제약이 느슨해질 미래 대비)."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        s.add(Company(corp_code="00000007", corp_name="정정공시"))
        s.add(ValueupPlan(
            corp_code="00000007", disclosure_date="2024-06-01",
            target_roe=8.0, period_start="2024", period_end="2027", buyback_planned=True,
        ))
        s.commit()
        s.add(ValueupPlan(  # 같은 (corp_code, disclosure_date) → UNIQUE 위반 확인
            corp_code="00000007", disclosure_date="2024-06-01",
            target_roe=9.0, period_start="2024", period_end="2027", buyback_planned=True,
        ))
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()


# ── T4: 통합 테스트 (SQLite in-memory + valuation_metrics 뷰) ──

@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:", future=True,
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.execute(text(CREATE_VALUATION_METRICS))
    return eng


def _seed(session: Session, corp_code: str = "00000001") -> None:
    session.add(Company(corp_code=corp_code, corp_name="테스트", market="KOSPI"))
    # 전년도(2024) 사업보고서 — look-ahead 부분차단(코드리뷰 High) 반영: as_of=2025-12-31
    # 시점엔 FY2025 사업보고서(2025년 quarter=4)는 아직 공시될 수 없어(통상 다음해 3월),
    # 실제로 알 수 있는 최신 확정실적은 FY2024다.
    session.add(Financial(
        corp_code=corp_code, year=2024, quarter=4,
        revenue=1000, net_income=80, operating_income=100, depreciation=10,
        equity=1000, total_assets=2000, total_liabilities=1000, cash=100,
        total_debt=200, dividend_total=24,
        buyback_amount=3_000_000, buyback_retired_amount=0,
    ))
    session.add(ValueupPlan(
        corp_code=corp_code, disclosure_date="2024-03-01",
        target_roe=10.0, target_payout_ratio=30.0, target_pbr=1.2,
        period_start="2024", period_end="2027", buyback_planned=True,
    ))
    session.commit()


def test_run_computes_and_upserts_score(engine) -> None:
    """AC1/2/4/5/6: end-to-end 계산이 정확히 나온다."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
        result = run(as_of="2025-12-31", session_factory=Session_)
        assert result.scored == 1
        assert result.complete is True  # 실패 0 → 이 as_of는 전 종목 동일 시점
        row = s.scalars(select(ValueupScore)).one()
        # actual_roe = net_income/equity*100 = 80/1000*100 = 8.0 → achievement = 8/10 = 0.8
        assert row.achievement_rate == pytest.approx(0.8)
        # progress(일 단위, 결정 B): (2025-12-31 − 2024-01-01) / (2027-12-31 − 2024-01-01)
        # = 730/1460 = 0.5 (연 단위 시절엔 1/3이었다)
        assert row.progress_rate == pytest.approx(0.5)
        assert row.buyback_executed is True
        assert row.buyback_retired is False  # 확정 0
        assert row.buyback_status == "purchased_only"
        # washing: progress 0.5>=0.5는 True 항이 됐지만 achievement 0.8<0.6이 확정 False
        # → 전체 False(목표를 80% 달성 중이면 워싱 아님. 연 단위 시절엔 진척 미달이 사유였다)
        assert row.washing_flag is False
        assert row.execution_score is not None


def test_run_skips_corp_without_plan(engine) -> None:
    """AC1: valueup_plan 없는 종목은 행 자체를 만들지 않는다(no-data 취급)."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        s.add(Company(corp_code="00000002", corp_name="계획없음"))
        s.commit()
        result = run(as_of="2025-12-31", corp_codes=["00000002"], session_factory=Session_)
        assert result.scored == 0
        assert s.scalar(select(ValueupScore)) is None


def test_run_is_idempotent(engine) -> None:
    """AC7: 같은 (corp_code, as_of) 재실행 시 중복 없이 갱신."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
        run(as_of="2025-12-31", session_factory=Session_)
        run(as_of="2025-12-31", session_factory=Session_)  # 재실행
        rows = s.scalars(select(ValueupScore)).all()
        assert len(rows) == 1


def test_run_picks_latest_disclosure_before_as_of(engine) -> None:
    """리드 결정 A: as_of 이전 최신 공시 채택(2024-03 목표10% 대신 2025-06 목표12%)."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)  # target_roe=10.0 @ 2024-03-01
        s.add(ValueupPlan(
            corp_code="00000001", disclosure_date="2025-06-01",
            target_roe=12.0, period_start="2025", period_end="2028",
            buyback_planned=True,
        ))
        s.commit()
        run(as_of="2025-12-31", session_factory=Session_)
        row = s.scalars(select(ValueupScore)).one()
        # actual_roe=8.0 → 8/12 (최신 공시 target) 아니라 8/10이면 구버전 채택 오류
        assert row.achievement_rate == pytest.approx(8.0 / 12.0)


def test_run_null_metrics_propagate_to_null_score(engine) -> None:
    """financials/metrics 없는 종목: plan은 있으나 실적 없음 → achievement_rate null."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        s.add(Company(corp_code="00000003", corp_name="실적없음"))
        s.add(ValueupPlan(
            corp_code="00000003", disclosure_date="2024-01-01",
            target_roe=10.0, period_start="2024", period_end="2027",
            buyback_planned=True,
        ))
        s.commit()
        run(as_of="2025-12-31", corp_codes=["00000003"], session_factory=Session_)
        row = s.scalars(select(ValueupScore)).one()
        assert row.achievement_rate is None
        assert row.execution_score is None
        assert row.buyback_status == "unknown"
        # 결정 B(일 단위)로 progress=0.5>=0.5 → True 항. 확정 False 항이 없고
        # achievement·retired가 unknown이므로 Kleene 3치상 washing은 None(판단 불가).
        # (연 단위 시절엔 progress=1/3<0.5 확정 False가 전체를 False로 지배했다 —
        # 산식 정밀도가 바뀌면 임계 근처 판정이 바뀌는 것이 올바른 null 전파다.)
        assert row.progress_rate == pytest.approx(0.5)
        assert row.washing_flag is None


# ── T5: 트랜잭션 정책 — 종목별 커밋 + 실패 목록 (코드리뷰 2026-07-21 결정) ──

def test_run_partial_failure_keeps_successful_corps(engine, monkeypatch) -> None:
    """한 종목이 터져도 나머지 종목의 결과는 살아남고, 실패는 목록에 남는다.

    전량 원자성을 택했다면 이 테스트는 '전부 롤백'을 기대했을 것 — 부분 성공을 택한 대신
    실패를 **숨기지 않는다**(ScoreRunResult.failed / .complete)는 것이 이 정책의 계약이다.
    """
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s, corp_code="00000001")
        _seed(s, corp_code="00000009")

    real_latest_plan = repo.latest_valueup_plan

    def _boom(session, corp_code, as_of):
        if corp_code == "00000009":
            raise RuntimeError("의도적 실패")
        return real_latest_plan(session, corp_code, as_of)

    monkeypatch.setattr(repo, "latest_valueup_plan", _boom)

    result = run(as_of="2025-12-31", session_factory=Session_)

    assert result.scored == 1  # 정상 종목은 저장됨
    assert result.succeeded == ["00000001"]
    assert [c for c, _ in result.failed] == ["00000009"]
    assert result.complete is False  # 이 as_of 스냅샷은 불완전 — 게시 전 확인 필요
    with Session_() as s:
        rows = s.scalars(select(ValueupScore)).all()
        assert [r.corp_code for r in rows] == ["00000001"]


def test_run_failed_corp_leaves_no_partial_row(engine, monkeypatch) -> None:
    """실패 종목의 트랜잭션은 통째로 롤백된다 — 반쪽 행이 남지 않는다.

    '종목별 커밋'은 종목 **경계**에서만 부분 성공을 허용한다는 뜻이지, 한 종목 안에서
    반쯤 쓰인 상태를 허용한다는 뜻이 아니다.
    """
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s, corp_code="00000001")

    real_upsert = repo.upsert_valueup_score

    def _boom_after_write(session, rec):
        real_upsert(session, rec)  # 행을 쓴 **직후** 실패시킨다
        raise RuntimeError("저장 직후 실패")

    monkeypatch.setattr(repo, "upsert_valueup_score", _boom_after_write)

    result = run(as_of="2025-12-31", session_factory=Session_)

    assert result.scored == 0
    assert [c for c, _ in result.failed] == ["00000001"]
    with Session_() as s:
        assert s.scalar(select(ValueupScore)) is None  # 롤백됨
```

### `tests/test_valueup_parser.py` (42행)

파서 오독 방지 테스트

```python
"""Story 5-1 — 밸류업 공시 목표 파싱(주주환원율 신규 필드) 검증.

기존 파서 테스트는 test_valueup_ingest.py에 있다. 이 파일은 5-1에서 추가된
총주주환원율 목표 추출과 "과거 실적 오독 방지" 규칙만 다룬다.
"""
# ── 5-1: 주주환원율 목표(배당성향과 다른 지표) ──

def test_total_return_target_parsed_separately() -> None:
    """AC1: 주주환원율 목표는 target_total_return_ratio로, 배당성향과 섞이지 않는다."""
    from app.ingest.dart_valueup import parse_targets

    got = parse_targets("□ 주주환원 확대\n- 주주환원율 중장기 50% 목표\n- K-ICS 비율 유지")
    assert got["target_total_return_ratio"] == 50.0
    assert got["target_payout_ratio"] is None  # 배당성향 필드는 건드리지 않는다


def test_total_return_past_result_is_rejected() -> None:
    """실샘플 회귀: 이행 실적으로 등장한 주주환원율을 목표로 오독하지 않는다.

    계획 공시는 목표와 실적을 한 문서에 함께 싣는다 — 라벨+숫자만 보면 실데이터 13건 중
    5건이 과거 실적이었다(고려아연 268%, KT&G 108.9%, HMM 72.8% 등).
    """
    from app.ingest.dart_valueup import parse_targets

    for text in (
        "- '25년 6월 자사주 전량 소각 완료\n- '25년 총 주주환원율 268.0%\n- '25년 유보율 9,504%",
        "- 자기주식 취득 및 소각완료 : 2조 1,432억원\n- 총주주환원율 72.8%\n□ 지배구조",
        "③ 주주환원 현황('22~'24 3년 평균 주주환원율 78%)\n3. 계획",
    ):
        assert parse_targets(text)["target_total_return_ratio"] is None


def test_total_return_picks_target_over_nearby_result() -> None:
    """한 문서에 실적과 목표가 같이 있으면 **목표 쪽**을 집는다(실샘플 plan 33)."""
    from app.ingest.dart_valueup import parse_targets

    text = (
        "③ 주주환원 현황('22~'24 3년 평균 주주환원율 78%)\n"
        "3. 계획 및 목표\n"
        "③ 주주환원: '25~'27 3년 평균 주주환원율 40% 목표\n"
    )
    assert parse_targets(text)["target_total_return_ratio"] == 40.0
```

### `dashboard/src/components/badges.tsx` (139행)

**5-2 핵심** — `ScoreBasisChip`·`ValueUpCell`

```tsx
import type { ScreeningRow } from "../api/screening";

// 3.2 Figma 범례(node 11:2)의 null 시각 언어를 그대로 구현.
// 원칙: null을 빈칸·0·"아니오"로 뭉개지 않는다(2.4~2.6 API 계약 승계).

function Pill({ text, bg, fg, dashed }: { text: string; bg?: string; fg: string; dashed?: boolean }) {
  return (
    <span
      className="inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-semibold"
      style={{
        background: bg ?? "transparent",
        color: fg,
        border: dashed ? "1px dashed #d1d5db" : undefined,
      }}
    >
      {text}
    </span>
  );
}

export function WashingBadge({ flag }: { flag: boolean | null }) {
  if (flag === true) return <Pill text="⚠ 워싱 의심" bg="#fee4e2" fg="#b42318" />;
  if (flag === false) return <span className="text-xs text-gray-400">근거 없음</span>;
  return <Pill text="판단 불가" fg="#6b7280" dashed />; // null
}

function scoreColor(v: number): string {
  if (v >= 70) return "#0e9f6e";
  if (v >= 50) return "#65a30d";
  if (v >= 30) return "#ca8a04";
  return "#dc2626";
}

// 5-1: execution_score는 **기업이 공시한 약속에 대해서만** 채점되므로 가중치 기반이 종목마다
// 다르다. 그 사실을 감추면 기준이 다른 점수를 같은 척도로 비교하게 된다 — null을 빈칸으로
// 뭉개지 않는다는 3.2 원칙과 같은 이유로, 근거를 점수 옆에 항상 붙인다.
const BASIS_LABEL: Record<string, string> = {
  roe: "ROE",
  buyback: "자사주",
  payout: "배당성향",
  total_return: "주주환원",
};

export function scoreBasisParts(basis: string): string[] {
  return basis.split("+").map((p) => BASIS_LABEL[p] ?? p);
}

export function ScoreBasisChip({ basis }: { basis: string | null }) {
  if (!basis) return null;
  const parts = scoreBasisParts(basis);
  const single = parts.length === 1;
  // 단일 항목은 특히 조심해야 한다 — 자사주 단독은 이진값이라 점수가 0 또는 100뿐이고,
  // 3개 항목으로 매긴 100점과 나란히 놓이면 같은 성취처럼 읽힌다.
  return (
    <span
      className="text-[9px]"
      style={{ color: single ? "#b45309" : "#9ca3af" }}
      title={
        single
          ? `${parts[0]} 항목 하나만 공시돼 그것만으로 채점됨 — 다항목 점수와 직접 비교 금지`
          : `공시한 ${parts.length}개 항목으로 채점: ${parts.join(", ")}`
      }
    >
      {single ? `${parts[0]}만` : parts.join("·")}
    </span>
  );
}

export function ValueUpCell({ row }: { row: ScreeningRow }) {
  if (!row.has_valueup_score) return <Pill text="미집계" fg="#9ca3af" dashed />;
  if (row.execution_score === null) {
    // 점수 null의 두 원인(약속 자체가 없음 / 약속은 있으나 실적 미상)은 API에서 구분되지
    // 않는다 — 둘 다 "판단 불가"로 정직하게 표시한다(추정해서 나누지 않는다).
    return (
      <div className="flex flex-col items-end gap-0.5">
        <span className="text-[15px] font-bold text-gray-400">—</span>
        <span className="text-[10px] text-gray-400">판단 불가</span>
      </div>
    );
  }
  return (
    <div className="flex flex-col items-end gap-0.5">
      <span className="text-[15px] font-bold" style={{ color: scoreColor(row.execution_score) }}>
        {row.execution_score.toFixed(0)}
      </span>
      <ScoreBasisChip basis={row.score_basis} />
    </div>
  );
}

// 은행·보험 등 M&A 스코어가 구조적으로 산출 불가한 업종(KSIC 64~66 금융·보험).
// 리스트(MnaCell)와 상세(MnaBreakdown)가 같은 판정을 공유(3.4 리뷰 Med — 표현 불일치 방지).
export function isUnsupportedSector(sector: string | null): boolean {
  if (!sector) return false;
  const p = sector.slice(0, 2);
  return p === "64" || p === "65" || p === "66";
}

export function MnaCell({ row }: { row: ScreeningRow }) {
  if (!row.has_mna_score) return <Pill text="미집계" fg="#9ca3af" dashed />;
  if (row.mna_target_score === null) {
    if (isUnsupportedSector(row.sector)) {
      return (
        <div className="flex flex-col items-end gap-0.5">
          <Pill text="미지원 업종" bg="#f3f4f6" fg="#6b7280" />
          <span className="text-[9px] text-gray-400">은행·보험</span>
        </div>
      );
    }
    return (
      <div className="flex flex-col items-end gap-0.5">
        <span className="text-[15px] font-bold text-gray-400">—</span>
        <span className="text-[10px] text-gray-400">산출 불가</span>
      </div>
    );
  }
  return (
    <div className="flex flex-col items-end gap-0.5">
      <span className="text-[15px] font-bold" style={{ color: scoreColor(row.mna_target_score) }}>
        {row.mna_target_score.toFixed(1)}
      </span>
      <PopulationBasisChip basis={row.population_basis} />
    </div>
  );
}

export function PopulationBasisChip({ basis }: { basis: string | null }) {
  if (!basis) return null;
  let label = "전체시장";
  if (basis.startsWith("sector:")) label = `업종 내 (KSIC ${basis.slice(7)})`;
  else if (basis === "market_fallback") label = "전체시장 폴백";
  return <span className="text-[9px] text-gray-400">{label}</span>;
}

export function MarketPill({ market }: { market: string | null }) {
  if (!market) return <span className="text-xs text-gray-400">—</span>;
  const kospi = market === "KOSPI";
  return <Pill text={market} bg={kospi ? "#eff6ff" : "#f5f3ff"} fg={kospi ? "#1d4ed8" : "#6d28d9"} />;
}
```

### `dashboard/src/components/badges.test.tsx` (136행)

프론트 테스트

```tsx
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

// vitest globals 미사용 시 testing-library 자동 cleanup이 비활성 — 명시적 cleanup
afterEach(cleanup);
import { MnaCell, ValueUpCell, WashingBadge, ScoreBasisChip } from "./badges";
import type { ScreeningRow } from "../api/screening";

// null 시각 언어(3.2 범례)의 상태 우선순위 검증 — 금칙: 빈칸·0·"아니오"로 뭉개기.

function row(partial: Partial<ScreeningRow>): ScreeningRow {
  return {
    corp_code: "00000000",
    corp_name: "테스트",
    market: "KOSPI",
    sector: "26100",
    as_of: "2026-07-13",
    roe: null,
    pbr: null,
    execution_score: null,
    score_basis: null,
    washing_flag: null,
    buyback_status: null,
    buyback_executed: null,
    mna_target_score: null,
    population_basis: null,
    has_valueup_score: true,
    has_mna_score: true,
    ...partial,
  };
}

describe("WashingBadge — 3상태", () => {
  it("true → 워싱 의심", () => {
    render(<WashingBadge flag={true} />);
    expect(screen.getByText(/워싱 의심/)).toBeTruthy();
  });
  it("false → 근거 없음(강조 없음)", () => {
    render(<WashingBadge flag={false} />);
    expect(screen.getByText("근거 없음")).toBeTruthy();
  });
  it('null → "판단 불가"(빈칸/"아니오" 금지)', () => {
    render(<WashingBadge flag={null} />);
    expect(screen.getByText("판단 불가")).toBeTruthy();
    expect(screen.queryByText("아니오")).toBeNull();
  });
});

describe("ValueUpCell — 미집계 vs 산출불가 vs 값", () => {
  it("has_valueup_score=false → 미집계(점수 null이어도 산출불가 아님)", () => {
    render(<ValueUpCell row={row({ has_valueup_score: false, execution_score: null })} />);
    expect(screen.getByText("미집계")).toBeTruthy();
  });
  it("row 있음 + score null → — (0으로 표시 금지)", () => {
    render(<ValueUpCell row={row({ execution_score: null })} />);
    expect(screen.getByText("—")).toBeTruthy();
    expect(screen.queryByText("0")).toBeNull();
  });
  it("값 있으면 숫자 표시", () => {
    render(<ValueUpCell row={row({ execution_score: 85 })} />);
    expect(screen.getByText("85")).toBeTruthy();
  });
});

describe("MnaCell — 상태 우선순위: 미집계 > 미지원업종 > 산출불가 > 값", () => {
  it("has_mna_score=false가 최우선(금융주라도 미집계)", () => {
    render(<MnaCell row={row({ has_mna_score: false, sector: "64110" })} />);
    expect(screen.getByText("미집계")).toBeTruthy();
    expect(screen.queryByText("미지원 업종")).toBeNull();
  });
  it("KSIC 64~66 + null → 미지원 업종(개별 산출불가가 아니라 업종 안내)", () => {
    render(<MnaCell row={row({ sector: "65121", mna_target_score: null })} />);
    expect(screen.getByText("미지원 업종")).toBeTruthy();
  });
  it("비금융 + null → 산출 불가(0점/최하위 금지)", () => {
    render(<MnaCell row={row({ sector: "26100", mna_target_score: null })} />);
    expect(screen.getByText("산출 불가")).toBeTruthy();
    expect(screen.queryByText("0.0")).toBeNull();
  });
  it("값 있으면 점수 + population_basis chip", () => {
    render(<MnaCell row={row({ mna_target_score: 71.1, population_basis: "market_fallback" })} />);
    expect(screen.getByText("71.1")).toBeTruthy();
    expect(screen.getByText("전체시장 폴백")).toBeTruthy();
  });
  it("sector null(미분류) + null → 산출 불가(미지원으로 오판하지 않음)", () => {
    render(<MnaCell row={row({ sector: null, mna_target_score: null })} />);
    expect(screen.getByText("산출 불가")).toBeTruthy();
  });
});

// ── 5-1: score_basis 시각 언어 ──

describe("ScoreBasisChip", () => {
  it("다항목은 근거를 나열한다", () => {
    render(<ScoreBasisChip basis="roe+buyback+payout" />);
    expect(screen.getByText("ROE·자사주·배당성향")).toBeTruthy();
  });

  it("주주환원율은 배당성향과 다른 라벨로 표시된다", () => {
    render(<ScoreBasisChip basis="buyback+total_return" />);
    expect(screen.getByText("자사주·주주환원")).toBeTruthy();
  });

  it("단일 항목은 '~만'으로 구분 표기한다", () => {
    // 자사주 단독은 이진값이라 0/100뿐 — 다항목 100점과 같아 보이면 안 된다
    render(<ScoreBasisChip basis="buyback" />);
    expect(screen.getByText("자사주만")).toBeTruthy();
  });

  it("basis가 없으면 아무것도 그리지 않는다", () => {
    const { container } = render(<ScoreBasisChip basis={null} />);
    expect(container.innerHTML).toBe("");
  });
});

describe("ValueUpCell + score_basis", () => {
  it("점수와 근거를 함께 보여준다", () => {
    render(<ValueUpCell row={row({ execution_score: 100, score_basis: "roe+buyback+payout" })} />);
    expect(screen.getByText("100")).toBeTruthy();
    expect(screen.getByText("ROE·자사주·배당성향")).toBeTruthy();
  });

  it("같은 100점이라도 근거가 다르면 다르게 읽힌다(회귀 방지)", () => {
    // 실데이터: 기아 100(roe+buyback+payout) vs 삼성전자 100(buyback 단독)
    const { unmount } = render(<ValueUpCell row={row({ execution_score: 100, score_basis: "buyback" })} />);
    expect(screen.getByText("자사주만")).toBeTruthy();
    unmount();
    render(<ValueUpCell row={row({ execution_score: 100, score_basis: "roe+buyback+payout" })} />);
    expect(screen.queryByText("자사주만")).toBeNull();
  });

  it("점수 null은 빈칸이 아니라 '판단 불가'로 표시한다", () => {
    render(<ValueUpCell row={row({ execution_score: null })} />);
    expect(screen.getByText("판단 불가")).toBeTruthy();
  });
});
```

### `dashboard/src/pages/CompanyDetail.tsx` (143행)

상세 화면 배선

```tsx
import { Link, useParams } from "react-router-dom";
import { useGapDetail, useMetricsByCorp, useMnaDetail } from "../api/detail";
import { useScreeningDetail } from "../api/screening";
import { GapCard } from "../components/detail/GapCard";
import { MetricsChart } from "../components/detail/MetricsChart";
import { MnaBreakdown } from "../components/detail/MnaBreakdown";
import { InvestmentPoints } from "../components/detail/InvestmentPoints";
import { MarketPill, ScoreBasisChip } from "../components/badges";
import { hasTagBasis, mnaTags, valueupTags } from "../lib/investmentTags";

// UX-DR3/UX-DR4 종목 상세 화면(3.2 Screen 2 시안).
//
// 시점 정합(3.4 리뷰 High): 화면 전체가 header(/screening)의 as_of 단일 기준일로 수렴 —
// gap·mna 쿼리는 header.as_of로 체이닝(두 API 모두 as_of 파라미터 기존재, 백엔드 무변경),
// 태그의 roe/pbr도 /metrics 시계열이 아니라 header 행에서 가져온다. 시계열 차트만 예외
// (본질이 "역사"라 시점 정합 위반이 아님).
//
// 에러 세탁 방지(3.4 리뷰 High): 각 쿼리의 isError를 구분 소비 — "미집계"는 성공 응답의
// 빈 결과일 때만, 요청 실패는 명시적 오류 카드로(장애를 정상 결측으로 위장 금지).
export default function CompanyDetail() {
  const { corpCode } = useParams<{ corpCode: string }>();

  const header = useScreeningDetail(corpCode);
  const asOf = header.data?.as_of;
  const gap = useGapDetail(corpCode, asOf);
  const mna = useMnaDetail(corpCode, asOf);
  const metrics = useMetricsByCorp(corpCode);

  const tags = [...valueupTags(header.data ?? null, gap.data ?? null), ...mnaTags(mna.data ?? null)];
  const tagInputsLoading = header.isLoading || gap.isLoading || mna.isLoading;
  const basis = hasTagBasis(header.data ?? null, gap.data ?? null, mna.data ?? null);

  return (
    <div className="min-h-screen bg-[#f5f6f8] p-7">
      <Link to="/" className="mb-4 inline-block text-xs font-semibold text-emerald-600">
        ← 리스트로
      </Link>

      {header.isError && (
        <div className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-xs font-semibold text-red-700">
          종목 정보를 불러오지 못했습니다 — 요청 오류(데이터 없음이 아닙니다)
        </div>
      )}

      <header className="mb-5 flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl font-bold text-gray-900">{header.data?.corp_name ?? corpCode}</h1>
            <MarketPill market={header.data?.market ?? null} />
            <span className="text-xs text-gray-400">
              {corpCode} · {header.data?.sector ?? "—"}
            </span>
          </div>
          <p className="mt-1 text-[11px] text-gray-400">{asOf ? `기준일 ${asOf}` : "…"}</p>
        </div>
        <div className="flex gap-3">
          <ScoreChip
            label="실행점수"
            value={header.data?.execution_score ?? null}
            color="#0e9f6e"
            basis={header.data?.score_basis ?? null}
          />
          <ScoreChip label="M&A 타겟" value={header.data?.mna_target_score ?? null} color="#65a30d" />
        </div>
      </header>

      <div className="flex gap-5">
        <div className="flex flex-1 flex-col gap-5">
          <div className="rounded-xl border border-gray-100 bg-white p-5">
            <h3 className="mb-3 text-sm font-bold text-gray-900">지표 분기 시계열 · ROE</h3>
            {metrics.isError ? (
              <ErrorNote what="지표 시계열" />
            ) : metrics.isLoading ? (
              <p className="py-8 text-center text-sm text-gray-400">불러오는 중…</p>
            ) : (
              <MetricsChart metrics={metrics.data ?? []} />
            )}
          </div>
          {gap.isError ? (
            <ErrorCard what="밸류업 갭 분석" />
          ) : gap.isLoading || !asOf ? (
            <LoadingCard />
          ) : (
            <GapCard gap={gap.data ?? null} />
          )}
        </div>
        <div className="flex w-[420px] shrink-0 flex-col gap-5">
          {mna.isError ? (
            <ErrorCard what="M&A 4요소 분해" />
          ) : mna.isLoading || !asOf ? (
            <LoadingCard />
          ) : (
            <MnaBreakdown mna={mna.data ?? null} />
          )}
          <InvestmentPoints tags={tags} loading={tagInputsLoading} hasBasis={basis} />
        </div>
      </div>
    </div>
  );
}

function ScoreChip({
  label, value, color, basis,
}: { label: string; value: number | null; color: string; basis?: string | null }) {
  return (
    <div className="rounded-xl border border-gray-100 bg-white px-4 py-3">
      <div className="text-[10px] font-semibold text-gray-500">{label}</div>
      <div className="flex items-center gap-1">
        <span className="text-xl font-bold" style={{ color: value === null ? "#9ca3af" : color }}>
          {value === null ? "—" : value.toFixed(0)}
        </span>
        <span className="text-[10px] text-gray-400">/100</span>
      </div>
      {/* 5-1: 점수만 크게 보여주고 채점 근거를 숨기면 기준이 다른 값이 같아 보인다 */}
      {value !== null && basis ? <ScoreBasisChip basis={basis} /> : null}
    </div>
  );
}

function LoadingCard() {
  return (
    <div className="rounded-xl border border-gray-100 bg-white p-5 text-sm text-gray-400">
      불러오는 중…
    </div>
  );
}

// 요청 실패는 "미집계/데이터 없음"과 명확히 구분되는 오류 표시(3.4 리뷰 High)
function ErrorCard({ what }: { what: string }) {
  return (
    <div className="rounded-xl border border-red-100 bg-red-50 p-5 text-sm text-red-700">
      {what}을(를) 불러오지 못했습니다 — 요청 오류(데이터 없음이 아닙니다)
    </div>
  );
}

function ErrorNote({ what }: { what: string }) {
  return (
    <p className="py-8 text-center text-sm text-red-600">
      {what}을(를) 불러오지 못했습니다 — 요청 오류
    </p>
  );
}
```

### 나머지 변경 (diff)

마이그레이션 2건, 스키마·리포지토리·모델, 프론트 타입입니다.

```diff
diff --git a/alembic/versions/0012_coverage_fields.py b/alembic/versions/0012_coverage_fields.py
new file mode 100644
index 0000000..f884ad3
--- /dev/null
+++ b/alembic/versions/0012_coverage_fields.py
@@ -0,0 +1,28 @@
+"""주주환원율 목표 + score_basis (5-1 execution_score 커버리지)
+
+Revision ID: 0012_coverage_fields
+Revises: 0011_valueup_score_gap_fields
+Create Date: 2026-07-22
+"""
+from __future__ import annotations
+
+from collections.abc import Sequence
+
+import sqlalchemy as sa
+from alembic import op
+
+revision: str = "0012_coverage_fields"
+down_revision: str | None = "0011_valueup_score_gap_fields"
+branch_labels: str | Sequence[str] | None = None
+depends_on: str | Sequence[str] | None = None
+
+
+def upgrade() -> None:
+    # 배당성향과 다른 지표라 별도 컬럼(기존 값을 옮기지 않는다 — 섞으면 정의가 어긋난다)
+    op.add_column("valueup_plan", sa.Column("target_total_return_ratio", sa.Float))
+    op.add_column("valueup_score", sa.Column("score_basis", sa.String(40)))
+
+
+def downgrade() -> None:
+    op.drop_column("valueup_score", "score_basis")
+    op.drop_column("valueup_plan", "target_total_return_ratio")
diff --git a/alembic/versions/0013_metrics_view_total_return.py b/alembic/versions/0013_metrics_view_total_return.py
new file mode 100644
index 0000000..0bede20
--- /dev/null
+++ b/alembic/versions/0013_metrics_view_total_return.py
@@ -0,0 +1,31 @@
+"""valuation_metrics 뷰에 total_return_ratio 추가 (5-1)
+
+Revision ID: 0013_metrics_view_total_return
+Revises: 0012_coverage_fields
+Create Date: 2026-07-22
+
+뷰는 Base.metadata 밖의 raw SQL이라(1.7 결정) 정의가 바뀌면 DROP→CREATE로 갈아끼운다.
+데이터 이동은 없다 — 뷰는 저장 실체가 없으므로 재생성만으로 새 컬럼이 반영된다.
+"""
+from __future__ import annotations
+
+from collections.abc import Sequence
+
+from alembic import op
+
+from app.sql_views import CREATE_VALUATION_METRICS, DROP_VALUATION_METRICS
+
+revision: str = "0013_metrics_view_total_return"
+down_revision: str | None = "0012_coverage_fields"
+branch_labels: str | Sequence[str] | None = None
+depends_on: str | Sequence[str] | None = None
+
+
+def upgrade() -> None:
+    op.execute(DROP_VALUATION_METRICS)
+    op.execute(CREATE_VALUATION_METRICS)
+
+
+def downgrade() -> None:
+    # 이전 정의로 되돌리려면 0005의 본문이 필요하다 — 뷰만 지운다(재생성은 0005 재실행).
+    op.execute(DROP_VALUATION_METRICS)
diff --git a/app/models.py b/app/models.py
index aa45d94..37b8134 100644
--- a/app/models.py
+++ b/app/models.py
@@ -123,6 +123,10 @@ class ValueupPlan(Base):
     # 목표치 (best-effort 파싱, 없으면 null)
     target_roe: Mapped[float | None] = mapped_column(Float)  # %
     target_payout_ratio: Mapped[float | None] = mapped_column(Float)  # 배당성향 %
+    # 총주주환원율(배당+자사주매입)/순이익 % — **배당성향과 다른 지표**(5-1).
+    # 실데이터상 기업 다수가 배당성향이 아니라 이쪽으로 약속한다(공시 60건 중 17건).
+    # 한 필드에 섞으면 목표와 실적의 정의가 어긋나므로 분리해서 받는다.
+    target_total_return_ratio: Mapped[float | None] = mapped_column(Float)
     target_pbr: Mapped[float | None] = mapped_column(Float)  # 배
     period_start: Mapped[str | None] = mapped_column(String(10))  # 목표기간 시작(연도/ISO)
     period_end: Mapped[str | None] = mapped_column(String(10))  # 목표기간 종료
@@ -199,6 +203,10 @@ class ValueupScore(Base):
     buyback_executed: Mapped[bool | None] = mapped_column(Boolean)
     buyback_retired: Mapped[bool | None] = mapped_column(Boolean)
     buyback_status: Mapped[str | None] = mapped_column(String(20))  # retired/purchased_only/none/unknown
+    # execution_score가 **어떤 약속을 기준으로** 채점됐는지(5-1). 예: 'return+buyback'.
+    # 기업이 공시한 항목만으로 채점하므로 가중치 기반이 종목마다 다르다 — 그 사실을
+    # 숨기면 점수를 종목 간 비교에 잘못 쓰게 된다(mna의 population_basis와 같은 이유).
+    score_basis: Mapped[str | None] = mapped_column(String(40))
 
 
 class MnaScore(Base):
diff --git a/app/repositories/screening.py b/app/repositories/screening.py
index be61212..69579fc 100644
--- a/app/repositories/screening.py
+++ b/app/repositories/screening.py
@@ -213,6 +213,9 @@ def list_screening(
             "has_valueup_score": vs is not None,
             "has_mna_score": ms is not None,
             "execution_score": vs.execution_score if vs else None,
+            # 점수가 **무엇을 근거로** 매겨졌는지(5-1). 공시한 약속만으로 채점하므로
+            # 가중치 기반이 종목마다 다르다 — 숨기면 기준이 다른 점수를 나란히 비교하게 된다.
+            "score_basis": vs.score_basis if vs else None,
             "washing_flag": vs.washing_flag if vs else None,
             "buyback_status": vs.buyback_status if vs else None,
             "buyback_executed": vs.buyback_executed if vs else None,
diff --git a/app/repositories/valueup_plan.py b/app/repositories/valueup_plan.py
index aa8192f..8815a36 100644
--- a/app/repositories/valueup_plan.py
+++ b/app/repositories/valueup_plan.py
@@ -14,6 +14,7 @@ from app.models import ValueupPlan
 _TARGET_FIELDS = (
     "target_roe",
     "target_payout_ratio",
+    "target_total_return_ratio",
     "target_pbr",
     "period_start",
     "period_end",
diff --git a/app/schemas.py b/app/schemas.py
index bc4d97a..16bf396 100644
--- a/app/schemas.py
+++ b/app/schemas.py
@@ -60,6 +60,10 @@ class ScreeningOut(BaseModel):
     has_valueup_score: bool
     has_mna_score: bool
     execution_score: float | None = None
+    # execution_score의 채점 근거(5-1): 'roe+buyback+payout' 등 + 구분 토큰.
+    # null이면 점수도 null. population_basis와 같은 역할 — 기준이 다른 값을 같은 척도로
+    # 쓰는 것을 막기 위해 점수와 항상 함께 전달한다.
+    score_basis: str | None = None
     washing_flag: bool | None = None
     buyback_status: str | None = None
     buyback_executed: bool | None = None
@@ -143,5 +147,6 @@ class GapAnalysisOut(BaseModel):
     achievement_rate: float | None = None
     progress_rate: float | None = None
     execution_score: float | None = None
+    score_basis: str | None = None  # 채점 근거(5-1) — ScreeningOut과 같은 계약
     washing_flag: bool | None = None
     buyback_status: str | None = None
diff --git a/dashboard/src/api/detail.ts b/dashboard/src/api/detail.ts
index 4065c02..787adca 100644
--- a/dashboard/src/api/detail.ts
+++ b/dashboard/src/api/detail.ts
@@ -14,6 +14,7 @@ export interface GapDetail {
   achievement_rate: number | null;
   progress_rate: number | null;
   execution_score: number | null;
+  score_basis: string | null; // 채점 근거(5-1)
   washing_flag: boolean | null;
   buyback_status: string | null;
 }
diff --git a/dashboard/src/api/screening.ts b/dashboard/src/api/screening.ts
index 33b1e03..a717887 100644
--- a/dashboard/src/api/screening.ts
+++ b/dashboard/src/api/screening.ts
@@ -11,6 +11,7 @@ export interface ScreeningRow {
   roe: number | null; // 핵심지표(AC3) — null=지표 없음
   pbr: number | null;
   execution_score: number | null;
+  score_basis: string | null; // 채점 근거(5-1) — 가중치 기반이 종목마다 다름
   washing_flag: boolean | null; // true=워싱의심 / false=근거없음 / null=판단불가
   buyback_status: string | null;
   buyback_executed: boolean | null;
```
