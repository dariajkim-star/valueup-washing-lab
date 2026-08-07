"""opacity_engine — 공시 불투명도 순위(washing_flag 후속, 파티 결정 2026-07-23).

washing_flag는 '고의(워싱 의심)'를 판정해 프로젝트 서명("불확실을 확실로 세탁하지 않는다")을
위반했고, 실측 True=0이었다 — target_roe 58%·buyback_planned 48% null인 표본에서 4치 AND가
전항 확정 True가 될 일이 구조적으로 거의 없어, **켜질 수 없는 경고등**이었다(버그 아님, 은퇴 대상).

그 자리를 대체하는 것이 opacity_rank. '고의'가 아니라 **격차** — 공시하지 않은 목표 축의 수를
peer(같은 KSIC 버킷) 대비 백분위로 순위화한다(레아 원칙: "고의를 판정하지 말고 격차를 드러내라").
입력은 valueup_plan의 목표 공시 여부뿐, **신규 수집 없음**.

구조는 mna_engine과 동형(peer 백분위 + 섹터 버킷 + 시장 폴백 + basis) — 그 원시함수를 재사용한다.

⚠️ 본문 밖 공시 사각지대(2026-07-23 발견 → 2026-07-28 실 DB 실측으로 규칙 교체):
    대기업 다수가 실계획을 본문이 아니라 **첨부(PDF/HWP)나 회사 웹페이지**로 낸다
    (SK하이닉스·LG에너지솔루션·하나금융·삼성화재·LG화학 등). document.xml엔 표지 통지문만
    남아 opacity_count가 최대로 잡히고, 그대로 두면 '가장 불투명한 워싱 기업'으로 **오인**된다
    — 실제로는 기계가독 형식으로 안 냈을 뿐 목표는 공시했다.
    그래서 **4축 전부 미공시(count==4)는 순위 불가로 제외**한다(is_unrankable). 처음엔 "첨부
    참조 문구 AND count==4"로 좁혔으나, 실 DB 첫 적재에서 그 참조 검사가 변별력 0임이
    드러나 참조 검사를 버렸다(사유는 is_unrankable docstring).
    본문 밖 계획 수집(DART 웹뷰어 스크래핑 + PDF/HWP 파싱)은 OpenAPI 범위 밖이라 별도
    백로그 스토리로 분리했다(2026-07-23 결정 ②).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.analysis.gap_engine import _validate_as_of  # as_of 검증 재사용(중복 정의 금지)
from app.analysis.mna_engine import _pct_rank_high, _sector_bucket
from app.analysis.plan_selection import OPACITY_AXES
from app.analysis.plan_selection import is_unrankable, opacity_count  # noqa: F401 — 재수출
from app.analysis.plan_selection import opacity_axes as _plan_opacity_axes
# 순위 불가의 사유는 판정 어휘(declares_no_attachment 이웃)를 쓰므로 plan_signals가 소유한다.
from app.analysis.plan_signals import (  # noqa: F401 — 재수출(호출부·테스트 호환)
    UNDISCLOSED,
    UNREADABLE,
    UNSTATED,
    unrankable_reason,
)
from app.config import settings
from app.db import SessionLocal
from app.repositories import opacity_score as repo

logger = logging.getLogger(__name__)

# ── 불투명 축(4개) ──
# 각 축이 null이면 "그 목표를 공시하지 않음" = 1점. 설계 근거(파티 2026-07-23):
#   - target_pbr 제외: 100% null이자 achievement 산식 미사용(gap_engine) → 변별력 0, 노이즈만.
#   - period: period_start/period_end는 항상 동반 null(둘 다 73%)이라 한 축으로 묶는다
#     (각각 세면 "기간 미공시"가 이중 가중).
#   - payout: 배당성향·총주주환원율은 **대체재**(하나만 약속해도 환원을 공시한 것)라 OR로 묶는다
#     (각각 세면 총주주환원율만 약속한 기업이 부당하게 불투명해진다 — Boundary 지적).
#   - buyback: None만 '미공시'. False는 "자사주 계획 없음"을 **공시한** 것이므로 불투명 아님
#     (_washing_flag가 buyback_planned를 3치로 다루는 것과 같은 기준).
# 축 정의의 실제 소유자는 plan_selection이다(2026-07-29). 공시 선택 규칙이 "목표가 몇 축
# 있는가"로 폴백을 판정하므로, 축을 두 벌로 두면 **채점에 쓴 축**과 **불투명도를 센 축**이
# 어긋난다. 여기서는 이름만 유지(호출부·테스트 호환).
_OPACITY_AXES = OPACITY_AXES
opacity_axes = _plan_opacity_axes


# ── peer 상대 순위(mna_engine 패턴 재사용) ──
def _bucket_of(
    corp_code: str, sectors: Mapping[str, str | None], market_key: str
) -> str:
    """corp → KSIC 버킷 키(분류 불가는 시장 모집단으로)."""
    return _sector_bucket(sectors.get(corp_code)) or market_key


def rank_opacity(
    counts: Mapping[str, int],
    sectors: Mapping[str, str | None],
    peer_min: int,
    *,
    market_key: str = "__market__",
) -> dict[str, tuple[float | None, str | None]]:
    """corp별 opacity_count → (opacity_rank, basis). mna와 동형의 섹터/시장 폴백.

    - 같은 KSIC 버킷 안 유효 peer가 peer_min 이상이면 sector 백분위(basis="sector:NN"),
      미달이면 시장 전체로 폴백(basis="market_fallback"), 버킷 미상이면 "market".
    - 순위는 `_pct_rank_high`(불투명 많을수록 높은 순위). 동점은 mid-rank(mna와 동일)라
      "전원 같은 수준" 버킷은 0.5로 중립. 유효 peer<2면 None(mna와 동일 계약).

    counts에서 제외된 종목(본문 전무 count==4 등)은 애초에 넘기지 않는다 — 모집단·순위 양쪽에서 빠진다.
    """
    # 버킷별 count 모집단
    sector_pop: dict[str, list[float]] = {}
    market_pop: list[float] = []
    for corp_code, cnt in counts.items():
        bucket = _bucket_of(corp_code, sectors, market_key)
        sector_pop.setdefault(bucket, []).append(float(cnt))
        market_pop.append(float(cnt))

    # 버킷 승격 판정(small-N 노이즈 방어, mna_peer_min과 같은 기준)
    sector_ready = {
        b: len(pop) >= peer_min
        for b, pop in sector_pop.items()
        if b != market_key
    }

    out: dict[str, tuple[float | None, str | None]] = {}
    for corp_code, cnt in counts.items():
        bucket = _bucket_of(corp_code, sectors, market_key)
        if bucket == market_key:
            pop, basis = market_pop, "market"
        elif sector_ready.get(bucket, False):
            pop, basis = sector_pop[bucket], f"sector:{bucket}"
        else:
            pop, basis = market_pop, "market_fallback"
        rank = _pct_rank_high(float(cnt), pop)
        out[corp_code] = (rank, basis if rank is not None else None)
    return out


def rank_from_plans(
    plans: Mapping[str, Mapping[str, object]],
    sectors: Mapping[str, str | None],
    peer_min: int,
) -> dict[str, tuple[float | None, str | None]]:
    """corp별 **최신** 계획 dict → opacity_rank. 순위 불가(본문 전무)는 모집단에서 제외.

    plans[corp] 은 target_* 필드를 가진 계획 한 건(최신)이어야 한다.
    """
    counts = {
        corp: opacity_count(plan)
        for corp, plan in plans.items()
        if not is_unrankable(plan)
    }
    return rank_opacity(counts, sectors, peer_min)


# ── DB 배선(run) ──────────────────────────────────────────────────────────────
# 위쪽은 순수 코어(입력=계획 dict). 아래는 그것을 DB에 배선하는 오케스트레이션 —
# mna_engine.run과 **동형**이다. opacity_rank도 cross-sectional 백분위라 세대가 섞이면
# 순위표 자체가 무의미해지므로, gap_engine의 종목별 커밋이 아니라 mna의 **전량 원자성 +
# 실패 보고** 정책을 그대로 쓴다(트랜잭션 성질이 순위와 묶여 있다).


class _IncompleteRun(Exception):
    """전량 롤백을 일으키기 위한 내부 신호. run() 밖으로 새지 않는다.

    실패 사유는 이미 OpacityRunResult에 담겨 있으므로 이 예외 자체는 정보를 나르지 않는다.
    """


@dataclass
class OpacityRunResult:
    """run()의 결과. MnaRunResult와 동형 — `complete=False`는 **아무것도 쓰이지 않았다**
    (전량 롤백)를 뜻한다(트랜잭션 정책이 mna와 같기 때문, run() docstring 참조)."""

    scored: int = 0  # upsert된 종목 수(롤백 시 DB에 남지 않음 — 계산된 수)
    deleted: int = 0  # 순위 불가(계획 없음·본문 전무·peer<2)로 정리된 종목 수
    succeeded: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (corp_code, reason)
    aborted_early: bool = False
    fatal_error: str | None = None
    partial_scope: bool = False

    @property
    def complete(self) -> bool:
        """실패 없이 끝났는가(= 트랜잭션이 커밋됐는가). '전 종목 동일 모집단'은 아니다
        (그건 publishable). mna의 같은 이름 속성과 동일 의미."""
        return not self.failed and self.fatal_error is None

    @property
    def publishable(self) -> bool:
        """이 as_of의 opacity_score 테이블을 게시·비교에 써도 되는가. 백분위 순위는 전 종목이
        같은 모집단 세대일 때만 의미가 있어, 부분 실행은 성공해도 게시 불가(mna와 동일)."""
        return self.complete and not self.partial_scope


def run(
    as_of: str,
    corp_codes: Sequence[str] | None = None,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> OpacityRunResult:
    """as_of 기준 corp별 opacity_score를 계산·upsert. OpacityRunResult 반환.

    트랜잭션 정책은 mna_engine.run과 동일한 **전량 원자성 + 실패 보고**다 — 순위표는
    세대가 섞이면 무의미하므로 부분 커밋이 없다. 실패 사실은 롤백돼도 result·로그로 남는다.

    모집단은 **밸류업 계획을 공시한 종목**뿐이다. 계획을 아예 내지 않은 종목은 opacity_score
    행을 만들지 않는다(reconciliation으로 기존 행 정리) — '약속하지 않은 것을 드러낸다'이지
    '참여하지 않은 것을 최대 불투명으로 벌한다'가 아니기 때문(레아 원칙). 본문 4축이 전부 빈
    계획(읽을 수 없는 공시)도 같은 이유로 모집단·행 양쪽에서 빠진다(is_unrankable).

    - 백분위 모집단은 corp_codes 부분집합과 무관하게 **전체 계획 공시 종목** 기준.
    - **부분 실행 주의**: corp_codes 부분집합은 대상만 최신 모집단으로 갱신하고 나머지는 과거
      모집단 순위로 남긴다 — 게시용은 반드시 전체 실행(corp_codes=None)으로 재계산할 것.
    """
    _validate_as_of(as_of)
    # 기본 인자로 두면 정의 시점에 factory가 고정돼 conftest의 monkeypatch가 못 막는다
    # (mna_engine과 동일 — 실 DB 오염 방어. conftest가 이 모듈의 SessionLocal도 갈아끼운다).
    session_factory = session_factory or SessionLocal
    result = OpacityRunResult(partial_scope=corp_codes is not None)
    try:
        with session_factory() as session, session.begin():
            _run_in_session(session, as_of, corp_codes, result)
    except _IncompleteRun:
        logger.error(
            "opacity 스코어 실패 → 전량 롤백(opacity_score는 실행 이전 상태). as_of=%s 사유=%s",
            as_of, result.fatal_error or f"{len(result.failed)}종목 실패",
        )
        result.scored = 0
        result.deleted = 0
        result.succeeded.clear()
    return result


def _run_in_session(
    session: Session,
    as_of: str,
    corp_codes: Sequence[str] | None,
    result: OpacityRunResult,
) -> None:
    """run()의 본문. 트랜잭션 경계 밖으로 빼서 롤백 책임을 호출부 한 곳에 둔다(mna와 동일).

    읽기·순위 계산이 종목 루프 이전에 전부 끝나고, 루프 안은 메모리 값 upsert/delete뿐이라
    예상 가능한 실패 유형이 구조적으로 적다. SQLAlchemy 오류는 세션을 못 쓰게 만들 수 있어
    즉시 중단(aborted_early), 그 외 예외는 엔진 버그로 보고 중단한다.
    """
    if corp_codes is None:
        corp_codes = repo.list_all_corp_codes(session)

    # 1단계: 전체 모집단 배치 구성(cross-sectional — corp 루프 전에 끝나야 함)
    plans = repo.all_latest_plans(session, as_of)
    if not plans:
        # 계획 공시 종목이 전무 — 밸류업 프로그램 규모상 정상 상태가 아니다(ETL 장애 가능성).
        # 기존 행은 지우지 않고(오삭제 방어), 정상 완료로 보고하지도 않는다(mna의 입력 전무
        # 가드와 동일 원칙). 유니버스 자체가 비었으면 진짜로 할 일이 없다.
        if corp_codes:
            result.fatal_error = (
                f"opacity 입력(밸류업 계획)이 전무하다(대상 {len(corp_codes)}종목, "
                "valueup_plan 0건) — 업스트림 수집 상태를 확인할 것"
            )
            raise _IncompleteRun
        return
    sectors = repo.all_company_sectors(session)

    # 순위 불가(본문 전무) 제외 후 corp별 미공시 축 수 → peer 백분위(코어 재사용). counts는 순위와
    # 함께 저장하므로 rank_from_plans 대신 두 단계를 펼친다(rank는 count로부터 나온다).
    counts = {
        corp: opacity_count(plan)
        for corp, plan in plans.items()
        if not is_unrankable(plan)
    }
    ranks = rank_opacity(counts, sectors, settings.opacity_peer_min)

    # 2단계: 종목별 upsert/reconcile
    for corp_code in corp_codes:
        rank, basis = ranks.get(corp_code, (None, None))
        try:
            if rank is None:
                # 계획 없음·본문 전무·유효 peer<2 → 순위 불가. 근거 없는 기존 행 정리.
                repo.delete_opacity_score(session, corp_code, as_of)
                deleted = True
            else:
                repo.upsert_opacity_score(session, {
                    "corp_code": corp_code, "as_of": as_of,
                    "opacity_rank": rank,
                    "opacity_count": counts.get(corp_code),
                    "opacity_basis": basis,
                })
                deleted = False
        except SQLAlchemyError as e:
            # 세션이 오염되면 이후 종목은 전부 노이즈 실패가 된다 — 여기서 멈추고 불완전 표시.
            logger.warning(
                "opacity SQLAlchemy 오류 corp_code=%s: %s — 세션 사용 불가 가능성으로 중단",
                corp_code, type(e).__name__,
            )
            result.failed.append((corp_code, str(e)))
            result.aborted_early = True
            break
        except Exception as e:  # noqa: BLE001
            # 루프 안은 순수 upsert/delete라 여기 오는 것은 엔진 버그다(데이터 오류 아님).
            logger.exception("opacity 엔진 내부 오류 corp_code=%s", corp_code)
            result.failed.append((corp_code, f"{type(e).__name__}: {e}"))
            result.fatal_error = f"엔진 내부 오류({type(e).__name__}) — 코드 결함일 가능성"
            result.aborted_early = True
            break
        if deleted:
            result.deleted += 1
        else:
            result.scored += 1
        result.succeeded.append(corp_code)

    if result.failed:
        raise _IncompleteRun
