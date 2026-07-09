"""Story 1.4 — ECOS 어댑터 검증 (라이브 키 없이 fixture/mock)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.ingest.ecos import (
    EcosAdapter,
    EcosAdapterError,
    EcosApiError,
    _parse_rows,
    _time_to_iso,
    _to_float,
)
from app.models import Base, MacroIndicator


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


_FAKE_ROWS = [
    {"TIME": "202401", "DATA_VALUE": "3.5"},
    {"TIME": "202402", "DATA_VALUE": "3.5"},
]


def test_time_to_iso() -> None:
    assert _time_to_iso("202401") == "2024-01-01"
    assert _time_to_iso("20240102") == "2024-01-02"
    # 지원 안 하는/이상 포맷 → None (자연키 오염 방지)
    assert _time_to_iso("2024Q1") is None
    assert _time_to_iso("202413") is None  # 13월
    assert _time_to_iso("") is None


def test_to_float_edge_cases() -> None:
    assert _to_float("1,346.8") == 1346.8
    assert _to_float("-") is None
    assert _to_float(".") is None
    assert _to_float("") is None
    assert _to_float("abc") is None


def test_parse_rows_maps_and_skips_bad_dates() -> None:
    rows = _parse_rows("base_rate", "M", _FAKE_ROWS + [{"TIME": "2024Q1", "DATA_VALUE": "1"}])
    assert rows[0] == {"indicator": "base_rate", "date": "2024-01-01", "value": 3.5, "frequency": "M"}
    assert len(rows) == 2  # 2024Q1 스킵


def test_upsert_is_idempotent(session: Session) -> None:
    adapter = EcosAdapter()
    recs = _parse_rows("base_rate", "M", _FAKE_ROWS)
    adapter.upsert(session, recs)
    session.commit()
    adapter.upsert(session, recs)
    session.commit()
    assert session.scalar(select(func.count()).select_from(MacroIndicator)) == 2


def test_fetch_without_key_raises(monkeypatch) -> None:
    from pydantic import SecretStr

    from app.config import settings

    monkeypatch.setattr(settings, "ecos_api_key", SecretStr(""))
    with pytest.raises(EcosAdapterError, match="ECOS_API_KEY"):
        EcosAdapter().fetch("20240101", "20240301")


def test_pagination_fetches_all_pages(monkeypatch) -> None:
    """1000건 초과 시 여러 페이지를 끝까지 fetch(조용한 잘림 방지)."""
    adapter = EcosAdapter()
    calls = []

    def fake_get(key, stat, cycle, s, e, item, start, end):
        calls.append((start, end))
        if start == 1:
            return {"rows": [{"TIME": "20240101", "DATA_VALUE": "1"}] * 1000, "total": 1001}
        return {"rows": [{"TIME": "20240102", "DATA_VALUE": "2"}], "total": 1001}

    monkeypatch.setattr(adapter, "_get", fake_get)
    rows = adapter._get_all("k", "817Y002", "D", "20240101", "20260101", "010200000")
    assert len(rows) == 1001  # 두 페이지 합
    assert calls == [(1, 1000), (1001, 2000)]


def test_error_code_matrix(monkeypatch) -> None:
    """INFO-200 → 빈결과, 그 외 코드 → EcosApiError(fail-fast)."""
    adapter = EcosAdapter()

    class _Resp:
        def __init__(self, payload):
            self._p = payload
        def raise_for_status(self): ...
        def json(self):
            return self._p

    # INFO-200 → None(빈결과)
    monkeypatch.setattr(adapter._session, "get",
                        lambda *a, **k: _Resp({"RESULT": {"CODE": "INFO-200"}}))
    assert adapter._get("k", "x", "M", "202401", "202401", "i", 1, 1000) is None

    # INFO-100(키오류) → EcosApiError
    monkeypatch.setattr(adapter._session, "get",
                        lambda *a, **k: _Resp({"RESULT": {"CODE": "INFO-100"}}))
    with pytest.raises(EcosApiError, match="INFO-100"):
        adapter._get("k", "x", "M", "202401", "202401", "i", 1, 1000)


def test_get_error_does_not_leak_key(monkeypatch) -> None:
    """키가 URL 경로에 있으므로 예외에 키/URL이 노출되지 않는다."""
    import requests

    adapter = EcosAdapter()

    def _boom(*a, **k):
        raise requests.ConnectionError("boom .../SECRETKEY123/json/...")

    monkeypatch.setattr(adapter._session, "get", _boom)
    with pytest.raises(EcosAdapterError) as ei:
        adapter._get("SECRETKEY123", "x", "M", "202401", "202401", "i", 1, 1000)
    assert "SECRETKEY123" not in str(ei.value)
    assert ei.value.__cause__ is None  # from None 으로 원인 URL 체인 차단
