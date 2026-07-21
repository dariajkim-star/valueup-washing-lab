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


def _validate_as_of(as_of: str) -> None:
    """as_of가 zero-padded YYYY-MM-DD **이자 달력상 유효**한지 fail-fast.

    정규식만으론 2025-02-30이 통과(코드리뷰 2026-07-10 Med) — 세 입력원(metrics 연도,
    ownership·macro 문자열 비교)이 무효 날짜를 서로 다르게 해석하는 것을 진입점에서 차단.
    gap_engine·mna_engine 공용(중복 정의 금지).
    """
    if not _AS_OF_RE.match(as_of):
        raise ValueError(f"as_of는 YYYY-MM-DD 형식이어야 합니다: {as_of!r}")
    try:
        date.fromisoformat(as_of)
    except ValueError:
        raise ValueError(f"as_of가 달력상 유효한 날짜가 아닙니다: {as_of!r}") from None


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
        """실패 0건 = 이 as_of 스냅샷이 전 종목 동일 시점 기준임을 보장.

        False면 valueup_score의 해당 as_of에는 이번 실행분과 이전 실행분이 **섞여 있다**.
        게시·비교 용도로 쓰기 전에 반드시 확인할 것(트레이드오프는 아래 run() docstring).
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
    execution_score = _execution_score(
        achievement_rate, executed, actual_payout, plan["target_payout_ratio"],
        settings.score_w_achievement, settings.score_w_buyback, settings.score_w_payout,
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
        },
    )
    return True


def run(
    as_of: str,
    corp_codes: Sequence[str] | None = None,
    *,
    session_factory: Callable[[], Session] = SessionLocal,
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
