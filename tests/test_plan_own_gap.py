"""plan_own_gap 뷰 + _ambition 자기과거 기준선 (P1-7 화면 반영, 0024).

이 파일이 생기기 전까지 야심도에는 **백엔드 테스트가 하나도 없었다**(프론트 GapCard만
있었다). 그 탓에 `_ambition`이 뷰에 의존하도록 바꿔도 테스트가 통과했다 — 뷰를 안 만든
인메모리 DB에서 조용히 빈 결과가 나올 뿐이었기 때문이다. 여기서 그 구멍을 메운다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base, Company, Financial, ValueupPlan
from app.repositories.valueup_score import _ambition
from app.sql_views import CREATE_PLAN_OWN_GAP, CREATE_VALUATION_METRICS


@pytest.fixture()
def session() -> Session:
    eng = create_engine(
        "sqlite:///:memory:", future=True,
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.execute(text(CREATE_VALUATION_METRICS))
        conn.execute(text(CREATE_PLAN_OWN_GAP))
    with Session(eng) as s:
        yield s


def _financial(corp: str, year: int, *, net_income: int, dividend: int) -> Financial:
    """payout_ratio = dividend/net_income*100 이 되도록 최소 필드만 채운다."""
    return Financial(
        corp_code=corp, year=year, quarter=4,
        revenue=1000, net_income=net_income, operating_income=100,
        equity=1000, total_assets=2000, total_liabilities=500, cash=100,
        dividend_total=dividend,
    )


def _seed(s: Session, corp: str = "00000001") -> None:
    s.add(Company(corp_code=corp, corp_name="테스트", market="KOSPI", sector="26100"))
    # FY2024 배당성향 = 400/1000*100 = 40%
    s.add(_financial(corp, 2024, net_income=1000, dividend=400))
    s.commit()


def test_own_gap_is_negative_when_target_below_own_past(session: Session) -> None:
    """자기 과거 40%인데 목표를 30%로 잡으면 -10.0%p — '하던 것보다 낮은 약속'."""
    _seed(session)
    plan = ValueupPlan(
        corp_code="00000001", disclosure_date="2025-03-01", target_payout_ratio=30.0,
    )
    session.add(plan)
    session.commit()

    row = session.execute(text(
        "SELECT baseline_year, own_past, own_gap FROM plan_own_gap "
        "WHERE plan_id = :p AND metric = 'payout_ratio'"
    ), {"p": plan.plan_id}).first()
    assert row == (2024, 40.0, -10.0)


def test_ambition_reads_the_view(session: Session) -> None:
    """상세(_ambition)와 목록이 **같은 정의**를 쓴다 — 뷰가 단일 정의처다."""
    _seed(session)
    plan = ValueupPlan(
        corp_code="00000001", disclosure_date="2025-03-01", target_payout_ratio=30.0,
    )
    session.add(plan)
    session.commit()

    items = {i["metric"]: i for i in _ambition(session, "00000001", plan)}
    assert items["payout_ratio"]["own_gap"] == -10.0
    assert items["payout_ratio"]["own_past"] == 40.0
    assert items["payout_ratio"]["baseline_year"] == 2024


def test_baseline_falls_back_one_more_year(session: Session) -> None:
    """공시 직전 연도 실적이 없으면 한 해 더 뒤로 간다(지표마다 따로 정한다)."""
    _seed(session)  # 2024만 있다
    plan = ValueupPlan(
        corp_code="00000001", disclosure_date="2026-03-01", target_payout_ratio=30.0,
    )
    session.add(plan)
    session.commit()

    row = session.execute(text(
        "SELECT baseline_year, own_gap FROM plan_own_gap WHERE plan_id = :p"
    ), {"p": plan.plan_id}).first()
    assert row == (2024, -10.0)  # 2025가 없어 2024로


def test_no_baseline_yields_null_not_zero(session: Session) -> None:
    """비교할 과거가 없으면 null이다 — 0(격차 없음)으로 세탁하지 않는다.

    이 계약이 깨지면 "잴 수 없는 기업"이 "자기 과거만큼은 약속한 기업"으로 보인다.
    """
    session.add(Company(corp_code="00000002", corp_name="신생", market="KOSPI"))
    plan = ValueupPlan(
        corp_code="00000002", disclosure_date="2025-03-01", target_payout_ratio=30.0,
    )
    session.add(plan)
    session.commit()

    row = session.execute(text(
        "SELECT own_past, own_gap FROM plan_own_gap WHERE plan_id = :p"
    ), {"p": plan.plan_id}).first()
    assert row == (None, None)


def test_undisclosed_axis_has_no_row(session: Session) -> None:
    """공시하지 않은 축은 행 자체가 없다 — 미공시를 '격차 0'으로 만들지 않는다."""
    _seed(session)
    plan = ValueupPlan(
        corp_code="00000001", disclosure_date="2025-03-01", target_payout_ratio=30.0,
    )
    session.add(plan)
    session.commit()

    metrics = [m for (m,) in session.execute(text(
        "SELECT metric FROM plan_own_gap WHERE plan_id = :p"
    ), {"p": plan.plan_id}).all()]
    assert metrics == ["payout_ratio"]  # roe·total_return_ratio는 미공시라 없음
