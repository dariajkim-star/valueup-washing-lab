"""Story 2.3 — M&A Target Score 엔진 검증 (순수 함수 + cross-sectional 통합)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.analysis.mna_engine import (
    _avg_scores,
    _build_populations,
    _mna_target_score,
    _pct_rank_high,
    _pct_rank_low,
    _percentile_rank,
    run,
)
from app.models import (
    Base,
    Company,
    Financial,
    MacroIndicator,
    MnaScore,
    Ownership,
    Price,
)
from app.sql_views import CREATE_VALUATION_METRICS


# ── T3: 순수 함수 단위 테스트 ──

def test_percentile_rank_min_zero_max_one() -> None:
    pop = [10.0, 20.0, 30.0, 40.0]
    assert _percentile_rank(10.0, pop) == 0.0
    assert _percentile_rank(40.0, pop) == 1.0
    assert _percentile_rank(20.0, pop) == pytest.approx(1 / 3)


def test_percentile_rank_ties_use_mid_rank() -> None:
    """[리뷰 High] 동점은 mid-rank — (below + (equal-1)/2) / (N-1). 최하위 몰림 방지."""
    pop = [10.0, 10.0, 30.0]
    # 10.0: below=0, equal=2 → (0 + 0.5)/2 = 0.25 (min-rank 0.0이 아님)
    assert _percentile_rank(10.0, pop) == pytest.approx(0.25)
    assert _percentile_rank(30.0, pop) == 1.0


def test_percentile_rank_all_equal_is_neutral() -> None:
    """[리뷰 High] 전원 동일값 → 전원 0.5(중립). min-rank였다면 0.0(→pct_low 1.0)로
    '모두 똑같은데 최고점' 왜곡 — 기준금리처럼 장기 동결되는 시계열에서 실제로 터지는 케이스."""
    assert _percentile_rank(5.0, [5.0, 5.0, 5.0]) == pytest.approx(0.5)
    assert _pct_rank_low(5.0, [5.0, 5.0, 5.0]) == pytest.approx(0.5)


def test_percentile_rank_rejects_nonfinite() -> None:
    """[리뷰 Med] NaN/Inf는 모집단·대상값 모두에서 배제(비교 연산이 조용히 왜곡됨)."""
    nan, inf = float("nan"), float("inf")
    # NaN이 대상값 → None (모든 < 비교가 False라 min-rank처럼 보이는 오류 방지)
    assert _percentile_rank(nan, [1.0, 2.0, 3.0]) is None
    # NaN/Inf가 모집단에 → 제외하고 계산 (분모 오염 방지)
    assert _percentile_rank(2.0, [1.0, nan, 2.0, inf]) == pytest.approx(1.0)


def test_percentile_rank_small_population_is_none() -> None:
    """peer<2면 순위가 무의미 → None."""
    assert _percentile_rank(10.0, [10.0]) is None
    assert _percentile_rank(10.0, []) is None


def test_percentile_rank_none_value_is_none() -> None:
    assert _percentile_rank(None, [1.0, 2.0, 3.0]) is None


def test_percentile_rank_ignores_none_in_population() -> None:
    pop = [10.0, None, 30.0, None]
    assert _percentile_rank(30.0, pop) == 1.0


def test_pct_rank_directions() -> None:
    pop = [1.0, 2.0, 3.0]
    # low: 낮을수록 좋은 지표(EV/EBITDA 등) → 최솟값이 1.0
    assert _pct_rank_low(1.0, pop) == 1.0
    assert _pct_rank_low(3.0, pop) == 0.0
    # high: 높을수록 좋은 지표(net_cash 등) → 최댓값이 1.0
    assert _pct_rank_high(3.0, pop) == 1.0
    assert _pct_rank_high(1.0, pop) == 0.0


def test_avg_scores_strict_null() -> None:
    """AC6(리드 결정 1, 엄격): 하나라도 None이면 요소 점수 전체 None."""
    assert _avg_scores(0.5, 0.7) == pytest.approx(0.6)
    assert _avg_scores(0.5, None) is None
    assert _avg_scores(None, None) is None


def test_mna_target_score_weighted_sum() -> None:
    score = _mna_target_score(
        valuation=1.0, capacity=0.5, ownership=0.0, macro=1.0,
        w_valuation=0.35, w_capacity=0.25, w_ownership=0.25, w_macro=0.15,
    )
    # 100*(0.35*1 + 0.25*0.5 + 0.25*0 + 0.15*1) = 100*0.625 = 62.5
    assert score == pytest.approx(62.5)


def test_mna_target_score_null_when_any_factor_missing() -> None:
    assert _mna_target_score(
        valuation=None, capacity=0.5, ownership=0.5, macro=0.5,
        w_valuation=0.35, w_capacity=0.25, w_ownership=0.25, w_macro=0.15,
    ) is None


def test_build_populations_single_group_v1() -> None:
    """grouping seam: v1은 전체시장 한 그룹 — 모든 종목 값이 같은 population에."""
    rows = {
        "A": {"pbr": 1.0, "net_cash": 100},
        "B": {"pbr": 2.0, "net_cash": None},
        "C": {"pbr": None, "net_cash": 300},
    }
    pops = _build_populations(rows, group_of=lambda c: "_all")
    assert sorted(pops["_all"]["pbr"]) == [1.0, 2.0]  # None 제외
    assert sorted(pops["_all"]["net_cash"]) == [100, 300]


def test_build_populations_custom_grouping_seam() -> None:
    """grouping seam: group_of를 갈아끼우면(2-7 sector) population이 그룹별로 분리."""
    rows = {
        "A": {"pbr": 1.0}, "B": {"pbr": 2.0},  # 은행 버킷
        "C": {"pbr": 5.0}, "D": {"pbr": 6.0},  # 반도체 버킷
    }
    sector = {"A": "bank", "B": "bank", "C": "semi", "D": "semi"}
    pops = _build_populations(rows, group_of=lambda c: sector[c])
    assert sorted(pops["bank"]["pbr"]) == [1.0, 2.0]
    assert sorted(pops["semi"]["pbr"]) == [5.0, 6.0]


# ── Story 2.7: sector peer-group ──

def test_sector_bucket_two_digit_prefix() -> None:
    from app.analysis.mna_engine import _sector_bucket

    assert _sector_bucket("64191") == "64"  # 은행업
    assert _sector_bucket("26121") == "26"  # 반도체
    assert _sector_bucket(None) is None
    assert _sector_bucket("") is None
    assert _sector_bucket("A1") is None  # 숫자 아님 → 분류 불가(값 안 만듦)


# ── T4: 통합 테스트 (cross-sectional, SQLite in-memory + 뷰) ──

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


def _seed_corp(
    s: Session, code: str, *, market_cap: int, net_income: int = 100,
    cash: int = 500, total_debt: int = 200, largest: float = 40.0,
    treasury: float = 5.0,
) -> None:
    """FY2024(사업보고서) 실적 + 최신가 + 지분구조 시드. as_of=2025-*에서 look-ahead 안전."""
    s.add(Company(corp_code=code, corp_name=f"기업{code}", market="KOSPI"))
    s.add(Financial(
        corp_code=code, year=2024, quarter=4,
        revenue=1000, net_income=net_income, operating_income=150, depreciation=50,
        equity=1000, total_assets=2000, total_liabilities=800,
        cash=cash, total_debt=total_debt, dividend_total=20,
    ))
    s.add(Price(corp_code=code, date="2025-06-30", close=100,
                market_cap=market_cap, volume=10, trading_value=1000))
    s.add(Ownership(corp_code=code, as_of="2024-12-31",
                    largest_shareholder_pct=largest, treasury_stock_pct=treasury))


def _seed_macro(s: Session) -> None:
    # 과거 금리 시계열: 3.5 → 3.0 → 2.5 (현재 2.5 = 역사적 최저 → macro_score 1.0)
    for d, v in (("2024-01-31", 3.5), ("2024-07-31", 3.0), ("2025-01-31", 2.5)):
        s.add(MacroIndicator(indicator="base_rate", date=d, value=v, frequency="M"))


def test_run_cross_sectional_relative_ranking(engine) -> None:
    """AC2/3/4/5: 가장 저평가(시총 최소)가 valuation 1.0, 최고평가가 0.0 — 상대 순위."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed_corp(s, "00000001", market_cap=1000, largest=20.0, treasury=10.0)  # 싸고 뺏기쉬움
        _seed_corp(s, "00000002", market_cap=3000, largest=40.0, treasury=5.0)
        _seed_corp(s, "00000003", market_cap=9000, largest=60.0, treasury=1.0)  # 비싸고 방어적
        _seed_macro(s)
        s.commit()

        result = run("2025-12-31", session_factory=Session_)
        assert result.scored == 3
        assert result.complete is True  # 실패 0 → 스냅숏이 커밋됐다

        rows = {r.corp_code: r for r in s.scalars(select(MnaScore)).all()}
        # 시총 최소 → pbr·ev_ebitda 최소 → 역백분위 1.0
        assert rows["00000001"].valuation_score == pytest.approx(1.0)
        assert rows["00000003"].valuation_score == pytest.approx(0.0)
        # 지배구조: 최대주주 최저+자사주 최고 → 1.0
        assert rows["00000001"].ownership_score == pytest.approx(1.0)
        assert rows["00000003"].ownership_score == pytest.approx(0.0)
        # 매크로: 현재 금리 2.5가 역사적 최저 → 전 종목 공통 1.0
        assert rows["00000001"].macro_score == pytest.approx(1.0)
        assert rows["00000002"].macro_score == pytest.approx(1.0)
        # 총점: 최저평가+뺏기쉬움 종목이 최고점
        assert rows["00000001"].mna_target_score > rows["00000003"].mna_target_score


def test_run_null_factor_propagates_to_total(engine) -> None:
    """AC6(엄격): ownership 미공시 종목은 ownership_score null → mna_target_score도 null."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed_corp(s, "00000001", market_cap=1000)
        _seed_corp(s, "00000002", market_cap=3000)
        # 3번: ownership 없이(재무·가격만)
        s.add(Company(corp_code="00000003", corp_name="지분미공시", market="KOSPI"))
        s.add(Financial(
            corp_code="00000003", year=2024, quarter=4,
            revenue=1000, net_income=100, operating_income=150, depreciation=50,
            equity=1000, total_assets=2000, total_liabilities=800,
            cash=500, total_debt=200, dividend_total=20,
        ))
        s.add(Price(corp_code="00000003", date="2025-06-30", close=100,
                    market_cap=5000, volume=10, trading_value=1000))
        _seed_macro(s)
        s.commit()

        run("2025-12-31", session_factory=Session_)
        row = s.scalars(
            select(MnaScore).where(MnaScore.corp_code == "00000003")
        ).one()
        assert row.ownership_score is None
        assert row.mna_target_score is None  # 요소 하나라도 null → 전체 null
        assert row.valuation_score is not None  # 계산 가능한 요소는 채워짐


def test_run_lookahead_excludes_same_year_annual(engine) -> None:
    """2.1 look-ahead 패턴 재사용: 같은 해(2025) 사업보고서는 as_of=2025에서 안 보임."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed_corp(s, "00000001", market_cap=1000)
        _seed_corp(s, "00000002", market_cap=3000)
        # FY2025 사업보고서만 있는 종목(2024 없음) → as_of=2025-12-31에서 지표 없음
        s.add(Company(corp_code="00000003", corp_name="당해만", market="KOSPI"))
        s.add(Financial(
            corp_code="00000003", year=2025, quarter=4,
            revenue=1000, net_income=100, operating_income=150, depreciation=50,
            equity=1000, total_assets=2000, total_liabilities=800,
            cash=500, total_debt=200, dividend_total=20,
        ))
        s.add(Price(corp_code="00000003", date="2025-06-30", close=100,
                    market_cap=5000, volume=10, trading_value=1000))
        _seed_macro(s)
        s.commit()

        run("2025-12-31", session_factory=Session_)
        row = s.scalars(
            select(MnaScore).where(MnaScore.corp_code == "00000003")
        ).one_or_none()
        # 지표·지분 전무 → 전 요소 null(매크로만 남음) → 행 미생성 or 전부 null
        if row is not None:
            assert row.valuation_score is None
            assert row.mna_target_score is None


def test_run_is_idempotent(engine) -> None:
    """AC7: 재실행 시 중복 없음."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed_corp(s, "00000001", market_cap=1000)
        _seed_corp(s, "00000002", market_cap=3000)
        _seed_macro(s)
        s.commit()
        run("2025-12-31", session_factory=Session_)
        run("2025-12-31", session_factory=Session_)
        rows = s.scalars(select(MnaScore)).all()
        assert len(rows) == 2


def test_run_rejects_malformed_as_of(engine) -> None:
    """2.1 패턴 재사용: as_of 포맷 fail-fast."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            run("2025-7-1", session_factory=Session_)


def test_run_macro_latest_null_propagates_not_substituted(engine) -> None:
    """[리뷰 High] 최신 macro 관측이 null이면 과거 non-null로 몰래 대체하지 않고
    macro_score도 null(AC6 엄격 null). 요소별 점수는 채워지되 총점은 null."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed_corp(s, "00000001", market_cap=1000)
        _seed_corp(s, "00000002", market_cap=3000)
        s.add(MacroIndicator(indicator="base_rate", date="2024-06-30", value=3.0, frequency="M"))
        s.add(MacroIndicator(indicator="base_rate", date="2025-01-31", value=2.5, frequency="M"))
        s.add(MacroIndicator(indicator="base_rate", date="2025-06-30", value=None, frequency="M"))  # 최신=null
        s.commit()

        run("2025-12-31", session_factory=Session_)
        row = s.scalars(select(MnaScore)).first()
        assert row.macro_score is None  # 2.5로 대체되면 안 됨
        assert row.valuation_score is not None
        assert row.mna_target_score is None


def test_run_rejects_calendar_invalid_as_of(engine) -> None:
    """[리뷰 Med] 정규식은 통과하지만 달력상 무효한 날짜(2025-02-30) 거부."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        with pytest.raises(ValueError):
            run("2025-02-30", session_factory=Session_)


def test_run_guards_against_mass_delete_on_empty_inputs(engine) -> None:
    """[리뷰 Med] metrics·ownership이 통째로 비면(업스트림 장애 가능성) 기존 점수를
    삭제하지 않고 스킵 — reconciliation 대량 오삭제 방어."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        s.add(Company(corp_code="00000001", corp_name="기존점수"))
        s.add(MnaScore(corp_code="00000001", as_of="2025-12-31",
                       mna_target_score=70.0, valuation_score=0.7,
                       capacity_score=0.7, ownership_score=0.7, macro_score=0.7))
        s.commit()

        result = run("2025-12-31", session_factory=Session_)  # 입력 데이터 전무
        assert result.scored == 0
        assert s.scalars(select(MnaScore)).one_or_none() is not None  # 안 지워짐


def test_run_sector_peer_percentile_and_fallback(engine) -> None:
    """2.7 AC1/3/4: peer 충분한 버킷은 업종 내 백분위, 미달 버킷은 시장 폴백, basis 저장.

    mna_peer_min=2로 낮춰 반도체 버킷(2종목)은 sector, 단독 버킷(1종목)은 폴백을 검증.
    """
    from app.config import settings as cfg

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        # 반도체(26) 2종목: 시총 1000 vs 9000 — 시장 전체가 아니라 '둘 사이' 백분위여야 함
        _seed_corp(s, "00000001", market_cap=1000)
        _seed_corp(s, "00000002", market_cap=9000)
        # 유통(47) 1종목: 버킷 peer 1 < min → 시장 폴백
        _seed_corp(s, "00000003", market_cap=3000)
        s.commit()
        from app.models import Company as _C
        for code, sec in (("00000001", "26121"), ("00000002", "26299"), ("00000003", "47111")):
            s.get(_C, code).sector = sec
        _seed_macro(s)
        s.commit()

        import pytest as _pytest
        orig = cfg.mna_peer_min
        try:
            cfg.mna_peer_min = 2
            run("2025-12-31", session_factory=Session_)
        finally:
            cfg.mna_peer_min = orig

        rows = {r.corp_code: r for r in s.scalars(select(MnaScore)).all()}
        # 반도체 버킷 내 상대화: 1번(저평가)=1.0, 2번(고평가)=0.0
        assert rows["00000001"].valuation_score == _pytest.approx(1.0)
        assert rows["00000002"].valuation_score == _pytest.approx(0.0)
        assert rows["00000001"].population_basis == "sector:26"
        assert rows["00000002"].population_basis == "sector:26"
        # 유통 1종목: 버킷 미달 → 시장(3종목) 폴백 — 시총 3000은 시장 중간
        assert rows["00000003"].population_basis == "market_fallback"
        assert rows["00000003"].valuation_score == _pytest.approx(0.5)
        # ownership은 업종 무관(시장 모집단) 유지 — basis와 무관하게 계산됨
        assert rows["00000001"].ownership_score is not None


def test_run_sector_null_uses_market_basis(engine) -> None:
    """2.7 AC5: sector 없는 종목은 market basis(정직 분류)."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed_corp(s, "00000001", market_cap=1000)  # _seed_corp은 sector 미지정
        _seed_corp(s, "00000002", market_cap=9000)
        _seed_macro(s)
        s.commit()
        run("2025-12-31", session_factory=Session_)
        rows = s.scalars(select(MnaScore)).all()
        assert all(r.population_basis == "market" for r in rows)


def test_run_macro_uses_only_history_before_as_of(engine) -> None:
    """AC4: as_of 이후 금리는 백분위 모집단에서 제외(look-ahead 방지)."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed_corp(s, "00000001", market_cap=1000)
        _seed_corp(s, "00000002", market_cap=3000)
        # as_of=2024-12-31 기준: 2024년 관측 2개(3.5, 3.0)만 유효, 2025-01의 2.5는 미래
        for d, v in (("2024-01-31", 3.5), ("2024-07-31", 3.0), ("2025-01-31", 2.5)):
            s.add(MacroIndicator(indicator="base_rate", date=d, value=v, frequency="M"))
        s.commit()

        run("2024-12-31", session_factory=Session_)
        row = s.scalars(select(MnaScore)).first()
        # 유효 모집단 [3.5, 3.0], 현재값 3.0(최저) → pct_rank_low = 1.0
        # (미래의 2.5가 포함됐다면 3.0은 최저가 아니어서 1.0이 안 나옴)
        assert row.macro_score == pytest.approx(1.0)


# ── Story 4-2: 전량 원자성 (gap_engine의 종목별 커밋과 의도적으로 반대) ──

def test_run_rolls_back_entirely_on_any_failure(engine, monkeypatch) -> None:
    """AC2: 한 종목이라도 실패하면 **전량 롤백** — 부분 커밋이 0건이어야 한다.

    백분위 순위는 부분적으로 옳을 수 없다. 두 종목 중 하나만 새 모집단 기준으로 쓰이면
    남은 한 줄과 등수를 견줄 수 없으므로, 그런 표는 만들지 않는 쪽을 택했다.
    """
    from app.analysis import mna_engine

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed_corp(s, "00000001", market_cap=1000)
        _seed_corp(s, "00000002", market_cap=3000)
        _seed_macro(s)
        s.commit()

    real_upsert = mna_engine.repo.upsert_mna_score
    calls: list[str] = []

    def flaky_upsert(session, rec):
        calls.append(rec["corp_code"])
        if len(calls) == 2:  # 첫 종목은 성공시키고 두 번째에서 터뜨린다
            raise RuntimeError("boom")
        return real_upsert(session, rec)

    monkeypatch.setattr(mna_engine.repo, "upsert_mna_score", flaky_upsert)
    result = run("2025-12-31", session_factory=Session_)

    assert len(calls) == 2  # 실제로 첫 종목은 upsert까지 갔다
    assert result.complete is False
    with Session_() as s:
        assert s.scalars(select(MnaScore)).all() == []  # 그럼에도 DB엔 한 줄도 없다


def test_run_reports_failures_even_though_rolled_back(engine, monkeypatch) -> None:
    """AC3: 롤백돼도 (corp_code, 사유)는 남는다 — gap에서 원자성을 기각한 사유의 해소책."""
    from app.analysis import mna_engine

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed_corp(s, "00000001", market_cap=1000)
        _seed_corp(s, "00000002", market_cap=3000)
        _seed_macro(s)
        s.commit()

    def always_fail(session, rec):
        raise RuntimeError(f"실패-{rec['corp_code']}")

    monkeypatch.setattr(mna_engine.repo, "upsert_mna_score", always_fail)
    result = run("2025-12-31", session_factory=Session_)

    assert result.complete is False
    assert "실패-00000001" in result.failed[0][1]  # 사유가 지워지지 않는다
    # 롤백됐으므로 '성공했다'는 숫자를 남기지 않는다
    assert result.scored == 0
    assert result.succeeded == []


def test_run_preserves_prior_snapshot_on_failure(engine, monkeypatch) -> None:
    """AC2 보강: 실패 시 이전 실행의 점수가 그대로 보존된다(반쪽 갱신 금지)."""
    from app.analysis import mna_engine

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed_corp(s, "00000001", market_cap=1000)
        _seed_corp(s, "00000002", market_cap=3000)
        _seed_macro(s)
        s.commit()

    run("2025-12-31", session_factory=Session_)  # 1차: 정상
    with Session_() as s:
        before = {r.corp_code: r.mna_target_score for r in s.scalars(select(MnaScore)).all()}
    assert len(before) == 2

    def always_fail(session, rec):
        raise RuntimeError("boom")

    monkeypatch.setattr(mna_engine.repo, "upsert_mna_score", always_fail)
    assert run("2025-12-31", session_factory=Session_).complete is False

    with Session_() as s:
        after = {r.corp_code: r.mna_target_score for r in s.scalars(select(MnaScore)).all()}
    assert after == before  # 1차 스냅숏 그대로


def test_run_owns_session_and_commits(engine) -> None:
    """AC1: 호출자가 커밋하지 않아도 저장된다 — flush만 하던 기존 결함의 회귀 테스트."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed_corp(s, "00000001", market_cap=1000)
        _seed_corp(s, "00000002", market_cap=3000)
        _seed_macro(s)
        s.commit()

    run("2025-12-31", session_factory=Session_)  # 호출자는 아무 커밋도 하지 않는다

    with Session_() as s:  # 완전히 새 세션에서 보인다 = 정말 커밋됐다
        assert len(s.scalars(select(MnaScore)).all()) == 2


def test_db_error_aborts_loop_instead_of_logging_noise(engine) -> None:
    """DB 오류는 즉시 중단 — 세션이 죽은 뒤의 실패 사유는 정보가 아니라 노이즈다.

    실측(2026-07-22): 첫 종목에서 IntegrityError가 나면 나머지 종목은 전부
    "Can't operate on closed transaction"으로 실패한다. 그 목록은 어느 종목이 진짜
    문제였는지를 가리므로, 진짜 사유 1건만 남기고 목록이 불완전함을 aborted_early로 알린다.
    """
    from app.analysis import mna_engine

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        for i, cap in enumerate((1000, 3000, 5000, 7000), start=1):
            _seed_corp(s, f"0000000{i}", market_cap=cap)
        _seed_macro(s)
        s.commit()

    real = mna_engine.repo.upsert_mna_score
    calls = {"n": 0}

    def db_error_upsert(session, rec):
        calls["n"] += 1
        if calls["n"] == 1:  # NOT NULL 위반으로 진짜 DB 오류를 만든다
            session.add(MnaScore(corp_code=None, as_of=rec["as_of"]))
            session.flush()
        return real(session, rec)

    monkeypatch_target = mna_engine.repo
    original = monkeypatch_target.upsert_mna_score
    monkeypatch_target.upsert_mna_score = db_error_upsert
    try:
        result = run("2025-12-31", session_factory=Session_)
    finally:
        monkeypatch_target.upsert_mna_score = original

    assert result.aborted_early is True
    assert len(result.failed) == 1  # 노이즈 3건이 붙지 않는다
    assert "NOT NULL" in result.failed[0][1]
    assert calls["n"] == 1  # 세션이 죽은 뒤 다음 종목을 시도하지 않았다
    with Session_() as s:
        assert s.scalars(select(MnaScore)).all() == []  # 전량 롤백은 그대로


def test_engine_bug_aborts_instead_of_inflating_per_corp_failures(engine, monkeypatch) -> None:
    """비-SQLAlchemy 예외는 **엔진 버그**로 보고 즉시 중단한다(코드리뷰 2026-07-22 Med).

    루프 안은 이미 메모리에 올린 값으로 하는 순수 계산이라, 예상 가능한 종목별 실패 유형이
    없다. 이전 구현은 사유를 담고 계속 돌았는데 — 그러면 리팩터링 실수 하나가 33종목의 독립
    데이터 오류처럼 부풀려진다. DB 오류에서 고쳤던 "노이즈 실패 목록" 문제의 재발이었다.

    (이 테스트는 이전 `test_non_db_error_still_collects_all_reasons`를 대체한다 — 그 테스트가
    고정하던 "끝까지 모은다"가 틀린 계약이었다.)
    """
    from app.analysis import mna_engine

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        for i, cap in enumerate((1000, 3000, 5000), start=1):
            _seed_corp(s, f"0000000{i}", market_cap=cap)
        _seed_macro(s)
        s.commit()

    calls = {"n": 0}

    def buggy(session, rec):
        calls["n"] += 1
        raise AttributeError("리팩터링 회귀를 흉내낸 엔진 버그")

    monkeypatch.setattr(mna_engine.repo, "upsert_mna_score", buggy)
    result = run("2025-12-31", session_factory=Session_)

    assert calls["n"] == 1              # 3종목 반복하지 않고 첫 종목에서 멈춘다
    assert len(result.failed) == 1      # 같은 버그가 3건으로 부풀지 않는다
    assert result.aborted_early is True
    assert result.fatal_error is not None
    assert "AttributeError" in result.fatal_error  # 데이터 문제가 아니라 코드 결함임을 명시
    assert result.complete is False
    with Session_() as s:
        assert s.scalars(select(MnaScore)).all() == []  # 전량 롤백은 그대로


# ── 코드리뷰 2026-07-22 후속: publishable · 입력 전무 · finite 판정 ──

def test_partial_run_is_complete_but_not_publishable(engine) -> None:
    """[리뷰 High-1] 부분 실행은 성공(complete)해도 게시 불가(publishable=False).

    이전엔 두 개념이 `complete` 하나에 섞여 있어, 세대 혼재를 만들면서도 complete=True를
    반환했다. docstring은 "전 종목이 동일 모집단 기준"을 보장한다고 말하고 있었다.
    """
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        for i, cap in enumerate((1000, 3000, 9000), start=1):
            _seed_corp(s, f"0000000{i}", market_cap=cap)
        _seed_macro(s)
        s.commit()

    partial = run("2025-12-31", ["00000001"], session_factory=Session_)
    assert partial.complete is True         # 실행 자체는 성공했다
    assert partial.partial_scope is True
    assert partial.publishable is False     # 그러나 순위표는 세대가 섞였다

    full = run("2025-12-31", session_factory=Session_)
    assert full.complete is True
    assert full.partial_scope is False
    assert full.publishable is True


def test_empty_inputs_are_fatal_not_silent_success(engine) -> None:
    """[리뷰 High-3] 유니버스는 있는데 입력이 전무하면 ETL 장애다 — 정상 완료로 보고하지 않는다.

    단, 기존 스냅숏은 절대 지우지 않는다(대량 오삭제 방어는 그대로).
    """
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        s.add(Company(corp_code="00000001", corp_name="기존점수"))
        s.add(MnaScore(corp_code="00000001", as_of="2025-12-31", mna_target_score=70.0,
                       valuation_score=0.7, capacity_score=0.7,
                       ownership_score=0.7, macro_score=0.7))
        s.commit()

    result = run("2025-12-31", session_factory=Session_)

    assert result.complete is False          # 이전엔 True였다
    assert result.publishable is False
    assert result.fatal_error is not None
    assert "전무" in result.fatal_error
    with Session_() as s:                    # 기존 행은 보존
        assert s.scalars(select(MnaScore)).one_or_none() is not None


def test_empty_universe_is_not_an_error(engine) -> None:
    """유니버스 자체가 비었으면 진짜로 할 일이 없다 — 이건 장애가 아니다(위와 구분)."""
    Session_ = sessionmaker(bind=engine)
    result = run("2025-12-31", session_factory=Session_)
    assert result.complete is True
    assert result.fatal_error is None


def test_nan_inf_not_counted_as_peers(engine) -> None:
    """[리뷰 Med-5] sector 준비 판정과 백분위가 같은 '유효값' 정의를 쓴다.

    이전엔 population이 None만 걸러 NaN/Inf를 peer로 세는 바람에, 실제 유효 peer가 부족한
    버킷이 sector 모집단으로 판정돼 시장 폴백을 놓치고 점수가 통째로 None이 될 수 있었다.
    """
    from app.analysis.mna_engine import _build_populations, _is_finite_value, _percentile_rank

    rows = {"A": {"pbr": 1.0}, "B": {"pbr": float("nan")}, "C": {"pbr": float("inf")}}
    pops = _build_populations(rows, group_of=lambda c: "g")
    assert pops["g"]["pbr"] == [1.0]  # NaN·Inf는 애초에 모집단에 들어가지 않는다

    # 준비 판정이 세는 개수 == 백분위가 실제로 쓰는 개수
    assert len(pops["g"]["pbr"]) == len([v for v in pops["g"]["pbr"] if _is_finite_value(v)])
    assert _percentile_rank(1.0, pops["g"]["pbr"]) is None  # 유효 peer<2 → 계산 불가

    assert _is_finite_value(None) is False
    assert _is_finite_value("문자열") is False  # 비수치도 배제(비교 연산이 성립하지 않음)
