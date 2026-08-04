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

# 본문 신호 종류(0018). 판정 로직은 plan_signals가 갖지만 **상수는 여기 둔다** —
# 선택 규칙(아래 choose_plan)이 refiling을 알아야 하는데, plan_signals가 이 모듈을
# import하므로 반대 방향 import는 순환이 된다. 낮은 층이 어휘를 소유한다.
AXIS_TARGETS = "axis_targets"
OTHER_METRIC = "other_metric"
REFILING = "refiling"
NO_TARGETS = "no_targets"
# 회사가 **첨부가 없다고 본문에 명시**한 약식 공시(2026-08-04 실측 101개사).
# no_targets에서 갈라낸 이유는 딱 하나 — **행동이 다르다**: 첨부 작업 목록이
# 이들을 부르면 안 된다(없는 문서를 찾으러 사람을 보내는 꼴).
EXEMPT_SHORT_FORM = "exempt_short_form"


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


_MERGEABLE = (
    "target_roe",
    "target_payout_ratio",
    "target_total_return_ratio",
    "target_pbr",
    "period_start",
    "period_end",
    "buyback_planned",
)


def merge_attachment(plan: dict[str, Any], attachment: Mapping[str, Any] | None) -> dict[str, Any]:
    """본문 목표 + 첨부(계획서 PDF) 목표를 한 공시의 **유효 목표**로 합친다.

    공시 본문은 "첨부된 계획을 참고하라"는 통지문인 경우가 많고, 실물은 첨부다. 둘은
    경쟁하는 두 값이 아니라 **같은 공시의 두 조각**이므로 합쳐야 그 공시의 실제 약속이 된다.

    규칙: 본문이 우선, 첨부는 **빈 축만 채운다.**
      - 본문은 규제 공시 원문이고 우리가 오래 검증한 파서가 읽은 것이다.
      - 첨부는 PDF 레이아웃 파싱이라 오탐 여지가 상대적으로 크다.
      - 그래서 충돌 시 본문을 남기고, 첨부는 **없는 것만** 보탠다(값을 덮어써서 조용히
        바뀌는 일이 없게). 충돌 사실은 target_conflicts에 남겨 숨기지 않는다.

    파싱 실패한 첨부(parse_error)는 무시한다 — 못 읽은 것을 목표 없음으로도, 목표로도
    쓰지 않는다.

    검토 대기 첨부(needs_review, 0020)도 무시한다 — OCR 유래 값은 후보이지 사실이
    아니다. 첫 실측에서 OCR+파서가 이행 실적을 목표로 오인했다(배당성향 35.0). 사람이
    승인(review_attachment CLI)하면 needs_review가 풀리고 그때 채점에 들어간다.
    """
    merged = dict(plan)
    merged.setdefault("attachment_filled", [])
    merged.setdefault("target_conflicts", [])
    if not attachment or attachment.get("parse_error") or attachment.get("needs_review"):
        return merged

    filled: list[str] = []
    conflicts: list[str] = []
    for field_name in _MERGEABLE:
        att_v = attachment.get(field_name)
        if att_v is None:
            continue
        if merged.get(field_name) is None:
            merged[field_name] = att_v
            filled.append(field_name)
        elif merged[field_name] != att_v:
            conflicts.append(field_name)
    merged["attachment_filled"] = filled
    merged["target_conflicts"] = conflicts
    return merged


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

    규칙 (적용 순서):
      1. **재공시는 계획이 아니다.** 최신이 refiling이면(예: 고배당기업 표시를 위한
         재공시) 그것이 가리킨 공시로 간다. 가리킨 날짜를 못 읽었으면 그 문서를 후보에서
         빼고 다음으로 내려간다 — 어느 쪽이든 "계획을 담지 않은 문서"를 근거로 삼지 않는다.
         실측: 금융지주 3사(신한·우리·하나)의 최신 공시가 전부 이 유형이었고, 그것이
         그들이 0축이던 이유였다.
      2. 최신(위에서 정해진)이 0축이면 목표가 하나라도 있는 가장 최근 공시로 내려간다.
      3. 그런 공시가 없으면 최신을 그대로 쓴다(폴백 아님 — 실제로 아무도 목표를 공시하지
         않은 것이고, 그건 순위 불가로 정직하게 남아야 한다).
    """
    if not ordered_plans:
        return None

    candidates = list(ordered_plans)
    used_fallback = False

    # 1) 재공시 건너뛰기 — 연쇄(재공시가 재공시를 가리키는 경우)도 따라간다.
    #    무한 루프 방지를 위해 방문한 날짜를 기억하고, 후보 수만큼만 시도한다.
    seen_dates: set[str] = set()
    for _ in range(len(candidates)):
        head = candidates[0]
        if head.get("body_signal") != REFILING:
            break
        ref = head.get("body_reference_date")
        if ref and ref not in seen_dates:
            seen_dates.add(ref)
            target = [c for c in candidates if c.get("disclosure_date") == ref]
            if target:
                # 가리킨 공시를 맨 앞으로(그 뒤로는 그보다 오래된 것들만 남긴다)
                idx = candidates.index(target[0])
                candidates = candidates[idx:]
                used_fallback = True
                continue
        # 날짜를 못 읽었거나 그 공시가 없다 → 이 문서를 빼고 다음으로
        if len(candidates) == 1:
            break  # 남은 게 이것뿐이면 그대로 둔다(빈 결과보다 낫다)
        candidates = candidates[1:]
        used_fallback = True

    head = candidates[0]
    if disclosed_axis_count(head) > 0:
        return PlanChoice(plan=head, used_fallback=used_fallback)

    # 2) 0축이면 목표가 있는 가장 최근 공시로
    for older in candidates[1:]:
        if disclosed_axis_count(older) > 0:
            return PlanChoice(plan=older, used_fallback=True)

    # 3) 아무도 목표를 공시하지 않았다
    return PlanChoice(plan=head, used_fallback=used_fallback)
