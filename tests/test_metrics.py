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
    """AC2/AC3/AC4: 뷰가 ROE·PBR·EV/EBIT·YoY를 정확히 계산."""
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
    # EV/EBIT = (3000 + 400 - 250)/180 = 3150/180 = 17.5
    # 감가상각 30이 있어도 분모에 더하지 않는다(2026-08-04 결정, 아래 전용 테스트 참조)
    assert rows["ev_ebit"] == 17.5
    # EBIT마진 = 180/600*100 = 30
    assert rows["ebit_margin"] == 30.0
    # net_cash = 250-400 = -150
    assert rows["net_cash"] == -150
    # YoY 매출 = (600-500)/500*100 = 20, 순이익 = (150-100)/100*100 = 50
    assert rows["yoy_revenue_growth"] == 20.0
    assert rows["yoy_income_growth"] == 50.0


def test_view_ignores_depreciation_even_when_present(engine) -> None:
    """[2026-08-04] 감가상각은 알아도 쓰지 않는다 — 두 회사의 분모가 같아야 한다.

    이전 정의는 COALESCE(depreciation, 0)이라 **공시한 회사만 EBITDA, 나머지는 EBIT**로
    재고 있었다. 백분위는 그 둘을 같은 모집단에서 세우므로 순위가 '감가상각을 공시했다'는
    사실에 가점을 줬다(실측: 58곳 백분위 중앙값 6.4%p 이동, 14곳 10%p 초과, 전부 한 방향).
    수집으로는 못 고친다(결측 표본 30곳 원문에 감가상각 행 0/30) → 분자를 EBIT로 통일.

    이 테스트가 지키는 것은 값이 아니라 **공시 여부가 지표를 움직이지 않는다**는 계약이다.
    """
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        for code, dep in (("00000011", 500), ("00000012", None)):
            s.add(Company(corp_code=code, corp_name=f"감가{code}"))
            s.add(Financial(corp_code=code, year=2024, quarter=4,
                            revenue=600, net_income=150, operating_income=180,
                            depreciation=dep, equity=1200, total_assets=2200,
                            total_liabilities=1000, cash=250, total_debt=400))
            s.add(Price(corp_code=code, date="2024-12-30", close=100,
                        market_cap=3000, volume=10, trading_value=1000))
        s.commit()
        rows = {r["corp_code"]: r for r in s.execute(text(
            "SELECT corp_code, ev_ebit, ebit_margin FROM valuation_metrics "
            "WHERE corp_code IN ('00000011','00000012')")).mappings().all()}
    assert rows["00000011"]["ev_ebit"] == rows["00000012"]["ev_ebit"] == 17.5
    assert rows["00000011"]["ebit_margin"] == rows["00000012"]["ebit_margin"] == 30.0


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
            "SELECT roe, pbr, per, debt_ratio, payout_ratio, ev_ebit "
            "FROM valuation_metrics WHERE corp_code='00000004'")).mappings().one()
    # 구버전(NULLIF만)이면 roe=+10·pbr=-10 등 유효값처럼 나옴 → 전부 NULL이어야 함
    assert row["roe"] is None       # equity<0
    assert row["pbr"] is None
    assert row["per"] is None        # net_income<0
    assert row["debt_ratio"] is None
    assert row["payout_ratio"] is None
    assert row["ev_ebit"] is None  # EBIT<0


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


def test_returns_breakdown_endpoint(engine, monkeypatch) -> None:
    """/metrics/{corp}/returns — 환원율 점프 설명 카드(2026-08-04, Sally).

    구성(배당·CF취득·소각수량·순이익)과 뷰의 총환원율을 연도별로 준다.
    비율은 재계산하지 않고 valuation_metrics 조인 — 정의처는 뷰 하나다.
    """
    from fastapi.testclient import TestClient

    import app.db as db_module

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)  # 2023: 배당 20/순익 100 · 2024: 배당 30/순익 150
        # 2024에 CF 취득 45 추가 → 총환원율 (30+45)/150 = 50.0
        s.execute(text(
            "UPDATE financials SET buyback_amount_krw=45, buyback_retired_amount=0 "
            "WHERE corp_code='00000001' AND year=2024"
        ))
        s.commit()
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    from app.main import app as fastapi_app
    client = TestClient(fastapi_app)

    r = client.get("/metrics/00000001/returns")
    assert r.status_code == 200
    rows = r.json()
    assert [x["year"] for x in rows] == [2023, 2024]
    y24 = rows[1]
    assert y24["dividend_total"] == 30
    assert y24["buyback_amount_krw"] == 45
    assert y24["buyback_retired_qty"] == 0
    assert y24["net_income"] == 150
    assert y24["total_return_ratio"] == 50.0
    # 2023은 CF취득 미상(null) → 뷰 계약대로 총환원율 null(0으로 메우지 않음),
    # payout_ratio는 살아있다(배당은 안다)
    y23 = rows[0]
    assert y23["buyback_amount_krw"] is None
    assert y23["total_return_ratio"] is None
    assert y23["payout_ratio"] == 20.0
    # 없는 종목은 빈 배열(404 아님 — 데이터 없음은 오류가 아니다)
    assert client.get("/metrics/99999999/returns").json() == []


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


def test_view_retired_return_and_retirement_rate(engine) -> None:
    """[0028] 이중 시선 파생 — 소각 기준 환원율·소각률.

    정의를 바꾸지 않는다: total_return_ratio(매입 기준)는 그대로, 소각 기준을 나란히.
    소각률은 이월 소각으로 100%를 넘을 수 있다(캡 없음 — payout_achievement 원칙).
    """
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
        # 2024: 배당 30 · 취득 45 · 소각 27 · 순익 150
        s.execute(text(
            "UPDATE financials SET buyback_amount_krw=45, buyback_retired_krw=27 "
            "WHERE corp_code='00000001' AND year=2024"
        ))
        # 2023: 취득 10 · 소각 15(이월 소각 — 취득보다 크다) · 배당 20 · 순익 100
        s.execute(text(
            "UPDATE financials SET buyback_amount_krw=10, buyback_retired_krw=15 "
            "WHERE corp_code='00000001' AND year=2023"
        ))
        s.commit()
        y24 = s.execute(text(
            "SELECT * FROM valuation_metrics WHERE year=2024")).mappings().one()
        y23 = s.execute(text(
            "SELECT * FROM valuation_metrics WHERE year=2023")).mappings().one()
    # 매입 기준 (30+45)/150=50 · 소각 기준 (30+27)/150=38 · 소각률 27/45=60
    assert y24["total_return_ratio"] == 50.0
    assert y24["retired_return_ratio"] == 38.0
    assert y24["retirement_rate"] == 60.0
    # 이월 소각: 소각률 150%(캡 없음), 소각 기준 (20+15)/100=35
    assert y23["retirement_rate"] == 150.0
    assert y23["retired_return_ratio"] == 35.0


def test_view_retired_metrics_null_contract(engine) -> None:
    """소각액 미상 → 두 파생 다 null(0 세탁 금지) · 취득 0인 해의 소각률 null(0% 아님)."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
        # 2024: 취득은 알고 소각은 미상
        s.execute(text(
            "UPDATE financials SET buyback_amount_krw=45, buyback_retired_krw=NULL "
            "WHERE corp_code='00000001' AND year=2024"
        ))
        # 2023: 취득 0 확정 + 소각 0 확정 → 환원율은 서고 소각률은 분모 없음
        s.execute(text(
            "UPDATE financials SET buyback_amount_krw=0, buyback_retired_krw=0 "
            "WHERE corp_code='00000001' AND year=2023"
        ))
        s.commit()
        y24 = s.execute(text(
            "SELECT * FROM valuation_metrics WHERE year=2024")).mappings().one()
        y23 = s.execute(text(
            "SELECT * FROM valuation_metrics WHERE year=2023")).mappings().one()
    assert y24["retired_return_ratio"] is None
    assert y24["retirement_rate"] is None
    assert y23["retired_return_ratio"] == 20.0  # (20+0)/100 — 배당만
    assert y23["retirement_rate"] is None  # 취득 0 — 분모가 없다(0%로 세탁 금지)
