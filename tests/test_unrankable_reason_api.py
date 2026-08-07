"""Story 6.4 — 순위 불가의 사유가 **서빙까지 관통하는가**(AC 1·2).

판정 자체는 `test_plan_signals.py`가 고정한다. 여기서는 그 값이 목록·상세 응답에
실제로 실려 나오는지만 본다 — 이 프로젝트가 반복해서 맞은 결함이 *"판정은 맞는데
화면에 배선되지 않아 조용히 침묵"*이었다(`exempt_short_form` 102건이 그랬다).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Company, ValueupPlan, ValueupScore
from app.sql_views import CREATE_PLAN_OWN_GAP, CREATE_VALUATION_METRICS

AS_OF = "2026-07-13"

DECL = ("조세특례제한법 제104조의27에 따른 고배당기업에 해당하여 별도의 기업가치 "
        "제고 계획 첨부 없이 주요 내용을 기재하였습니다.")
REF = "상세한 내용은 첨부된 '2024년 기업가치 제고 계획'을 참고하시기 바랍니다."
BARE = "기업가치 제고 계획을 공시합니다. 5. 관련 자료 \n게재일시 \n- \n관련 웹페이지 \n-"

# (corp_code, 이름, 원문, attachment_absent, 기대 사유)
CASES = (
    ("00000001", "선언사", DECL, True, "undisclosed"),
    ("00000002", "참조사", REF, False, "unreadable"),
    ("00000003", "무언급사", BARE, False, "unstated"),
    ("00000004", "축보유사", BARE, False, None),  # 순위 가능 → 사유 없음
)


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:", future=True,
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    with eng.connect() as conn:
        conn.execute(text(CREATE_VALUATION_METRICS))
        conn.execute(text(CREATE_PLAN_OWN_GAP))
        conn.commit()
    with Session(eng) as s:
        for code, name, raw, absent, _ in CASES:
            s.add(Company(corp_code=code, corp_name=name, market="KOSPI", sector="26100"))
            plan = ValueupPlan(
                corp_code=code, disclosure_date="2026-01-02", raw_text=raw,
                attachment_absent=absent,
                # 마지막 종목만 축을 하나 채운다 — 순위 대상이므로 사유가 없어야 한다.
                target_roe=10.0 if code == "00000004" else None,
            )
            s.add(plan)
            s.flush()
            s.add(ValueupScore(
                corp_code=code, as_of=AS_OF, execution_score=50.0,
                source_plan_id=plan.plan_id,
            ))
        s.commit()
    return eng


@pytest.fixture()
def client(engine, monkeypatch):
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    monkeypatch.setattr(db_module, "SessionLocal", sessionmaker(bind=engine, future=True))
    with TestClient(fastapi_app) as c:
        yield c


def test_screening_serves_unrankable_reason(client):
    """목록에 세 사유가 각각 실려 나온다."""
    r = client.get("/screening", params={"as_of": AS_OF, "size": 100})
    assert r.status_code == 200
    got = {i["corp_code"]: i["unrankable_reason"] for i in r.json()["items"]}
    for code, _name, _raw, _absent, expected in CASES:
        assert got[code] == expected, code


def test_rankable_plan_has_no_reason_in_serving(client):
    """축을 하나라도 공시했으면 순위 대상 — 사유 칸은 비어 있다(요약을 만들지 않는다)."""
    r = client.get("/screening", params={"as_of": AS_OF, "corp_code": "00000004"})
    assert r.json()["items"][0]["unrankable_reason"] is None


def test_unstated_is_not_collapsed_into_undisclosed(client):
    """**AC 4** — 근거가 없는 종목을 "회사가 안 냈다"로 세지 않는다.

    무언급을 미공시로 접으면 실측 67건이 근거 없이 신호로 승격된다. 그것이 세탁이다.
    """
    r = client.get("/screening", params={"as_of": AS_OF, "corp_code": "00000003"})
    assert r.json()["items"][0]["unrankable_reason"] == "unstated"


def test_standard_form_field_does_not_make_it_unreadable(client):
    """`게재일시`·`관련 웹페이지`는 519건 중 463건에 있는 서식 필드다.

    2026-07-28에 참조 검사를 폐기한 이유가 이것이었다 — 무언급사의 원문에 그 필드가
    들어 있는데도 `unreadable`이 되면, 그때 폐기한 규칙을 되살린 것이다.
    """
    r = client.get("/screening", params={"as_of": AS_OF, "corp_code": "00000003"})
    assert r.json()["items"][0]["unrankable_reason"] != "unreadable"
