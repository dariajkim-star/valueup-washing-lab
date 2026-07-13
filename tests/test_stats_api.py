"""Story 3.1 — 시장·매크로 통계 API 검증 (SQLite in-memory + TestClient)."""

from __future__ import annotations

import math

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Company, MacroIndicator, ValueupScore
from app.sql_views import CREATE_VALUATION_METRICS

AS_OF = "2026-07-13"


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:", future=True,
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    with eng.connect() as conn:
        conn.execute(text(CREATE_VALUATION_METRICS))
        conn.commit()
    return eng


def _seed_financials(session: Session) -> None:
    """valuation_metrics 뷰가 읽을 원천(financials·prices)을 직접 raw SQL로 시드.

    look-ahead 안전성 검증을 위해 일부는 같은 해 사업보고서(quarter=4)로 넣는다.
    """
    session.execute(text(
        "INSERT INTO financials (corp_code, year, quarter, revenue, net_income, equity, "
        "total_assets, total_liabilities, operating_income) VALUES "
        # KOSPI: 고평가 저ROE 종목(과거 3분기 실적 — as_of 시점 조회 가능)
        "('00000001', 2025, 3, 1000, 50, 1000, 3000, 1000, 60), "
        # KOSPI: 저평가 고ROE 종목
        "('00000002', 2025, 3, 1000, 200, 1000, 3000, 1000, 220), "
        # KOSPI: look-ahead 배제 대상 — 같은 해(2026) 사업보고서(quarter=4)는 제외돼야 함
        "('00000001', 2026, 4, 9999, 9999, 9999, 9999, 9999, 9999), "
        # KOSDAQ 종목
        "('00000003', 2025, 3, 500, 100, 500, 1500, 500, 110)"
    ))
    session.execute(text(
        "INSERT INTO prices (corp_code, date, close, volume, trading_value, market_cap) VALUES "
        "('00000001', '2025-12-31', 1000, 100, 100000, 5000), "
        "('00000002', '2025-12-31', 1000, 100, 100000, 1000), "
        "('00000003', '2025-12-31', 1000, 100, 100000, 1500)"
    ))
    session.commit()


def _seed(s: Session) -> None:
    for code, name, market in (
        ("00000001", "고평가워싱", "KOSPI"),
        ("00000002", "저평가양호", "KOSPI"),
        ("00000003", "코스닥종목", "KOSDAQ"),
        ("00000004", "지표없음", "KOSPI"),  # metrics 없음 — 평균에서 자연 제외
    ):
        s.add(Company(corp_code=code, corp_name=name, market=market))
    s.add(ValueupScore(corp_code="00000001", as_of=AS_OF, washing_flag=True))
    s.add(ValueupScore(corp_code="00000002", as_of=AS_OF, washing_flag=False))
    s.add(ValueupScore(corp_code="00000003", as_of=AS_OF, washing_flag=None))  # 판단 불가
    s.add(MacroIndicator(indicator="base_rate", date="2026-07-01", value=3.5))
    s.add(MacroIndicator(indicator="usd_krw", date="2026-06-01", value=1350.0))
    # bond_3y·leading_index는 의도적으로 미수집 — null 자리 검증
    s.commit()
    _seed_financials(s)


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


def test_market_comparison_avg_and_washing_ratio(client) -> None:
    """AC1/4: null-safe 평균 + washing_ratio(분모=n_judged) + look-ahead 배제."""
    r = client.get("/stats/market-comparison")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "total", "page", "size"}
    assert body["page"] == 1 and body["size"] == body["total"]
    by_market = {i["market"]: i for i in body["items"]}
    kospi = by_market["KOSPI"]
    # KOSPI: 00000001(roe=5%)·00000002(roe=20%) — 2026년 사업보고서(look-ahead)는 배제돼야 함
    assert kospi["n"] == 2
    assert kospi["avg_roe"] == pytest.approx((5.0 + 20.0) / 2)
    # washing: 00000001=True·00000002=False 둘 다 KOSPI에서 판단됨 → n_judged=2, n_washing=1
    assert kospi["n_judged"] == 2 and kospi["n_washing"] == 1
    assert kospi["washing_ratio"] == 0.5
    kosdaq = by_market["KOSDAQ"]
    assert kosdaq["n_judged"] == 0  # washing_flag=None(판단불가)만 있어 분모 0
    assert kosdaq["washing_ratio"] is None


def test_summary_headline_kpi(client) -> None:
    """AC2: 전체 헤드라인 KPI, n_companies(전체) vs n_metrics(지표보유) 분리."""
    r = client.get("/stats/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["n_companies"] == 4  # 4번 종목(지표없음)도 포함
    assert body["n_metrics"] == 3    # 지표 있는 종목만
    assert body["n_judged"] == 2 and body["n_washing"] == 1
    assert body["washing_ratio"] == 0.5


def test_summary_returns_404_when_no_scores(engine, monkeypatch) -> None:
    """AC5: valueup_score 미적재 → 404 {detail,code}(500 아님, GPT 리뷰 Med)."""
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    r = TestClient(fastapi_app).get("/stats/summary")
    assert r.status_code == 404
    body = r.json()
    assert set(body) == {"detail", "code"}
    assert body["code"] == "VALUEUP_SCORE_NOT_FOUND"


def test_explicit_as_of_does_not_bypass_empty_scores(engine, monkeypatch) -> None:
    """[GPT 리뷰 Med] valueup_score가 통째로 비어있으면 as_of를 명시해도 정책이 우회되지
    않는다 — "테이블 전체 미적재"와 "이 특정 as_of엔 없음"을 구분."""
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    client = TestClient(fastapi_app)

    r1 = client.get("/stats/market-comparison", params={"as_of": AS_OF})
    assert r1.json() == {"items": [], "total": 0, "page": 1, "size": 0}

    r2 = client.get("/stats/summary", params={"as_of": AS_OF})
    assert r2.status_code == 404
    assert r2.json()["code"] == "VALUEUP_SCORE_NOT_FOUND"


def test_unknown_market_does_not_break_comparison(client, engine) -> None:
    """[GPT 리뷰 High] market=None(미분류) 종목이 있어도 500·TypeError 없이 동작하고,
    응답은 KOSPI/KOSDAQ로만 한정된다(AC1 계약 — KONEX 등 계약 밖 시장도 새어나가면 안 됨)."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        s.add(Company(corp_code="00000099", corp_name="시장미분류", market=None))
        s.add(ValueupScore(corp_code="00000099", as_of=AS_OF, washing_flag=True))
        s.commit()

    r = client.get("/stats/market-comparison")
    assert r.status_code == 200
    markets = {i["market"] for i in r.json()["items"]}
    assert markets <= {"KOSPI", "KOSDAQ"}


def test_market_comparison_empty_when_no_scores(engine, monkeypatch) -> None:
    """AC5: valueup_score 미적재 → market-comparison은 빈 봉투(500 아님)."""
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    r = TestClient(fastapi_app).get("/stats/market-comparison")
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0, "page": 1, "size": 0}


def test_macro_fixed_four_slots_with_nulls(client) -> None:
    """AC3: 4개 지표 자리 항상 보장, 미수집 지표는 date/value null."""
    r = client.get("/stats/macro")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 4
    by_indicator = {i["indicator"]: i for i in body["items"]}
    assert set(by_indicator) == {"base_rate", "bond_3y", "usd_krw", "leading_index"}
    assert by_indicator["base_rate"]["value"] == 3.5
    assert by_indicator["bond_3y"]["value"] is None
    assert by_indicator["bond_3y"]["date"] is None


def test_macro_independent_as_of_default(engine, monkeypatch) -> None:
    """AC5: macro의 기본 as_of는 macro_indicator 자체 최신 관측일 — valueup_score와 독립.

    valueup_score가 전혀 없어도(다른 두 엔드포인트는 빈/404) macro는 정상 동작해야 한다.
    """
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        s.add(MacroIndicator(indicator="base_rate", date="2026-05-01", value=3.0))
        s.commit()
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    r = TestClient(fastapi_app).get("/stats/macro")
    assert r.status_code == 200
    by_indicator = {i["indicator"]: i for i in r.json()["items"]}
    assert by_indicator["base_rate"]["value"] == 3.0


def test_macro_empty_returns_four_null_slots(engine, monkeypatch) -> None:
    """AC5: macro_indicator가 완전히 비어있어도(시스템 시계 미사용) 4개 null 자리 반환."""
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    r = TestClient(fastapi_app).get("/stats/macro")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 4
    assert all(i["value"] is None for i in body["items"])


def test_nonfinite_metrics_excluded_from_average(client, engine) -> None:
    """[GPT 리뷰 Med] NaN/Infinity가 섞여도 평균에서 제외되고 500이 나지 않는다."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        s.add(Company(corp_code="00000098", corp_name="비정상값", market="KOSPI"))
        s.commit()
        s.execute(text(
            "INSERT INTO financials (corp_code, year, quarter, revenue, net_income, "
            "equity, total_assets, total_liabilities, operating_income) VALUES "
            "('00000098', 2025, 3, 100, 0, 0, 100, 50, 10)"  # equity=0 → roe는 뷰에서 NULLIF로 null
        ))
        s.commit()

    r = client.get("/stats/market-comparison")
    assert r.status_code == 200  # 500 아님
    kospi = next(i for i in r.json()["items"] if i["market"] == "KOSPI")
    assert kospi["n"] == 3  # 신규 종목 포함(00000001·00000002·00000098)
    assert math.isfinite(kospi["avg_roe"])  # NaN/Inf가 새어나가지 않음


def test_explicit_as_of_and_invalid_date_422(client) -> None:
    """AC5: as_of 명시 조회 + 무효 날짜 422(전역 핸들러, {detail,code})."""
    r = client.get("/stats/market-comparison", params={"as_of": AS_OF})
    assert r.status_code == 200
    r2 = client.get("/stats/summary", params={"as_of": "2026-02-30"})
    assert r2.status_code == 422
    assert set(r2.json()) == {"detail", "code"}
