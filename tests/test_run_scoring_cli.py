"""Story 4-1 — 스코어링 배치 CLI 검증.

핵심은 "계산이 맞나"가 아니라(그건 2.1이 검증한다) **엔진이 노출한 `complete`가
종료 코드로 번역되는가**다. 그 번역이 이 모듈의 존재 이유다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.analysis import run_scoring
from app.analysis.gap_engine import ScoreRunResult
from app.analysis.run_scoring import EXIT_INCOMPLETE, EXIT_OK, EXIT_USAGE, main
from app.models import Base, Company, Financial, ValueupPlan, ValueupScore
from app.sql_views import CREATE_VALUATION_METRICS


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:", future=True,
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.execute(text(CREATE_VALUATION_METRICS))
    return eng


def _seed(session: Session, corp_code: str = "00000001") -> None:
    """2.1 통합 테스트와 동일한 최소 시드(계획 + 전년도 확정실적)."""
    session.add(Company(corp_code=corp_code, corp_name="테스트", market="KOSPI"))
    session.add(Financial(
        corp_code=corp_code, year=2024, quarter=4,
        revenue=1000, net_income=80, operating_income=100, depreciation=10,
        equity=1000, total_assets=2000, total_liabilities=1000, cash=100,
        total_debt=200, dividend_total=24,
        buyback_amount=3_000_000, buyback_retired_amount=0,
    ))
    session.add(ValueupPlan(
        corp_code=corp_code, disclosure_date="2024-03-01",
        target_roe=10.0, target_payout_ratio=30.0, target_pbr=1.2,
        period_start="2024", period_end="2027", buyback_planned=True,
    ))
    session.commit()


# ── 종료 코드 계약 (AC3) ──

def test_complete_run_exits_zero(engine, monkeypatch) -> None:
    """AC1/AC3: 전체 실행이 성공하면 종료 코드 0이고 실제로 점수가 기록된다."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
    monkeypatch.setattr(run_scoring, "SessionLocal", Session_)

    assert main(["--as-of", "2025-12-31"]) == EXIT_OK

    with Session_() as s:
        row = s.scalars(select(ValueupScore)).one()
        assert row.corp_code == "00000001"
        assert row.as_of == "2025-12-31"


def test_partial_failure_exits_one(monkeypatch) -> None:
    """AC3의 핵심: complete=False가 종료 코드 1로 번역된다.

    여기서 실패를 '만들어' 주입하는 이유 — 엔진이 실패를 어떻게 만드는지는 2.1의 관심사고,
    이 모듈의 관심사는 실패가 있을 때 **조용히 0을 반환하지 않는다**는 것뿐이다.
    """
    def fake_run(as_of, corp_codes=None, *, session_factory=None):
        return ScoreRunResult(
            scored=2, deleted=0, succeeded=["00000001", "00000002"],
            failed=[("00000003", "boom")],
        )
    monkeypatch.setattr(run_scoring.gap_engine, "run", fake_run)

    assert main(["--as-of", "2025-12-31"]) == EXIT_INCOMPLETE


def test_failed_corp_codes_are_all_logged(monkeypatch, caplog) -> None:
    """AC4: 실패 목록은 전건 출력된다(자르지 않는다)."""
    failed = [(f"0000000{i}", f"사유{i}") for i in range(1, 6)]

    def fake_run(as_of, corp_codes=None, *, session_factory=None):
        return ScoreRunResult(scored=0, failed=list(failed))
    monkeypatch.setattr(run_scoring.gap_engine, "run", fake_run)

    with caplog.at_level("ERROR"):
        assert main(["--as-of", "2025-12-31"]) == EXIT_INCOMPLETE
    for corp_code, reason in failed:
        assert corp_code in caplog.text
        assert reason in caplog.text


def test_summary_is_logged(engine, monkeypatch, caplog) -> None:
    """AC2: 실행 요약(scored/deleted/failed/complete)이 남는다."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
    monkeypatch.setattr(run_scoring, "SessionLocal", Session_)

    with caplog.at_level("INFO"):
        assert main(["--as-of", "2025-12-31"]) == EXIT_OK
    assert "scored=1" in caplog.text
    assert "complete=True" in caplog.text


# ── 입력 계약 (AC5, AC6) ──

def test_as_of_is_required(capsys) -> None:
    """AC5: --as-of 미지정은 종료 코드 2 — 시스템 시계로 대체하지 않는다(D2)."""
    with pytest.raises(SystemExit) as exc:  # argparse의 required 처리
        main([])
    assert exc.value.code == EXIT_USAGE


@pytest.mark.parametrize("bad", ["2025-7-1", "not-a-date", "2025-02-30"])
def test_invalid_as_of_exits_two_without_traceback(bad, monkeypatch, caplog) -> None:
    """AC6: 형식 오류(2025-7-1)·달력 무효(2025-02-30) 모두 트레이스백이 아니라 종료 코드 2.

    2025-02-30은 정규식만으론 통과하는 값 — 엔진의 달력 검증까지 CLI가 삼키는지 확인한다.
    """
    Session_ = sessionmaker(bind=create_engine("sqlite:///:memory:", future=True))
    monkeypatch.setattr(run_scoring, "SessionLocal", Session_)

    with caplog.at_level("ERROR"):
        assert main(["--as-of", bad]) == EXIT_USAGE
    assert "입력 오류" in caplog.text


# ── 부분 실행 (AC7) ──

def test_partial_run_warns_not_publishable(engine, monkeypatch, caplog) -> None:
    """AC7: --corp-codes 실행은 complete=True여도 '게시용 아님' 경고를 남긴다(D3)."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
    monkeypatch.setattr(run_scoring, "SessionLocal", Session_)

    with caplog.at_level("WARNING"):
        assert main(["--as-of", "2025-12-31", "--corp-codes", "00000001"]) == EXIT_OK
    assert "게시용 아님" in caplog.text


def test_empty_corp_codes_is_usage_error(monkeypatch, caplog) -> None:
    """빈 --corp-codes는 '대상 0종목 조용한 성공'이 되므로 사용법 오류로 막는다.

    전체 실행(옵션 생략)과 구분되지 않는 무작업이 complete=True·exit 0으로 나가면,
    이 스토리가 만들려는 신호 자체가 거짓이 된다.
    """
    called = False

    def fake_run(*a, **kw):
        nonlocal called
        called = True
        return ScoreRunResult()
    monkeypatch.setattr(run_scoring.gap_engine, "run", fake_run)

    with caplog.at_level("ERROR"):
        assert main(["--as-of", "2025-12-31", "--corp-codes", " , "]) == EXIT_USAGE
    assert called is False  # 엔진에 도달하기 전에 막혔다
