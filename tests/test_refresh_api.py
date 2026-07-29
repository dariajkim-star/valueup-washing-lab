"""POST /valueup/refresh/{corp_code} — 단건 재수집+재채점 (0015 출처 추적 동반).

DART(외부)는 호출하지 않는다: refresh 서비스의 세 단계를 각각 대역으로 바꿔
**라우터가 보고하는 계약**(부분 성공을 뭉개지 않는가·범위가 맞는가)만 검증한다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Company, ValueupPlan
from app.repositories.valueup_plan import upsert_valueup_plan
from app.services import refresh as refresh_service


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:", future=True,
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine)


@pytest.fixture()
def db_session(session_factory) -> Session:
    with session_factory() as s:
        yield s


@pytest.fixture()
def client(session_factory, db_session, monkeypatch):
    import app.db as db_module
    from app.main import app as fastapi_app

    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    return TestClient(fastapi_app)


def _company(session, code="00126380", name="삼성전자(주)"):
    session.add(Company(corp_code=code, corp_name=name, market="KOSPI", sector="2612"))
    session.commit()


def test_refresh_404_when_company_unknown(client, db_session):
    r = client.post("/valueup/refresh/99999999")
    assert r.status_code == 404
    assert "99999999" in r.json()["detail"]


def test_refresh_reports_each_stage(client, db_session, monkeypatch):
    """세 단계를 개별 필드로 보고 — '성공' 한 단어로 뭉치지 않는다."""
    _company(db_session)
    monkeypatch.setattr(
        refresh_service, "refresh_company",
        lambda code, as_of=None: refresh_service.RefreshResult(
            corp_code=code, as_of="2026-07-13", plans_ingested=2,
            ingest_ok=True, scored=True, opacity_reranked=True,
        ),
    )
    body = client.post("/valueup/refresh/00126380").json()
    assert body["plans_ingested"] == 2
    assert body["ingest_ok"] is True and body["scored"] is True
    assert body["opacity_reranked"] is True
    assert body["complete"] is True


def test_partial_failure_is_not_reported_as_complete(client, db_session, monkeypatch):
    """수집 성공 + 채점 실패는 complete=False이고, 실패 사유가 남는다."""
    _company(db_session)
    monkeypatch.setattr(
        refresh_service, "refresh_company",
        lambda code, as_of=None: refresh_service.RefreshResult(
            corp_code=code, as_of="2026-07-13", plans_ingested=1,
            ingest_ok=True, scored=False, score_error="DBError",
            opacity_reranked=True,
        ),
    )
    body = client.post("/valueup/refresh/00126380").json()
    assert body["complete"] is False
    assert body["score_error"] == "DBError"


def test_ingest_failure_still_attempts_rescoring(monkeypatch):
    """수집 실패가 재채점을 막지 않는다(단계 격리) — 서비스 레벨 계약."""
    calls: list[str] = []

    def boom(*a, **k):
        raise RuntimeError("DART down")

    monkeypatch.setattr(refresh_service, "ingest_valueup_plans", boom)
    monkeypatch.setattr(
        refresh_service.gap_engine, "run",
        lambda *a, **k: calls.append("gap") or type("R", (), {"complete": True})(),
    )
    monkeypatch.setattr(
        refresh_service.opacity_engine, "run",
        lambda *a, **k: calls.append("opacity") or type("R", (), {"complete": True})(),
    )
    r = refresh_service.refresh_company("00126380", "2026-07-13")
    assert r.ingest_error == "RuntimeError"
    assert calls == ["gap", "opacity"]  # 수집이 죽어도 두 엔진은 돌았다
    assert r.complete is False  # 그래도 완전 성공은 아니다


def test_opacity_rerun_is_population_wide(monkeypatch):
    """opacity는 **전체**(corp_codes=None), gap은 해당 종목만 — 범위가 다르다.

    백분위 순위를 한 종목만 갱신하면 서로 다른 모집단 기준의 등수가 한 표에 섞인다.
    """
    seen: dict[str, object] = {}
    monkeypatch.setattr(refresh_service, "ingest_valueup_plans",
                        lambda codes, a, b: type("I", (), {
                            "ingested": 1, "succeeded": list(codes),
                            "failed": [], "degraded": []})())
    monkeypatch.setattr(
        refresh_service.gap_engine, "run",
        lambda as_of, codes, **k: seen.__setitem__("gap", codes)
        or type("R", (), {"complete": True})(),
    )
    monkeypatch.setattr(
        refresh_service.opacity_engine, "run",
        lambda as_of, codes, **k: seen.__setitem__("opacity", codes)
        or type("R", (), {"complete": True})(),
    )
    refresh_service.refresh_company("00126380", "2026-07-13")
    assert seen["gap"] == ["00126380"]  # 절대 측정치 → 단건
    assert seen["opacity"] is None  # 백분위 → 전량


def test_defaults_to_existing_generation_not_today(db_session, session_factory, monkeypatch):
    """[회귀 2026-07-29] 새로고침이 **새 as_of 세대를 만들지 않는다.**

    처음 구현은 as_of 기본값이 date.today()였고, 버튼 한 번에 valueup/opacity만 새 세대로
    가고 mna는 남아 화면이 최신 as_of로 수렴하는 순간 M&A가 전 종목에서 사라졌다.
    이 버튼은 mna를 돌리지 않으므로 새 세대를 열 자격이 없다 — 기존 세대를 제자리 갱신한다.
    """
    import app.db as db_module
    from app.models import ValueupScore

    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    _company(db_session)
    db_session.add(ValueupScore(corp_code="00126380", as_of="2026-07-13"))
    db_session.commit()

    seen: dict[str, object] = {}
    monkeypatch.setattr(refresh_service, "ingest_valueup_plans",
                        lambda codes, a, b: type("I", (), {
                            "ingested": 0, "succeeded": list(codes),
                            "failed": [], "degraded": []})())
    monkeypatch.setattr(refresh_service.gap_engine, "run",
                        lambda as_of, codes, **k: seen.__setitem__("as_of", as_of)
                        or type("R", (), {"complete": True})())
    monkeypatch.setattr(refresh_service.opacity_engine, "run",
                        lambda *a, **k: type("R", (), {"complete": True})())

    r = refresh_service.refresh_company("00126380")
    assert seen["as_of"] == "2026-07-13"  # 오늘이 아니라 기존 세대
    assert r.as_of == "2026-07-13"


def test_opens_first_generation_when_no_scores_exist(db_session, session_factory, monkeypatch):
    """스코어가 하나도 없으면(초기 상태) 오늘로 첫 세대를 연다 — 섞일 세대가 없으므로 안전."""
    import app.db as db_module

    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    _company(db_session)
    monkeypatch.setattr(refresh_service, "ingest_valueup_plans",
                        lambda codes, a, b: type("I", (), {
                            "ingested": 0, "succeeded": list(codes),
                            "failed": [], "degraded": []})())
    monkeypatch.setattr(refresh_service.gap_engine, "run",
                        lambda *a, **k: type("R", (), {"complete": True})())
    monkeypatch.setattr(refresh_service.opacity_engine, "run",
                        lambda *a, **k: type("R", (), {"complete": True})())

    from datetime import date as _date
    assert refresh_service.refresh_company("00126380").as_of == _date.today().isoformat()


def test_rcept_no_is_persisted_and_not_erased_by_null(db_session):
    """rcept_no는 저장되고, 이후 재파싱이 null로 덮어쓰지 않는다(신원 ≠ 파싱 산물)."""
    _company(db_session)
    upsert_valueup_plan(db_session, {
        "corp_code": "00126380", "disclosure_date": "2024-11-27",
        "raw_text": "원문", "rcept_no": "20241127000123", "target_roe": 10.0,
    })
    db_session.flush()
    obj = db_session.query(ValueupPlan).one()
    assert obj.rcept_no == "20241127000123"

    # 재파싱: 목표는 null로 정정될 수 있어야 하지만(오탐 제거), 출처 신원은 유지된다
    upsert_valueup_plan(db_session, {
        "corp_code": "00126380", "disclosure_date": "2024-11-27",
        "raw_text": "원문", "rcept_no": None, "target_roe": None,
    })
    db_session.flush()
    obj = db_session.query(ValueupPlan).one()
    assert obj.target_roe is None  # 목표는 전체 교체(정정 가능)
    assert obj.rcept_no == "20241127000123"  # 신원은 유지
