"""Story 1.5 — 밸류업 공시 어댑터 파싱·멱등 upsert 검증 (라이브 키 없이 fixture)."""

from __future__ import annotations

import io
import zipfile

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.ingest.dart import DartAdapterError
from app.ingest.dart_valueup import (
    DartDocumentError,
    DartValueupAdapter,
    _parse_date,
    _strip_tags,
    _zip_to_text,
    parse_targets,
)
from app.models import Base, Company, ValueupPlan
from app.repositories.valueup_plan import upsert_valueup_plan

# 가짜 공시 원문(자유서식 텍스트)
SAMPLE = (
    "당사는 기업가치 제고 계획을 다음과 같이 공시합니다. "
    "목표 ROE 10% 이상을 2024년 ~ 2026년 기간 동안 달성하고, "
    "배당성향 30%를 목표로 합니다. 목표 PBR 1.0배. "
    "주주가치 제고를 위해 자기주식 취득 및 소각을 계획합니다."
)


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Company(corp_code="00000001", corp_name="테스트"))
        s.commit()
        yield s


def test_parse_targets_extracts_all() -> None:
    """AC2: raw_text에서 목표필드가 추출된다."""
    t = parse_targets(SAMPLE)
    assert t["target_roe"] == 10.0
    assert t["target_payout_ratio"] == 30.0
    assert t["target_pbr"] == 1.0
    assert t["period_start"] == "2024"
    assert t["period_end"] == "2026"
    assert t["buyback_planned"] is True


def test_parse_targets_missing_is_null() -> None:
    """AC3/NFR2: 목표 수치가 없으면 해당 필드 null, 수집 실패 없음."""
    t = parse_targets("기업가치 제고 계획 공시. 구체적 목표 수치는 추후 공시.")
    assert t["target_roe"] is None
    assert t["target_payout_ratio"] is None
    assert t["target_pbr"] is None
    assert t["period_start"] is None
    assert t["buyback_planned"] is None


def test_payout_only_matches_배당성향_not_주주환원율() -> None:
    """리뷰 E1: 주주환원율은 배당성향과 다른 지표 → target_payout_ratio에 넣지 않는다."""
    t = parse_targets("주주환원율 35%를 목표로 합니다.")  # 배당성향 언급 없음
    assert t["target_payout_ratio"] is None
    t2 = parse_targets("배당성향 25% 목표")
    assert t2["target_payout_ratio"] == 25.0


def test_zip_to_text_and_strip() -> None:
    """document.xml ZIP 해제 + 태그→개행(경계 보존). 비ZIP/빈은 DartDocumentError로 격리."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("doc.xml", "<DOCUMENT><P>목표 ROE 10%</P></DOCUMENT>".encode("utf-8"))
    text = _zip_to_text(buf.getvalue())
    assert "목표 ROE 10%" in text
    assert "<" not in text and ">" not in text
    # 비ZIP(오류 HTML/XML)·빈 응답은 '빈 원문'으로 오인하지 않고 예외로 격리
    with pytest.raises(DartDocumentError):
        _zip_to_text(b"not a zip")
    with pytest.raises(DartDocumentError):
        _zip_to_text(b"")
    # 태그 자리는 개행으로 → 셀/문단 경계 보존
    assert _strip_tags("<a>x</a><b>y</b>") == "x\ny"


def test_pbr_requires_bae_unit() -> None:
    """PBR은 '배' 단위 필수 — 연도·페이지번호를 PBR로 오탐하지 않음(G1)."""
    assert parse_targets("PBR 개선 2027년까지 추진")["target_pbr"] is None
    assert parse_targets("목표 PBR 1.5배")["target_pbr"] == 1.5
    assert parse_targets("PBR 200배")["target_pbr"] is None  # 비현실적 → 배제


def test_percent_point_not_absolute() -> None:
    """'%p'(퍼센트포인트 증감)를 절대목표로 오독하지 않음(G4)."""
    assert parse_targets("ROE 10%p 개선")["target_roe"] is None
    assert parse_targets("ROE 10% 이상")["target_roe"] == 10.0


def test_buyback_negation_and_past() -> None:
    """자사주 부정·과거 문맥은 False, 계획은 True, 미언급은 None(G5)."""
    assert parse_targets("자사주 취득 계획 없음")["buyback_planned"] is False
    assert parse_targets("자기주식 취득하지 않기로")["buyback_planned"] is False
    assert parse_targets("자사주 소각 계획")["buyback_planned"] is True
    assert parse_targets("배당 확대 예정")["buyback_planned"] is None


def test_period_order_validated() -> None:
    """목표기간 start<=end만 인정(역순 범위는 오탐이므로 null)(G6)."""
    assert parse_targets("2024~2026년")["period_start"] == "2024"
    t = parse_targets("2026~2024")
    assert t["period_start"] is None and t["period_end"] is None


def test_strip_tags_prevents_cross_cell_grab() -> None:
    """표 셀 경계(개행)를 넘어 인접 지표 %를 잡지 않는다(G2)."""
    doc = "<TABLE><TR><TD>ROE 개선</TD><TD>배당성향 30%</TD></TR></TABLE>"
    t = parse_targets(_strip_tags(doc))
    assert t["target_roe"] is None           # ROE 셀엔 %가 없음(개행 못 넘음)
    assert t["target_payout_ratio"] == 30.0   # 배당성향 셀에서만


def test_parse_date_strict() -> None:
    """날짜 엄격검증: 무효는 None(적재 제외)(G10)."""
    assert _parse_date("20240315") == "2024-03-15"
    assert _parse_date("20241399") is None  # 13월 99일
    assert _parse_date("2024") is None
    assert _parse_date("") is None
    assert _parse_date(None) is None


def test_upsert_full_replace_clears_stale(session: Session) -> None:
    """G9: 재파싱 null이 과거 오탐 non-null을 정정한다(유효 문서 기반 전체 교체)."""
    upsert_valueup_plan(session, {
        "corp_code": "00000001", "disclosure_date": "2024-03-15",
        "target_pbr": 2027.0, "raw_text": "old"})  # 최초 오탐 저장
    session.commit()
    upsert_valueup_plan(session, {
        "corp_code": "00000001", "disclosure_date": "2024-03-15",
        "target_pbr": None, "raw_text": "new"})  # 고쳐진 파서: null
    session.commit()
    obj = session.scalars(select(ValueupPlan)).one()
    assert obj.target_pbr is None  # 옛 오값 정정됨
    assert obj.raw_text == "new"


def test_fetch_isolates_document_failure(monkeypatch) -> None:
    """G7: 한 문서 실패가 그 종목의 다른 공시를 날리지 않는다(부분 보존)."""
    from pydantic import SecretStr

    from app.config import settings

    monkeypatch.setattr(settings, "dart_api_key", SecretStr("k"))
    adapter = DartValueupAdapter()
    listing = {"status": "000", "total_page": 1, "list": [
        {"report_nm": "기업가치 제고 계획", "rcept_no": "A", "rcept_dt": "20240301"},
        {"report_nm": "기업가치 제고 계획", "rcept_no": "B", "rcept_dt": "20240401"},
    ]}
    monkeypatch.setattr(adapter, "_get_json", lambda *a, **k: listing)

    def fake_doc(key, rcept_no):
        if rcept_no == "A":
            return "배당성향 20% 목표"
        raise DartDocumentError("boom")
    monkeypatch.setattr(adapter, "_fetch_document", fake_doc)

    raw = adapter.fetch("00000001", "20240101", "20241231")
    assert [p["disclosure_date"] for p in raw["plans"]] == ["2024-03-01"]  # A만 성공
    assert any(f[0] == "B" for f in raw["failed"])  # B는 격리 실패


def test_fetch_skips_invalid_date(monkeypatch) -> None:
    """무효 rcept_dt 공시는 자연키 붕괴 방지 위해 적재 제외(G10)."""
    from pydantic import SecretStr

    from app.config import settings

    monkeypatch.setattr(settings, "dart_api_key", SecretStr("k"))
    adapter = DartValueupAdapter()
    listing = {"status": "000", "total_page": 1, "list": [
        {"report_nm": "기업가치 제고 계획", "rcept_no": "X", "rcept_dt": "20241399"},
    ]}
    monkeypatch.setattr(adapter, "_get_json", lambda *a, **k: listing)
    raw = adapter.fetch("00000001", "20240101", "20241231")
    assert raw["plans"] == []
    assert any(f[0] == "X" for f in raw["failed"])


def test_normalize_preserves_raw_text() -> None:
    """AC2/AC3: normalize가 목표필드 + raw_text 원문을 레코드로 만든다."""
    raw = {
        "corp_code": "00000001",
        "plans": [
            {"disclosure_date": "2024-03-15", "report_nm": "기업가치 제고 계획",
             "raw_text": SAMPLE},
        ],
    }
    recs = DartValueupAdapter().normalize(raw)
    assert len(recs) == 1
    rec = recs[0]
    assert rec["corp_code"] == "00000001"
    assert rec["disclosure_date"] == "2024-03-15"
    assert rec["target_roe"] == 10.0
    assert rec["raw_text"] == SAMPLE  # 원문 보존


def test_upsert_idempotent_and_updates(session: Session) -> None:
    """AC4: (corp_code, disclosure_date) 자연키 멱등 — 재실행 중복 없음, 값 갱신."""
    adapter = DartValueupAdapter()
    raw = {
        "corp_code": "00000001",
        "plans": [
            {"disclosure_date": "2024-03-15", "raw_text": SAMPLE},
        ],
    }
    recs = adapter.normalize(raw)
    adapter.upsert(session, recs)
    session.commit()
    adapter.upsert(session, recs)  # 재실행
    session.commit()
    assert session.scalar(select(func.count()).select_from(ValueupPlan)) == 1

    recs[0]["target_roe"] = 12.5  # 값 변경 후 재적재
    adapter.upsert(session, recs)
    session.commit()
    obj = session.scalars(select(ValueupPlan)).one()
    assert obj.target_roe == 12.5
    assert obj.raw_text == SAMPLE


def test_multiple_disclosures_multiple_rows(session: Session) -> None:
    """리뷰 E2: 한 종목이 여러 공시(예고·본공시) → 날짜별 행."""
    adapter = DartValueupAdapter()
    raw = {
        "corp_code": "00000001",
        "plans": [
            {"disclosure_date": "2024-03-15", "raw_text": "배당성향 20% 목표"},
            {"disclosure_date": "2024-09-20", "raw_text": "배당성향 30% 목표"},
        ],
    }
    adapter.upsert(session, adapter.normalize(raw))
    session.commit()
    assert session.scalar(select(func.count()).select_from(ValueupPlan)) == 2


def test_fetch_without_key_raises(monkeypatch) -> None:
    """AC5: DART_API_KEY 미설정 시 명확한 에러(키/URL 미노출)."""
    from pydantic import SecretStr

    from app.config import settings

    monkeypatch.setattr(settings, "dart_api_key", SecretStr(""))
    with pytest.raises(DartAdapterError, match="DART_API_KEY"):
        DartValueupAdapter().fetch("00000001", "20240101", "20241231")
