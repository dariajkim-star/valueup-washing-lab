"""시장·매크로 통계 유스케이스 (routers→services→repositories, AD-2)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.repositories import stats as repo
from app.repositories import valueup_score
from app.schemas import MacroSnapshotOut, MarketComparisonOut, Page, StatsSummaryOut


def market_comparison(session: Session, as_of: str | None) -> Page[MarketComparisonOut]:
    # latest_as_of()를 as_of 유무와 무관하게 먼저 확인(GPT 리뷰 Med) — 그렇지 않으면
    # "테이블이 통째로 비어있음"과 "이 특정 as_of엔 데이터 없음"이 명시 as_of 유무에 따라
    # 다르게 취급된다(테이블이 비었어도 명시 as_of를 주면 통과해버리던 버그).
    latest = valueup_score.latest_as_of(session)
    if latest is None:  # valueup_score 미적재 → 빈 봉투(500 아님)
        return Page(items=[], total=0, page=1, size=0)
    rows = repo.market_comparison(session, as_of or latest)
    items = [MarketComparisonOut(**r) for r in rows]
    return Page(items=items, total=len(items), page=1, size=len(items))


def summary(session: Session, as_of: str | None) -> StatsSummaryOut | None:
    latest = valueup_score.latest_as_of(session)
    if latest is None:  # valueup_score 미적재 → None(404)
        return None
    return StatsSummaryOut(**repo.summary(session, as_of or latest))


def macro(session: Session, as_of: str | None) -> Page[MacroSnapshotOut]:
    # macro_indicator 자체의 최신 관측일이 기본값 — valueup_score와 독립(서로 다른 데이터 계열).
    # 관측이 아예 없으면(resolved=None) 시스템 시계로 대체하지 않고(AD-8 정신) 4개 지표
    # 자리를 null로 채운 빈 스냅샷을 바로 구성 — DB 재조회 불필요(어차피 빈 결과).
    resolved = as_of or repo.latest_macro_as_of(session)
    if resolved is None:
        rows = [{"indicator": ind, "date": None, "value": None} for ind in repo.MACRO_INDICATORS]
    else:
        rows = repo.macro_snapshot(session, resolved)
    items = [MacroSnapshotOut(**r) for r in rows]
    return Page(items=items, total=len(items), page=1, size=len(items))
