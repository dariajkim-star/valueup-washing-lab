"""목록의 목표 야심도 — lowest_own_gap 서빙 + max_own_gap 필터 (P1-7, 뷰 0024).

착수 근거(실측 2026-08-03): 만점 70건 중 **40건이 자기 과거보다 낮은 목표**인데
목록에서 구분되지 않았다. 그 사실을 찾으려면 상세를 70번 열어야 했다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Company, Financial, ValueupPlan, ValueupScore
from app.sql_views import CREATE_PLAN_OWN_GAP, CREATE_VALUATION_METRICS

AS_OF = "2026-07-13"


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:", future=True,
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.execute(text(CREATE_VALUATION_METRICS))
        conn.execute(text(CREATE_PLAN_OWN_GAP))
    return eng


def _financial(corp: str, year: int, net_income: int, dividend: int) -> Financial:
    return Financial(
        corp_code=corp, year=year, quarter=4, revenue=1000, net_income=net_income,
        operating_income=100, equity=1000, total_assets=2000,
        total_liabilities=500, cash=100, dividend_total=dividend,
    )


def _seed(s: Session) -> None:
    # ① 낮은 목표: 과거 배당성향 40% → 목표 30% (-10.0%p)
    # ② 야심찬 목표: 과거 40% → 목표 60% (+20.0%p)
    # ③ 기준선 없음: 과거 실적이 없다 → null (0이 아니다)
    for code, name in (("00000001", "낮은목표"), ("00000002", "야심목표"),
                       ("00000003", "기준선없음")):
        s.add(Company(corp_code=code, corp_name=name, market="KOSPI", sector="26100"))
    s.add(_financial("00000001", 2024, 1000, 400))
    s.add(_financial("00000002", 2024, 1000, 400))
    s.commit()

    for code, target in (("00000001", 30.0), ("00000002", 60.0), ("00000003", 30.0)):
        plan = ValueupPlan(
            corp_code=code, disclosure_date="2025-03-01", target_payout_ratio=target,
        )
        s.add(plan)
        s.flush()
        s.add(ValueupScore(
            corp_code=code, as_of=AS_OF, execution_score=100.0,
            source_plan_id=plan.plan_id,
        ))
    s.commit()


@pytest.fixture()
def client(engine, monkeypatch):
    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    return TestClient(fastapi_app)


def test_lowest_own_gap_is_served(client) -> None:
    """세 기업이 execution_score 100으로 같지만 야심도는 서로 다르다 — 그게 요점이다."""
    r = client.get("/screening", params={"as_of": AS_OF})
    assert r.status_code == 200
    by_code = {i["corp_code"]: i for i in r.json()["items"]}
    assert by_code["00000001"]["lowest_own_gap"] == -10.0
    assert by_code["00000002"]["lowest_own_gap"] == 20.0
    # 비교할 과거가 없으면 null — 0(격차 없음)으로 세탁하지 않는다
    assert by_code["00000003"]["lowest_own_gap"] is None
    assert {i["execution_score"] for i in r.json()["items"]} == {100.0}


def test_max_own_gap_filter(client) -> None:
    """max_own_gap=0 → '하던 것만큼도 약속하지 않은' 기업만."""
    r = client.get("/screening", params={"as_of": AS_OF, "max_own_gap": 0})
    assert r.status_code == 200
    codes = [i["corp_code"] for i in r.json()["items"]]
    assert codes == ["00000001"]


def test_filter_excludes_unmeasurable_not_treats_as_ambitious(client) -> None:
    """기준선이 없는 기업은 필터에 매칭되지 않는다 — 통과로도 탈락으로도 세탁 안 함.

    널널한 상한(+100)을 줘도 기준선 없는 기업은 나오지 않는다. "잴 수 없음"은
    "야심찼음"이 아니다(레아 원칙: 측정 불가와 가장 나쁨은 다른 범주다).
    """
    r = client.get("/screening", params={"as_of": AS_OF, "max_own_gap": 100})
    codes = {i["corp_code"] for i in r.json()["items"]}
    assert codes == {"00000001", "00000002"}
    assert "00000003" not in codes
