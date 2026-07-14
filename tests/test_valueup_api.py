"""Story 2.4 — 갭분석/워싱랭킹 API 검증 (SQLite in-memory + TestClient)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Company, ValueupScore


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:", future=True,
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    return eng


def _seed(s: Session) -> None:
    for code, name, market in (
        ("00000001", "워싱의심", "KOSPI"),
        ("00000002", "이행양호", "KOSPI"),
        ("00000003", "판단불가", "KOSDAQ"),
        ("00000004", "점수없음", "KOSPI"),
    ):
        s.add(Company(corp_code=code, corp_name=name, market=market))
    s.add(ValueupScore(
        corp_code="00000001", as_of="2026-07-13",
        target_roe=10.0, actual_roe=3.0, roe_gap=-7.0,
        achievement_rate=0.3, progress_rate=0.8, execution_score=25.0,
        washing_flag=True, buyback_status="purchased_only",
    ))
    s.add(ValueupScore(
        corp_code="00000002", as_of="2026-07-13",
        target_roe=10.0, actual_roe=11.0, roe_gap=1.0,
        achievement_rate=1.1, progress_rate=0.8, execution_score=95.0,
        washing_flag=False, buyback_status="retired",
    ))
    s.add(ValueupScore(
        corp_code="00000003", as_of="2026-07-13",
        achievement_rate=None, progress_rate=0.2, execution_score=None,
        washing_flag=None, buyback_status="unknown",
    ))
    s.add(ValueupScore(  # 다른 as_of(과거) — 최신 기본 조회에서 제외돼야
        corp_code="00000004", as_of="2025-12-31",
        execution_score=10.0, washing_flag=False,
    ))
    s.commit()


@pytest.fixture()
def client(engine, monkeypatch):
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    return TestClient(fastapi_app)


def test_gap_analysis_envelope_and_order(client) -> None:
    """AC1/3: 봉투 + execution_score 오름차순(null last) + 기본 as_of=최신."""
    r = client.get("/valueup/gap-analysis")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "total", "page", "size"}
    assert body["total"] == 3  # 최신 as_of(2026-07-13)만, 과거 행 제외
    codes = [i["corp_code"] for i in body["items"]]
    # 25.0 → 95.0 → null(판단불가 마지막)
    assert codes == ["00000001", "00000002", "00000003"]
    # 목표·실제·갭 동결값 노출
    assert body["items"][0]["roe_gap"] == -7.0
    # washing null은 null 그대로(false 강제 금지)
    assert body["items"][2]["washing_flag"] is None


def test_washing_ranking_only_true(client) -> None:
    """AC2: washing_flag=true만 — 판단불가(null)·근거없음(false) 제외."""
    r = client.get("/valueup/washing-ranking")
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["corp_code"] == "00000001"
    assert body["items"][0]["washing_flag"] is True


def test_filters_market_and_min_progress(client) -> None:
    """AC3: market·min_progress 필터."""
    r = client.get("/valueup/gap-analysis", params={"market": "KOSDAQ"})
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000003"]
    r2 = client.get("/valueup/gap-analysis", params={"min_progress": 0.5})
    assert {i["corp_code"] for i in r2.json()["items"]} == {"00000001", "00000002"}


def test_corp_code_filter(client) -> None:
    """[3.4] 상세화면 단건 조회 — corp_code 정확일치 필터."""
    r = client.get("/valueup/gap-analysis", params={"corp_code": "00000001"})
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["corp_code"] == "00000001"
    assert body["items"][0]["roe_gap"] == -7.0
    r2 = client.get("/valueup/gap-analysis", params={"corp_code": "00000099"})
    assert r2.json()["total"] == 0  # 존재하지 않는 종목 → 빈 결과(404 아님)


def test_explicit_as_of(client) -> None:
    """AC3: as_of 명시 조회(과거 스냅샷)."""
    r = client.get("/valueup/gap-analysis", params={"as_of": "2025-12-31"})
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000004"]


def test_empty_scores_returns_empty_envelope(engine, monkeypatch) -> None:
    """스코어 미적재 → 빈 봉투(500 아님)."""
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    r = TestClient(fastapi_app).get("/valueup/gap-analysis")
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0, "page": 1, "size": 20}


def test_invalid_as_of_is_422_not_empty_200(client) -> None:
    """[일괄리뷰 Med] 달력상 무효/쓰레기 as_of는 422 — 빈 200으로 세탁 금지."""
    assert client.get("/valueup/gap-analysis", params={"as_of": "2026-02-30"}).status_code == 422
    assert client.get("/valueup/gap-analysis", params={"as_of": "garbage"}).status_code == 422
