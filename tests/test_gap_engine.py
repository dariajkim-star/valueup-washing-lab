"""Story 2.1 — Value-up 갭 스코어링 엔진 검증 (순수 함수 + 통합, DB는 SQLite in-memory)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.analysis.gap_engine import (
    _achievement_rate,
    _buyback_signals,
    _execution_score,
    _progress_rate,
    _safe_ratio,
    _washing_flag,
    run,
)
from app.models import Base, Company, Financial, ValueupPlan, ValueupScore
from app.sql_views import CREATE_VALUATION_METRICS


# ── T3: 순수 함수 단위 테스트 (DB 미접촉) ──

def test_safe_ratio_normal() -> None:
    assert _safe_ratio(8.0, 10.0) == 0.8


def test_safe_ratio_target_zero_or_negative_is_none() -> None:
    assert _safe_ratio(8.0, 0.0) is None
    assert _safe_ratio(8.0, -5.0) is None


def test_safe_ratio_missing_input_is_none() -> None:
    assert _safe_ratio(None, 10.0) is None
    assert _safe_ratio(8.0, None) is None


def test_progress_rate_mid_period() -> None:
    """3년 계획(2024~2027) 중 1년 경과 → 1/3."""
    assert _progress_rate("2024", "2027", 2025) == pytest.approx(1 / 3)


def test_progress_rate_before_start_clamps_zero() -> None:
    assert _progress_rate("2024", "2027", 2023) == 0.0


def test_progress_rate_after_end_clamps_one() -> None:
    assert _progress_rate("2024", "2027", 2030) == 1.0


def test_progress_rate_invalid_period_is_none() -> None:
    assert _progress_rate(None, "2027", 2025) is None
    assert _progress_rate("2024", None, 2025) is None
    assert _progress_rate("2027", "2024", 2025) is None  # end<=start
    assert _progress_rate("2024", "2024", 2025) is None  # end==start, 0나눗셈 방어
    assert _progress_rate("abc", "2027", 2025) is None  # 파싱 실패


def test_achievement_rate_normal() -> None:
    assert _achievement_rate(8.0, 10.0) == pytest.approx(0.8)


def test_achievement_rate_target_missing_or_nonpositive_is_none() -> None:
    assert _achievement_rate(8.0, None) is None
    assert _achievement_rate(8.0, 0.0) is None
    assert _achievement_rate(None, 10.0) is None


def test_buyback_signals_retired() -> None:
    executed, retired, status = _buyback_signals(3_000_000, 1_000_000)
    assert executed is True
    assert retired is True
    assert status == "retired"


def test_buyback_signals_purchased_only() -> None:
    executed, retired, status = _buyback_signals(3_000_000, 0)
    assert executed is True
    assert retired is False
    assert status == "purchased_only"


def test_buyback_signals_none_activity() -> None:
    executed, retired, status = _buyback_signals(0, 0)
    assert executed is False
    assert retired is False
    assert status == "none"


def test_buyback_signals_unknown_when_either_missing() -> None:
    assert _buyback_signals(None, 0)[2] == "unknown"
    assert _buyback_signals(3_000_000, None)[2] == "unknown"
    assert _buyback_signals(None, None) == (None, None, "unknown")


def test_execution_score_normal() -> None:
    # achievement=0.8(0.5) + buyback=1(0.3) + payout=1.0달성(0.2) → 100*(0.4+0.3+0.2)=90
    score = _execution_score(
        achievement_rate=0.8, buyback_executed=True,
        actual_payout=35.0, target_payout=30.0,  # 초과달성 → min(,1.0)=1.0
        w_achievement=0.5, w_buyback=0.3, w_payout=0.2,
    )
    assert score == pytest.approx(90.0)


def test_execution_score_caps_overachievement() -> None:
    """achievement_rate 150%여도 min(,1.0)으로 캡."""
    score = _execution_score(
        achievement_rate=1.5, buyback_executed=True,
        actual_payout=30.0, target_payout=30.0,
        w_achievement=0.5, w_buyback=0.3, w_payout=0.2,
    )
    assert score == pytest.approx(100.0)


def test_execution_score_none_when_achievement_missing() -> None:
    assert _execution_score(
        achievement_rate=None, buyback_executed=True,
        actual_payout=30.0, target_payout=30.0,
        w_achievement=0.5, w_buyback=0.3, w_payout=0.2,
    ) is None


def test_execution_score_none_when_buyback_unknown() -> None:
    assert _execution_score(
        achievement_rate=0.8, buyback_executed=None,
        actual_payout=30.0, target_payout=30.0,
        w_achievement=0.5, w_buyback=0.3, w_payout=0.2,
    ) is None


def test_execution_score_none_when_payout_ratio_undefined() -> None:
    assert _execution_score(
        achievement_rate=0.8, buyback_executed=True,
        actual_payout=30.0, target_payout=None,
        w_achievement=0.5, w_buyback=0.3, w_payout=0.2,
    ) is None


def test_washing_flag_true_case() -> None:
    assert _washing_flag(
        progress_rate=0.6, achievement_rate=0.4, buyback_planned=True,
        buyback_retired=False, progress_min=0.5, achievement_max=0.6,
    ) is True


def test_washing_flag_false_case_achievement_high() -> None:
    assert _washing_flag(
        progress_rate=0.6, achievement_rate=0.9, buyback_planned=True,
        buyback_retired=False, progress_min=0.5, achievement_max=0.6,
    ) is False


def test_washing_flag_false_when_retired_true() -> None:
    assert _washing_flag(
        progress_rate=0.6, achievement_rate=0.4, buyback_planned=True,
        buyback_retired=True, progress_min=0.5, achievement_max=0.6,
    ) is False


def test_washing_flag_none_when_all_unknown_no_confirmed_false() -> None:
    """확정 False가 없고 unknown만 있으면 None(판단 불가) — Kleene 3치의 두 번째 경우."""
    assert _washing_flag(
        progress_rate=None, achievement_rate=0.4, buyback_planned=True,
        buyback_retired=False, progress_min=0.5, achievement_max=0.6,
    ) is None  # progress unknown, 나머지 True 방향이라 확정 False 없음


# ── 코드리뷰 회귀 테스트 (2026-07-10, GPT 교차검증) ──

def test_washing_flag_kleene_retired_true_dominates() -> None:
    """[High] 소각이 확정(retired=True)되면 나머지가 unknown이어도 washing은 확정 False —
    이전 구현("하나라도 None→전체 None")은 이 케이스도 None으로 냈다(과잉보수적)."""
    assert _washing_flag(
        progress_rate=None, achievement_rate=None, buyback_planned=True,
        buyback_retired=True, progress_min=0.5, achievement_max=0.6,
    ) is False


def test_washing_flag_kleene_buyback_not_planned_dominates() -> None:
    """[High] buyback_planned=False가 확정 False 항이면 나머지 unknown이어도 전체 False."""
    assert _washing_flag(
        progress_rate=None, achievement_rate=None, buyback_planned=False,
        buyback_retired=None, progress_min=0.5, achievement_max=0.6,
    ) is False


def test_washing_flag_kleene_progress_below_min_dominates() -> None:
    """[High] progress_rate가 확정으로 임계 미달이면 나머지 unknown이어도 전체 False."""
    assert _washing_flag(
        progress_rate=0.1, achievement_rate=None, buyback_planned=True,
        buyback_retired=None, progress_min=0.5, achievement_max=0.6,
    ) is False


def test_buyback_signals_negative_quantity_is_unknown() -> None:
    """[High] 음수 수량(도메인에 없는 값)은 확정 False/True가 아니라 unknown 취급.
    1.8의 _parse_quantity가 상류에서 이미 음수를 걸러 DB엔 안 들어오지만, gap_engine 자체도
    방어(다른 writer 경로·수동 DB 편집 등에 대한 belt-and-suspenders)."""
    from app.analysis.gap_engine import _buyback_signals

    assert _buyback_signals(-5, 0)[0] is None  # executed
    assert _buyback_signals(-5, 0)[2] == "unknown"
    assert _buyback_signals(3_000_000, -1)[1] is None  # retired
    assert _buyback_signals(3_000_000, -1)[2] == "unknown"


def test_run_rejects_malformed_as_of(engine) -> None:
    """[High] as_of가 YYYY-MM-DD가 아니면 fail-fast — 문자열 날짜 비교가 실제 날짜 비교와
    어긋나는 입력(예: zero-pad 없는 월)을 사전에 차단."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            run(s, as_of="2025-7-1")
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            run(s, as_of="not-a-date")


def test_run_ac3_invalid_period_nulls_achievement_and_execution(engine) -> None:
    """[High] AC3: period_start가 없으면 progress_rate뿐 아니라 achievement_rate·
    execution_score도 null이어야 한다(이전 구현은 achievement_rate를 별도 계산해 AC3 위반)."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        s.add(Company(corp_code="00000005", corp_name="기간불명"))
        s.add(Financial(
            corp_code="00000005", year=2024, quarter=4,
            net_income=80, equity=1000, revenue=1000,
            operating_income=100, depreciation=10, total_assets=2000,
            total_liabilities=1000, cash=100, total_debt=200, dividend_total=24,
        ))
        s.add(ValueupPlan(
            corp_code="00000005", disclosure_date="2024-01-01",
            target_roe=10.0, target_payout_ratio=30.0,
            period_start=None, period_end=None,  # 파싱 실패로 기간 불명
            buyback_planned=True,
        ))
        s.commit()
        run(s, as_of="2025-12-31", corp_codes=["00000005"])
        s.commit()
        row = s.scalars(select(ValueupScore)).one()
        assert row.progress_rate is None
        assert row.achievement_rate is None  # actual_roe=8.0, target_roe=10.0로 계산 가능했었지만 null
        assert row.execution_score is None


def test_run_deletes_stale_score_when_plan_removed(engine) -> None:
    """[High] plan이 있어 score가 생성된 뒤 plan이 삭제되면, 같은 as_of 재실행 시 근거를
    잃은 기존 score도 함께 정리된다(정합성 reconciliation)."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
        run(s, as_of="2025-12-31")
        s.commit()
        assert s.scalar(select(ValueupScore)) is not None  # score 생성 확인

        plan = s.scalars(select(ValueupPlan).where(ValueupPlan.corp_code == "00000001")).one()
        s.delete(plan)
        s.commit()

        run(s, as_of="2025-12-31")
        s.commit()
        assert s.scalar(select(ValueupScore)) is None  # 정리됨


def test_run_excludes_same_year_annual_report_lookahead(engine) -> None:
    """[High] look-ahead 부분차단: 같은 연도의 사업보고서(quarter=4)는 그 해 안에 공시될 수
    없으므로(통상 다음해 3월) as_of가 같은 해면 사용하지 않는다. 다음 해로 넘어가면 사용됨."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        s.add(Company(corp_code="00000006", corp_name="당해사업보고서"))
        s.add(Financial(
            corp_code="00000006", year=2025, quarter=4,  # FY2025 사업보고서
            net_income=80, equity=1000, revenue=1000,
            operating_income=100, depreciation=10, total_assets=2000,
            total_liabilities=1000, cash=100, total_debt=200, dividend_total=24,
        ))
        s.add(ValueupPlan(
            corp_code="00000006", disclosure_date="2024-01-01",
            target_roe=10.0, period_start="2024", period_end="2027",
            buyback_planned=True,
        ))
        s.commit()

        run(s, as_of="2025-12-31", corp_codes=["00000006"])
        s.commit()
        row_same_year = s.scalars(
            select(ValueupScore).where(ValueupScore.as_of == "2025-12-31")
        ).one()
        assert row_same_year.achievement_rate is None  # 같은 해 → 아직 못 봄

        run(s, as_of="2026-06-30", corp_codes=["00000006"])
        s.commit()
        row_next_year = s.scalars(
            select(ValueupScore).where(ValueupScore.as_of == "2026-06-30")
        ).one()
        assert row_next_year.achievement_rate == pytest.approx(0.8)  # 다음 해 → 이제 보임


def test_latest_valueup_plan_tie_break_is_structurally_unreachable(engine) -> None:
    """[Med, GPT 지적 재검증] "동일 disclosure_date 2건" 시나리오는 valueup_plan의
    UniqueConstraint(corp_code, disclosure_date)(1.5, AD-7)가 DB 레벨에서 이미 차단한다 —
    같은 날짜에 정정공시가 겹쳐도 자연키 충돌로 두 번째 insert가 실패하므로 tie-break 자체가
    발생할 수 없다(GPT 원 지적은 스키마 확인 없이 나온 것으로 재검증 후 반례 확인, REFUTED).
    plan_id 보조 정렬키는 그래도 무해한 방어코드로 유지(제약이 느슨해질 미래 대비)."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        s.add(Company(corp_code="00000007", corp_name="정정공시"))
        s.add(ValueupPlan(
            corp_code="00000007", disclosure_date="2024-06-01",
            target_roe=8.0, period_start="2024", period_end="2027", buyback_planned=True,
        ))
        s.commit()
        s.add(ValueupPlan(  # 같은 (corp_code, disclosure_date) → UNIQUE 위반 확인
            corp_code="00000007", disclosure_date="2024-06-01",
            target_roe=9.0, period_start="2024", period_end="2027", buyback_planned=True,
        ))
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()


# ── T4: 통합 테스트 (SQLite in-memory + valuation_metrics 뷰) ──

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
    session.add(Company(corp_code=corp_code, corp_name="테스트", market="KOSPI"))
    # 전년도(2024) 사업보고서 — look-ahead 부분차단(코드리뷰 High) 반영: as_of=2025-12-31
    # 시점엔 FY2025 사업보고서(2025년 quarter=4)는 아직 공시될 수 없어(통상 다음해 3월),
    # 실제로 알 수 있는 최신 확정실적은 FY2024다.
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


def test_run_computes_and_upserts_score(engine) -> None:
    """AC1/2/4/5/6: end-to-end 계산이 정확히 나온다."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
        n = run(s, as_of="2025-12-31")
        s.commit()
        assert n == 1
        row = s.scalars(select(ValueupScore)).one()
        # actual_roe = net_income/equity*100 = 80/1000*100 = 8.0 → achievement = 8/10 = 0.8
        assert row.achievement_rate == pytest.approx(0.8)
        # progress: (2025-2024)/(2027-2024) = 1/3
        assert row.progress_rate == pytest.approx(1 / 3)
        assert row.buyback_executed is True
        assert row.buyback_retired is False  # 확정 0
        assert row.buyback_status == "purchased_only"
        # washing: progress(1/3)<0.5 → False(달성률 낮아도 진척 미달로 워싱 아님)
        assert row.washing_flag is False
        assert row.execution_score is not None


def test_run_skips_corp_without_plan(engine) -> None:
    """AC1: valueup_plan 없는 종목은 행 자체를 만들지 않는다(no-data 취급)."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        s.add(Company(corp_code="00000002", corp_name="계획없음"))
        s.commit()
        n = run(s, as_of="2025-12-31", corp_codes=["00000002"])
        s.commit()
        assert n == 0
        assert s.scalar(select(ValueupScore)) is None


def test_run_is_idempotent(engine) -> None:
    """AC7: 같은 (corp_code, as_of) 재실행 시 중복 없이 갱신."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
        run(s, as_of="2025-12-31")
        s.commit()
        run(s, as_of="2025-12-31")  # 재실행
        s.commit()
        rows = s.scalars(select(ValueupScore)).all()
        assert len(rows) == 1


def test_run_picks_latest_disclosure_before_as_of(engine) -> None:
    """리드 결정 A: as_of 이전 최신 공시 채택(2024-03 목표10% 대신 2025-06 목표12%)."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)  # target_roe=10.0 @ 2024-03-01
        s.add(ValueupPlan(
            corp_code="00000001", disclosure_date="2025-06-01",
            target_roe=12.0, period_start="2025", period_end="2028",
            buyback_planned=True,
        ))
        s.commit()
        run(s, as_of="2025-12-31")
        s.commit()
        row = s.scalars(select(ValueupScore)).one()
        # actual_roe=8.0 → 8/12 (최신 공시 target) 아니라 8/10이면 구버전 채택 오류
        assert row.achievement_rate == pytest.approx(8.0 / 12.0)


def test_run_null_metrics_propagate_to_null_score(engine) -> None:
    """financials/metrics 없는 종목: plan은 있으나 실적 없음 → achievement_rate null."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        s.add(Company(corp_code="00000003", corp_name="실적없음"))
        s.add(ValueupPlan(
            corp_code="00000003", disclosure_date="2024-01-01",
            target_roe=10.0, period_start="2024", period_end="2027",
            buyback_planned=True,
        ))
        s.commit()
        run(s, as_of="2025-12-31", corp_codes=["00000003"])
        s.commit()
        row = s.scalars(select(ValueupScore)).one()
        assert row.achievement_rate is None
        assert row.execution_score is None
        assert row.buyback_status == "unknown"
        # Kleene 3치(코드리뷰 Med): progress_rate=1/3<0.5는 확정 False → 나머지 unknown이어도
        # washing_flag는 확정 False(과거엔 achievement/retired가 None이라 전체 None이었음).
        assert row.progress_rate == pytest.approx(1 / 3)
        assert row.washing_flag is False
