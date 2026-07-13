"""Story 2.5 — M&A 타겟 랭킹 API 검증 (SQLite in-memory + TestClient)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Company, MnaScore


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:", future=True,
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    return eng


def _seed(s: Session) -> None:
    for code, name, market, sector in (
        ("00000001", "저평가매력", "KOSPI", "26100"),   # 반도체
        ("00000002", "보통", "KOSPI", "26200"),
        ("00000003", "산출불가금융", "KOSPI", "64110"),  # 금융(엄격 null)
        ("00000004", "코스닥유통", "KOSDAQ", "47000"),
        ("00000005", "과거스냅샷", "KOSPI", None),
    ):
        s.add(Company(corp_code=code, corp_name=name, market=market, sector=sector))
    s.add(MnaScore(
        corp_code="00000001", as_of="2026-07-13",
        mna_target_score=82.5, valuation_score=0.9, capacity_score=0.8,
        ownership_score=0.7, macro_score=0.6, population_basis="sector:26",
    ))
    s.add(MnaScore(
        corp_code="00000002", as_of="2026-07-13",
        mna_target_score=41.0, valuation_score=0.4, capacity_score=0.4,
        ownership_score=0.5, macro_score=0.6, population_basis="sector:26",
    ))
    s.add(MnaScore(  # 엄격 null(요소 산출 불가 → 총점 null)
        corp_code="00000003", as_of="2026-07-13",
        mna_target_score=None, valuation_score=None, capacity_score=None,
        ownership_score=0.9, macro_score=0.6, population_basis=None,
    ))
    s.add(MnaScore(
        corp_code="00000004", as_of="2026-07-13",
        mna_target_score=60.0, valuation_score=0.6, capacity_score=0.6,
        ownership_score=0.6, macro_score=0.6, population_basis="market_fallback",
    ))
    s.add(MnaScore(  # 다른 as_of(과거) — 최신 기본 조회에서 제외돼야
        corp_code="00000005", as_of="2025-12-31",
        mna_target_score=99.0, valuation_score=1.0, capacity_score=1.0,
        ownership_score=1.0, macro_score=1.0, population_basis="market",
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


def test_ranking_envelope_desc_null_last(client) -> None:
    """AC1/2: 봉투 + mna_target_score 내림차순(null last) + 기본 as_of=최신 + 요소별 분해."""
    r = client.get("/mna/ranking")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "total", "page", "size"}
    assert body["total"] == 4  # 최신 as_of만, 과거(00000005) 제외
    codes = [i["corp_code"] for i in body["items"]]
    # 82.5 → 60.0 → 41.0 → null(산출 불가 마지막)
    assert codes == ["00000001", "00000004", "00000002", "00000003"]
    top = body["items"][0]
    # 요소별 분해 + population_basis 노출
    assert top["valuation_score"] == 0.9
    assert top["capacity_score"] == 0.8
    assert top["ownership_score"] == 0.7
    assert top["macro_score"] == 0.6
    assert top["population_basis"] == "sector:26"


def test_null_score_returned_as_null(client) -> None:
    """AC3: 엄격 null — 총점 null은 null 그대로(0점 강제 금지), 산출된 요소는 노출."""
    r = client.get("/mna/ranking")
    last = r.json()["items"][-1]
    assert last["corp_code"] == "00000003"
    assert last["mna_target_score"] is None
    assert last["ownership_score"] == 0.9  # 산출된 요소는 그대로


def test_filters_market_and_sector_prefix(client) -> None:
    """AC2: market 필터 + sector는 KSIC prefix 매칭."""
    r = client.get("/mna/ranking", params={"market": "KOSDAQ"})
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000004"]
    r2 = client.get("/mna/ranking", params={"sector": "26"})  # 26100·26200 모두
    assert [i["corp_code"] for i in r2.json()["items"]] == ["00000001", "00000002"]
    r3 = client.get("/mna/ranking", params={"sector": "26100"})  # 세분류 정확 매칭도 동작
    assert [i["corp_code"] for i in r3.json()["items"]] == ["00000001"]


def test_explicit_as_of_and_pagination(client) -> None:
    """AC2/5: as_of 스냅샷 + 페이지네이션 + 무효 날짜 422."""
    r = client.get("/mna/ranking", params={"as_of": "2025-12-31"})
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000005"]
    r2 = client.get("/mna/ranking", params={"page": 2, "size": 2})
    body = r2.json()
    assert body["total"] == 4 and body["page"] == 2
    assert [i["corp_code"] for i in body["items"]] == ["00000002", "00000003"]
    assert client.get("/mna/ranking", params={"as_of": "2026-02-30"}).status_code == 422
    assert client.get("/mna/ranking", params={"as_of": "garbage"}).status_code == 422


def test_blank_filters_are_rejected(client) -> None:
    """[GPT 리뷰 Med] 빈 문자열 필터는 '필터 없음'으로 확대되지 않고 422."""
    assert client.get("/mna/ranking?market=").status_code == 422
    assert client.get("/mna/ranking?sector=").status_code == 422
    # 빈 sector가 있어도 다른 유효 필터와 함께면 여전히 422(부분 적용 금지)
    assert client.get("/mna/ranking?market=KOSPI&sector=").status_code == 422
    # sector는 숫자 KSIC 코드만(2~5자리)
    assert client.get("/mna/ranking", params={"sector": "abc"}).status_code == 422


def test_validation_error_contract(client) -> None:
    """[GPT 리뷰 Med] 422 본문이 AD-6 에러 계약 {detail, code}를 따른다."""
    r = client.get("/mna/ranking", params={"as_of": "2026-02-30"})
    assert r.status_code == 422
    body = r.json()
    assert set(body) == {"detail", "code"}
    assert body["code"] == "VALIDATION_ERROR"


def test_huge_page_is_rejected(client) -> None:
    """[GPT 리뷰 Med] OFFSET 오버플로(500)로 새지 않도록 page 상한 초과는 422."""
    r = client.get("/mna/ranking", params={"page": "100000000000000000000"})
    assert r.status_code == 422


def test_empty_scores_returns_empty_envelope(engine, monkeypatch) -> None:
    """AC5: 스코어 미적재 → 빈 봉투(500 아님)."""
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    r = TestClient(fastapi_app).get("/mna/ranking")
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0, "page": 1, "size": 20}
