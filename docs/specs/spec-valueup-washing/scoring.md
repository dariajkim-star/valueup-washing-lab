# 밸류업 갭 스코어 산식

> SPEC-valueup-washing companion. CAP-4·CAP-5의 계산 규칙. 임계치·가중치는 `config.py`로 노출(튜닝 가능).

## 정의

```
달성률   achievement_rate = actual_metric / target_metric        (target > 0)
진척률   progress_rate    = (today - period_start) / (period_end - period_start)   → [0,1] 클램프
                            (일 단위. 입력이 연도뿐이므로 경계 규약: start=시작연도 1/1, end=종료연도 12/31)
갭       gap              = actual_metric - target_metric
```

## 자사주 3단계 (말 → 행동 → 진짜 환원)

| 변수 | 출처 | 의미 |
|---|---|---|
| `buyback_planned` | valueup_plan | 자사주 하겠다고 공시 (말) |
| `buyback_executed` | financials.buyback_amount > 0 | 실제 매입 (행동 1단계) |
| `buyback_retired` | financials.buyback_retired_amount > 0 | 실제 **소각** (행동 2단계 = 주식수 영구 감소, 진짜 주주환원) |

> 2026 상법개정 자사주 **의무소각** 반영: 매입만 하고 소각 안 하면(보관·경영권 방어 전용) 실질 환원이 아니므로 미이행으로 본다.

> **두 축이 자사주를 다르게 본다(2026-08-04, 의도된 이중 시선 — 모순 아님)**: 위 3단계 축은
> **소각**을 기준으로 "진짜 환원"을 가르는 반면, `total_return_ratio`는 업계 표준 정의
> (배당 + 자사주 **매입액**)를 따른다. 같은 사건을 엄격한 자와 관행의 자로 각각 재는 것이고,
> 그 차이 자체가 신호다 — 총환원율은 높은데 소각이 0인 기업이 곧 "매입만 한 기업"으로 드러난다.

### 🔒 채점 축을 소각 기준으로 좁히는 안 — **기각(2026-08-04, 리드 결정)**

선행 조건이었던 소각 '금액' 수집은 **완료**됐다(0027 `buyback_retired_krw`, 자본변동표 원천,
수량>0인 95행 중 71행 회수). 조건이 충족됐으므로 재론했고, **실측이 이 안을 기각했다.**

**기각 사유 — 벌 대상을 오조준하고, 도울 대상에겐 효과가 없다.**

| 실측 | 값 |
|---|---|
| `total_return` 축을 쓰는 종목 | 37 / 채점 174 |
| 축 교체 시 점수가 **움직이는** 종목 | **10** (나머지 27은 `_axis_score`의 [0,1] 캡이 흡수) |
| 방향 | 9곳 하락 · **1곳 상승**(금호석유화학 +0.9 — 이월 소각이라 소각액 > 취득액) |
| 최대 낙폭 | 에이피알 **100.0 → 60.0** |

**결정적 근거는 기업들이 "총주주환원율"을 서로 다르게 정의한다는 사실이다.** 원문 37건 판독:

| 정의 유형 | 수 | 예 |
|---|---|---|
| 소각만 명시 | **2** | 신세계인터내셔날 *"(주주환원율:현금배당+자사주 소각)"* · 금호석유화학 *"현금배당 및 자사주 소각을 통해 40% 지향"* |
| 매입+소각 병기 | 4 | 메리츠금융지주 *"배당 및 자사주 매입·소각을 포함한 총 주주환원율 … 50%"* |
| 소각 무언급 | 29 | — |

- 낙폭 1위 **에이피알**은 *"현금배당 및 자기주식 **매입/소각**"*이라 병기했다 — 소각 기준으로
  채점하면 **회사가 하지 않은, 더 좁은 약속으로 판정**하는 것이다. 이는 범위 공시에서
  상한을 기각하고 하한을 채택한 결정(PRD OQ-1)과 **같은 원칙 위반**이다.
- 정작 소각 기준으로 약속한 2곳은 이미 목표를 넘거나(신세계 42.4% vs 목표 30%)
  오히려 점수가 오른다(금호석유화학). **교체가 도와줄 대상이 아니다.**

**그래서 채점 축은 매입 기준(업계 표준)을 유지한다.** 소각 기준은 축이 아니라 **나란히 놓인
사실**로 남는다 — `retired_return_ratio`·`retirement_rate`(0028)가 목록 셀 둘째 줄과 상세
주주환원 카드에서 매입 기준과 함께 표시되고, `매입만·소각 0` 필터가 그 조합을 걸러낸다.
**정보를 잃지 않으면서 약속대로 채점한다.**

> #### 조건부 백로그 — 기업 정의별 축 선택
> 기각한 것은 **전역 교체**이지, "회사가 소각 기준으로 약속했으면 소각 기준으로 잰다"는
> 안까지는 아니다. 다만 지금 착수하지 않는다:
> - **대상이 2곳**이고 그 2곳은 축을 바꿔도 **점수가 변하지 않는다**(효과 0).
> - 판별 문구가 미묘하다 — *"매입·소각을 포함한"*(메리츠, 매입 기준)과 *"소각을 통해"*
>   (금호, 소각 기준)를 정규식으로 가르는 것은 P1-5에서 데인 자리다.
> - small-N에서 선언하지 않는 이 프로젝트의 규율(`isUnsupportedSector` 소분류·`peer_min`)에 걸린다.
>
> **재검토 트리거**: 자기 정의를 본문에 명시한 기업이 **5곳 이상** 관측될 때.
> 그때 열 것은 축 교체가 아니라 **`return_basis` 표기**다(`score_basis`·`population_basis`와
> 같은 계열 — 어느 자로 쟀는지를 값과 함께 전달).
>
> **알려진 잔여(트리거 전까지 감수)**: 신세계인터내셔날의 화면 총환원율은 **100.2%**(매입 기준)
> 인데 그 회사의 자기 정의로는 **42.4%**다. 점수는 어느 자로 재도 100점이라 채점 왜곡은 없으나,
> **표시 숫자가 그 회사가 말한 정의와 다르다**는 사실은 기록해 둔다.

## 워싱 플래그

```
washing_flag = (progress_rate >= 0.5)                 -- 목표기간 절반 이상 경과
            AND (achievement_rate < 0.6)              -- 목표의 60% 미달
            AND (buyback_planned AND buyback_retired_amount = 0)  -- 약속했으나 소각 '확정 0'
```

> **null ≠ 소각 안 함 (코드리뷰 2026-07-10, GPT High)**: `buyback_retired_amount IS NULL`은
> "모름(미공시/수집실패/파싱애매)"이지 "소각 안 함"의 증거가 아니다. `NOT (NULL > 0)`을
> False→"미소각"으로 강제하면 미공시 기업이 워싱으로 오판된다. 따라서 소각 항은
> **확정 0(공시된 활동 없음)**일 때만 워싱 성립.

> **null 전파 = 3치(Kleene) AND (코드리뷰 2026-07-10, GPT Med로 정정)**: 위 세 조건의 AND는
> "하나라도 unknown이면 전체 null"이 아니라 **하나라도 확정 False면 나머지가 unknown이어도
> 전체 확정 False**(그 다음 확정 False가 없고 unknown이 하나라도 있으면 null, 전부 확정
> True면 True). 예: 소각이 확정 이뤄졌으면(`buyback_retired_amount>0`) 진척률을 몰라도
> washing은 이미 확정 아님(False). progress_rate가 확정으로 0.5 미만이면 나머지를 몰라도
> 이미 확정 아님(False). 이렇게 해야 "확정 가능한 정상 케이스"까지 불필요하게 판단불가로
> 내지 않는다(false positive 없이 unknown을 줄임). `gap_engine._washing_flag` 구현 참조.

> `buyback_status` = retired(소각완료) / purchased_only(매입만) / none(미실행) /
> **unknown(취득·소각 중 하나라도 null → 판정 불가)** — UI 표시·부분워싱 신호용.
> `purchased_only`는 `buyback_amount > 0 AND buyback_retired_amount = 0`처럼 **양쪽 모두
> 확정**일 때만 부여(소각이 null이면 unknown). 약한 워싱 신호로 별도 노출.

## 실행점수 (0~100)

```
execution_score = 100 * clamp(
      0.5 * min(achievement_rate, 1.0)          -- 목표 달성 (가중 0.5)
    + 0.3 * (buyback_executed ? 1 : 0)          -- 자사주 실이행 (가중 0.3)
    + 0.2 * min(actual_payout / target_payout, 1.0)  -- 배당 이행 (가중 0.2)
    , 0, 1)
```

## 튜닝 파라미터 (config.py)

| 파라미터 | 기본값 | 의미 |
|---|---|---|
| `WASHING_PROGRESS_MIN` | 0.5 | 워싱 판정 최소 진척률 |
| `WASHING_ACHIEVEMENT_MAX` | 0.6 | 워싱 판정 달성률 상한 |
| `SCORE_W_ACHIEVEMENT` | 0.5 | Value-up 달성 가중 |
| `SCORE_W_BUYBACK` | 0.3 | Value-up 자사주 가중 |
| `SCORE_W_PAYOUT` | 0.2 | Value-up 배당 가중 |

> 가중치 합은 1.0을 유지한다(검증 필요). `as_of` 기준일은 진척률 계산의 `today`로 쓰인다.

---

# M&A Target Score 산식 (CAP-10)

"이 회사, 인수 매력이 있나?"를 IB/PE 관점 4요소로 본다. 각 지표를 **시장 내 백분위(0~1)** 로 정규화 후 가중합 → 0~100. Value-up Score와 정반대 관점(스스로 vs 남이 사감).

```
mna_target_score = 100 * (
      0.35 * valuation_score    -- 저평가: EV/EBIT·PBR 낮을수록 ↑ (역백분위)
    + 0.25 * capacity_score     -- 인수여력: 부채비율 낮음·순현금 많음·EBIT마진 ↑
    + 0.25 * ownership_score    -- 지배구조: 최대주주 지분율 낮음·자사주 비중 ↑ (뺏기 쉬움)
    + 0.15 * macro_score        -- 매크로: 기준금리 낮을수록 ↑ (차입인수 유리)
)
```

- `valuation_score` = avg(pct_rank_low(ev_ebit), pct_rank_low(pbr))
- `capacity_score` = avg(pct_rank_low(debt_ratio), pct_rank_high(net_cash), pct_rank_high(ebit_margin))
- `ownership_score` = avg(pct_rank_low(largest_shareholder_pct), pct_rank_high(treasury_stock_pct))
- `macro_score` = pct_rank_low(기준금리) — 종목 무관, as_of 시점 값

## M&A 튜닝 파라미터 (config.py)

| 파라미터 | 기본값 | 의미 |
|---|---|---|
| `MNA_W_VALUATION` | 0.35 | 저평가 가중 |
| `MNA_W_CAPACITY` | 0.25 | 인수여력 가중 |
| `MNA_W_OWNERSHIP` | 0.25 | 지배구조 가중 |
| `MNA_W_MACRO` | 0.15 | 매크로 가중 |

> 가중치 합 1.0 유지. `pct_rank_low`=낮을수록 높은 점수, `pct_rank_high`=높을수록 높은 점수. 입력=valuation_metrics 뷰 + ownership + macro_indicator (mna_engine이 mna_score의 유일 writer, AD-10).

> **진척률 일 단위 정합화 (코드리뷰 2026-07-21, 결정 B)**: 초기 구현은 연 단위
> `(as_of_year - start_year) / (end_year - start_year)`로 위 원식(`today` 기반)에서 이탈해
> 있었다 — 해가 바뀌는 1/1에 진척률이 계단식 점프해(3년 계획이면 +1/3) washing 임계(0.5)를
> 하루 사이에 넘는 종목이 생겼다. 일 단위로 정정. 임계 근처 종목은 판정이 달라질 수 있다
> (예: 3년 계획 2년차 말 = 연 단위 1/3 → 일 단위 0.5). `end <= start` 무효 규칙은 유지
> (단년 계획 수용은 AC3 계약 변경이라 별도 결정 — deferred-work.md).
