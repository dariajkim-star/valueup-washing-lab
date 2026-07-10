# 밸류업 갭 스코어 산식

> SPEC-valueup-washing companion. CAP-4·CAP-5의 계산 규칙. 임계치·가중치는 `config.py`로 노출(튜닝 가능).

## 정의

```
달성률   achievement_rate = actual_metric / target_metric        (target > 0)
진척률   progress_rate    = (today - period_start) / (period_end - period_start)   → [0,1] 클램프
갭       gap              = actual_metric - target_metric
```

## 자사주 3단계 (말 → 행동 → 진짜 환원)

| 변수 | 출처 | 의미 |
|---|---|---|
| `buyback_planned` | valueup_plan | 자사주 하겠다고 공시 (말) |
| `buyback_executed` | financials.buyback_amount > 0 | 실제 매입 (행동 1단계) |
| `buyback_retired` | financials.buyback_retired_amount > 0 | 실제 **소각** (행동 2단계 = 주식수 영구 감소, 진짜 주주환원) |

> 2026 상법개정 자사주 **의무소각** 반영: 매입만 하고 소각 안 하면(보관·경영권 방어 전용) 실질 환원이 아니므로 미이행으로 본다.

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
      0.35 * valuation_score    -- 저평가: EV/EBITDA·PBR 낮을수록 ↑ (역백분위)
    + 0.25 * capacity_score     -- 인수여력: 부채비율 낮음·순현금 많음·EBITDA마진 ↑
    + 0.25 * ownership_score    -- 지배구조: 최대주주 지분율 낮음·자사주 비중 ↑ (뺏기 쉬움)
    + 0.15 * macro_score        -- 매크로: 기준금리 낮을수록 ↑ (차입인수 유리)
)
```

- `valuation_score` = avg(pct_rank_low(ev_ebitda), pct_rank_low(pbr))
- `capacity_score` = avg(pct_rank_low(debt_ratio), pct_rank_high(net_cash), pct_rank_high(ebitda_margin))
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
