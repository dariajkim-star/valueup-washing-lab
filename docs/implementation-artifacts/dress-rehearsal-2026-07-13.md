# 드레스 리허설 리포트 — 2026-07-13 (KOSPI 33종목 라이브 end-to-end)

> 목적: Epic 2 API(2-4)로 숫자가 노출되기 전에 **실데이터로 두 엔진을 처음 완주**시켜,
> "실데이터 보고 판단"으로 미뤄둔 결정들을 데이터로 전환. 수집→뷰→gap_engine→mna_engine 전 구간.

## 실행 요약

- **유니버스**: KOSPI 대표 33종목(티커→corpCode 매칭 33/33)
- **수집(359초, 실패 0)**: 재무 FY2023·FY2024 66행(buyback 1.8 경로 포함) · 지분 33행 · **밸류업 공시 79건/26종목** · 매크로 3,369행(4지표, 2020~) · 시세 990행(KRX 로그인 포함)
- **엔진(as_of=2026-07-13)**: gap 26행 · mna 31행 적재. 예외·중단 0(NFR2 준수 확인)

## 핵심 발견 5가지

### 🔴 발견 1 — `dividend_total`이 구조적 100% null (1-8 이전 buyback과 동일한 병)

재무 66행 전부 dividend_total null → 뷰 payout_ratio 전부 null → **execution_score 0/26(0%)**.
1.2가 "배당은 별도공시 best-effort"로 남겨둔 채 실제 수집 경로가 한 번도 구현되지 않았음
(fnlttSinglAcntAll에 배당 라인 없음 — buyback과 정확히 같은 패턴). 실행점수의 배당 항(0.2 가중)이
이것 없이는 영원히 계산 불가. **→ DART `alotMatter.json`(배당에 관한 사항) 수집 스토리 필요(1-8 미러).**

### 🔴 발견 2 — 금융주 섹터 문제가 정확히 예측대로 실증됨 (2-7 우선순위 상승)

mna 총점 null 16종목의 결측 원인을 보면 **금융주 7개(메리츠·우리·KB·신한·하나·삼성화재·삼성생명)가
전부 valuation+capacity null** — 은행·보험은 사업모델상 EV/EBITDA·부채비율이 무의미해서 뷰가 null을
내고, 엄격 null이 정직하게 전파한 것. "은행 EV/EBITDA는 무의미"라던 finance 우려가 관념이 아니라
**데이터로 확인됨**. 해법은 "있는 것만 평균"(왜곡)이 아니라 **2-7(sector peer-group) + 레벨2(금융=P/B·ROE
변수 세트)**가 맞다는 것도 함께 실증. 비금융 결측(현대글로비스·삼성바이오=ownership, 셀트리온·현대모비스
등=재무 일부)은 개별 수집 이슈.

### 🟡 발견 3 — 1.5 자유서식 파서의 실전 파싱률: target_roe 24%·payout 14%·period 13%·pbr 0%

79건 공시 중 목표수치 파싱 성공률이 낮음 → achievement_rate 2/26(8%). 두 가지 원인 혼재:
(a) "이행현황"류 문서가 계획공시와 함께 잡힘(1.5 defer F9 그대로), (b) 표·서술형 목표의 정규식 한계.
**이제 raw_text 실샘플 79건이 확보**됐으므로 1.5가 미뤄둔 "실샘플 후 튜닝"이 가능해짐. target_pbr 0%는
2.1에서 "계산 미사용" 결정이라 실해 없음.

### 🟢 발견 4 — 1.8 buyback 데이터·Kleene 3치 논리가 실전에서 설계대로 작동

buyback_status: **retired 16 / unknown 10 / none·purchased_only 0** — 대형주가 실제로 소각까지
간다는 신호가 잡힘(2026 의무소각 정책 정합). washing_flag: **False 18 / None 8 / True 0** —
소각 확정(retired=True)이면 진척률 몰라도 확정 False(Kleene), 애매하면 null. 대형 우량주 표본에서
워싱 0은 타당(워싱 후보는 중소형에서 나올 가능성). **null>틀린값 계약이 실데이터에서 그대로 구현됨.**

### 🟢 발견 5 — M&A 랭킹이 finance 직관과 부합 + mid-rank 패치 실증

총점 15종목 랭킹: **POSCO홀딩스(71.1, 저PBR+자사주多) > NAVER > 크래프톤 > 기아 > HMM(저평가+순현금)**
> … > 두산에너빌리티(28.6, 고평가). 저평가·현금부자·지배구조 취약 순서가 IB 직관과 맞음.
macro_score 전종목 0.5(중립) — 기준금리 동결 구간에서 **mid-rank 패치 덕에 중립**으로 나옴
(패치 전 min-rank였으면 1.0 "역사적 최저" 왜곡이 그대로 노출될 뻔).

## 원천 커버리지 상세

| 필드 | non-null | 판정 |
|---|---|---|
| financials.depreciation | **6/66 (9%)** | EBITDA≈EBIT 근사가 사실상 표준 상태 — 기존 defer(감가상각 수집) 우선순위 재확인 |
| financials.dividend_total | **0/66 (0%)** | 🔴 발견 1 — 수집 스토리 필요 |
| financials.buyback_amount / retired | 53% / 50% | 1.8 작동(2023년 일부 무공시로 null — 정상) |
| financials.cash / total_debt | 85% / 83% | 양호 |
| ownership.largest / treasury | 100% / 88% | 양호 |
| valueup_plan.target_* | 24% / 14% / 0% | 🟡 발견 3 — 파서 튜닝 스토리 가능해짐 |

## 후속 제안 (우선순위순)

1. **배당 수집 스토리 신설** (🔴발견1, 1-8 미러: DART alotMatter.json → dividend_total) — 없으면 execution_score 영구 0%
2. **2-7(sector peer-group) 우선순위 상승** (🔴발견2 실증) — 금융주 7종목이 M&A 스코어에서 구조적 탈락 중
3. **1.5 파서 튜닝 스토리** (🟡발견3) — raw_text 79건 실샘플 확보로 착수 조건 충족(이행현황 제외 + 표 파싱)
4. 기존 defer 재확인: 감가상각(9%), 가격 point-in-time(뷰) — 순위 유지

## 방법 (재현)

scratchpad 스크립트 3종(corpCode 매칭 → ingest → analyze). 유니버스는 티커 33종
(005930 삼성전자 외). as_of=2026-07-13. DB=valueup.db(.env). 소요 ~6분(rate-limit 0.65s).
