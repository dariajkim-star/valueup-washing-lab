"""스코어링 배치 진입점 (Story 4-1) — `gap_engine.run()`의 첫 프로덕션 호출자.

`python -m app.analysis.run_scoring --as-of 2026-07-13`

**이 모듈이 존재하는 이유**: `gap_engine.run()`은 종목별 커밋 + 실패 목록 정책이라
부분 성공이 가능하고, 그 사실을 `ScoreRunResult.complete`로 **숨기지 않고 노출**한다.
호출자가 없으면 그 노출은 아무도 읽지 않는 값일 뿐이다. 이 모듈이 그것을 읽어
종료 코드로 번역한다 — 배치의 1차 소비자는 사람이 아니라 셸·스케줄러이고,
종료 코드는 그 계층이 이해하는 유일한 신호다.

종료 코드: 0=완전(complete), 1=부분 실패, 2=사용법·입력 오류(argparse 관례).
"""

from __future__ import annotations

import argparse
import logging

from app.analysis import gap_engine
from app.db import SessionLocal

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_INCOMPLETE = 1
EXIT_USAGE = 2


def _parse_corp_codes(raw: str | None) -> list[str] | None:
    """쉼표 구분 corp_code 목록. 미지정(None)은 '전체 실행'을 뜻하므로 그대로 None을 넘긴다.

    빈 문자열·공백만 있는 입력을 빈 리스트로 넘기면 엔진이 '대상 0종목'으로 조용히 성공한다
    (`complete=True`, scored=0). 전체 실행과 구분되지 않는 조용한 무작업이라 사용법 오류로 막는다.
    """
    if raw is None:
        return None
    codes = [c.strip() for c in raw.split(",") if c.strip()]
    if not codes:
        raise ValueError("--corp-codes에 유효한 corp_code가 없습니다(전체 실행은 옵션 생략)")
    return codes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.analysis.run_scoring",
        description="valueup_score 재계산 배치 (gap_engine)",
    )
    parser.add_argument(
        "--as-of", dest="as_of", required=True,
        help="기준일(YYYY-MM-DD). **필수** — progress_rate가 as_of에 직접 의존하므로 "
             "암묵적 오늘 날짜는 재현 불가능한 실행을 만든다(D2).",
    )
    parser.add_argument(
        "--corp-codes", dest="corp_codes", default=None,
        help="쉼표 구분 corp_code(디버깅용 부분 실행). 생략 시 전체 종목 — "
             "게시용 점수는 반드시 전체 실행이어야 한다.",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        corp_codes = _parse_corp_codes(args.corp_codes)
    except ValueError as e:
        logger.error("입력 오류: %s", e)
        return EXIT_USAGE

    if corp_codes is not None:
        # complete=True여도 부분 실행 스냅샷은 여전히 부분적 — 두 개념은 다르다(D3).
        logger.warning(
            "부분 실행(%d종목): 나머지 종목은 이전 실행분이 그대로 남는다. **게시용 아님**.",
            len(corp_codes),
        )

    try:
        result = gap_engine.run(
            args.as_of, corp_codes, session_factory=SessionLocal
        )
    except ValueError as e:  # _validate_as_of의 fail-fast — 트레이스백 대신 사용법 오류로(AC6)
        logger.error("입력 오류: %s", e)
        return EXIT_USAGE

    logger.info(
        "as_of=%s scored=%d deleted=%d failed=%d complete=%s",
        args.as_of, result.scored, result.deleted, len(result.failed), result.complete,
    )
    if result.failed:
        # 전건 출력(자르지 않는다) — 무엇이 왜 실패했는지가 종목별 커밋 정책을 택한 이유다.
        logger.error("실패 %d종목:", len(result.failed))
        for corp_code, reason in result.failed:
            logger.error("  %s: %s", corp_code, reason)
        logger.error(
            "이 as_of에는 이번 실행분과 이전 실행분이 섞여 있다 — 게시 전 재실행할 것."
        )
        return EXIT_INCOMPLETE
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
