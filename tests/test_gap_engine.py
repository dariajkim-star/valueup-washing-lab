"""Story 2.1 — Value-up 갭 스코어링 엔진 검증 (순수 함수 + 통합, DB는 SQLite in-memory)."""

from __future__ import annotations

from datetime import date

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
from app.repositories import valueup_score as repo
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


def test_progress_rate_mid_period_day_precision() -> None:
    """[결정 B, 2026-07-21] 일 단위 정밀도(scoring.md 원식 `today` 기반 정합화).
    2024~2027 계획(2024-01-01~2027-12-31, 1460일)의 2025-12-31 시점 = 730일 = 정확히 0.5."""
    assert _progress_rate("2024", "2027", date(2025, 12, 31)) == pytest.approx(0.5)


def test_progress_rate_no_new_year_jump() -> None:
    """[결정 B 핵심 회귀] 12/31→1/1 사이 진척률이 점프하지 않는다 — 연 단위 구현은
    같은 구간에서 1/3→2/3으로 +0.33 점프해 washing 임계(0.5)를 하루 만에 넘겼다."""
    before = _progress_rate("2024", "2027", date(2025, 12, 31))
    after = _progress_rate("2024", "2027", date(2026, 1, 1))
    assert after - before == pytest.approx(1 / 1460)  # 정확히 하루치


def test_progress_rate_before_start_clamps_zero() -> None:
    assert _progress_rate("2024", "2027", date(2023, 6, 1)) == 0.0


def test_progress_rate_after_end_clamps_one() -> None:
    assert _progress_rate("2024", "2027", date(2030, 1, 1)) == 1.0


def test_progress_rate_invalid_period_is_none() -> None:
    d = date(2025, 12, 31)
    assert _progress_rate(None, "2027", d) is None
    assert _progress_rate("2024", None, d) is None
    assert _progress_rate("2027", "2024", d) is None  # end<start
    # end==start: 0나눗셈은 일 단위 전환으로 사라졌지만(분모 364일) AC3 계약("end<=start
    # 무효") 유지 — 단년 계획 수용은 별도 결정(deferred-work.md 2026-07-21).
    assert _progress_rate("2024", "2024", d) is None
    assert _progress_rate("abc", "2027", d) is None  # 파싱 실패


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


def test_washing_flag_buyback_planned_none_is_unknown_term() -> None:
    """[코드리뷰 2026-07-21] buyback_planned는 파싱 실패 시 DB에 null로 들어온다
    (ValueupPlan.buyback_planned: bool|None, 자유서식 best-effort). _washing_flag에서
    래핑 없이 raw로 들어가는 것은 의도 — 이미 3치(bool|None)라 변환이 불필요하며,
    None은 Kleene unknown으로 처리된다. 이 테스트가 그 계약을 고정한다."""
    assert _washing_flag(
        progress_rate=0.6, achievement_rate=0.4, buyback_planned=None,
        buyback_retired=False, progress_min=0.5, achievement_max=0.6,
    ) is None  # 확정 False 없음 + unknown 있음 → 판단 불가


def test_washing_flag_buyback_planned_none_still_dominated_by_retired() -> None:
    """[코드리뷰 2026-07-21] planned가 unknown이어도 소각 확정(retired=True)이면 전체
    확정 False — unknown 항이 확정 False 항의 지배를 막지 않는다."""
    assert _washing_flag(
        progress_rate=0.6, achievement_rate=0.4, buyback_planned=None,
        buyback_retired=True, progress_min=0.5, achievement_max=0.6,
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
        run(as_of="2025-7-1", session_factory=Session_)
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        run(as_of="not-a-date", session_factory=Session_)


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
        run(as_of="2025-12-31", corp_codes=["00000005"], session_factory=Session_)
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
        run(as_of="2025-12-31", session_factory=Session_)
        assert s.scalar(select(ValueupScore)) is not None  # score 생성 확인

        plan = s.scalars(select(ValueupPlan).where(ValueupPlan.corp_code == "00000001")).one()
        s.delete(plan)
        s.commit()

        result = run(as_of="2025-12-31", session_factory=Session_)
        assert s.scalar(select(ValueupScore)) is None  # 정리됨
        assert result.scored == 0 and result.deleted == 1


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

        run(as_of="2025-12-31", corp_codes=["00000006"], session_factory=Session_)
        row_same_year = s.scalars(
            select(ValueupScore).where(ValueupScore.as_of == "2025-12-31")
        ).one()
        assert row_same_year.achievement_rate is None  # 같은 해 → 아직 못 봄
        s.commit()  # run()이 자체 세션을 열기 전에 커넥션을 놓아준다(StaticPool 공유)

        run(as_of="2026-06-30", corp_codes=["00000006"], session_factory=Session_)
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
        result = run(as_of="2025-12-31", session_factory=Session_)
        assert result.scored == 1
        assert result.complete is True  # 실패 0 → 이 as_of는 전 종목 동일 시점
        row = s.scalars(select(ValueupScore)).one()
        # actual_roe = net_income/equity*100 = 80/1000*100 = 8.0 → achievement = 8/10 = 0.8
        assert row.achievement_rate == pytest.approx(0.8)
        # progress(일 단위, 결정 B): (2025-12-31 − 2024-01-01) / (2027-12-31 − 2024-01-01)
        # = 730/1460 = 0.5 (연 단위 시절엔 1/3이었다)
        assert row.progress_rate == pytest.approx(0.5)
        assert row.buyback_executed is True
        assert row.buyback_retired is False  # 확정 0
        assert row.buyback_status == "purchased_only"
        # washing: progress 0.5>=0.5는 True 항이 됐지만 achievement 0.8<0.6이 확정 False
        # → 전체 False(목표를 80% 달성 중이면 워싱 아님. 연 단위 시절엔 진척 미달이 사유였다)
        assert row.washing_flag is False
        assert row.execution_score is not None


def test_run_skips_corp_without_plan(engine) -> None:
    """AC1: valueup_plan 없는 종목은 행 자체를 만들지 않는다(no-data 취급)."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        s.add(Company(corp_code="00000002", corp_name="계획없음"))
        s.commit()
        result = run(as_of="2025-12-31", corp_codes=["00000002"], session_factory=Session_)
        assert result.scored == 0
        assert s.scalar(select(ValueupScore)) is None


def test_run_is_idempotent(engine) -> None:
    """AC7: 같은 (corp_code, as_of) 재실행 시 중복 없이 갱신."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
        run(as_of="2025-12-31", session_factory=Session_)
        run(as_of="2025-12-31", session_factory=Session_)  # 재실행
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
        run(as_of="2025-12-31", session_factory=Session_)
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
        run(as_of="2025-12-31", corp_codes=["00000003"], session_factory=Session_)
        row = s.scalars(select(ValueupScore)).one()
        assert row.achievement_rate is None
        assert row.execution_score is None
        assert row.buyback_status == "unknown"
        # 결정 B(일 단위)로 progress=0.5>=0.5 → True 항. 확정 False 항이 없고
        # achievement·retired가 unknown이므로 Kleene 3치상 washing은 None(판단 불가).
        # (연 단위 시절엔 progress=1/3<0.5 확정 False가 전체를 False로 지배했다 —
        # 산식 정밀도가 바뀌면 임계 근처 판정이 바뀌는 것이 올바른 null 전파다.)
        assert row.progress_rate == pytest.approx(0.5)
        assert row.washing_flag is None


# ── T5: 트랜잭션 정책 — 종목별 커밋 + 실패 목록 (코드리뷰 2026-07-21 결정) ──

def test_run_partial_failure_keeps_successful_corps(engine, monkeypatch) -> None:
    """한 종목이 터져도 나머지 종목의 결과는 살아남고, 실패는 목록에 남는다.

    전량 원자성을 택했다면 이 테스트는 '전부 롤백'을 기대했을 것 — 부분 성공을 택한 대신
    실패를 **숨기지 않는다**(ScoreRunResult.failed / .complete)는 것이 이 정책의 계약이다.
    """
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s, corp_code="00000001")
        _seed(s, corp_code="00000009")

    real_latest_plan = repo.latest_valueup_plan

    def _boom(session, corp_code, as_of):
        if corp_code == "00000009":
            raise RuntimeError("의도적 실패")
        return real_latest_plan(session, corp_code, as_of)

    monkeypatch.setattr(repo, "latest_valueup_plan", _boom)

    result = run(as_of="2025-12-31", session_factory=Session_)

    assert result.scored == 1  # 정상 종목은 저장됨
    assert result.succeeded == ["00000001"]
    assert [c for c, _ in result.failed] == ["00000009"]
    assert result.complete is False  # 이 as_of 스냅샷은 불완전 — 게시 전 확인 필요
    with Session_() as s:
        rows = s.scalars(select(ValueupScore)).all()
        assert [r.corp_code for r in rows] == ["00000001"]


def test_run_failed_corp_leaves_no_partial_row(engine, monkeypatch) -> None:
    """실패 종목의 트랜잭션은 통째로 롤백된다 — 반쪽 행이 남지 않는다.

    '종목별 커밋'은 종목 **경계**에서만 부분 성공을 허용한다는 뜻이지, 한 종목 안에서
    반쯤 쓰인 상태를 허용한다는 뜻이 아니다.
    """
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s, corp_code="00000001")

    real_upsert = repo.upsert_valueup_score

    def _boom_after_write(session, rec):
        real_upsert(session, rec)  # 행을 쓴 **직후** 실패시킨다
        raise RuntimeError("저장 직후 실패")

    monkeypatch.setattr(repo, "upsert_valueup_score", _boom_after_write)

    result = run(as_of="2025-12-31", session_factory=Session_)

    assert result.scored == 0
    assert [c for c, _ in result.failed] == ["00000001"]
    with Session_() as s:
        assert s.scalar(select(ValueupScore)) is None  # 롤백됨
