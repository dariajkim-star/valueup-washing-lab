"""어느 공시를 채점 근거로 쓸 것인가 — **선택 규칙의 단일 정의처**.

이 규칙은 원래 세 곳에 각자 구현돼 있었다(gap repo·opacity repo·서빙 조인). 세 곳이
어긋나면 화면이 **실제 채점 근거가 아닌 공시**를 출처로 표시하게 된다 — 출처 표기를
붙이는 순간 그 위험이 실재화되므로 여기로 모은다.

SQL은 여전히 각 repository에 있다(AD-2). 여기 있는 것은 "정렬된 후보들 중 무엇을 고르는가"
라는 **정책**뿐이며, 순수 함수라 DB 없이 검증된다.

──────────────────────────────────────────────────────────────────────────
과거 공시 폴백 (2026-07-29 리드 결정, '출처 표기하는 중간안')
──────────────────────────────────────────────────────────────────────────
문제(실측): 엔진은 **최신 공시 1건**만 봤다. 그런데 7종목은 최신 공시보다 과거 공시에
목표가 더 많다 — 회사가 나중에 낸 공시가 "첨부 참고" 수준의 표지 통지문이기 때문이다.

    (주)하나금융지주   최신 0축  ←  2024-10-29: ROE 10.0 · 자사주 계획 Y (2축)
    (주)LG화학        최신 0축  ←  2024-11-22: ROE 10.0 (1축)
    삼성화재해상보험     최신 0축  ←  2025-01-31: 자사주 계획 Y (1축)
    (주)신한금융지주    최신 1축  ←  과거 최대 3축
    (주)KB금융지주 / (주)케이티앤지 / 고려아연(주) 도 같은 계열

그 결과 하나금융·LG화학·삼성화재는 **우리가 이미 파싱해서 DB에 갖고 있는 목표를 두고도**
0축 → is_unrankable → "순위 불가"로 화면에서 사라졌다. 최신 걸 쓰지도, 과거 걸 쓰지도
않고 "모른다"고 말하는 제3의 상태였다.

기각한 대안: "무조건 과거 값 살리기"는 회사가 목표를 **철회**한 경우를 잘못 되살린다.
채택한 중간안: **최신 공시에 목표가 하나도 없을 때만** 그 이전 공시로 내려간다.
    - 최신이 1축이라도 있으면 그것이 회사의 현재 입장이다 → 건드리지 않는다.
    - 최신이 0축이면 그것은 "목표를 철회했다"가 아니라 **"이 문서엔 목표가 없다"**이다
      (표지 통지문). 없는 문서를 근거로 삼는 대신 실제 목표가 적힌 문서로 내려간다.
    - 대신 **어느 공시를 썼는지 반드시 표기한다** — 그래서 이 함수는 고른 결과와 함께
      '폴백했는가'를 돌려주고, valueup_score가 그 plan_id를 저장한다(0016).

이것은 첨부 수집(P1-3)의 대체재가 아니라 **먼저 할 일**이다. 첨부를 긁기 전에, 이미
받아둔 공시를 다 쓰지 않고 있었다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# 불투명 4축 — opacity_engine의 축 정의와 **같은 것**이다(그쪽이 이 모듈을 import한다).
# 두 벌로 두면 한쪽만 바뀌어 "채점에 쓴 축"과 "불투명도를 센 축"이 어긋난다.
OPACITY_AXES = ("roe", "payout", "period", "buyback")


def opacity_axes(plan: Mapping[str, Any]) -> dict[str, bool]:
    """축별 '미공시(True=불투명)' 판정. 설계 근거는 opacity_engine 모듈 문서 참조.

    payout은 배당성향·총주주환원율의 OR(대체재), period는 period_start 대표,
    buyback은 None만 미공시(False는 "계획 없음"을 공시한 것).
    """
    return {
        "roe": plan.get("target_roe") is None,
        "payout": plan.get("target_payout_ratio") is None
        and plan.get("target_total_return_ratio") is None,
        "period": plan.get("period_start") is None,
        "buyback": plan.get("buyback_planned") is None,
    }


def disclosed_axis_count(plan: Mapping[str, Any]) -> int:
    """공시된 축의 수(0~4). opacity_count의 여집합 — 폴백 판정의 기준."""
    return len(OPACITY_AXES) - sum(opacity_axes(plan).values())


@dataclass(frozen=True)
class PlanChoice:
    """고른 공시 + 그 선택이 폴백이었는지.

    used_fallback을 굳이 돌려주는 이유: 화면이 "2024-10-29 공시 기준"이라고만 쓰면
    사용자는 왜 최신 공시가 아닌지 모른다. 폴백 사실 자체가 정보다 —
    "최신 공시엔 목표가 없어서 그 이전 것을 썼다"까지가 출처다.
    """

    plan: Mapping[str, Any]
    used_fallback: bool


def choose_plan(ordered_plans: Sequence[Mapping[str, Any]]) -> PlanChoice | None:
    """채점 근거로 쓸 공시를 고른다. `ordered_plans`는 **최신 우선** 정렬이어야 한다
    (disclosure_date DESC → plan_id DESC — 동일 접수일의 정정공시를 나중 것으로).

    규칙: 최신을 쓴다. 단 최신이 0축(목표 전무)이면, 목표가 하나라도 있는 가장 최근
    공시로 내려간다. 그런 공시가 없으면 최신을 그대로 쓴다(폴백 아님 — 실제로 아무도
    목표를 공시하지 않은 것이고, 그건 순위 불가로 정직하게 남아야 한다).
    """
    if not ordered_plans:
        return None
    latest = ordered_plans[0]
    if disclosed_axis_count(latest) > 0:
        return PlanChoice(plan=latest, used_fallback=False)
    for older in ordered_plans[1:]:
        if disclosed_axis_count(older) > 0:
            return PlanChoice(plan=older, used_fallback=True)
    return PlanChoice(plan=latest, used_fallback=False)
