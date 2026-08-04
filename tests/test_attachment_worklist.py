"""첨부 작업 목록 — **받을 수 있는 것만 부른다**(2026-08-04).

이 파일이 존재하는 이유: 이 도구에 테스트가 **0건**이었고, 그래서 목록이
129건 중 101개사에게 **존재하지 않는 문서를 찾아오라고** 말하는 동안 아무도 몰랐다.
같은 계열의 실패를 이미 세 번 겪었다(워싱 플래그·`washing_only` 토글·
`isUnsupportedSector`) — 도구가 사실이 아닌 것을 말하는데 아무도 세지 않는 것.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.analysis.plan_selection import AXIS_TARGETS, EXEMPT_SHORT_FORM, NO_TARGETS
from app.ingest.attachment_worklist import build_worklist
from app.models import Base, Company, ValueupPlan

# 실측 문안(101개사가 쓴 형태)
EXEMPT_TEXT = (
    "1. 조세특례제한법 제104조의27에 따른 고배당기업에 해당하여 "
    "별도의 기업가치 제고 계획 첨부 없이 주요 내용을 기재하였습니다."
)
REFERENCE_TEXT = "상세한 내용은 첨부된 '기업가치 제고 계획'을 참고하시기 바랍니다."


@pytest.fixture()
def session():
    eng = create_engine(
        "sqlite:///:memory:", future=True,
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng)() as s:
        yield s


def _add(s: Session, code: str, name: str, signal: str, raw: str, **kw) -> None:
    s.add(Company(corp_code=code, corp_name=name))
    s.add(ValueupPlan(
        corp_code=code, disclosure_date="2026-03-27", rcept_no=f"2026032780{code[-4:]}",
        body_signal=signal, raw_text=raw, **kw,
    ))


def test_exempt_short_form_is_not_listed(session: Session) -> None:
    """회사가 '첨부 없이 기재'라 말한 공시는 목록에 없다 — 받으러 갈 곳이 없다.

    실측: E1·LX인터내셔널·SBS·SIMPAC·SNT홀딩스 등 101개사가 이 부류였고
    전부 목록 상단에 올라와 있었다.
    """
    _add(session, "00000001", "(주)E1", EXEMPT_SHORT_FORM, EXEMPT_TEXT)
    session.commit()
    assert build_worklist(session) == []


def test_real_attachment_reference_is_listed(session: Session) -> None:
    """진짜 첨부 참조는 목록에 남는다 — 이쪽이 첨부 수집의 실제 대상이다(실측 13개사)."""
    _add(session, "00000002", "(주)포스코퓨처엠", NO_TARGETS, REFERENCE_TEXT)
    session.commit()
    rows = build_worklist(session)
    assert [r["corp_name"] for r in rows] == ["(주)포스코퓨처엠"]
    assert rows[0]["axes"] == 0


def test_disclosed_plan_is_not_listed(session: Session) -> None:
    """축을 확보한 공시는 첨부가 필요 없다(기존 계약 — 회귀 방지)."""
    _add(session, "00000003", "(주)공시양호", AXIS_TARGETS, "목표 ROE 10% 이상",
         target_roe=10.0)
    session.commit()
    assert build_worklist(session) == []


def test_mixed_population_only_keeps_obtainable(session: Session) -> None:
    """섞어 넣어도 '받을 수 있는 것'만 남는다 — 이 파일의 핵심 계약."""
    _add(session, "00000001", "(주)면제A", EXEMPT_SHORT_FORM, EXEMPT_TEXT)
    _add(session, "00000004", "(주)면제B", EXEMPT_SHORT_FORM,
         EXEMPT_TEXT.replace("첨부 없이", "첨부없이"))
    _add(session, "00000002", "(주)참조", NO_TARGETS, REFERENCE_TEXT)
    _add(session, "00000003", "(주)공시양호", AXIS_TARGETS, "목표 ROE 10% 이상",
         target_roe=10.0)
    session.commit()
    assert [r["corp_name"] for r in build_worklist(session)] == ["(주)참조"]
