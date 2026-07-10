"""Value-up 갭 스코어링 엔진 (writer = 이 모듈, AD-4).

Epic 1(수집)과 다른 새 패턴: HTTP 어댑터가 아니라 **순수 계산**. 입력은 이미 DB에 있다
(valuation_metrics 뷰 + valueup_plan + financials.buyback_*). 산식은 scoring.md 참조.

null 전파가 핵심 계약(2026-07-10 코드리뷰로 scoring.md 강화): 입력이 애매/누락이면
0이나 False로 강제하지 않고 해당 스코어도 null로 전파한다(NFR2 "null > 틀린 값").
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.config import settings
from app.repositories import valueup_score as repo

_AS_OF_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _safe_ratio(actual: float | None, target: float | None) -> float | None:
    """target이 없거나 0 이하면 계산 불가(0 나눗셈·역설 방어) → None."""
    if actual is None or target is None or target <= 0:
        return None
    return actual / target


def _progress_rate(
    period_start: str | None, period_end: str | None, as_of_year: int
) -> float | None:
    """계획기간(연도 문자열) 대비 진척률, [0,1] 클램프. 연 단위 정밀도만(입력이 연도뿐)."""
    if period_start is None or period_end is None:
        return None
    try:
        start, end = int(period_start), int(period_end)
    except (TypeError, ValueError):
        return None
    if end <= start:
        return None
    raw = (as_of_year - start) / (end - start)
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
) -> float | None:
    """execution_score = 100*clamp(w_a*min(achv,1) + w_b*(executed?1:0) + w_p*min(payout,1)).

    세 항 중 하나라도 계산 불가면 0으로 메우지 않고 전체 null(AC5).
    """
    payout_ratio = _safe_ratio(actual_payout, target_payout)
    if achievement_rate is None or buyback_executed is None or payout_ratio is None:
        return None
    raw = (
        w_achievement * min(achievement_rate, 1.0)
        + w_buyback * (1.0 if buyback_executed else 0.0)
        + w_payout * min(payout_ratio, 1.0)
    )
    return 100 * max(0.0, min(1.0, raw))


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


def run(
    session: Session, as_of: str, corp_codes: Sequence[str] | None = None
) -> int:
    """as_of 기준으로 corp별 valueup_score를 계산·upsert. 적재 행 수 반환.

    valueup_plan이 없는 종목은 목표가 없어 갭을 정의할 수 없으므로 행을 만들지 않는다
    (1-6 no-data 교훈과 동일 원칙). 이전에 plan이 있어 score가 생성됐다가 이후 plan이
    삭제/정정된 경우, 근거를 잃은 기존 score도 함께 정리한다(코드리뷰 High, GPT: gap_engine이
    valueup_score의 유일 writer(AD-4)이므로 정합성 유지 책임도 이 모듈에 있음).

    as_of는 YYYY-MM-DD 형식만 허용(fail-fast) — 비표준 포맷은 disclosure_date와의 문자열
    비교(사전식)를 실제 날짜 비교와 어긋나게 만들 수 있다(코드리뷰 High, GPT).
    """
    if not _AS_OF_RE.match(as_of):
        raise ValueError(f"as_of는 YYYY-MM-DD 형식이어야 합니다: {as_of!r}")
    if corp_codes is None:
        corp_codes = repo.list_all_corp_codes(session)
    as_of_year = int(as_of[:4])

    count = 0
    for corp_code in corp_codes:
        plan = repo.latest_valueup_plan(session, corp_code, as_of)
        if plan is None:
            repo.delete_valueup_score(session, corp_code, as_of)
            continue

        metrics = repo.latest_metrics(session, corp_code, as_of)
        buyback = repo.latest_financial_buyback(session, corp_code, as_of)
        actual_roe = metrics.get("roe") if metrics else None
        actual_payout = metrics.get("payout_ratio") if metrics else None
        amount = buyback.get("buyback_amount") if buyback else None
        retired_amount = buyback.get("buyback_retired_amount") if buyback else None

        progress_rate = _progress_rate(plan["period_start"], plan["period_end"], as_of_year)
        # AC3: 계획기간이 무효(null·end<=start)면 achievement_rate도 계산하지 않고 null로
        # 명시한다(코드리뷰 High, GPT — 이전 구현은 progress_rate만 null이 되고 achievement_rate는
        # 별개로 계산돼 AC3를 위반했다). execution_score는 achievement_rate가 None이면 이미 null.
        achievement_rate = (
            None if progress_rate is None
            else _achievement_rate(actual_roe, plan["target_roe"])
        )
        executed, retired, status = _buyback_signals(amount, retired_amount)
        execution_score = _execution_score(
            achievement_rate, executed, actual_payout, plan["target_payout_ratio"],
            settings.score_w_achievement, settings.score_w_buyback, settings.score_w_payout,
        )
        washing_flag = _washing_flag(
            progress_rate, achievement_rate, plan["buyback_planned"], retired,
            settings.washing_progress_min, settings.washing_achievement_max,
        )

        repo.upsert_valueup_score(
            session,
            {
                "corp_code": corp_code,
                "as_of": as_of,
                "achievement_rate": achievement_rate,
                "progress_rate": progress_rate,
                "execution_score": execution_score,
                "washing_flag": washing_flag,
                "buyback_executed": executed,
                "buyback_retired": retired,
                "buyback_status": status,
            },
        )
        count += 1

    session.flush()
    return count
