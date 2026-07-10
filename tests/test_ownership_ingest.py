"""Story 1.6 — 지분구조 어댑터 계산·멱등 upsert 검증 (라이브 키 없이 fixture)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.ingest.dart import DartAdapterError
from app.ingest.dart_ownership import (
    DartOwnershipAdapter,
    _largest_shareholder_pct,
    _parse_ratio,
    _treasury_stock_pct,
)
from app.models import Base, Company, Ownership

# 가짜 hyslrSttus: 보통주 계 40% + 우선주 계 5%(무의결권, 선택되면 안 됨)
HYSLR = [
    {"nm": "홍길동", "relate": "본인", "stock_knd": "보통주",
     "trmend_posesn_stock_qota_rt": "30.00"},
    {"nm": "특수관계인A", "relate": "특수관계인", "stock_knd": "보통주",
     "trmend_posesn_stock_qota_rt": "10.00"},
    {"nm": "계", "relate": "-", "stock_knd": "보통주",
     "trmend_posesn_stock_qota_rt": "40.00"},
    {"nm": "계", "relate": "-", "stock_knd": "우선주",
     "trmend_posesn_stock_qota_rt": "5.00"},
]
# 가짜 stockTotqySttus: 합계 자기주식 100,000 / 발행총수 1,000,000 = 10%
STOCK = [
    {"se": "보통주", "istc_totqy": "900,000", "tesstk_co": "50,000"},
    {"se": "합계", "istc_totqy": "1,000,000", "tesstk_co": "100,000"},
]


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Company(corp_code="00000001", corp_name="테스트"))
        s.commit()
        yield s


def test_parse_ratio() -> None:
    assert _parse_ratio("12.34") == 12.34
    assert _parse_ratio("1,234.5") == 1234.5
    assert _parse_ratio("-") is None
    assert _parse_ratio("") is None
    assert _parse_ratio(None) is None
    assert _parse_ratio("abc") is None


def test_largest_uses_common_stock_gye() -> None:
    """M2: 보통주 '계'(40%)를 쓰고 우선주 '계'(5%)는 무시(의결권 기준)."""
    assert _largest_shareholder_pct(HYSLR) == 40.00
    assert _largest_shareholder_pct([]) is None


def test_treasury_uses_total_row() -> None:
    """합계 행 기준 자사주 비중 = 100,000 / 1,000,000 * 100 = 10%."""
    assert _treasury_stock_pct(STOCK) == 10.0
    # 발행총수 0 → 0 나눗셈 방어 → null
    assert _treasury_stock_pct([{"se": "합계", "istc_totqy": "0", "tesstk_co": "10"}]) is None
    assert _treasury_stock_pct([]) is None


def test_normalize_computes_both() -> None:
    """AC2: normalize가 largest_shareholder_pct·treasury_stock_pct를 계산."""
    raw = {"corp_code": "00000001", "as_of": "2024-12-31",
           "rows_hyslr": HYSLR, "rows_stock": STOCK}
    recs = DartOwnershipAdapter().normalize(raw)
    assert len(recs) == 1
    assert recs[0]["largest_shareholder_pct"] == 40.00
    assert recs[0]["treasury_stock_pct"] == 10.0


def test_normalize_no_disclosure_makes_no_row() -> None:
    """M3: 양 엔드포인트 모두 빈 응답이면 행을 만들지 않는다(no-data)."""
    raw = {"corp_code": "00000001", "as_of": "2024-12-31",
           "rows_hyslr": [], "rows_stock": []}
    assert DartOwnershipAdapter().normalize(raw) == []


def test_normalize_partial_fills_available() -> None:
    """AC3: 한쪽만 있으면 있는 값만 채우고 나머지는 null."""
    raw = {"corp_code": "00000001", "as_of": "2024-12-31",
           "rows_hyslr": [], "rows_stock": STOCK}
    recs = DartOwnershipAdapter().normalize(raw)
    assert recs[0]["largest_shareholder_pct"] is None
    assert recs[0]["treasury_stock_pct"] == 10.0


def test_upsert_idempotent_and_none_safe(session: Session) -> None:
    """AC4: (corp_code, as_of) 멱등 + None은 기존값 안 덮음."""
    adapter = DartOwnershipAdapter()
    raw = {"corp_code": "00000001", "as_of": "2024-12-31",
           "rows_hyslr": HYSLR, "rows_stock": STOCK}
    adapter.upsert(session, adapter.normalize(raw))
    session.commit()
    adapter.upsert(session, adapter.normalize(raw))  # 재실행
    session.commit()
    assert session.scalar(select(func.count()).select_from(Ownership)) == 1

    # None-safe: 이후 largest만 null인 레코드로 재적재해도 기존 40 유지
    adapter.upsert(session, [{"corp_code": "00000001", "as_of": "2024-12-31",
                              "largest_shareholder_pct": None,
                              "treasury_stock_pct": 12.0}])
    session.commit()
    obj = session.scalars(select(Ownership)).one()
    assert obj.largest_shareholder_pct == 40.00  # 안 덮임
    assert obj.treasury_stock_pct == 12.0         # 갱신됨


def test_fetch_without_key_raises(monkeypatch) -> None:
    """AC5: DART_API_KEY 미설정 시 명확한 에러(키/URL 미노출)."""
    from pydantic import SecretStr

    from app.config import settings

    monkeypatch.setattr(settings, "dart_api_key", SecretStr(""))
    with pytest.raises(DartAdapterError, match="DART_API_KEY"):
        DartOwnershipAdapter().fetch("00000001", "2024")


def test_fetch_rejects_bad_reprt_and_year(monkeypatch) -> None:
    """L3: reprt_code·bsns_year fail-fast."""
    from pydantic import SecretStr

    from app.config import settings

    monkeypatch.setattr(settings, "dart_api_key", SecretStr("k"))
    with pytest.raises(DartAdapterError, match="reprt_code"):
        DartOwnershipAdapter().fetch("00000001", "2024", "99999")
    with pytest.raises(DartAdapterError, match="bsns_year"):
        DartOwnershipAdapter().fetch("00000001", "20A4", "11011")


# ── 코드리뷰 patch 회귀 테스트 ──

def test_largest_gye_null_fallthrough() -> None:
    """리뷰: '계'행 지분율이 null이면 개별 보통주 행으로 폴백(데이터 손실 방지)."""
    rows = [
        {"nm": "홍길동", "stock_knd": "보통주", "trmend_posesn_stock_qota_rt": "30.00"},
        {"nm": "계", "stock_knd": "보통주", "trmend_posesn_stock_qota_rt": "-"},  # 값 없음
    ]
    assert _largest_shareholder_pct(rows) == 30.00


def test_largest_fallback_excludes_summary() -> None:
    """리뷰: 개별합 폴백은 요약행(소계/합계)을 제외해 이중집계를 막는다."""
    rows = [
        {"nm": "홍길동", "stock_knd": "보통주", "trmend_posesn_stock_qota_rt": "30.00"},
        {"nm": "특수관계인A", "stock_knd": "보통주", "trmend_posesn_stock_qota_rt": "10.00"},
        {"nm": "소계", "stock_knd": "보통주", "trmend_posesn_stock_qota_rt": "40.00"},  # 제외
    ]
    assert _largest_shareholder_pct(rows) == 40.00  # 80 아님(소계 이중가산 방지)


def test_treasury_no_total_returns_none() -> None:
    """리뷰: 합계행이 없으면 단일 종류로 오산하지 말고 None."""
    rows = [{"se": "보통주", "istc_totqy": "1,000,000", "tesstk_co": "50,000"}]
    assert _treasury_stock_pct(rows) is None


def test_treasury_range_guard() -> None:
    """리뷰: 자사주>발행총수·회계음수 등 범위 밖은 None(데이터오류 방어)."""
    assert _treasury_stock_pct(
        [{"se": "합계", "istc_totqy": "100", "tesstk_co": "150"}]) is None  # >100%
    assert _treasury_stock_pct(
        [{"se": "합계", "istc_totqy": "100", "tesstk_co": "(10)"}]) is None  # 음수


def test_normalize_all_none_no_row() -> None:
    """리뷰: 행은 있으나 두 지표 모두 파싱 실패면 all-NULL 행 대신 no-data([])."""
    raw = {"corp_code": "00000001", "as_of": "2024-12-31",
           "rows_hyslr": [{"nm": "X", "stock_knd": "우선주",
                           "trmend_posesn_stock_qota_rt": "5"}],
           "rows_stock": [{"se": "우선주", "istc_totqy": "100", "tesstk_co": "0"}]}
    assert DartOwnershipAdapter().normalize(raw) == []


def test_parse_ratio_percent_and_nonfinite() -> None:
    """리뷰: '%' suffix 허용, nan/inf 거부."""
    assert _parse_ratio("12.34%") == 12.34
    assert _parse_ratio("nan") is None
    assert _parse_ratio("inf") is None


def test_as_of_by_reprt(monkeypatch) -> None:
    """리뷰(High): reprt별 기간말로 as_of → 분기·사업보고서 자연키 충돌 없음."""
    from pydantic import SecretStr

    from app.config import settings

    monkeypatch.setattr(settings, "dart_api_key", SecretStr("k"))
    adapter = DartOwnershipAdapter()
    monkeypatch.setattr(adapter, "_get_json", lambda *a, **k: {"list": []})
    assert adapter.fetch("00000001", "2024", "11013")["as_of"] == "2024-03-31"
    assert adapter.fetch("00000001", "2024", "11011")["as_of"] == "2024-12-31"


def test_get_json_non_json_raises(monkeypatch) -> None:
    """리뷰: 비JSON 200(resp.json ValueError)도 DartAdapterError로 래핑, 키 미노출."""
    adapter = DartOwnershipAdapter()

    class _Resp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            raise ValueError("No JSON could be decoded")

    monkeypatch.setattr(adapter._session, "get", lambda *a, **k: _Resp())
    with pytest.raises(DartAdapterError, match="DART 요청 실패") as ei:
        adapter._get_json("hyslrSttus.json", {"crtfc_key": "SECRETKEY"})
    assert "SECRETKEY" not in str(ei.value)
