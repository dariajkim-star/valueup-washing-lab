"""Story 1.3 — KRX 어댑터 정규화·멱등 upsert 검증 (라이브 계정 없이 fixture)."""

from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.ingest.krx import KrxAdapter, KrxAdapterError, _merge_frames
from app.models import Base, Company, Price


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        # prices.corp_code FK 충족을 위한 company
        s.add(Company(corp_code="00126380", stock_code="005930", corp_name="삼성전자"))
        s.commit()
        yield s


def _fake_ohlcv_df() -> pd.DataFrame:
    """pykrx get_market_ohlcv 형태(종가·거래량 포함)."""
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    return pd.DataFrame(
        {"시가": [78200, 78500], "고가": [79800, 78800], "저가": [78200, 77000],
         "종가": [79600, 77000], "거래량": [17_142_847, 21_753_644], "등락률": [1, -3]},
        index=idx,
    )


def _fake_cap_df() -> pd.DataFrame:
    """pykrx get_market_cap 형태(시총·거래대금, 종가 없음)."""
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    return pd.DataFrame(
        {"시가총액": [475_000_000_000_000, 459_000_000_000_000],
         "거래량": [17_142_847, 21_753_644],
         "거래대금": [1_360_000_000_000, 1_680_000_000_000],
         "상장주식수": [5969782550, 5969782550]},
        index=idx,
    )


def test_merge_frames_maps_and_formats() -> None:
    """두 소스 병합: 종가(ohlcv) + 시총·거래대금(cap), ISO 날짜, 정수."""
    rows = _merge_frames(_fake_ohlcv_df(), _fake_cap_df())
    assert rows[0] == {
        "date": "2024-01-02",
        "close": 79600,
        "volume": 17_142_847,
        "trading_value": 1_360_000_000_000,
        "market_cap": 475_000_000_000_000,
    }
    assert len(rows) == 2


def test_merge_frames_cap_none_keeps_close() -> None:
    """cap이 None(로그인 실패)이어도 종가·거래량은 남고 시총은 null."""
    rows = _merge_frames(_fake_ohlcv_df(), None)
    assert rows[0]["close"] == 79600
    assert rows[0]["market_cap"] is None


def test_normalize_attaches_corp_code() -> None:
    raw = {"corp_code": "00126380",
           "rows": _merge_frames(_fake_ohlcv_df(), _fake_cap_df())}
    recs = KrxAdapter().normalize(raw)
    assert all(r["corp_code"] == "00126380" for r in recs)
    assert recs[0]["market_cap"] == 475_000_000_000_000


def test_upsert_is_idempotent(session: Session) -> None:
    """AC5: (corp_code, date) 멱등 — 2회 실행해도 중복 없음."""
    adapter = KrxAdapter()
    recs = adapter.normalize(
        {"corp_code": "00126380",
         "rows": _merge_frames(_fake_ohlcv_df(), _fake_cap_df())}
    )
    adapter.upsert(session, recs)
    session.commit()
    adapter.upsert(session, recs)
    session.commit()
    count = session.scalar(select(func.count()).select_from(Price))
    assert count == 2  # 2일치, 중복 없음


def test_fetch_without_credentials_raises(monkeypatch) -> None:
    """AC6: KRX_ID/KRX_PW 미설정 시 명확한 에러."""
    from pydantic import SecretStr

    from app.config import settings

    monkeypatch.setattr(settings, "krx_id", SecretStr(""))
    monkeypatch.setattr(settings, "krx_pw", SecretStr(""))
    with pytest.raises(KrxAdapterError, match="KRX_ID"):
        KrxAdapter().fetch("005930", "00126380", "20240101", "20240105")


def test_fetch_rejects_bad_stock_code(monkeypatch) -> None:
    """stock_code 6자리 숫자 검증(조용한 누락 방지)."""
    from pydantic import SecretStr

    from app.config import settings

    monkeypatch.setattr(settings, "krx_id", SecretStr("x"))
    monkeypatch.setattr(settings, "krx_pw", SecretStr("y"))
    with pytest.raises(KrxAdapterError, match="stock_code"):
        KrxAdapter().fetch("5930", "00126380", "20240101", "20240105")


def test_krx_env_restores_environment() -> None:
    """보안: 자격증명은 pykrx 호출 스코프에서만 주입되고 원복된다."""
    import os

    from app.ingest.krx import _krx_env

    os.environ.pop("KRX_ID", None)
    with _krx_env("myid", "mypw"):
        assert os.environ["KRX_ID"] == "myid"
    assert "KRX_ID" not in os.environ  # 원복(주입 전 없었음)


def test_require_columns_raises_on_schema_change() -> None:
    """pykrx 컬럼명이 바뀌면 조용한 null이 아니라 에러."""
    bad = pd.DataFrame({"CLOSE": [1]}, index=pd.to_datetime(["2024-01-02"]))
    with pytest.raises(KrxAdapterError, match="컬럼 없음"):
        _merge_frames(bad, None)


def test_to_iso_handles_string_index() -> None:
    """날짜 인덱스가 문자열이어도 ISO로 변환."""
    from app.ingest.krx import _to_iso

    assert _to_iso("20240102") == "2024-01-02"
    assert _to_iso(pd.Timestamp("2024-01-02")) == "2024-01-02"
