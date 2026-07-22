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

from app.analysis import gap_engine, mna_engine
from app.db import SessionLocal

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_INCOMPLETE = 1
EXIT_USAGE = 2

ENGINES = ("gap", "mna", "all")


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


def _report(name: str, as_of: str, result) -> bool:
    """엔진 실행 결과를 로그로 옮기고 완전성 여부를 돌려준다.

    두 엔진의 결과 타입(ScoreRunResult / MnaRunResult)은 동형이라 같은 코드로 읽는다.
    다만 `complete=False`의 뜻은 다르다 — gap은 "실행분이 섞였다", mna는 "전량 롤백됐다".
    그 차이는 실패 안내 문구로 구분한다(정책은 각 엔진 docstring 참조).
    """
    logger.info(
        "[%s] as_of=%s scored=%d deleted=%d failed=%d complete=%s",
        name, as_of, result.scored, result.deleted, len(result.failed), result.complete,
    )
    if not result.failed:
        return True
    # 전건 출력(자르지 않는다) — 무엇이 왜 실패했는지가 이 정책들을 택한 이유다.
    logger.error("[%s] 실패 %d종목:", name, len(result.failed))
    for corp_code, reason in result.failed:
        logger.error("  %s: %s", corp_code, reason)
    if name == "gap":
        logger.error(
            "[gap] 이 as_of에는 이번 실행분과 이전 실행분이 섞여 있다 — 게시 전 재실행할 것."
        )
    else:
        if getattr(result, "aborted_early", False):
            logger.error(
                "[mna] DB 오류로 중단 — 위 목록은 **완전하지 않다**(남은 종목은 시도되지 않음)."
            )
        logger.error(
            "[mna] 전량 롤백됐다 — mna_score는 실행 이전 상태 그대로다(순위표는 부분적으로 "
            "옳을 수 없으므로). 원인 해소 후 재실행할 것."
        )
    return False


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
    parser.add_argument(
        "--engine", choices=ENGINES, default="all",
        help="실행할 엔진 (기본 all). 재계산의 정상 경로는 '둘 다'이고 한쪽만 돌리는 것이 "
             "예외이므로 안전한 쪽을 기본값으로 둔다.",
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

    engines = ("gap", "mna") if args.engine == "all" else (args.engine,)
    runners = {"gap": gap_engine.run, "mna": mna_engine.run}

    complete = True
    for name in engines:
        try:
            result = runners[name](
                args.as_of, corp_codes, session_factory=SessionLocal
            )
        except ValueError as e:  # as_of fail-fast — 트레이스백 대신 사용법 오류로(AC6)
            logger.error("입력 오류: %s", e)
            return EXIT_USAGE
        # 한 엔진이 불완전해도 나머지는 돌린다 — 먼저 실패한 쪽만 보고하고 끝내면
        # 전체 상태를 알기 위해 두 번 돌려야 한다.
        complete &= _report(name, args.as_of, result)

    return EXIT_OK if complete else EXIT_INCOMPLETE


if __name__ == "__main__":
    raise SystemExit(main())
