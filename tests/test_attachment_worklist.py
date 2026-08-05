"""첨부 작업 목록 — **받을 수 있는 것만 부른다**(2026-08-04, 2026-08-05 보강).

이 파일이 존재하는 이유: 이 도구에 테스트가 **0건**이었고, 그래서 목록이
129건 중 101개사에게 **존재하지 않는 문서를 찾아오라고** 말하는 동안 아무도 몰랐다.
같은 계열의 실패를 이미 세 번 겪었다(워싱 플래그·`washing_only` 토글·
`isUnsupportedSector`) — 도구가 사실이 아닌 것을 말하는데 아무도 세지 않는 것.

**첫 테스트가 절반만 잡았다(2026-08-05)**: 여기 있던 케이스는 전부
`body_signal='exempt_short_form'`을 **직접 넣어** 만든 것이라, 실제 파이프라인에서
그 신호가 붙지 않는 조합(목표를 공시한 회사가 첨부 부존재도 선언한 경우)을 못 봤다.
실측하니 7건이 그렇게 새고 있었다. 그래서 이제 테스트는 신호를 손으로 넣지 않고
**원문에서 판정되게** 둔다 — 픽스처가 파이프라인보다 친절하면 결함이 통과한다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.analysis.plan_selection import AXIS_TARGETS, NO_TARGETS, OTHER_METRIC, REFILING
from app.analysis.plan_signals import declares_no_attachment
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
    """수집 파이프라인이 하는 그대로 적재한다.

    `attachment_absent`를 **원문에서 판정해** 넣는 것이 핵심이다(dart_valueup과 같은
    호출). 손으로 True를 넣으면 픽스처가 파이프라인보다 친절해져, 실제로 새는 조합을
    테스트가 못 본다 — 2026-08-05에 정확히 그 일이 있었다.
    """
    s.add(Company(corp_code=code, corp_name=name))
    kw.setdefault("attachment_absent", declares_no_attachment(raw) if raw else None)
    s.add(ValueupPlan(
        corp_code=code, disclosure_date="2026-03-27", rcept_no=f"2026032780{code[-4:]}",
        body_signal=signal, raw_text=raw, **kw,
    ))


def test_exempt_short_form_is_not_listed(session: Session) -> None:
    """회사가 '첨부 없이 기재'라 말한 공시는 목록에 없다 — 받으러 갈 곳이 없다.

    실측: E1·LX인터내셔널·SBS·SIMPAC·SNT홀딩스 등 101개사가 이 부류였고
    전부 목록 상단에 올라와 있었다.
    """
    _add(session, "00000001", "(주)E1", NO_TARGETS, EXEMPT_TEXT)
    session.commit()
    assert build_worklist(session) == []


def test_declaration_is_not_hidden_by_other_metric(session: Session) -> None:
    """**다른 지표로 목표를 공시하면서** 첨부 부존재도 선언한 공시 — 실측 6건.

    이것이 2026-08-04 수정을 빠져나간 경로다: `body_signal`은 우선순위 사다리라
    other_metric이 이기고, exempt 칸에 도달하지 못했다. 축을 나눈 뒤로는 신호가
    무엇이든 선언은 선언이다.
    """
    _add(session, "00000005", "(주)도화엔지니어링", OTHER_METRIC,
         EXEMPT_TEXT + "\n'28년 EBITDA Margin 10% 중반 이상 목표")
    session.commit()
    assert build_worklist(session) == []


def test_declaration_is_not_hidden_by_refiling(session: Session) -> None:
    """재공시이면서 첨부 부존재를 선언한 공시 — 실측 2건(신도리코 등).

    여기서 우선순위를 뒤집는 처방을 썼다면 선택 규칙이 깨졌다(재공시가 가리킨 실제
    계획으로 못 감). 직교 컬럼이라 둘 다 성립한다.
    """
    _add(session, "00000006", "(주)신도리코", REFILING,
         EXEMPT_TEXT + "\n旣공시(2026.2.6) 내용 참조")
    session.commit()
    assert build_worklist(session) == []


def test_unbackfilled_row_still_filtered(session: Session) -> None:
    """컬럼이 비어 있어도(백필 전) 원문으로 판정해 거른다.

    백필을 잊었다는 이유로 목록이 다시 없는 문서를 부르면 안 된다 — 이 도구의 실패는
    항상 '사람을 헛걸음시키는' 형태로 나타난다.
    """
    _add(session, "00000007", "(주)미백필", NO_TARGETS, EXEMPT_TEXT,
         attachment_absent=None)
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
    _add(session, "00000001", "(주)면제A", NO_TARGETS, EXEMPT_TEXT)
    _add(session, "00000004", "(주)면제B", NO_TARGETS,
         EXEMPT_TEXT.replace("첨부 없이", "첨부없이"))
    _add(session, "00000002", "(주)참조", NO_TARGETS, REFERENCE_TEXT)
    _add(session, "00000003", "(주)공시양호", AXIS_TARGETS, "목표 ROE 10% 이상",
         target_roe=10.0)
    session.commit()
    assert [r["corp_name"] for r in build_worklist(session)] == ["(주)참조"]
