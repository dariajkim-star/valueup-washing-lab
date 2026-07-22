"""M&A Target Score 엔진 (writer = 이 모듈, AD-10).

2.1(gap_engine, 종목별 독립 계산)과 다른 아키텍처: **cross-sectional 백분위** — 한 종목의
점수가 전체 모집단 분포에 의존한다. 따라서 (1) 전체 모집단을 배치로 먼저 구성하고,
(2) 그 안에서 각 종목의 백분위를 계산하는 2단계 구조. 산식은 scoring.md M&A 섹션 참조.

null 규칙(엄격, 리드 결정 2026-07-10): 요소의 서브지표가 하나라도 null이면 요소 점수 null,
요소가 하나라도 null이면 mna_target_score null — "일부만 알면서 평균 내서 숫자 만들기" 금지
(2.1 execution_score와 동일 원칙, NFR2 "null > 틀린 값").

grouping seam(리드 결정, finance 스코프 분리): 백분위 모집단은 `_build_populations`의
`group_of` 콜러블이 결정한다. v1 = 전체시장 단일 그룹. 후속 2-7이 `company.sector` 기반
peer-group으로 갈아끼울 이음새 — 백분위 계산부는 population 출처를 모른다.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.analysis.gap_engine import _validate_as_of  # as_of 검증 재사용(중복 정의 금지)
from app.config import settings
from app.db import SessionLocal
from app.repositories import mna_score as repo

logger = logging.getLogger(__name__)

# 전체시장 그룹키(폴백·sector 미상 종목용)
_WHOLE_MARKET = "_all"


def _sector_bucket(sector: str | None) -> str | None:
    """DART induty_code → KSIC 2자리 버킷(2.7 택소노미 v1 — 수작업 매핑 없이 결정적).

    2자리 미만·비숫자는 None(분류 불가 → market 모집단, 값을 만들지 않음).
    """
    if not sector:
        return None
    prefix = str(sector).strip()[:2]
    return prefix if len(prefix) == 2 and prefix.isdigit() else None

# (지표명, 방향) — 요소별 서브지표 정의. low=낮을수록 좋음, high=높을수록 좋음.
_VALUATION_INDICATORS = (("ev_ebitda", "low"), ("pbr", "low"))
_CAPACITY_INDICATORS = (("debt_ratio", "low"), ("net_cash", "high"), ("ebitda_margin", "high"))
_OWNERSHIP_INDICATORS = (("largest_shareholder_pct", "low"), ("treasury_stock_pct", "high"))


def _percentile_rank(value: float | None, population: Sequence[float | None]) -> float | None:
    """population 내 value의 백분위(0~1), **mid-rank** — (below + (equal-1)/2) / (N-1).

    동점을 최하위에 몰지 않고 구간 중앙에 배치(코드리뷰 2026-07-10 High): min-rank였다면
    전원 동일값에서 전원 rank 0 → pct_low 1.0("모두 똑같은데 최고점") — 기준금리처럼 장기
    동결되는 시계열에서 실제로 발생. mid-rank는 전원 동일 → 0.5(중립), 고유 최솟값 0·최댓값 1.
    NaN/Inf는 대상값·모집단 모두 배제(비교 연산 왜곡 방지, 리뷰 Med). 유효 peer<2 → None.
    """
    if not _is_finite_value(value):
        return None
    pop = [v for v in population if _is_finite_value(v)]
    if len(pop) < 2:
        return None
    below = sum(1 for v in pop if v < value)
    equal = sum(1 for v in pop if v == value)
    return (below + max(equal - 1, 0) / 2) / (len(pop) - 1)


def _pct_rank_low(value: float | None, population: Sequence[float | None]) -> float | None:
    """낮을수록 좋은 지표(EV/EBITDA·PBR·부채비율·최대주주지분율·기준금리) → 역백분위."""
    rank = _percentile_rank(value, population)
    return None if rank is None else 1.0 - rank


def _pct_rank_high(value: float | None, population: Sequence[float | None]) -> float | None:
    """높을수록 좋은 지표(순현금·EBITDA마진·자사주비중) → 백분위 그대로."""
    return _percentile_rank(value, population)


def _avg_scores(*scores: float | None) -> float | None:
    """서브지표 점수 평균. 하나라도 None이면 전체 None(엄격, 리드 결정 — 결측이 잦은
    지표가 은근히 가중치를 왜곡하는 '있는 것만 평균' 부작용 방지)."""
    if any(s is None for s in scores):
        return None
    return sum(scores) / len(scores)


def _mna_target_score(
    valuation: float | None,
    capacity: float | None,
    ownership: float | None,
    macro: float | None,
    w_valuation: float,
    w_capacity: float,
    w_ownership: float,
    w_macro: float,
) -> float | None:
    """가중합 0~100. 요소 하나라도 None이면 전체 None(NFR2)."""
    if valuation is None or capacity is None or ownership is None or macro is None:
        return None
    return 100 * (
        w_valuation * valuation
        + w_capacity * capacity
        + w_ownership * ownership
        + w_macro * macro
    )


def _is_finite_value(value: Any) -> bool:
    """백분위 계산에 실제로 쓸 수 있는 값인가 — None·NaN·Inf·비수치 전부 배제.

    `_percentile_rank`와 `_build_populations`가 **같은 정의**를 써야 한다(코드리뷰 2026-07-22 Med).
    이전엔 population은 `is not None`만 걸러 NaN/Inf를 유효 peer로 세고, rank 계산은 isfinite로
    다시 걸렀다 — 그 결과 sector_ready 판정(모집단 길이 기준)이 실제 유효 peer 수보다 부풀려져,
    시장 폴백으로 갔어야 할 종목이 sector 모집단을 쓰고 점수가 통째로 None이 되는 경로가 있었다.
    """
    if value is None:
        return False
    try:
        return math.isfinite(value)
    except TypeError:  # 수치가 아닌 값(문자열 등) — 비교 연산 자체가 성립하지 않는다
        return False


def _build_populations(
    rows: Mapping[str, Mapping[str, Any]],
    group_of: Callable[[str], str],
) -> dict[str, dict[str, list[float]]]:
    """corp별 지표 dict → 그룹별·지표별 population(유효값 리스트).

    grouping seam: `group_of(corp_code) -> 그룹키`. v1은 상수(전체시장), 2-7에서
    sector 버킷으로 교체. 백분위 계산부는 이 함수가 준 population만 소비한다.

    "유효값"의 정의는 `_is_finite_value` 하나로 통일된다 — sector 준비 판정이 세는 개수와
    실제 백분위가 쓰는 개수가 달라지면 모집단 선택이 틀어진다.
    """
    pops: dict[str, dict[str, list[float]]] = {}
    for corp_code, indicators in rows.items():
        group = group_of(corp_code)
        bucket = pops.setdefault(group, {})
        for name, value in indicators.items():
            if _is_finite_value(value):
                bucket.setdefault(name, []).append(value)
    return pops


def _factor_score(
    indicators: tuple[tuple[str, str], ...],
    corp_row: Mapping[str, Any] | None,
    population: Mapping[str, list[float]],
) -> float | None:
    """요소 점수 = 서브지표 백분위들의 평균(엄격 null). corp 데이터 자체가 없으면 None."""
    if corp_row is None:
        return None
    scores: list[float | None] = []
    for name, direction in indicators:
        value = corp_row.get(name)
        pop = population.get(name, [])
        rank = _pct_rank_low(value, pop) if direction == "low" else _pct_rank_high(value, pop)
        scores.append(rank)
    return _avg_scores(*scores)


class _IncompleteRun(Exception):
    """전량 롤백을 일으키기 위한 내부 신호. run() 밖으로 새지 않는다.

    실패 사유는 이미 MnaRunResult.failed에 담겨 있으므로 이 예외 자체는 정보를 나르지 않는다.
    트랜잭션을 되돌리는 것이 유일한 역할이다.
    """


@dataclass
class MnaRunResult:
    """run()의 결과. gap_engine의 ScoreRunResult와 **동형**이되 의미가 하나 다르다.

    `complete=False`는 gap에서는 "이 as_of에 실행분이 섞여 있다"였지만, 여기서는
    **"아무것도 쓰이지 않았다"**(전량 롤백)를 뜻한다. 트랜잭션 정책이 다르기 때문이며
    그 이유는 run() docstring 참조.
    """

    scored: int = 0  # upsert된 종목 수(롤백 시 DB에 남지 않음 — 계산된 수)
    deleted: int = 0  # 근거를 잃어 정리된 종목 수
    succeeded: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (corp_code, reason)
    # 세션 오류·엔진 버그로 루프를 중단했는가. True면 failed는 **완전한 목록이 아니다** —
    # 남은 종목은 시도조차 되지 않았다(성공했을지 실패했을지 알 수 없음).
    aborted_early: bool = False
    # 실행 자체를 무산시킨 사유(업스트림 입력 전무, 엔진 내부 오류 등). None이면 없음.
    fatal_error: str | None = None
    # corp_codes 부분집합 실행이었는가. 성공 여부와 **무관하게** 스냅숏을 부분적으로 만든다.
    partial_scope: bool = False

    @property
    def complete(self) -> bool:
        """이번 실행이 실패 없이 끝났는가(= 트랜잭션이 커밋됐는가).

        **"전 종목이 동일 모집단 기준"을 뜻하지 않는다**(코드리뷰 2026-07-22 High).
        그건 `publishable`이다 — 이전 docstring이 두 개념을 한 값에 담아 과장했고, 부분 실행이
        혼재를 만들면서도 complete=True를 반환했다.
        """
        return not self.failed and self.fatal_error is None

    @property
    def publishable(self) -> bool:
        """이 as_of의 mna_score 테이블을 게시·비교에 써도 되는가.

        백분위 순위는 **전 종목이 같은 모집단 세대**일 때만 의미가 있다. 부분 실행은 대상 밖
        종목을 이전 세대 점수로 남기므로, 실행 자체가 성공(complete)해도 결과 표는 게시 불가다.
        """
        return self.complete and not self.partial_scope


def run(
    as_of: str,
    corp_codes: Sequence[str] | None = None,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> MnaRunResult:
    """as_of 기준 corp별 mna_score를 계산·upsert. MnaRunResult 반환.

    트랜잭션 정책(결정, Story 4-2): **전량 원자성 + 실패 보고**. gap_engine의 종목별 커밋과
    의도적으로 **반대**다 — 일관성 결여가 아니라 점수의 성질이 다르기 때문이다.

    `valueup_score`는 종목별 절대 측정치라 한 종목이 낡아도 나머지는 여전히 옳다. 반면
    `mna_target_score`는 **백분위 순위**로 모집단 안의 상대 위치가 곧 점수다. 세대가 섞인
    mna 테이블은 "일부만 오래된 값"이 아니라 **순위 자체가 무의미한 표**가 된다 — 서로 다른
    모집단 기준으로 매긴 등수를 한 줄에 세운 것이므로. 게다가 읽기가 전부 루프 이전에 끝나
    루프 안은 순수 계산 + upsert뿐이라, 종목별 커밋이 방어할 실패 유형 자체가 구조적으로 적다.

    gap에서 원자성을 기각한 사유("어느 종목이 왜 실패했는지 정보까지 소실")는 여기서
    해소된다 — 실패 목록을 DB가 아니라 MnaRunResult·로그로 남기므로 롤백되는 것은 **점수**뿐,
    **실패 사실은 보고된다**. "섞임을 없애는 대신 숨기지 않는다"(2026-07-21)와 어긋나지 않는다.
    이 엔진에서 숨기지 않는 방식이 '섞어서 노출'이 아니라 '롤백하고 보고'일 뿐이다.

    세션은 이 함수가 소유한다(gap_engine과 동일 이유 — 넘겨받은 세션에 커밋을 걸면 호출자의
    미저장 작업까지 함께 커밋된다). 단 gap과 달리 **전체가 단일 트랜잭션**이다.

    - 백분위 모집단은 corp_codes 부분집합과 무관하게 **전체 시장**(all_latest_* 배치 결과)
      기준 — 부분 실행이어도 순위 기준이 흔들리면 안 된다.
    - 종목별 3요소(valuation/capacity/ownership)가 전부 None이면 행을 만들지 않는다
      (macro는 전 종목 공통이라 그것만으론 종목별 정보가 없음 — all-null 행 방지, 1-6 교훈).
      기존 행이 있으면 정리(2.1 reconciliation 패턴). 단, **metrics·ownership이 통째로
      비면**(업스트림 수집 장애/ETL 중간 상태 가능성) 오삭제를 막기 위해 계산·삭제 모두
      스킵하고 0을 반환한다(코드리뷰 2026-07-10 Med 가드).
    - **부분 실행 주의(문서화된 한계, 리뷰 High)**: corp_codes 부분집합 실행은 대상 종목만
      최신 모집단 기준으로 갱신하고 나머지 행은 과거 모집단 점수로 남긴다 — 같은 as_of
      테이블 안에 서로 다른 population snapshot이 섞일 수 있다. **게시용 점수는 반드시
      전체 실행(corp_codes=None)으로 재계산**할 것. 부분 실행은 테스트/디버깅 용도.
    """
    _validate_as_of(as_of)
    # 기본 인자로 두면 정의 시점에 객체가 고정돼 테스트가 모듈 속성만 바꿔선 못 막는다
    # (코드리뷰 2026-07-22 Med — 실 DB 오염 사고의 구조적 원인).
    session_factory = session_factory or SessionLocal
    result = MnaRunResult(partial_scope=corp_codes is not None)
    # 전량 원자성: 읽기·계산·쓰기 전부가 하나의 트랜잭션. _IncompleteRun이 오르면
    # session.begin() 블록이 롤백하고, 그 신호는 여기서 삼킨다(사유는 result에 있다).
    try:
        with session_factory() as session, session.begin():
            _run_in_session(session, as_of, corp_codes, result)
    except _IncompleteRun:
        logger.error(
            "M&A 스코어 실패 → 전량 롤백(mna_score는 실행 이전 상태). as_of=%s 사유=%s",
            as_of, result.fatal_error or f"{len(result.failed)}종목 실패",
        )
        # 롤백됐으므로 '계산된 수'는 DB에 없다 — 결과가 쓰이지 않은 것을 숫자로도 드러낸다.
        result.scored = 0
        result.deleted = 0
        result.succeeded.clear()
    return result


def _run_in_session(
    session: Session,
    as_of: str,
    corp_codes: Sequence[str] | None,
    result: MnaRunResult,
) -> None:
    """run()의 본문. 트랜잭션 경계 밖으로 빼서 롤백 책임을 호출부 한 곳에 둔다.

    실패는 result.failed에 담고 루프를 계속 돈다 — 순위표는 부분적으로 옳을 수 없으므로
    어차피 전량 롤백되지만, 그 전에 **진짜 사유를 최대한 모으는** 편이 재실행에 쓸모 있다.
    루프가 끝나면 예외를 올려 롤백시킨다(사유는 result에 이미 담겼다).

    **예외 — DB 오류는 즉시 중단한다**(2026-07-22 실측). SQLAlchemy 오류가 나면 세션이
    사용 불가 상태가 되어 이후 종목은 전부 "Can't operate on closed transaction"으로 실패한다.
    그 사유들은 정보가 아니라 **노이즈**이고(해당 종목이 실제로 성공했을지는 알 수 없다),
    계속 도는 이유 자체가 사라진다. 이때는 `aborted_early=True`로 **목록이 불완전함을 표시**한다.
    """
    if corp_codes is None:
        corp_codes = repo.list_all_corp_codes(session)

    # 1단계: 전체 모집단 배치 구성(cross-sectional — corp 루프 전에 끝나야 함)
    metrics = repo.all_latest_metrics(session, as_of)
    ownership = repo.all_latest_ownership(session, as_of)
    if not metrics and not ownership:
        # 입력 전무 — 업스트림 장애 가능성. 기존 행은 절대 지우지 않는다(reconciliation 오삭제 방어).
        # 다만 **정상 완료로 보고하지도 않는다**(코드리뷰 2026-07-22 High): 유니버스에 종목이
        # 있는데 입력이 통째로 비었다면 그건 "계산할 게 없었다"가 아니라 ETL 장애다.
        # 이전엔 그냥 return이라 complete=True·종료 코드 0으로 나가 재계산이 정상 완료된 것처럼
        # 보였다 — "롤백하되 실패를 숨기지 않는다"는 이 엔진의 원칙과 정면으로 어긋났다.
        if corp_codes:
            result.fatal_error = (
                f"M&A 입력 데이터가 전무하다(대상 {len(corp_codes)}종목, "
                "metrics·ownership 둘 다 0건) — 업스트림 수집 상태를 확인할 것"
            )
            raise _IncompleteRun
        return  # 유니버스 자체가 비었다 = 진짜로 할 일이 없다
    current_rate, rate_history = repo.latest_macro_percentile_basis(session, as_of)
    sectors = repo.all_company_sectors(session)

    # 시장 모집단(폴백·sector 미상·ownership용) + sector 버킷 모집단(2.7, valuation·capacity용)
    market_pops = _build_populations(metrics, group_of=lambda c: _WHOLE_MARKET)
    sector_pops = _build_populations(
        metrics, group_of=lambda c: _sector_bucket(sectors.get(c)) or _WHOLE_MARKET
    )
    # 버킷 sector 승격 판정(일괄리뷰 High: '행 개수'가 아니라 **지표별 유효값 개수** 기준 —
    # 행은 6개인데 ev_ebitda 유효값이 2개면 mna_peer_min의 small-N 방어가 우회되던 문제).
    # valuation·capacity의 5개 서브지표 전부가 peer_min 이상일 때만 sector 사용(단일
    # basis의 의미 보존), 하나라도 미달이면 그 버킷 전체를 시장 폴백.
    _factor_indicators = tuple(
        name for name, _ in _VALUATION_INDICATORS + _CAPACITY_INDICATORS
    )
    sector_ready: dict[str, bool] = {}
    for b, pops in sector_pops.items():
        if b == _WHOLE_MARKET:
            continue
        sector_ready[b] = all(
            len(pops.get(name, [])) >= settings.mna_peer_min
            for name in _factor_indicators
        )
    # ownership은 업종 무관(절대적 취약성 신호, epics 2.7 AC) — 시장 모집단 유지
    owner_pops = _build_populations(ownership, group_of=lambda c: _WHOLE_MARKET)
    # macro_score: 종목 무관, as_of당 1회(낮은 금리 = 차입인수 유리 → 역백분위)
    macro_score = _pct_rank_low(current_rate, rate_history)

    pops = _Populations(
        market=market_pops, sector=sector_pops, owner=owner_pops,
        sector_ready=sector_ready, sectors=sectors, macro_score=macro_score,
    )
    for corp_code in corp_codes:
        try:
            upserted = _score_one(
                session, corp_code, as_of, metrics, ownership, pops
            )
        except SQLAlchemyError as e:
            # SQLAlchemy 계층 오류는 세션을 못 쓰게 만들 수 있다 — 이후 종목은 전부
            # "closed transaction"으로 실패해 **사유가 노이즈**가 되고, 그 종목들이 실제로
            # 성공했을지는 알 수 없게 된다. 계속 도는 이유가 사라지므로 여기서 멈춘다.
            # (모든 SQLAlchemyError가 세션을 오염시키진 않지만 — NoResultFound 등 — 구분보다
            #  보수적 중단이 안전하다. 리뷰어도 같은 판단: 데이터 안전에 유리.)
            logger.warning(
                "M&A 스코어 SQLAlchemy 오류 corp_code=%s: %s — 세션 사용 불가 가능성으로 중단",
                corp_code, type(e).__name__,
            )
            result.failed.append((corp_code, str(e)))
            result.aborted_early = True
            break
        except Exception as e:  # noqa: BLE001
            # 여기 오는 것은 **종목별 데이터 오류가 아니라 엔진 버그**다 — 루프 안은 이미
            # 메모리에 올린 값으로 하는 순수 계산이라 예상 가능한 실패 유형이 없다.
            # 이전엔 사유를 담고 계속 돌았는데, 그러면 리팩터링 실수 하나가 33종목의 독립
            # 데이터 오류처럼 부풀려지고 traceback도 사라진다(코드리뷰 2026-07-22 Med —
            # DB 오류에서 고친 "노이즈 실패 목록" 문제가 프로그램 오류에서 재발하던 것).
            logger.exception("M&A 엔진 내부 오류 corp_code=%s", corp_code)
            result.failed.append((corp_code, f"{type(e).__name__}: {e}"))
            result.fatal_error = f"엔진 내부 오류({type(e).__name__}) — 코드 결함일 가능성"
            result.aborted_early = True
            break
        if upserted:
            result.scored += 1
        else:
            result.deleted += 1
        result.succeeded.append(corp_code)

    if result.failed:
        # 루프를 끝까지 돌고 나서 올린다 — 첫 실패에서 멈추면 실패 목록이 1건으로 잘려
        # "무엇이 왜 실패했는지"를 남기려던 이유가 사라진다(사유는 result에 이미 담겼다).
        raise _IncompleteRun


@dataclass
class _Populations:
    """_score_one에 넘길 모집단 묶음. 루프 이전에 확정되며 종목별로 바뀌지 않는다."""

    market: dict[str, dict[str, list[float]]]
    sector: dict[str, dict[str, list[float]]]
    owner: dict[str, dict[str, list[float]]]
    sector_ready: dict[str, bool]
    sectors: Mapping[str, str | None]
    macro_score: float | None


def _score_one(
    session: Session,
    corp_code: str,
    as_of: str,
    metrics: Mapping[str, Any],
    ownership: Mapping[str, Any],
    pops: _Populations,
) -> bool:
    """한 종목의 점수를 계산·upsert. upsert했으면 True, 근거가 없어 정리했으면 False."""
    bucket = _sector_bucket(pops.sectors.get(corp_code))
    if bucket is None:
        pop, basis = pops.market.get(_WHOLE_MARKET, {}), "market"
    elif pops.sector_ready.get(bucket, False):
        pop, basis = pops.sector.get(bucket, {}), f"sector:{bucket}"
    else:  # 버킷 지표별 peer 미달 → 시장 폴백(small-N 노이즈 방어)
        pop, basis = pops.market.get(_WHOLE_MARKET, {}), "market_fallback"

    valuation = _factor_score(_VALUATION_INDICATORS, metrics.get(corp_code), pop)
    capacity = _factor_score(_CAPACITY_INDICATORS, metrics.get(corp_code), pop)
    owner = _factor_score(
        _OWNERSHIP_INDICATORS, ownership.get(corp_code),
        pops.owner.get(_WHOLE_MARKET, {}),
    )
    if valuation is None and capacity is None:
        # basis 과장 방지(일괄리뷰 Med): 이 종목의 valuation·capacity에 모집단이
        # 실제로 쓰이지 않았으면(둘 다 null) basis를 기록하지 않는다.
        basis = None
    if valuation is None and capacity is None and owner is None:
        repo.delete_mna_score(session, corp_code, as_of)  # 근거 없는 기존 행 정리
        return False

    total = _mna_target_score(
        valuation, capacity, owner, pops.macro_score,
        settings.mna_w_valuation, settings.mna_w_capacity,
        settings.mna_w_ownership, settings.mna_w_macro,
    )
    repo.upsert_mna_score(
        session,
        {
            "corp_code": corp_code,
            "as_of": as_of,
            "mna_target_score": total,
            "valuation_score": valuation,
            "capacity_score": capacity,
            "ownership_score": owner,
            "macro_score": pops.macro_score,
            "population_basis": basis,
        },
    )
    return True
