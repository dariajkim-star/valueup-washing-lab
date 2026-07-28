"""스코어링 배치 진입점 (Story 4-1) — `gap_engine.run()`의 첫 프로덕션 호출자.

`python -m app.analysis.run_scoring --as-of 2026-07-13`

**이 모듈이 존재하는 이유**: `gap_engine.run()`은 종목별 커밋 + 실패 목록 정책이라
부분 성공이 가능하고, 그 사실을 `ScoreRunResult.complete`로 **숨기지 않고 노출**한다.
호출자가 없으면 그 노출은 아무도 읽지 않는 값일 뿐이다. 이 모듈이 그것을 읽어
종료 코드로 번역한다 — 배치의 1차 소비자는 사람이 아니라 셸·스케줄러이고,
종료 코드는 그 계층이 이해하는 유일한 신호다.

종료 코드: 0=성공, 1=엔진 실패 또는 게시 불가 결과, 2=사용법·입력 오류(argparse 관례).

0의 기준은 엔진마다 다르다(코드리뷰 2026-07-22 High) — gap은 `complete`(대상 종목이 모두
저장됐는가), mna는 `publishable`(전 종목이 같은 모집단 세대인가). mna의 부분 실행은 실행이
성공해도 순위표를 게시 불가로 만들므로 0으로 끝내지 않는다.
"""

from __future__ import annotations

import argparse
import logging

from app.analysis import gap_engine, mna_engine, opacity_engine
from app.analysis.gap_engine import InvalidAsOfError
from app.db import SessionLocal

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_INCOMPLETE = 1
EXIT_USAGE = 2

ENGINES = ("gap", "mna", "opacity", "all")
# 순위 기반 엔진 — cross-sectional 백분위라 세대가 섞이면 표가 무의미해진다. gap(종목별 절대
# 측정치)과 달리 부분 실행이 성공해도 게시 불가이고, complete 대신 publishable로 종료를 판단한다.
_RANK_ENGINES = ("mna", "opacity")


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
    """엔진 실행 결과를 로그로 옮기고 **성공 종료해도 되는지**를 돌려준다.

    두 엔진의 결과 타입(ScoreRunResult / MnaRunResult)은 동형이라 같은 코드로 읽는다.
    다만 `complete=False`의 뜻은 다르다 — gap은 "실행분이 섞였다", mna는 "전량 롤백됐다".
    그 차이는 실패 안내 문구로 구분한다(정책은 각 엔진 docstring 참조).

    순위 기반 엔진(mna·opacity)은 `complete` 대신 `publishable`을 본다(코드리뷰 2026-07-22
    High): 백분위 순위는 전 종목이 같은 모집단 세대일 때만 의미가 있어, 부분 실행은 성공해도
    게시 불가다. gap 점수는 종목별 절대 측정치라 부분 실행분도 그 자체로 유효하므로 경고만 한다.
    """
    logger.info(
        "[%s] as_of=%s scored=%d deleted=%d failed=%d complete=%s",
        name, as_of, result.scored, result.deleted, len(result.failed), result.complete,
    )
    fatal = getattr(result, "fatal_error", None)  # gap의 ScoreRunResult엔 없는 필드
    if fatal:
        logger.error("[%s] 실행 무산: %s", name, fatal)

    if result.failed:
        # 전건 출력(자르지 않는다) — 무엇이 왜 실패했는지가 이 정책들을 택한 이유다.
        logger.error("[%s] 실패 %d종목:", name, len(result.failed))
        for corp_code, reason in result.failed:
            logger.error("  %s: %s", corp_code, reason)
        if name == "gap":
            logger.error(
                "[gap] 이 as_of에는 이번 실행분과 이전 실행분이 섞여 있다 — 게시 전 재실행할 것."
            )

    if name in _RANK_ENGINES:
        table = f"{name}_score"
        if getattr(result, "aborted_early", False):
            logger.error(
                "[%s] 중단됨 — 위 목록은 **완전하지 않다**(남은 종목은 시도되지 않음).", name,
            )
        if not result.complete:
            logger.error(
                "[%s] 전량 롤백됐다 — %s는 실행 이전 상태 그대로다(순위표는 부분적으로 "
                "옳을 수 없으므로). 원인 해소 후 재실행할 것.", name, table,
            )
        elif getattr(result, "partial_scope", False):
            # 실행은 성공했지만 표는 세대가 섞였다 — 성공으로 종료하면 그 사실이 사라진다.
            logger.error(
                "[%s] 부분 실행 — 대상 밖 종목은 이전 모집단 세대 점수로 남아 있다. "
                "이 as_of의 %s는 **게시 불가**다(순위 비교가 성립하지 않음). "
                "게시용 스냅숏은 --corp-codes 없이 전체 실행할 것.", name, table,
            )
        return result.publishable

    return result.complete


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.analysis.run_scoring",
        description="스코어 재계산 배치 — valueup_score(gap)·mna_score(mna)·opacity_score"
                    "(opacity). 기본은 셋 다.",
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
        help="실행할 엔진 (기본 all). 재계산의 정상 경로는 '셋 다'이고 한쪽만 돌리는 것이 "
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
        if args.engine == "all":
            # 두 엔진의 부분 실행 의미가 달라(gap=유효한 부분 갱신 / mna=순위 세대 혼재),
            # 한 명령으로 뭉뚱그리면 어느 쪽을 의도했는지 알 수 없다. gap 한 종목만 디버깅하려던
            # 명령이 mna 순위표까지 부분 갱신하는 것을 막는다(코드리뷰 2026-07-22 High —
            # "안전한 기본값 all"이 --corp-codes와 결합하면 안전하지 않다).
            logger.error(
                "입력 오류: --corp-codes는 --engine을 명시해야 한다(gap·mna·opacity 중 하나). "
                "엔진별 부분 실행 의미가 다르다 — gap은 유효한 부분 갱신이지만, mna·opacity는 "
                "순위 모집단 세대를 섞어 그 as_of 표를 게시 불가로 만든다."
            )
            return EXIT_USAGE
        # complete=True여도 부분 실행 스냅샷은 여전히 부분적 — 두 개념은 다르다(D3).
        logger.warning(
            "부분 실행(%d종목): 나머지 종목은 이전 실행분이 그대로 남는다. **게시용 아님**.",
            len(corp_codes),
        )

    engines = ("gap", "mna", "opacity") if args.engine == "all" else (args.engine,)
    runners = {
        "gap": gap_engine.run,
        "mna": mna_engine.run,
        "opacity": opacity_engine.run,
    }

    ok = True
    for name in engines:
        try:
            result = runners[name](
                args.as_of, corp_codes, session_factory=SessionLocal
            )
        except InvalidAsOfError as e:  # as_of fail-fast — 트레이스백 대신 사용법 오류로(AC6)
            logger.error("입력 오류: %s", e)
            return EXIT_USAGE
        except Exception:  # noqa: BLE001
            # 엔진 실행 자체가 실패했다(모집단 조회·세션 생성·커밋 등 루프 밖 경로).
            # 이전엔 ValueError만 잡아 이런 예외가 CLI 밖으로 새면서 traceback으로 프로세스가
            # 죽었고, **다음 엔진이 아예 실행되지 않아 AC7이 깨졌다**(코드리뷰 2026-07-22 High).
            # 여기서 엔진 단위 실패로 격리하고 계속 진행한다 — traceback은 로그에 남긴다.
            logger.exception("[%s] 엔진 실행 자체가 실패했다", name)
            ok = False
            continue
        # 한 엔진이 불완전해도 나머지는 돌린다 — 먼저 실패한 쪽만 보고하고 끝내면
        # 전체 상태를 알기 위해 두 번 돌려야 한다.
        ok &= _report(name, args.as_of, result)

    return EXIT_OK if ok else EXIT_INCOMPLETE


if __name__ == "__main__":
    raise SystemExit(main())
