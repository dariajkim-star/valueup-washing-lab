"""look-ahead 단일 정의처 검증 (0029/0030).

이 파일이 지키는 계약 셋:
  ① `available_at`을 아는 행은 **날짜로** 판정한다 — 연도 휴리스틱을 넘어선다.
  ② 모르는 행(null)은 **연도 휴리스틱으로 폴백**한다 — 미수집을 조회에서 떨구지 않는다.
  ③ SQL판과 파이썬판이 **같은 답**을 낸다 — 두 벌 정의가 갈라지는 것이 이 프로젝트가
     `plan_own_gap`(0024)·`plan_selection`(0016)에서 반복해 경계해온 실패다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.analysis import lookahead
from app.models import Base, Company, Financial


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:", future=True,
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    return eng


# (available_at, year, quarter) — 실측에서 뽑은 형태들
CASES = [
    # 2024 사업보고서가 2025-03-06 공시(기아 실측). 연도 휴리스틱은 as_of=2025-01-15에
    # 이 행을 통과시키지만, 실제로는 아직 공시 전이다 — 여기가 0029가 닫은 구멍.
    ("2025-03-06", 2024, 4),
    ("2024-03-06", 2023, 4),
    # 비12월 결산(신영증권 3월 결산 — 2024 회계연도가 2024-06-12 공시)
    ("2024-06-12", 2024, 4),
    # 미수집 — 폴백 대상
    (None, 2024, 4),
    (None, 2023, 4),
]
AS_OFS = ["2024-02-01", "2024-06-30", "2025-01-15", "2025-03-31", "2026-07-13"]


def _seed(s: Session) -> None:
    """케이스마다 corp를 나눈다 — (corp_code, year, quarter)가 자연키라
    같은 회사에 2024·Q4를 두 벌 넣을 수 없다."""
    for i, (av, y, q) in enumerate(CASES):
        code = f"0000000{i + 1}"
        s.add(Company(corp_code=code, corp_name=f"케이스{i + 1}"))
        s.add(Financial(
            corp_code=code, year=y, quarter=q,
            available_at=av, net_income=100, equity=1000,
        ))
    s.commit()


def test_known_date_beats_year_heuristic() -> None:
    """① 공시일을 알면 그 날짜로 판정한다 — 연도가 과거라는 사실이 공시됐다는 뜻은 아니다."""
    # 2024 재무, 2025-03-06 공시. as_of가 그 사이면 **못 본다**.
    assert lookahead.is_available("2025-03-06", 2024, 4, "2025-01-15") is False
    # 휴리스틱만이었다면 통과했을 자리다(year 2024 < as_of_year 2025)
    assert (2024 < 2025) is True
    # 공시 이후면 본다
    assert lookahead.is_available("2025-03-06", 2024, 4, "2025-03-31") is True
    # 공시 당일도 본다(<=)
    assert lookahead.is_available("2025-03-06", 2024, 4, "2025-03-06") is True


def test_null_falls_back_to_year_heuristic() -> None:
    """② 미수집(null)은 기존 휴리스틱 그대로 — 모르는 행을 조회에서 떨구지 않는다(NFR2)."""
    assert lookahead.is_available(None, 2024, 4, "2025-01-15") is True   # year < as_of_year
    assert lookahead.is_available(None, 2025, 4, "2025-06-30") is False  # 같은 해 사업보고서
    assert lookahead.is_available(None, 2025, 3, "2025-06-30") is True   # 같은 해 분기보고서


def test_non_december_fiscal_year() -> None:
    """비12월 결산: 2024 회계연도가 2024-06-12에 공시된다(신영증권 실측).

    휴리스틱은 이 행을 2024년 내내 막지만(year == as_of_year AND quarter == 4),
    실제로는 6월부터 볼 수 있다. 날짜를 알면 그 사실이 이긴다.
    """
    assert lookahead.is_available("2024-06-12", 2024, 4, "2024-09-01") is True
    assert lookahead.is_available(None, 2024, 4, "2024-09-01") is False  # 휴리스틱은 막는다


@pytest.mark.parametrize("as_of", AS_OFS)
def test_sql_and_python_agree(engine, as_of: str) -> None:
    """③ SQL판 ↔ 파이썬판 전건 대조. 하나라도 갈리면 두 정의가 갈라진 것이다."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
        rows = s.execute(text(
            "SELECT id, available_at, year, quarter FROM financials"
        )).mappings().all()
        passing_sql = {
            r["id"] for r in s.execute(
                text(f"SELECT id FROM financials WHERE {lookahead.sql_where()}"),
                lookahead.params(as_of),
            ).mappings().all()
        }
    passing_py = {
        r["id"] for r in rows
        if lookahead.is_available(r["available_at"], r["year"], r["quarter"], as_of)
    }
    assert passing_sql == passing_py, f"as_of={as_of}에서 SQL과 파이썬 판정이 갈렸다"


def test_sql_prefix_for_joined_queries(engine) -> None:
    """별칭이 붙은 조회(export의 financials f JOIN …)에서도 같은 조건이 나온다."""
    assert "f.available_at" in lookahead.sql_where("f.")
    assert "f.year" in lookahead.sql_where("f.")
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
        n = s.execute(
            text(f"SELECT COUNT(*) FROM financials f WHERE {lookahead.sql_where('f.')}"),
            lookahead.params("2026-07-13"),
        ).scalar_one()
    assert n == len(CASES)  # 2026-07-13이면 전부 공시 이후


def test_gate_is_not_a_silent_year_filter(engine) -> None:
    """회귀 방지: 게이트가 available_at을 무시하고 연도만 보면 이 테스트가 깨진다."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
        n = s.execute(
            text(f"SELECT COUNT(*) FROM financials WHERE {lookahead.sql_where()}"),
            lookahead.params("2025-01-15"),
        ).scalar_one()
    # 2025-01-15 기준: 2024-03-06(2023) ✓ · 2024-06-12(2024) ✓ · null 2023 ✓ · null 2024 ✓
    # 2025-03-06(2024) ✗ ← 날짜를 봐야만 걸러진다
    assert n == len(CASES) - 1
