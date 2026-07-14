"""Story 2.6 — 다중조건 스크리닝 API 검증 (SQLite in-memory + TestClient)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Company, MnaScore, ValueupScore
from app.sql_views import CREATE_VALUATION_METRICS

AS_OF = "2026-07-13"


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:", future=True,
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    with eng.connect() as conn:  # roe/pbr·지표 필터가 뷰를 읽음(3.3 리뷰 반영)
        conn.execute(text(CREATE_VALUATION_METRICS))
        conn.commit()
    return eng


def _seed(s: Session) -> None:
    for code, name, market, sector in (
        ("00000001", "워싱저평가", "KOSPI", "26100"),  # 워싱 의심 + M&A 매력
        ("00000002", "이행양호", "KOSPI", "26200"),    # 실행점수 높음, M&A 매력 낮음
        ("00000003", "밸류업만", "KOSDAQ", "47000"),   # valueup_score만 있음
        ("00000004", "엠앤에이만", "KOSPI", "64110"),  # mna_score만 있음
        ("00000005", "스코어없음", "KOSPI", "10000"),  # 두 스코어 다 없음 → 제외
    ):
        s.add(Company(corp_code=code, corp_name=name, market=market, sector=sector))
    s.add(ValueupScore(
        corp_code="00000001", as_of=AS_OF,
        execution_score=20.0, washing_flag=True,
        buyback_executed=True, buyback_status="purchased_only",
    ))
    s.add(MnaScore(
        corp_code="00000001", as_of=AS_OF,
        mna_target_score=80.0, population_basis="sector:26",
    ))
    s.add(ValueupScore(
        corp_code="00000002", as_of=AS_OF,
        execution_score=95.0, washing_flag=False,
        buyback_executed=False, buyback_status="planned",
    ))
    s.add(MnaScore(
        corp_code="00000002", as_of=AS_OF,
        mna_target_score=30.0, population_basis="sector:26",
    ))
    s.add(ValueupScore(  # buyback_executed=null(판단 불가)
        corp_code="00000003", as_of=AS_OF,
        execution_score=50.0, washing_flag=None,
        buyback_executed=None, buyback_status="unknown",
    ))
    s.add(MnaScore(
        corp_code="00000004", as_of=AS_OF,
        mna_target_score=60.0, population_basis="market_fallback",
    ))
    s.commit()
    # 지표·시총(3.3 리뷰 반영): 00000001=고ROE(20%)·저PBR·저부채(50%), 00000002=저ROE(5%)·
    # 고PBR·고부채(200%). 00000003/4는 지표 없음(roe/pbr null — 범위 필터 불통과 검증용).
    # ev_ebitda = (market_cap + total_debt - cash) / operating_income:
    #   corp1 = (1000+500-100)/220 = 6.36 / corp2 = (5000+2000-100)/60 = 115.0
    s.execute(text(
        "INSERT INTO financials (corp_code, year, quarter, revenue, net_income, equity, "
        "total_assets, total_liabilities, operating_income, total_debt, cash) VALUES "
        "('00000001', 2025, 3, 1000, 200, 1000, 3000, 500, 220, 500, 100), "
        "('00000002', 2025, 3, 1000, 50, 1000, 3000, 2000, 60, 2000, 100)"
    ))
    s.execute(text(
        "INSERT INTO prices (corp_code, date, close, volume, trading_value, market_cap) VALUES "
        "('00000001', '2026-07-01', 1000, 100, 100000, 1000), "   # PBR=1.0, 시총 1000
        "('00000002', '2026-07-01', 1000, 100, 100000, 5000)"     # PBR=5.0, 시총 5000
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


def test_outer_join_and_universe(client) -> None:
    """AC1: outer join 정직 노출 — 한쪽만 있으면 그쪽만, 둘 다 없으면 제외."""
    r = client.get("/screening")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "total", "page", "size"}
    assert body["total"] == 4  # 00000005(스코어 없음) 제외
    by_code = {i["corp_code"]: i for i in body["items"]}
    assert "00000005" not in by_code
    # valueup만 있는 종목: mna 필드 null + has_* 플래그로 미실행 식별
    assert by_code["00000003"]["execution_score"] == 50.0
    assert by_code["00000003"]["mna_target_score"] is None
    assert by_code["00000003"]["has_valueup_score"] is True
    assert by_code["00000003"]["has_mna_score"] is False
    # mna만 있는 종목: valueup 필드 null
    assert by_code["00000004"]["mna_target_score"] == 60.0
    assert by_code["00000004"]["execution_score"] is None
    assert by_code["00000004"]["washing_flag"] is None
    assert by_code["00000004"]["has_valueup_score"] is False
    assert by_code["00000004"]["has_mna_score"] is True


def test_range_filters_and_combination(client) -> None:
    """AC2: 범위 필터 AND 조합 + null은 범위에 매칭되지 않음."""
    # 실행점수 낮고(워싱 방향) M&A 매력 높은 종목
    r = client.get("/screening", params={
        "max_execution_score": 40, "min_mna_score": 70,
    })
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000001"]
    # min_mna_score=0: mna null(00000003)은 매칭 안 됨
    r2 = client.get("/screening", params={"min_mna_score": 0})
    codes = {i["corp_code"] for i in r2.json()["items"]}
    assert codes == {"00000001", "00000002", "00000004"}


def test_washing_only_and_buyback_filters(client) -> None:
    """AC2: washing_only + buyback_executed(true/false 모두 null 미포함)."""
    r = client.get("/screening", params={"washing_only": True})
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000001"]
    r_true = client.get("/screening", params={"buyback_executed": True})
    assert [i["corp_code"] for i in r_true.json()["items"]] == ["00000001"]
    r_false = client.get("/screening", params={"buyback_executed": False})
    # null(00000003)은 false에도 포함되지 않는다(판단 불가 세탁 금지)
    assert [i["corp_code"] for i in r_false.json()["items"]] == ["00000002"]


def test_sort_whitelist_and_null_last(client) -> None:
    """AC3: field/-field 규약 + null last + 화이트리스트 밖 400 {detail,code}."""
    r = client.get("/screening", params={"sort": "-mna_target_score"})
    codes = [i["corp_code"] for i in r.json()["items"]]
    # 80 → 60 → 30 → null(00000003) last
    assert codes == ["00000001", "00000004", "00000002", "00000003"]
    r2 = client.get("/screening", params={"sort": "execution_score"})
    codes2 = [i["corp_code"] for i in r2.json()["items"]]
    # 20 → 50 → 95 → null(00000004) last
    assert codes2 == ["00000001", "00000003", "00000002", "00000004"]
    r3 = client.get("/screening", params={"sort": "corp_name; DROP TABLE"})
    assert r3.status_code == 400
    assert set(r3.json()) == {"detail", "code"}
    assert r3.json()["code"] == "INVALID_SORT"


def test_corp_code_filter(client) -> None:
    """[3.4] 상세화면 단건 조회 — corp_code 정확일치 필터."""
    r = client.get("/screening", params={"corp_code": "00000001"})
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["corp_code"] == "00000001"
    r2 = client.get("/screening", params={"corp_code": "00000099"})
    assert r2.json()["total"] == 0  # 존재하지 않는 종목 → 빈 결과(404 아님)


def test_market_sector_blank_rejected_and_pagination(client) -> None:
    """AC2/4: market/sector 필터 + 빈 문자열 422 + 페이지네이션."""
    r = client.get("/screening", params={"market": "KOSDAQ"})
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000003"]
    r2 = client.get("/screening", params={"sector": "26"})
    assert {i["corp_code"] for i in r2.json()["items"]} == {"00000001", "00000002"}
    assert client.get("/screening?market=").status_code == 422
    assert client.get("/screening?sector=").status_code == 422
    r3 = client.get("/screening", params={"page": 2, "size": 3})
    assert r3.json()["total"] == 4 and len(r3.json()["items"]) == 1


def test_roe_pbr_in_response(client) -> None:
    """[3.3 리뷰 High] AC3 핵심지표 — roe·pbr이 응답에 포함되고 지표 없는 종목은 null."""
    r = client.get("/screening")
    by_code = {i["corp_code"]: i for i in r.json()["items"]}
    assert by_code["00000001"]["roe"] == pytest.approx(20.0)
    assert by_code["00000001"]["pbr"] == pytest.approx(1.0)
    assert by_code["00000002"]["roe"] == pytest.approx(5.0)
    assert by_code["00000003"]["roe"] is None  # 지표 없음 → null(0 아님)
    assert by_code["00000003"]["pbr"] is None


def test_metric_range_filters(client) -> None:
    """[3.3 리뷰 BLOCKER] AC2 지표 범위 필터 — null 지표는 어느 범위에도 매칭 안 됨."""
    # min_roe=10: 00000001(20%)만. 00000003/4(지표 null)는 제외
    r = client.get("/screening", params={"min_roe": 10})
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000001"]
    # max_pbr=2: 00000001(1.0)만
    r2 = client.get("/screening", params={"max_pbr": 2})
    assert [i["corp_code"] for i in r2.json()["items"]] == ["00000001"]
    # AND 조합: min_roe=10 & max_pbr=0.5 → 0건
    r3 = client.get("/screening", params={"min_roe": 10, "max_pbr": 0.5})
    assert r3.json()["total"] == 0
    # 스코어 필터와의 조합도 동작
    r4 = client.get("/screening", params={"min_roe": 1, "max_execution_score": 50})
    assert [i["corp_code"] for i in r4.json()["items"]] == ["00000001"]


def test_ev_ebitda_and_debt_ratio_filters(client) -> None:
    """[재리뷰 #7] 남은 지표 필터 2종 — max_ev_ebitda·max_debt_ratio."""
    # corp1 ev_ebitda=6.36 / corp2=115.0
    r = client.get("/screening", params={"max_ev_ebitda": 10})
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000001"]
    # corp1 debt_ratio=50% / corp2=200%
    r2 = client.get("/screening", params={"max_debt_ratio": 100})
    assert [i["corp_code"] for i in r2.json()["items"]] == ["00000001"]
    # 지표 없는 종목(00000003/4)은 불통과 확인(총 1건)
    assert r2.json()["total"] == 1


def test_filtered_count_and_pagination(client) -> None:
    """[재리뷰 #7] 지표 필터 적용 상태의 total·페이지네이션 정합(2단계 IN 방식 검증)."""
    r = client.get("/screening", params={"min_roe": 1, "page": 2, "size": 1})
    body = r.json()
    assert body["total"] == 2  # roe 있는 corp1(20%)·corp2(5%)
    assert len(body["items"]) == 1  # 2페이지 1건
    # 1·2페이지 합집합 = 두 종목 전부(중복·누락 없음)
    r1 = client.get("/screening", params={"min_roe": 1, "page": 1, "size": 1})
    codes = {r1.json()["items"][0]["corp_code"], body["items"][0]["corp_code"]}
    assert codes == {"00000001", "00000002"}


def test_metric_and_market_cap_combined(client) -> None:
    """[재리뷰 #7] 지표 필터 × 시총 필터 동시 적용(두 IN 조건 AND)."""
    # min_roe=1(corp1·2 통과) & max_market_cap=2000(corp1만) → corp1
    r = client.get("/screening", params={"min_roe": 1, "max_market_cap": 2000})
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000001"]
    # min_roe=10(corp1만) & min_market_cap=2000(corp2만) → 0건(교집합 공집합)
    r2 = client.get("/screening", params={"min_roe": 10, "min_market_cap": 2000})
    assert r2.json()["total"] == 0


def test_market_cap_boundary_inclusive(client) -> None:
    """[재리뷰 #2] 백엔드 비교는 포함(>=,<=) — 경계 배타는 프론트 버킷(-1)이 담당.

    시총 정확히 1000(corp1): min=1000 포함, max=1000 포함, max=999 불포함.
    """
    assert "00000001" in {i["corp_code"] for i in client.get(
        "/screening", params={"min_market_cap": 1000}).json()["items"]}
    assert "00000001" in {i["corp_code"] for i in client.get(
        "/screening", params={"max_market_cap": 1000}).json()["items"]}
    assert "00000001" not in {i["corp_code"] for i in client.get(
        "/screening", params={"max_market_cap": 999}).json()["items"]}


def test_market_cap_filter(client) -> None:
    """[3.3 리뷰 BLOCKER] AC2 시총구간 — prices 최신 시총 기준, 시총 없는 종목 불통과."""
    r = client.get("/screening", params={"min_market_cap": 2000})
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000002"]
    r2 = client.get("/screening", params={"max_market_cap": 2000})
    assert [i["corp_code"] for i in r2.json()["items"]] == ["00000001"]
    # 시총 데이터 없는 00000003/4는 어느 구간에도 안 걸림
    r3 = client.get("/screening", params={"min_market_cap": 0})
    assert {i["corp_code"] for i in r3.json()["items"]} == {"00000001", "00000002"}


def test_empty_scores_returns_empty_envelope(engine, monkeypatch) -> None:
    """AC4: 두 스코어 모두 미적재 → 빈 봉투(500 아님)."""
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    r = TestClient(fastapi_app).get("/screening")
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0, "page": 1, "size": 20}


def test_invalid_sort_rejected_when_scores_empty(engine, monkeypatch) -> None:
    """[GPT 리뷰 Med] 스코어 미적재여도 잘못된 sort는 400 — 데이터 유무로 계약이 갈리면 안 됨."""
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    r = TestClient(fastapi_app).get("/screening", params={"sort": "drop_table"})
    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_SORT"


def test_blank_sort_rejected(client) -> None:
    """[GPT 리뷰 Low] 빈 sort는 기본 정렬로 조용히 대체되지 않고 400(생략과 빈 입력 구분)."""
    r = client.get("/screening?sort=")
    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_SORT"
    # `-` 단독도 필드 없음 → 400
    assert client.get("/screening", params={"sort": "-"}).status_code == 400


def test_internal_validation_error_not_mislabeled_as_sort(engine, monkeypatch) -> None:
    """[GPT 리뷰 Med] 내부 데이터 오류(pydantic ValidationError)는 400 INVALID_SORT로
    세탁되지 않고 500으로 드러난다."""
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app
    from app.repositories import screening as repo

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    # repo가 오염된 행(corp_code=None)을 반환하는 상황을 강제
    monkeypatch.setattr(
        repo, "list_screening",
        lambda *a, **k: ([{"corp_code": None, "as_of": AS_OF}], 1),
    )
    client = TestClient(fastapi_app, raise_server_exceptions=False)
    r = client.get("/screening")
    assert r.status_code == 500  # 400 INVALID_SORT 아님


def test_latest_as_of_across_both_tables(engine, monkeypatch) -> None:
    """[GPT 리뷰 Low] 기본 as_of가 두 테이블 latest 중 max로 선택되는지 교차 검증."""
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        s.add(Company(corp_code="00000001", corp_name="옛밸류업", market="KOSPI"))
        s.add(Company(corp_code="00000002", corp_name="새엠앤에이", market="KOSPI"))
        s.add(ValueupScore(corp_code="00000001", as_of="2026-07-12", execution_score=10.0))
        s.add(MnaScore(corp_code="00000002", as_of="2026-07-13", mna_target_score=50.0))
        s.commit()
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    body = TestClient(fastapi_app).get("/screening").json()
    # max("2026-07-12","2026-07-13")="2026-07-13" — mna 쪽만 조인됨
    assert body["total"] == 1
    item = body["items"][0]
    assert item["corp_code"] == "00000002"
    assert item["as_of"] == "2026-07-13"
    assert item["execution_score"] is None and item["has_valueup_score"] is False


def test_parity_blank_filters_valueup_metrics(client) -> None:
    """AC6[편승]: valueup·metrics 라우터도 빈 필터 422 + 거대 page 422."""
    assert client.get("/valueup/gap-analysis?market=").status_code == 422
    assert client.get("/metrics?market=").status_code == 422
    assert client.get("/metrics?sector=").status_code == 422
    huge = "100000000000000000000"
    assert client.get("/valueup/gap-analysis", params={"page": huge}).status_code == 422
    assert client.get("/metrics", params={"page": huge}).status_code == 422
