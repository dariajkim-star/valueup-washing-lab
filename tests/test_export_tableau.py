"""Story 3.5 — Tableau CSV export 검증 (SQLite in-memory).

계약: ① 두 엔진 교집합 as_of(한쪽만 최신이면 공통일 선택/거부) ② null → 빈 셀
+ 정상값 0 보존 ③ 원자적 스냅숏(부분 실패 시 기존 출력 유지) ④ 스키마 강제
(누락 키를 null로 세탁 금지) ⑤ 기간별 자사주 상태(스냅숏 상태 시계열 반복 금지).
"""

from __future__ import annotations

import csv
import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.export import tableau as tableau_mod
from app.export.tableau import ExportSchemaError, NoScoreDataError, export_all
from app.models import Base, Company, MacroIndicator, MnaScore, ValueupScore
from app.repositories.export import latest_common_as_of, period_buyback_status
from app.sql_views import CREATE_VALUATION_METRICS

AS_OF_OLD = "2026-07-01"
AS_OF = "2026-07-13"
AS_OF_NEWER = "2026-07-14"


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
    # sector는 실데이터처럼 DART induty 숫자 코드(문자열) — 타입 추론 이슈 재현용
    for code, name, market, sector in (
        ("00000001", "알파", "KOSPI", "24213"),
        ("00000002", "베타", "KOSPI", "64110"),
        ("00000003", "감마", "KOSDAQ", "21210"),
    ):
        s.add(Company(corp_code=code, corp_name=name, market=market, sector=sector))
    s.execute(text(
        "INSERT INTO financials (corp_code, year, quarter, revenue, net_income, equity, "
        "total_assets, total_liabilities, operating_income, dividend_total, "
        "buyback_amount, buyback_retired_amount) VALUES "
        # 알파 2024: 매입만(purchased_only) / 2025: 소각(retired) — 연도별 상태 상이
        "('00000001', 2024, 3, 900, 90, 900, 2700, 900, 100, 20, 100, NULL), "
        "('00000001', 2025, 3, 1000, 100, 1000, 3000, 1000, 120, 30, NULL, 50), "
        # 같은 해(2026) 사업보고서 — look-ahead 배제 대상
        "('00000001', 2026, 4, 9999, 9999, 9999, 9999, 9999, 9999, 9999, NULL, NULL), "
        # 베타: net_income null → payout_ratio null / 자사주 무관측(null)
        "('00000002', 2025, 3, 500, NULL, 500, 1500, 500, 60, NULL, NULL, NULL), "
        # 감마: 관측 있음+활동 없음(0) → none
        "('00000003', 2025, 3, 300, 60, 300, 900, 300, 70, 10, 0, 0)"
    ))
    s.execute(text(
        "INSERT INTO prices (corp_code, date, close, volume, trading_value, market_cap) VALUES "
        "('00000001', '2025-12-31', 1000, 1, 1, 800), "
        "('00000002', '2025-12-31', 1000, 1, 1, 400), "
        "('00000003', '2025-12-31', 1000, 1, 1, 600)"
    ))
    # 스코어: 구 as_of 행(섞이면 안 됨) + 공통 최신 as_of 행(두 엔진 모두 존재)
    s.add(ValueupScore(corp_code="00000001", as_of=AS_OF_OLD, execution_score=10.0,
                       washing_flag=True, buyback_status="none"))
    s.add(ValueupScore(corp_code="00000001", as_of=AS_OF, execution_score=72.5,
                       achievement_rate=0.0, washing_flag=False, buyback_status="retired"))
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


def _out(tmp_path):
    return tmp_path / "tableau"


def test_export_writes_five_views_manifest_and_single_as_of(session, tmp_path):
    _seed(session)
    out = _out(tmp_path)
    counts = export_all(session, out)
    assert set(counts) == {
        "valueup_scores", "sector_valuation_map", "roe_pbr_scatter",
        "dividend_buyback", "macro_layer",
    }
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["as_of"] == AS_OF
    assert manifest["views"] == counts
    vs = _read(out / "valueup_scores.csv")
    assert {r["as_of"] for r in vs} == {AS_OF}
    alpha = next(r for r in vs if r["corp_code"] == "00000001")
    assert alpha["execution_score"] == "72.5"  # 구 as_of의 10.0이 아님
    assert alpha["washing_flag"] == "false"


def test_common_as_of_prefers_date_both_engines_share(session, tmp_path):
    """valueup만 더 최신인 상태 — max가 아니라 두 엔진 공통일을 골라야 함(GPT High)."""
    _seed(session)
    session.add(ValueupScore(corp_code="00000001", as_of=AS_OF_NEWER,
                             execution_score=99.0, washing_flag=False))
    session.commit()
    assert latest_common_as_of(session) == AS_OF  # NEWER에는 mna가 없음
    out = _out(tmp_path)
    export_all(session, out)
    smap = _read(out / "sector_valuation_map.csv")
    alpha = next(r for r in smap if r["corp_code"] == "00000001")
    assert alpha["mna_target_score"] != ""  # 공통일이라 M&A 컬럼이 채워짐


def test_stale_engine_warns(session, tmp_path, caplog):
    """공통일보다 최신인 엔진 실행분이 있으면 경고 — 조용한 과거 후퇴 방지."""
    _seed(session)
    session.add(ValueupScore(corp_code="00000001", as_of=AS_OF_NEWER,
                             execution_score=99.0, washing_flag=False))
    session.commit()
    with caplog.at_level("WARNING"):
        export_all(session, _out(tmp_path))
    assert any(AS_OF_NEWER in r.message and "포함되지 않습니다" in r.message
               for r in caplog.records)


def test_explicit_as_of_reproduces_past_snapshot(session, tmp_path):
    """--as-of로 과거 기준일 스냅숏 재현(두 엔진 모두 존재 시)."""
    _seed(session)
    session.add(MnaScore(corp_code="00000001", as_of=AS_OF_OLD,
                         mna_target_score=50.0, valuation_score=0.5))
    session.commit()
    out = _out(tmp_path)
    export_all(session, out, as_of=AS_OF_OLD)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["as_of"] == AS_OF_OLD
    vs = _read(out / "valueup_scores.csv")
    alpha = next(r for r in vs if r["corp_code"] == "00000001")
    assert alpha["execution_score"] == "10.0"  # 과거 행(최신 72.5 아님)


def test_explicit_as_of_missing_in_one_engine_raises(session, tmp_path):
    """--as-of가 한 엔진에만 있으면 거부 — 과거라도 반쪽 스냅숏 금지."""
    _seed(session)  # AS_OF_OLD는 valueup에만 존재
    with pytest.raises(NoScoreDataError, match="mna"):
        export_all(session, _out(tmp_path), as_of=AS_OF_OLD)


def test_old_dir_cleaned_after_successful_swap(session, tmp_path):
    """재실행 성공 시 .old 임시 디렉터리가 남지 않고 새 스냅숏만 존재."""
    _seed(session)
    out = _out(tmp_path)
    export_all(session, out)
    export_all(session, out)  # 기존 스냅숏 위에 재실행
    assert not (out.parent / f".{out.name}.old").exists()
    assert (out / "manifest.json").exists()


def test_no_common_as_of_raises(session, tmp_path):
    """한 엔진만 실행된 DB — 빈 반쪽 CSV로 조용히 성공하면 안 됨."""
    _seed(session)
    session.execute(text("DELETE FROM mna_score"))
    session.commit()
    with pytest.raises(NoScoreDataError):
        export_all(session, _out(tmp_path))
    assert not _out(tmp_path).exists()


def test_partial_failure_preserves_previous_snapshot(session, tmp_path, monkeypatch):
    """세 번째 CSV 실패 시 기존 5개+manifest가 그대로 남아야 함(원자성, GPT High)."""
    _seed(session)
    out = _out(tmp_path)
    export_all(session, out)
    before = {p.name: p.read_bytes() for p in out.iterdir()}

    def boom(session_, as_of):
        raise RuntimeError("disk error")
    monkeypatch.setattr(tableau_mod.export_repo, "roe_pbr_rows", boom)
    with pytest.raises(RuntimeError):
        export_all(session, out)
    after = {p.name: p.read_bytes() for p in out.iterdir()}
    assert after == before  # 부분 갱신·세대 혼합 없음
    assert not (out.parent / f".{out.name}.staging").exists()  # staging 청소


def test_missing_key_raises_schema_error(session, tmp_path, monkeypatch):
    """repository가 필수 키를 빠뜨리면 빈 셀 세탁 대신 ExportSchemaError(GPT Med)."""
    _seed(session)

    def broken(session_, as_of):
        return [{"corp_code": "00000001"}]  # 나머지 키 전부 누락
    monkeypatch.setattr(tableau_mod.export_repo, "valueup_scores_rows", broken)
    with pytest.raises(ExportSchemaError, match="missing="):
        export_all(session, _out(tmp_path))


def test_null_stays_empty_cell_not_zero(session, tmp_path):
    _seed(session)
    out = _out(tmp_path)
    export_all(session, out)
    vs = _read(out / "valueup_scores.csv")
    gamma = next(r for r in vs if r["corp_code"] == "00000003")
    assert gamma["execution_score"] == ""  # null → 빈 셀(0 아님)
    assert gamma["washing_flag"] == ""
    alpha = next(r for r in vs if r["corp_code"] == "00000001")
    assert alpha["achievement_rate"] == "0.0"  # 정상값 0 보존(3.4 High 회귀)
    db = _read(out / "dividend_buyback.csv")
    beta = next(r for r in db if r["corp_code"] == "00000002")
    assert beta["payout_ratio"] == ""
    assert beta["dividend_total"] == ""


def test_period_buyback_status_per_year_not_snapshot(session, tmp_path):
    """연도별 상태가 그 해 원천에서 나와야 함 — 스냅숏 반복 금지(GPT High)."""
    _seed(session)
    out = _out(tmp_path)
    export_all(session, out)
    db = _read(out / "dividend_buyback.csv")
    alpha = {r["year"]: r["period_buyback_status"]
             for r in db if r["corp_code"] == "00000001"}
    assert alpha == {"2024": "purchased_only", "2025": "retired"}
    beta = next(r for r in db if r["corp_code"] == "00000002")
    assert beta["period_buyback_status"] == ""  # 무관측 → null(none 아님)
    gamma = next(r for r in db if r["corp_code"] == "00000003")
    assert gamma["period_buyback_status"] == "none"  # 관측 있음+활동 0
    assert beta["market"] == "KOSPI"  # 전역 시장 필터용 market 컬럼(GPT Med)


def test_period_buyback_status_unit():
    assert period_buyback_status(100, None) == "purchased_only"
    assert period_buyback_status(100, 50) == "retired"
    assert period_buyback_status(0, 0) == "none"
    assert period_buyback_status(None, None) is None


def test_lookahead_partial_block_applies(session, tmp_path):
    _seed(session)
    out = _out(tmp_path)
    export_all(session, out)
    scatter = _read(out / "roe_pbr_scatter.csv")
    alpha = next(r for r in scatter if r["corp_code"] == "00000001")
    assert (alpha["metrics_year"], alpha["metrics_quarter"]) == ("2025", "3")
    db = _read(out / "dividend_buyback.csv")
    assert not any(r["corp_code"] == "00000001" and r["year"] == "2026" for r in db)


def test_mna_absence_exposed_not_hidden(session, tmp_path):
    _seed(session)
    out = _out(tmp_path)
    export_all(session, out)
    smap = _read(out / "sector_valuation_map.csv")
    beta = next(r for r in smap if r["corp_code"] == "00000002")
    assert beta["mna_target_score"] == ""
    assert beta["sector"] == "64110"  # 숫자 코드가 문자열 원문으로 보존


def test_macro_layer_full_series(session, tmp_path):
    _seed(session)
    out = _out(tmp_path)
    export_all(session, out)
    macro = _read(out / "macro_layer.csv")
    assert len(macro) == 2
    usd = next(r for r in macro if r["indicator"] == "usd_krw")
    assert usd["value"] == ""
