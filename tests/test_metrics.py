"""Story 1.7 — valuation_metrics SQL VIEW 계산 + /metrics API 검증."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Company, Financial, Price
from app.sql_views import CREATE_VALUATION_METRICS


@pytest.fixture()
def engine():
    # StaticPool + check_same_thread=False: in-memory DB를 스레드 간 공유(TestClient 워커 스레드 대응)
    eng = create_engine(
        "sqlite:///:memory:", future=True,
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.execute(text(CREATE_VALUATION_METRICS))  # 뷰 생성(마이그레이션과 동일 SQL)
    return eng


def _seed(session: Session) -> None:
    session.add(Company(corp_code="00000001", stock_code="000001",
                        corp_name="테스트", market="KOSPI", sector="반도체"))
    # 2023: 순이익 100, 자본 1000, 자산 2000, 부채 1000, 매출 500,
    #       영업이익 120, 감가 30, 현금 200, 차입금 400, 배당 20
    session.add(Financial(corp_code="00000001", year=2023, quarter=4,
        revenue=500, net_income=100, operating_income=120, depreciation=30,
        equity=1000, total_assets=2000, total_liabilities=1000, cash=200,
        total_debt=400, dividend_total=20))
    # 2024: 매출 600, 순이익 150 (YoY 매출 +20%, 순이익 +50%)
    session.add(Financial(corp_code="00000001", year=2024, quarter=4,
        revenue=600, net_income=150, operating_income=180, depreciation=30,
        equity=1200, total_assets=2200, total_liabilities=1000, cash=250,
        total_debt=400, dividend_total=30))
    # 최신 시총 3000
    session.add(Price(corp_code="00000001", date="2024-12-30", close=100,
                      market_cap=3000, volume=10, trading_value=1000))
    session.commit()


def test_view_computes_metrics(engine) -> None:
    """AC2/AC3/AC4: 뷰가 ROE·PBR·EV/EBITDA·YoY를 정확히 계산."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
        rows = s.execute(text(
            "SELECT * FROM valuation_metrics WHERE year=2024")).mappings().one()
    # ROE = 150/1200*100 = 12.5
    assert rows["roe"] == 12.5
    # PBR = 3000/1200 = 2.5
    assert rows["pbr"] == 2.5
    # PER = 3000/150 = 20
    assert rows["per"] == 20.0
    # EV/EBITDA = (3000 + 400 - 250)/(180+30) = 3150/210 = 15
    assert rows["ev_ebitda"] == 15.0
    # net_cash = 250-400 = -150
    assert rows["net_cash"] == -150
    # YoY 매출 = (600-500)/500*100 = 20, 순이익 = (150-100)/100*100 = 50
    assert rows["yoy_revenue_growth"] == 20.0
    assert rows["yoy_income_growth"] == 50.0


def test_view_yoy_same_quarter(engine) -> None:
    """리뷰 패치: YoY는 직전 '행'이 아니라 전년 '동분기' 대비여야 한다.

    분기 데이터가 섞여도 window(PARTITION BY corp_code, quarter ORDER BY year)로
    2024 Q3은 2023 Q3(300) 대비 +20%, 2024 Q4는 2023 Q4(500) 대비 +20%.
    (구 window였다면 2024 Q3이 직전행 2023 Q4 대비 QoQ로 잘못 계산됨)
    """
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        s.add(Company(corp_code="00000009", corp_name="분기테스트"))
        for y, q, rev in [(2023, 3, 300), (2023, 4, 500), (2024, 3, 360), (2024, 4, 600)]:
            s.add(Financial(corp_code="00000009", year=y, quarter=q,
                            revenue=rev, net_income=10, equity=1000, total_assets=2000))
        s.commit()
        rows = {(r["year"], r["quarter"]): r["yoy_revenue_growth"] for r in s.execute(text(
            "SELECT year, quarter, yoy_revenue_growth FROM valuation_metrics "
            "WHERE corp_code='00000009'")).mappings().all()}
    assert rows[(2024, 3)] == 20.0  # vs 2023 Q3, not QoQ vs 2023 Q4
    assert rows[(2024, 4)] == 20.0  # vs 2023 Q4
    assert rows[(2023, 3)] is None  # 전년 동분기 없음
    assert rows[(2023, 4)] is None


def test_view_null_safe(engine) -> None:
    """NFR2: 0 나눗셈은 NULLIF로 방어(null)."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        s.add(Company(corp_code="00000002", corp_name="영값"))
        s.add(Financial(corp_code="00000002", year=2024, quarter=4,
              revenue=0, net_income=0, equity=0, total_assets=0))
        s.commit()
        row = s.execute(text(
            "SELECT roe, pbr FROM valuation_metrics WHERE corp_code='00000002'"
        )).mappings().one()
    assert row["roe"] is None  # equity 0 → NULLIF → null
    assert row["pbr"] is None


def test_metrics_api(engine, monkeypatch) -> None:
    """AC6: /metrics API가 봉투로 반환하고 필터가 동작."""
    from fastapi.testclient import TestClient

    import app.db as db_module

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    # get_db가 위 SessionLocal을 쓰도록
    from app.main import app as fastapi_app
    client = TestClient(fastapi_app)

    r = client.get("/metrics", params={"min_roe": 10})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "total", "page", "size"}
    assert body["total"] >= 1
    assert all(i["roe"] >= 10 for i in body["items"] if i["roe"] is not None)


def test_metrics_sort_whitelist_and_payout_filter(engine, monkeypatch) -> None:
    """GPT 리뷰 patch: sort 화이트리스트(인젝션 차단) + min_payout_ratio 필터."""
    from fastapi.testclient import TestClient

    import app.db as db_module

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)  # 00000001: pbr 2023=3.0/2024=2.5, payout_ratio 20
        # 저PBR·고배당 종목 추가: pbr=2500/5000=0.5, payout=250/500*100=50
        s.add(Company(corp_code="00000003", corp_name="저PBR고배당",
                      market="KOSPI", sector="반도체"))
        s.add(Financial(corp_code="00000003", year=2024, quarter=4,
              revenue=1000, net_income=500, operating_income=600, depreciation=0,
              equity=5000, total_assets=8000, total_liabilities=1000,
              cash=100, total_debt=200, dividend_total=250))
        s.add(Price(corp_code="00000003", date="2024-12-30", close=100,
                    market_cap=2500, volume=10, trading_value=1000))
        s.commit()
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    from app.main import app as fastapi_app
    client = TestClient(fastapi_app)

    # 오름차순: 최저 PBR(00000003, 0.5)이 먼저
    r = client.get("/metrics", params={"sort": "pbr"})
    assert r.status_code == 200
    pbrs = [i["pbr"] for i in r.json()["items"]]
    assert pbrs == sorted(pbrs)
    assert r.json()["items"][0]["corp_code"] == "00000003"

    # 내림차순: 최고 PBR(00000001 2023행, 3.0)이 먼저
    r = client.get("/metrics", params={"sort": "-pbr"})
    assert r.json()["items"][0]["corp_code"] == "00000001"
    assert r.json()["items"][0]["pbr"] == 3.0

    # 화이트리스트 밖 필드 → 400. raw SQL 삽입 시도도 여기서 차단.
    assert client.get("/metrics", params={"sort": "bogus"}).status_code == 400
    assert client.get(
        "/metrics", params={"sort": "pbr; DROP TABLE prices"}).status_code == 400

    # min_payout_ratio 필터: payout_ratio>=30 → 00000003만(50), 00000001(20) 제외
    r = client.get("/metrics", params={"min_payout_ratio": 30})
    assert r.status_code == 200
    assert {i["corp_code"] for i in r.json()["items"]} == {"00000003"}


def _seed_capital_impaired(s: Session) -> None:
    """자본잠식·적자 기업: equity<0, net_income<0."""
    s.add(Company(corp_code="00000004", corp_name="자본잠식"))
    s.add(Financial(corp_code="00000004", year=2024, quarter=4,
          revenue=50, net_income=-10, operating_income=-5, depreciation=0,
          equity=-100, total_assets=100, total_liabilities=200,
          cash=10, total_debt=50, dividend_total=0))
    s.add(Price(corp_code="00000004", date="2024-12-30", close=100,
                market_cap=1000, volume=10, trading_value=1000))


def test_view_negative_denominators_null(engine) -> None:
    """GPT 교차검증 patch: 음수/0 분모(자본잠식·적자) 지표는 NULL(스크리너 오염 방지)."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed_capital_impaired(s)
        s.commit()
        row = s.execute(text(
            "SELECT roe, pbr, per, debt_ratio, payout_ratio, ev_ebitda "
            "FROM valuation_metrics WHERE corp_code='00000004'")).mappings().one()
    # 구버전(NULLIF만)이면 roe=+10·pbr=-10 등 유효값처럼 나옴 → 전부 NULL이어야 함
    assert row["roe"] is None       # equity<0
    assert row["pbr"] is None
    assert row["per"] is None        # net_income<0
    assert row["debt_ratio"] is None
    assert row["payout_ratio"] is None
    assert row["ev_ebitda"] is None  # EBITDA<0


def test_min_roe_filter_excludes_capital_impaired(engine, monkeypatch) -> None:
    """GPT 교차검증 patch: min_roe 필터가 자본잠식 기업을 통과시키지 않는다."""
    from fastapi.testclient import TestClient

    import app.db as db_module

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)  # 정상 기업 00000001 (roe 10~12.5)
        _seed_capital_impaired(s)  # roe NULL이어야 함
        s.commit()
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    from app.main import app as fastapi_app
    client = TestClient(fastapi_app)
    r = client.get("/metrics", params={"min_roe": 10})
    assert r.status_code == 200
    codes = {i["corp_code"] for i in r.json()["items"]}
    assert "00000004" not in codes  # 자본잠식 제외(roe NULL)
    assert "00000001" in codes      # 정상 우량 포함


def test_nan_inf_filter_rejected(engine, monkeypatch) -> None:
    """GPT 교차검증 patch: NaN/inf 필터값은 422로 거부(DB별 비교 규칙 갈림 방지)."""
    from fastapi.testclient import TestClient

    import app.db as db_module

    Session_ = sessionmaker(bind=engine)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    from app.main import app as fastapi_app
    client = TestClient(fastapi_app)
    assert client.get("/metrics", params={"max_pbr": "nan"}).status_code == 422
    assert client.get("/metrics", params={"min_roe": "inf"}).status_code == 422
