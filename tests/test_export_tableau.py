"""Story 3.5 — Tableau CSV export 검증 (SQLite in-memory).

핵심 계약 3종: ① 단일 as_of 수렴 ② null → 빈 셀(0 세탁 금지) ③ 빈 스코어면
빈 CSV 대신 명시적 에러. + look-ahead 부분 차단 규칙이 export에도 동일 적용.
"""

from __future__ import annotations

import csv

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.export.tableau import NoScoreDataError, export_all
from app.models import Base, Company, MacroIndicator, MnaScore, ValueupScore
from app.sql_views import CREATE_VALUATION_METRICS

AS_OF_OLD = "2026-07-01"
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


@pytest.fixture()
def session(engine):
    s = sessionmaker(bind=engine, future=True)()
    yield s
    s.close()


def _seed(s: Session) -> None:
    for code, name, market, sector in (
        ("00000001", "알파", "KOSPI", "전자"),
        ("00000002", "베타", "KOSPI", "은행"),
        ("00000003", "감마", "KOSDAQ", "바이오"),
    ):
        s.add(Company(corp_code=code, corp_name=name, market=market, sector=sector))
    s.execute(text(
        "INSERT INTO financials (corp_code, year, quarter, revenue, net_income, equity, "
        "total_assets, total_liabilities, operating_income, dividend_total) VALUES "
        "('00000001', 2025, 3, 1000, 100, 1000, 3000, 1000, 120, 30), "
        # 같은 해(2026) 사업보고서 — look-ahead 배제 대상
        "('00000001', 2026, 4, 9999, 9999, 9999, 9999, 9999, 9999, 9999), "
        # 베타: net_income null → payout_ratio null(뷰 CASE) — null 빈 셀 검증용
        "('00000002', 2025, 3, 500, NULL, 500, 1500, 500, 60, NULL), "
        "('00000003', 2025, 3, 300, 60, 300, 900, 300, 70, 10)"
    ))
    s.execute(text(
        "INSERT INTO prices (corp_code, date, close, volume, trading_value, market_cap) VALUES "
        "('00000001', '2025-12-31', 1000, 1, 1, 800), "
        "('00000002', '2025-12-31', 1000, 1, 1, 400), "
        "('00000003', '2025-12-31', 1000, 1, 1, 600)"
    ))
    # 스코어: 구 as_of 행(섞이면 안 됨) + 최신 as_of 행
    s.add(ValueupScore(corp_code="00000001", as_of=AS_OF_OLD, execution_score=10.0,
                       washing_flag=True, buyback_status="none"))
    s.add(ValueupScore(corp_code="00000001", as_of=AS_OF, execution_score=72.5,
                       achievement_rate=0.0, washing_flag=False, buyback_status="retired"))
    # 감마: execution_score null(엔진이 판단불가로 남긴 케이스)
    s.add(ValueupScore(corp_code="00000003", as_of=AS_OF, execution_score=None,
                       washing_flag=None, buyback_status=None))
    s.add(MnaScore(corp_code="00000001", as_of=AS_OF, mna_target_score=71.0,
                   valuation_score=0.89, population_basis="sector"))
    s.add(MacroIndicator(indicator="base_rate", date="2026-07-01", value=2.5, frequency="M"))
    s.add(MacroIndicator(indicator="usd_krw", date="2026-07-01", value=None, frequency="D"))
    s.commit()


def _read(path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def test_export_writes_five_views_with_single_as_of(session, tmp_path):
    _seed(session)
    counts = export_all(session, tmp_path)
    assert set(counts) == {
        "valueup_scores", "sector_valuation_map", "roe_pbr_scatter",
        "dividend_buyback", "macro_layer",
    }
    # 단일 as_of: 최신(AS_OF)만, 구 as_of 행 미혼입
    vs = _read(tmp_path / "valueup_scores.csv")
    assert {r["as_of"] for r in vs} == {AS_OF}
    alpha = next(r for r in vs if r["corp_code"] == "00000001")
    assert alpha["execution_score"] == "72.5"  # 구 as_of의 10.0이 아님
    assert alpha["washing_flag"] == "false"  # bool 소문자 통일


def test_null_stays_empty_cell_not_zero(session, tmp_path):
    _seed(session)
    export_all(session, tmp_path)
    vs = _read(tmp_path / "valueup_scores.csv")
    gamma = next(r for r in vs if r["corp_code"] == "00000003")
    assert gamma["execution_score"] == ""  # null → 빈 셀(0 아님)
    assert gamma["washing_flag"] == ""
    # 정상값 0은 보존(0 falsy 세탁 금지 — 3.4 High 회귀)
    alpha = next(r for r in vs if r["corp_code"] == "00000001")
    assert alpha["achievement_rate"] == "0.0"
    # payout_ratio null(net_income null) → 빈 셀
    db = _read(tmp_path / "dividend_buyback.csv")
    beta = next(r for r in db if r["corp_code"] == "00000002")
    assert beta["payout_ratio"] == ""
    assert beta["dividend_total"] == ""


def test_lookahead_partial_block_applies(session, tmp_path):
    _seed(session)
    export_all(session, tmp_path)
    scatter = _read(tmp_path / "roe_pbr_scatter.csv")
    alpha = next(r for r in scatter if r["corp_code"] == "00000001")
    # 같은 해(2026) 사업보고서(quarter=4)가 아니라 2025Q3이 최신으로 선택돼야 함
    assert (alpha["metrics_year"], alpha["metrics_quarter"]) == ("2025", "3")
    db = _read(tmp_path / "dividend_buyback.csv")
    assert not any(r["corp_code"] == "00000001" and r["year"] == "2026" for r in db)


def test_mna_absence_exposed_not_hidden(session, tmp_path):
    """mna_score 없는 종목(은행 등)도 업종맵에 남고 스코어만 빈 셀 — 조인 세탁 금지."""
    _seed(session)
    export_all(session, tmp_path)
    smap = _read(tmp_path / "sector_valuation_map.csv")
    beta = next(r for r in smap if r["corp_code"] == "00000002")
    assert beta["mna_target_score"] == ""
    assert beta["sector"] == "은행"


def test_empty_scores_raise_instead_of_empty_csv(session, tmp_path):
    with pytest.raises(NoScoreDataError):
        export_all(session, tmp_path)
    assert not list(tmp_path.iterdir())  # 파일을 하나도 쓰지 않음


def test_macro_layer_full_series(session, tmp_path):
    _seed(session)
    export_all(session, tmp_path)
    macro = _read(tmp_path / "macro_layer.csv")
    assert len(macro) == 2
    usd = next(r for r in macro if r["indicator"] == "usd_krw")
    assert usd["value"] == ""  # 매크로 결측도 빈 셀
