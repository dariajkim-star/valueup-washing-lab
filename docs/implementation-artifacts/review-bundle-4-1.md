# Review Bundle — Story 4.1: 스코어링 배치 CLI (2026-07-22)

> ⚠️ **이 번들은 낡았습니다(2026-07-22). 리뷰에 사용하지 마세요.**
>
> Story 4-2에서 `run_scoring.py`에 `--engine {gap,mna,all}`이 추가되고 실패 보고 로직이
> 바뀌면서, 아래 실린 원문(99행 시점)은 **현재 코드와 다릅니다**. 그대로 리뷰하면 존재하지
> 않는 코드를 검토하게 됩니다.
>
> 대신 [`review-bundle-4-2.md`](review-bundle-4-2.md)를 쓰세요 — 현재 `run_scoring.py`·
> `gap_engine.py`·양쪽 테스트 원문을 담고 있어 4-1의 산출물까지 함께 검토됩니다.
> 이 파일은 4-1 시점의 판단 근거(D1 종료 코드·D2 as_of 필수·D3 부분 실행 경고) 기록으로만 남깁니다.

`gap_engine.run()`의 **첫 프로덕션 호출자**를 만든 스토리입니다. PR: #3 (`feat/scoring-batch-cli`).

## 이 스토리가 답하려는 질문

`gap_engine.run()`은 2026-07-21 코드리뷰에서 **종목별 커밋 + 실패 목록** 정책이 확정되며
`ScoreRunResult.complete`(부분 실패 스냅숏 여부)를 반환하게 됐습니다. 그런데 호출자가 테스트뿐이라
그 값을 **읽는 주체가 없었습니다**. 이 스토리는 "누가, 어떻게 `complete`를 소비하는가"에 답합니다.

## AC 요약

- **AC1** `python -m app.analysis.run_scoring --as-of YYYY-MM-DD`로 전 종목 재계산 실행
- **AC2** 실행 요약(scored/deleted/failed/complete) 로그 출력
- **AC3** `complete=True`→종료 코드 0, `complete=False`→1
- **AC4** 실패 종목 `(corp_code, 사유)` **전건** 로그 출력
- **AC5** `--as-of` 미지정 시 종료 코드 2 (시스템 시계로 대체하지 않음)
- **AC6** 잘못된 `--as-of`(형식·달력 무효)는 트레이스백이 아니라 종료 코드 2 + 사람이 읽는 메시지
- **AC7** `--corp-codes` 부분 실행 시 "게시용 아님" 경고
- **AC8** 기존 테스트 전건 통과 + CLI 테스트 신규 (251 → 261 passed)

## 아키텍처 제약

- **AD-4**: `valueup_score`의 유일 writer는 `gap_engine`. CLI는 엔진을 호출만 하고 직접 쓰지 않음.
- **AD-6**: 에러 계약. (이 스토리는 HTTP가 아니라 CLI 경계 — 종료 코드가 그 대응물)
- **AD-8**: `as_of` 명시. 시스템 시계 의존 금지(3-1에서 매크로 as_of 기본값 정할 때 확립).
- 세션 소유권: `run()`이 세션을 소유한다(호출자가 세션을 넘기면 호출자의 미저장 작업까지 커밋되므로).
  CLI는 `session_factory=SessionLocal`만 넘긴다.

## 설계상 의도된 선택 (재보고 불필요)

1. **`complete` 소비 = 종료 코드**(0/1/2). `score_run` 메타데이터 테이블은 2026-07-14 **리드 결정으로
   이미 닫혔습니다**(v2 백로그 "멀티유저·운영 서비스화 시" 트리거, README 한계 §2). "실행 메타를
   테이블로 남기자"는 제안은 이 스토리 범위 밖입니다.
2. **범위 = gap_engine만.** `mna_engine.run()`이 구식 시그니처(`session` 인자 + `int` 반환)로 남아 있는
   것은 인지하고 있습니다. cross-sectional(모집단을 루프 전 1회 구성)이라 부분 실패의 의미가 gap과
   달라 종목별 커밋이 옳은지 자체가 별도 판단이며, **Story 4-2로 분리**했습니다.
3. **`--as-of` 필수**(기본값 없음). 편의보다 재현성을 택했습니다 — `progress_rate`가 as_of에 직접
   의존하므로 암묵적 오늘 날짜는 같은 명령이 날마다 다른 결과를 내게 만듭니다.
4. **부분 실행 허용**. 막지 않고 경고만 합니다(디버깅에 필요). `complete=True`여도 부분 실행
   스냅숏은 여전히 부분적이라는 점을 로그가 구분해서 말합니다.
5. **HTTP 라우터(`POST /scoring/run`) 미구현** — 현재 전 엔드포인트가 무인증이라 배포 스토리의
   보안 게이트(deferred-work.md)와 함께 다뤄야 합니다.

## 알려진 것 (재보고 불필요)

- **gap_engine 종목당 3쿼리 N+1** — 33종목×3=99왕복. 유니버스(~2,600종목) 확대 스토리의 선행
  조건으로 이미 defer됨(deferred-work.md).
- **`latest_as_of`가 단순 MAX(as_of)** — 부분/디버그 실행이 기본 조회를 오염시킬 수 있음.
  score_run defer와 같은 항목(위 1번).
- **select-then-insert 동시성 미보장** — 단일 프로세스 배치 전제. 병렬화 시 `ON CONFLICT` 전환.
- **`--corp-codes` 부분 실행이 population/시점 혼재를 만들 수 있음** — 엔진 docstring에 문서화된
  기존 한계이며, 이 CLI는 그것을 **경고로 노출**하는 쪽을 택했습니다(숨기지 않는다는 2026-07-21 정책).

## 특히 봐주셨으면 하는 것

- **종료 코드 계약이 실제로 새는 곳은 없는지.** 예: `complete=True`이지만 사실상 아무 일도
  안 한 실행이 0을 반환하는 경로. (빈 `--corp-codes` 한 건은 이미 막았습니다 — 아래 코드 참조.
  같은 성격의 다른 경로가 있는지 봐주세요.)
- **`ValueError` 삼키기가 과한지.** `gap_engine.run()`을 감싼 `except ValueError`는 `_validate_as_of`의
  fail-fast를 사용법 오류로 번역하려는 것인데, 엔진 내부의 **다른** `ValueError`까지 종료 코드 2로
  세탁할 위험이 있습니다. (0 falsy 세탁·에러 세탁은 3-4 리뷰에서 지적받은 전력이 있는 계열입니다.)
- **로깅이 `logging.basicConfig`에 의존하는 것이 라이브러리 사용 시 문제되는지.**
- **테스트가 계약을 고정하는지, 구현을 고정하는지.**

## 검증 결과

- **261 passed** (251 + CLI 10종)
- 라이브(실 DB 33종목): `--as-of 2026-07-13` → `scored=26 deleted=7 failed=0 complete=True`, exit 0
- 종료 코드 2 실증: `--as-of` 미지정 / `2026-02-30`(달력 무효) / 빈 `--corp-codes`
- **멱등성**: 실행 전/후 `valueup_score` 전 행 해시 `2d84c01a5a5ef5b0`(26행) 불변,
  2026-07-22 인라인 호출 결과와 정확히 동일

## 파일 (verbatim)

### `docs/implementation-artifacts/4-1-scoring-batch-cli.md` (115행)

스토리 문서

````markdown
# Story 4-1 — 스코어링 배치 CLI (`run()` 첫 실호출자)

- **에픽**: 4 운영·배치 (v1 이후 신규)
- **상태**: review (구현·라이브 검증 완료, GPT 교차리뷰 대기)
- **작성일**: 2026-07-22
- **선행**: PR #1(`gap_engine` 트랜잭션 정책 확정 + `progress_rate` 일 단위 정합화, main `2ed33ef`)

## 배경

`gap_engine.run()`은 2026-07-21 party 코드리뷰에서 트랜잭션 정책이 확정되며
`ScoreRunResult(scored/deleted/succeeded/failed/complete)`를 반환하도록 바뀌었다.
그런데 **프로덕션 호출자가 없다** — 테스트만 호출한다. 그 결과 두 가지가 미결로 남았다.

1. `ScoreRunResult.complete`(부분 실패 스냅샷 여부)를 **확인하는 주체가 없다**
   (deferred-work.md, 트리거: "run() 실호출자 스토리")
2. 재계산 수단이 없다 — 2026-07-22 `progress_rate` 산식 변경분 반영은
   `python -c "from app.analysis import gap_engine; gap_engine.run(...)"` 인라인 호출로 때웠다.
   이 스토리가 그 임시 수단을 대체한다.

## 범위

**`gap_engine`만.** `mna_engine.run()`도 구식 시그니처(`session` 인자 + `int` 반환)로 남아 있고
deferred-work.md에 "mna 배치 실호출자 스토리" 트리거가 걸려 있으나, mna는 **cross-sectional**
(모집단을 루프 전 1회 구성)이라 부분 실패의 의미가 gap과 다르다 — 종목별 커밋이 옳은지 자체가
별도 판단이다. 같은 스토리에 끼워넣으면 두 개의 무관한 결정이 한 번에 승인되므로 분리한다.
**후속: Story 4-2(mna 배치 호출자 + 정책 판단).**

## 결정

### D1. `complete` 소비 = 종료 코드 + 경고 로그 (테이블 아님)

`score_run` 배치 메타데이터 테이블은 2026-07-14 리드 결정으로 **이미 닫혔다**
(v2 백로그 "멀티유저·운영 서비스화 시" 트리거, README 한계 §2). 그러므로 이 스토리에서
재론하지 않는다. CLI 네이티브 해법을 쓴다.

| 종료 코드 | 의미 |
|---|---|
| 0 | `complete=True` — 전 종목 동일 시점 스냅샷 |
| 1 | `complete=False` — 부분 실패, 같은 as_of에 실행분이 섞여 있음 |
| 2 | 사용법·입력 오류(argparse 관례, 잘못된 `--as-of` 포함) |

근거: 배치의 1차 소비자는 사람이 아니라 **셸·스케줄러**다. 종료 코드는 그 계층이 이미
이해하는 유일한 신호이고, "N건 완료"만 찍고 0을 반환하면 엔진이 애써 노출한 `complete`가
정확히 그 지점에서 다시 숨겨진다. 실패 목록은 `(corp_code, reason)` 전건을 로그로 출력한다
(잘라내지 않는다 — 무엇이 왜 실패했는지가 종목별 커밋 정책을 택한 이유이므로).

### D2. `--as-of` 필수 (시스템 시계 미사용)

기본값을 `date.today()`로 두지 않는다. `progress_rate`가 as_of에 직접 의존하므로
암묵적 오늘 날짜는 **재현 불가능한 실행**을 만든다. 3-1에서 매크로 as_of 기본값을 정할 때도
같은 이유로 시스템 시계를 배제했다(자체 최신 관측일 사용) — 그 원칙을 잇는다.

### D3. `--corp-codes` 부분 실행은 허용하되 경고

엔진 docstring이 "게시용 점수는 전체 실행"을 계약으로 명시한다. CLI도 부분 실행을 막지는
않되(디버깅에 필요) **경고 로그로 게시 부적합을 알린다**. `complete=True`여도 부분 실행이면
스냅샷은 여전히 부분적이다 — 두 개념이 다르다는 점을 로그가 구분해서 말해야 한다.

## 인수 조건

- **AC1** `python -m app.analysis.run_scoring --as-of YYYY-MM-DD`로 전 종목 재계산이 실행된다.
- **AC2** 실행 결과 요약(scored/deleted/failed/complete)이 로그로 출력된다.
- **AC3** `complete=True`면 종료 코드 0, `complete=False`면 1을 반환한다.
- **AC4** 실패 종목은 `(corp_code, 사유)` 전건이 로그에 출력된다.
- **AC5** `--as-of` 미지정 시 종료 코드 2로 실패한다(시스템 시계로 대체하지 않는다).
- **AC6** 잘못된 `--as-of`(형식·달력 무효)는 트레이스백이 아니라 종료 코드 2 + 사람이 읽을 수
  있는 메시지로 실패한다.
- **AC7** `--corp-codes` 부분 실행 시 "게시용 아님" 경고가 출력된다.
- **AC8** 기존 테스트 전건 통과(251 passed) + CLI 테스트 신규.

## 비범위

- `mna_engine` 배치 호출자 → Story 4-2
- `POST /scoring/run` HTTP 라우터 → 배포 스토리(현재 전 엔드포인트 무인증, deferred 보안 게이트)
- `score_run` 메타데이터 테이블 → v2 백로그(리드 결정으로 닫힘)
- gap_engine N+1 최적화 → 유니버스 확대 스토리의 선행 조건으로 이미 defer됨

## 검증 계획

- 단위: `main(argv)` 반환값으로 종료 코드 3종(0/1/2) 검증, 부분 실행 경고 검증
- 통합: SQLite in-memory + `session_factory` 주입(2.1 테스트 seam 재사용)으로 실제 스코어 기록 확인
- 라이브: 실 DB에 `--as-of 2026-07-13` 재실행 → 2026-07-22 인라인 호출 결과와 **동일**해야 함
  (멱등성 실증: scored 26 / deleted 7 / failed 0 / complete True)

## 검증 결과 (2026-07-22)

**테스트**: 251 → **261 passed** (CLI 10종 신규). 실패 주입은 `ScoreRunResult`를 직접 만들어
넣는다 — 엔진이 실패를 *어떻게* 만드는지는 2.1의 관심사고, 이 모듈의 관심사는 실패가 있을 때
**조용히 0을 반환하지 않는다**는 것뿐이기 때문이다.

**라이브(실 DB, valueup.db 33종목)**:

| 실행 | 출력 | 종료 코드 |
|---|---|---|
| `--as-of 2026-07-13` | `scored=26 deleted=7 failed=0 complete=True` | 0 |
| (미지정) | argparse `required` 오류 | 2 |
| `--as-of 2026-02-30` | `입력 오류: as_of가 달력상 유효한 날짜가 아닙니다` | 2 |
| `--as-of 2026-07-13 --corp-codes 00106641` | `부분 실행(1종목) … **게시용 아님**` + `scored=1 complete=True` | 0 |
| `--corp-codes " , "` | `입력 오류: 유효한 corp_code가 없습니다` (엔진 미도달) | 2 |

**멱등성 실증**: 전체 실행 전/후 `valueup_score` 전 행 해시 `2d84c01a5a5ef5b0`(26행) **불변**,
2026-07-22 인라인 호출 결과(26/7/0/True)와 정확히 동일. 부분 실행 후에도 동일 해시.

**설계 중 발견**: 빈 `--corp-codes`가 엔진에 `[]`로 도달하면 "대상 0종목"으로 `complete=True`,
`scored=0`, 종료 코드 0이 된다 — 전체 실행과 구분되지 않는 **조용한 무작업**이고, 이 스토리가
만들려는 신호 자체가 거짓이 되는 경로다. `_parse_corp_codes`에서 엔진 도달 전에 차단했다
(테스트가 `called is False`로 차단 지점을 고정한다).

## 인계

- **Story 4-2(mna 배치 호출자)**: gap 정책이 실호출로 안정화됐으므로 deferred-work.md의
  `mna_engine.run()` 트리거가 발동 상태. cross-sectional 특성상 종목별 커밋이 맞는지부터 판단 필요.
- **재계산 표준 절차**: 스코어 산식이 바뀌면 `run_scoring` → `app.export.tableau` →
  `.twbx` 재패키징 순서로 세 레이어를 정렬해야 한다(2026-07-22 실증). CSV에 `progress_rate`가
  있고 `.twbx`는 CSV를 임베드하므로 어느 하나만 갱신하면 레이어 간 값이 어긋난다.
````

### `app/analysis/run_scoring.py` (99행)

**이번 스토리의 신규 코드**

```python
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
```

### `tests/test_run_scoring_cli.py` (165행)

**이번 스토리의 신규 테스트**

```python
"""Story 4-1 — 스코어링 배치 CLI 검증.

핵심은 "계산이 맞나"가 아니라(그건 2.1이 검증한다) **엔진이 노출한 `complete`가
종료 코드로 번역되는가**다. 그 번역이 이 모듈의 존재 이유다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.analysis import run_scoring
from app.analysis.gap_engine import ScoreRunResult
from app.analysis.run_scoring import EXIT_INCOMPLETE, EXIT_OK, EXIT_USAGE, main
from app.models import Base, Company, Financial, ValueupPlan, ValueupScore
from app.sql_views import CREATE_VALUATION_METRICS


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:", future=True,
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.execute(text(CREATE_VALUATION_METRICS))
    return eng


def _seed(session: Session, corp_code: str = "00000001") -> None:
    """2.1 통합 테스트와 동일한 최소 시드(계획 + 전년도 확정실적)."""
    session.add(Company(corp_code=corp_code, corp_name="테스트", market="KOSPI"))
    session.add(Financial(
        corp_code=corp_code, year=2024, quarter=4,
        revenue=1000, net_income=80, operating_income=100, depreciation=10,
        equity=1000, total_assets=2000, total_liabilities=1000, cash=100,
        total_debt=200, dividend_total=24,
        buyback_amount=3_000_000, buyback_retired_amount=0,
    ))
    session.add(ValueupPlan(
        corp_code=corp_code, disclosure_date="2024-03-01",
        target_roe=10.0, target_payout_ratio=30.0, target_pbr=1.2,
        period_start="2024", period_end="2027", buyback_planned=True,
    ))
    session.commit()


# ── 종료 코드 계약 (AC3) ──

def test_complete_run_exits_zero(engine, monkeypatch) -> None:
    """AC1/AC3: 전체 실행이 성공하면 종료 코드 0이고 실제로 점수가 기록된다."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
    monkeypatch.setattr(run_scoring, "SessionLocal", Session_)

    assert main(["--as-of", "2025-12-31"]) == EXIT_OK

    with Session_() as s:
        row = s.scalars(select(ValueupScore)).one()
        assert row.corp_code == "00000001"
        assert row.as_of == "2025-12-31"


def test_partial_failure_exits_one(monkeypatch) -> None:
    """AC3의 핵심: complete=False가 종료 코드 1로 번역된다.

    여기서 실패를 '만들어' 주입하는 이유 — 엔진이 실패를 어떻게 만드는지는 2.1의 관심사고,
    이 모듈의 관심사는 실패가 있을 때 **조용히 0을 반환하지 않는다**는 것뿐이다.
    """
    def fake_run(as_of, corp_codes=None, *, session_factory=None):
        return ScoreRunResult(
            scored=2, deleted=0, succeeded=["00000001", "00000002"],
            failed=[("00000003", "boom")],
        )
    monkeypatch.setattr(run_scoring.gap_engine, "run", fake_run)

    assert main(["--as-of", "2025-12-31"]) == EXIT_INCOMPLETE


def test_failed_corp_codes_are_all_logged(monkeypatch, caplog) -> None:
    """AC4: 실패 목록은 전건 출력된다(자르지 않는다)."""
    failed = [(f"0000000{i}", f"사유{i}") for i in range(1, 6)]

    def fake_run(as_of, corp_codes=None, *, session_factory=None):
        return ScoreRunResult(scored=0, failed=list(failed))
    monkeypatch.setattr(run_scoring.gap_engine, "run", fake_run)

    with caplog.at_level("ERROR"):
        assert main(["--as-of", "2025-12-31"]) == EXIT_INCOMPLETE
    for corp_code, reason in failed:
        assert corp_code in caplog.text
        assert reason in caplog.text


def test_summary_is_logged(engine, monkeypatch, caplog) -> None:
    """AC2: 실행 요약(scored/deleted/failed/complete)이 남는다."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
    monkeypatch.setattr(run_scoring, "SessionLocal", Session_)

    with caplog.at_level("INFO"):
        assert main(["--as-of", "2025-12-31"]) == EXIT_OK
    assert "scored=1" in caplog.text
    assert "complete=True" in caplog.text


# ── 입력 계약 (AC5, AC6) ──

def test_as_of_is_required(capsys) -> None:
    """AC5: --as-of 미지정은 종료 코드 2 — 시스템 시계로 대체하지 않는다(D2)."""
    with pytest.raises(SystemExit) as exc:  # argparse의 required 처리
        main([])
    assert exc.value.code == EXIT_USAGE


@pytest.mark.parametrize("bad", ["2025-7-1", "not-a-date", "2025-02-30"])
def test_invalid_as_of_exits_two_without_traceback(bad, monkeypatch, caplog) -> None:
    """AC6: 형식 오류(2025-7-1)·달력 무효(2025-02-30) 모두 트레이스백이 아니라 종료 코드 2.

    2025-02-30은 정규식만으론 통과하는 값 — 엔진의 달력 검증까지 CLI가 삼키는지 확인한다.
    """
    Session_ = sessionmaker(bind=create_engine("sqlite:///:memory:", future=True))
    monkeypatch.setattr(run_scoring, "SessionLocal", Session_)

    with caplog.at_level("ERROR"):
        assert main(["--as-of", bad]) == EXIT_USAGE
    assert "입력 오류" in caplog.text


# ── 부분 실행 (AC7) ──

def test_partial_run_warns_not_publishable(engine, monkeypatch, caplog) -> None:
    """AC7: --corp-codes 실행은 complete=True여도 '게시용 아님' 경고를 남긴다(D3)."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
    monkeypatch.setattr(run_scoring, "SessionLocal", Session_)

    with caplog.at_level("WARNING"):
        assert main(["--as-of", "2025-12-31", "--corp-codes", "00000001"]) == EXIT_OK
    assert "게시용 아님" in caplog.text


def test_empty_corp_codes_is_usage_error(monkeypatch, caplog) -> None:
    """빈 --corp-codes는 '대상 0종목 조용한 성공'이 되므로 사용법 오류로 막는다.

    전체 실행(옵션 생략)과 구분되지 않는 무작업이 complete=True·exit 0으로 나가면,
    이 스토리가 만들려는 신호 자체가 거짓이 된다.
    """
    called = False

    def fake_run(*a, **kw):
        nonlocal called
        called = True
        return ScoreRunResult()
    monkeypatch.setattr(run_scoring.gap_engine, "run", fake_run)

    with caplog.at_level("ERROR"):
        assert main(["--as-of", "2025-12-31", "--corp-codes", " , "]) == EXIT_USAGE
    assert called is False  # 엔진에 도달하기 전에 막혔다
```

### `app/analysis/gap_engine.py` (296행)

호출 대상 엔진 — `run()`·`ScoreRunResult` 판단에 필요

```python
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
```

### `app/ingest/run.py` (194행)

CLI가 정책을 맞춘 형제 레이어(IngestResult 동형)

```python
"""수집 실행 진입점 (간단 함수형; 라우터 POST /ingest/run은 후속 스토리).

트랜잭션 정책(결정): **종목별 커밋 + 실패 목록**. 한 종목의 네트워크/파싱 실패가
이미 성공한 다른 종목의 적재를 되돌리지 않도록 부분 성공을 허용한다.
fetch(네트워크)는 짧은 DB 트랜잭션 밖에서 수행해 DB 커넥션 점유를 최소화한다.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.db import SessionLocal
from app.ingest.dart import DartAdapter, DartAdapterError
from app.ingest.dart_ownership import DartOwnershipAdapter
from app.ingest.dart_valueup import DartValueupAdapter
from app.ingest.ecos import EcosAdapter
from app.ingest.krx import KrxAdapter
from app.models import Company

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    ingested: int = 0
    succeeded: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (corp_code, reason)
    degraded: list[str] = field(default_factory=list)  # 부분성공(예: 시총·거래대금 미수집)


def ingest_financials(
    corp_codes: Sequence[str],
    bsns_year: str,
    reprt_code: str = "11011",
) -> IngestResult:
    """종목별로 fetch→normalize→upsert. 실패는 건너뛰고 목록에 담는다."""
    adapter = DartAdapter()
    result = IngestResult()
    for corp_code in corp_codes:
        try:
            raw = adapter.fetch(corp_code, bsns_year, reprt_code)  # 네트워크(트랜잭션 밖)
            records = adapter.normalize(raw)
            with SessionLocal() as session:  # 종목당 짧은 트랜잭션
                with session.begin():
                    n = adapter.upsert(session, records)
            result.ingested += n
            result.succeeded.append(corp_code)
            if not raw.get("buyback_ok", True):  # 자사주 현황 실패 → 부분성공(1.8, krx cap_ok 패턴)
                logger.warning("자기주식 현황 미수집(degraded) corp_code=%s", corp_code)
                result.degraded.append(corp_code)
            if not raw.get("dividend_ok", True):  # 배당 현황 실패 → 부분성공(1.9, 동일 패턴)
                logger.warning("배당 현황 미수집(degraded) corp_code=%s", corp_code)
                if corp_code not in result.degraded:
                    result.degraded.append(corp_code)
        except (DartAdapterError, Exception) as e:  # noqa: BLE001 (부분성공 정책)
            logger.warning("수집 실패 corp_code=%s: %s", corp_code, type(e).__name__)
            result.failed.append((corp_code, str(e)))
    return result


def ingest_valueup_plans(
    corp_codes: Sequence[str], date_from: str, date_to: str
) -> IngestResult:
    """종목별 밸류업 계획공시(DART) 수집. [date_from, date_to]는 YYYYMMDD(bgn_de/end_de).

    한 종목이 예고·본공시·정정 등 여러 공시를 내면 각각 valueup_plan 행이 된다.
    실패는 건너뛰고 목록에 담는다(부분성공). fetch(네트워크)는 짧은 트랜잭션 밖.
    """
    adapter = DartValueupAdapter()
    result = IngestResult()
    for corp_code in corp_codes:
        try:
            raw = adapter.fetch(corp_code, date_from, date_to)  # 네트워크(트랜잭션 밖)
            records = adapter.normalize(raw)
            with SessionLocal() as session:  # 종목당 짧은 트랜잭션
                with session.begin():
                    n = adapter.upsert(session, records)
            result.ingested += n
            result.succeeded.append(corp_code)
            # 문서별 실패(무효 날짜·문서 다운로드 실패 등)는 종목 전체를 막지 않고 degraded 표시
            if raw.get("failed"):
                result.degraded.append(corp_code)
                for doc_id, reason in raw["failed"]:
                    logger.warning(
                        "밸류업 문서 실패 corp_code=%s doc=%s: %s",
                        corp_code, doc_id, reason,
                    )
        except Exception as e:  # noqa: BLE001 (부분성공 정책)
            logger.warning(
                "밸류업 공시 수집 실패 corp_code=%s: %s", corp_code, type(e).__name__
            )
            result.failed.append((corp_code, str(e)))
    return result


def ingest_ownership(
    corp_codes: Sequence[str], bsns_year: str, reprt_code: str = "11011"
) -> IngestResult:
    """종목별 지분구조(DART hyslrSttus+stockTotqySttus) 수집.

    완전 미공시(양 엔드포인트 데이터 없음)는 행을 만들지 않고 failed에 사유로 분리한다.
    실패는 건너뛰고 목록에 담는다(부분성공). fetch(네트워크)는 짧은 트랜잭션 밖.
    """
    adapter = DartOwnershipAdapter()
    result = IngestResult()
    for corp_code in corp_codes:
        try:
            raw = adapter.fetch(corp_code, bsns_year, reprt_code)  # 네트워크(트랜잭션 밖)
            records = adapter.normalize(raw)
            with SessionLocal() as session:  # 종목당 짧은 트랜잭션
                with session.begin():
                    n = adapter.upsert(session, records)
            result.ingested += n
            if records:
                result.succeeded.append(corp_code)
            else:
                # 미공시(에러 아님) → degraded로 분리(진짜 실패와 구분)
                logger.info("지분공시 데이터 없음 corp_code=%s", corp_code)
                result.degraded.append(corp_code)
        except Exception as e:  # noqa: BLE001 (부분성공 정책)
            logger.warning(
                "지분구조 수집 실패 corp_code=%s: %s", corp_code, type(e).__name__
            )
            result.failed.append((corp_code, str(e)))
    return result


def ingest_macro(date_from: str, date_to: str) -> IngestResult:
    """ECOS 매크로 지표(4종)를 [date_from, date_to](YYYYMMDD) 수집·적재.

    지표별 실패는 격리(fetch가 지표별로 잡아 raw['failed'] 반환) → result.failed에 표시.
    """
    adapter = EcosAdapter()
    result = IngestResult()
    try:
        raw = adapter.fetch(date_from, date_to)
        records = adapter.normalize(raw)
        with SessionLocal() as session:
            with session.begin():
                result.ingested = adapter.upsert(session, records)
        for indicator, reason in raw.get("failed", []):
            logger.warning("매크로 지표 실패 %s: %s", indicator, reason)
            result.failed.append((indicator, reason))
        # 성공한(=실패 목록에 없는) 지표
        failed_names = {i for i, _ in raw.get("failed", [])}
        result.succeeded.extend(
            i for i in ("base_rate", "bond_3y", "usd_krw", "leading_index")
            if i not in failed_names
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("매크로 수집 실패: %s", type(e).__name__)
        result.failed.append(("ecos", str(e)))
    return result


def ingest_prices(
    corp_codes: Sequence[str], date_from: str, date_to: str
) -> IngestResult:
    """종목별 시세·시총·거래대금 수집. stock_code는 company에서 조회(AD-5).

    - preflight: company/stock_code 매핑 부재는 먼저 failed로 분리.
    - degraded: 종가는 적재됐으나 시총·거래대금(cap 로그인) 실패 시 corp_code를 degraded에 표시.
    """
    adapter = KrxAdapter()
    result = IngestResult()
    # preflight: stock_code 매핑 확인
    stock_map: dict[str, str] = {}
    with SessionLocal() as session:
        for corp_code in corp_codes:
            company = session.get(Company, corp_code)
            sc = company.stock_code if company else None
            if not sc:
                result.failed.append((corp_code, "company.stock_code 없음(먼저 1.2 수집)"))
            else:
                stock_map[corp_code] = sc

    for corp_code, stock_code in stock_map.items():
        try:
            raw = adapter.fetch(stock_code, corp_code, date_from, date_to)
            records = adapter.normalize(raw)
            with SessionLocal() as session:
                with session.begin():
                    n = adapter.upsert(session, records)
            result.ingested += n
            result.succeeded.append(corp_code)
            if not raw.get("cap_ok"):  # 시총·거래대금 원천 실패 → 부분성공
                logger.warning("시총·거래대금 미수집(degraded) corp_code=%s", corp_code)
                result.degraded.append(corp_code)
        except Exception as e:  # noqa: BLE001 (부분성공 정책)
            logger.warning("시세 수집 실패 corp_code=%s: %s", corp_code, type(e).__name__)
            result.failed.append((corp_code, str(e)))
    return result
```

### `app/export/tableau.py` (발췌: 195–223행 / 전체 223행)

CLI 관례 선례(`main(argv)->int` + `SystemExit`)

```python
        shutil.rmtree(staging, ignore_errors=True)
        if old.exists() and not out_dir.exists():
            old.rename(out_dir)  # 교체 도중 실패 — 기존 스냅숏 원위치
        raise
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tableau Public용 CSV export")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR,
                        help=f"출력 디렉터리 (기본 {DEFAULT_OUT_DIR})")
    parser.add_argument("--as-of", dest="as_of", default=None,
                        help="과거 스냅숏 재현용 기준일(YYYY-MM-DD, 두 엔진 모두 존재해야 함). "
                             "생략 시 두 엔진 공통 최신일.")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    session = SessionLocal()
    try:
        counts = export_all(session, args.out, as_of=args.as_of)
    finally:
        session.close()
    total = sum(counts.values())
    logger.info("완료: %d개 뷰, 총 %d행", len(counts), total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

### `README.md` (diff)

PR #1 이후 동작하지 않는 시그니처였던 예시를 정정한 부수 수정입니다.

```diff
diff --git a/README.md b/README.md
index a095f5d..dee4966 100644
--- a/README.md
+++ b/README.md
@@ -37,24 +37,35 @@ cd dashboard && npm install && cd ..
 # 2) 프론트 대시보드  →  http://localhost:5175 (Vite proxy → :8000)
 cd dashboard && npm run dev
 
-# 3) Tableau용 CSV 스냅숏  →  exports/tableau/*.csv + manifest.json
+# 3) valueup_score 재계산  →  종료 코드 0=완전 / 1=부분 실패 / 2=입력 오류
+.venv/Scripts/python -m app.analysis.run_scoring --as-of 2026-07-13
+
+# 4) Tableau용 CSV 스냅숏  →  exports/tableau/*.csv + manifest.json
 .venv/Scripts/python -m app.export.tableau            # 두 엔진 공통 최신 기준일
 .venv/Scripts/python -m app.export.tableau --as-of 2026-07-13   # 과거 시점 재현
 ```
 
-데이터 수집·스코어링은 Python API로 실행합니다(단일 사용자 로컬 도구라 별도 CLI 대신 함수 직접 호출):
+`--as-of`는 **필수**입니다. `progress_rate`가 기준일에 직접 의존하므로 암묵적 오늘 날짜는
+재현 불가능한 실행을 만듭니다. 부분 실패가 있으면 실패 종목을 전건 출력하고 종료 코드 1을
+반환합니다 — 그 as_of 스냅숏에 이번 실행분과 이전 실행분이 섞여 있다는 뜻입니다.
+
+> **스코어 산식을 바꾼 뒤에는 세 레이어를 함께 정렬해야 합니다**: `run_scoring` → `app.export.tableau`
+> → `.twbx` 재패키징. CSV가 `progress_rate`를 담고 `.twbx`는 그 CSV를 임베드하므로, 하나만
+> 갱신하면 레이어 간 값이 어긋납니다.
+
+데이터 수집과 M&A 스코어링은 아직 Python API로 실행합니다(배치 CLI는 gap 엔진부터 도입 중):
 
 ```python
 from app.db import SessionLocal
 from app.ingest import run as ingest          # ingest_financials / prices / macro / valueup_plans / ownership
-from app.analysis import gap_engine, mna_engine
+from app.analysis import mna_engine
 
-s = SessionLocal()
-gap_engine.run(s, as_of="2026-07-13")         # valueup_score 계산·upsert (유일 writer)
-mna_engine.run(s, as_of="2026-07-13")         # mna_score 계산·upsert (유일 writer)
+with SessionLocal() as s:
+    with s.begin():
+        mna_engine.run(s, as_of="2026-07-13")  # mna_score 계산·upsert (유일 writer)
 ```
 
-테스트: `pytest -q`(백엔드 246) · `cd dashboard && npm test`(프론트 56) · 마이그레이션 `alembic upgrade head`(0001~0011).
+테스트: `pytest -q`(백엔드 261) · `cd dashboard && npm test`(프론트 56) · 마이그레이션 `alembic upgrade head`(0001~0011).
 
 ## 아키텍처 (AD 요약)
 
```
