"""KRX 소스 어댑터 — prices의 writer (AD-3). 시가총액 단일원천(AD-9).

pykrx:
  - get_market_ohlcv(from,to,ticker) : 종가·거래량 (로그인 불필요, 안정)
  - get_market_cap(from,to,ticker)   : 시가총액·거래대금 (KRX 로그인 필요)
두 소스를 날짜로 병합한다. close는 항상 ohlcv 원천, market_cap/trading_value는 cap 원천.

보안: KRX_ID/KRX_PW를 프로세스 전역 os.environ에 상주시키지 않는다.
     pykrx 호출 스코프에서만 임시 주입 후 finally에서 원복(context manager).
데이터 품질: cap(로그인) 실패는 조용히 성공 처리하지 않고 degraded로 표시한다.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.ingest.base import SourceAdapter
from app.repositories.prices import upsert_price

_OHLCV_MAP = {"종가": "close", "거래량": "volume"}
_CAP_MAP = {"시가총액": "market_cap", "거래대금": "trading_value"}
_STOCK_CODE_LEN = 6


class KrxAdapterError(RuntimeError):
    """KRX 어댑터 오류(로그인 미설정·스키마 불일치 등)."""


@contextmanager
def _krx_env(krx_id: str, krx_pw: str) -> Iterator[None]:
    """pykrx 호출 동안만 KRX_ID/KRX_PW를 os.environ에 주입하고 원복한다."""
    prev = {k: os.environ.get(k) for k in ("KRX_ID", "KRX_PW")}
    os.environ["KRX_ID"] = krx_id
    os.environ["KRX_PW"] = krx_pw
    try:
        yield
    finally:
        for k, v in prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class KrxAdapter(SourceAdapter):
    source = "krx"

    def fetch(
        self, stock_code: str, corp_code: str, date_from: str, date_to: str
    ) -> dict[str, Any]:
        """[date_from, date_to] 시세·시총·거래대금 수집. 날짜 YYYYMMDD.

        반환에 `cap_ok`(시총·거래대금 원천 성공 여부)를 포함해 degraded를 상위에 알린다.
        """
        if not (stock_code and len(stock_code) == _STOCK_CODE_LEN and stock_code.isdigit()):
            raise KrxAdapterError(f"잘못된 stock_code(6자리 숫자 아님): {stock_code!r}")
        krx_id = settings.krx_id.get_secret_value()
        krx_pw = settings.krx_pw.get_secret_value()
        if not (krx_id and krx_pw):
            raise KrxAdapterError(
                "KRX_ID/KRX_PW가 설정되지 않았습니다(시총·거래대금 조회에 필요)."
            )
        try:
            from pykrx import stock  # noqa: PLC0415  (지연 import)
        except ImportError as e:  # pragma: no cover
            raise KrxAdapterError("pykrx가 설치되지 않았습니다.") from e

        with _krx_env(krx_id, krx_pw):
            ohlcv = stock.get_market_ohlcv(date_from, date_to, stock_code)  # 로그인 불필요
            try:
                cap = stock.get_market_cap(date_from, date_to, stock_code)  # 로그인 필요
                cap_ok = cap is not None and not cap.empty
            except Exception:  # noqa: BLE001 — cap 실패는 degraded로 표시(삼키지 않음)
                cap, cap_ok = None, False

        return {
            "corp_code": corp_code,
            "rows": _merge_frames(ohlcv, cap),
            "cap_ok": cap_ok,
        }

    def normalize(self, raw: Mapping[str, Any]) -> list[dict[str, Any]]:
        corp_code = raw["corp_code"]
        return [{"corp_code": corp_code, **row} for row in raw.get("rows", [])]

    def upsert(self, session: Session, records: Sequence[dict[str, Any]]) -> int:
        for rec in records:
            upsert_price(session, rec)
        session.flush()
        return len(records)


def _merge_frames(ohlcv: Any, cap: Any) -> list[dict[str, Any]]:
    """ohlcv(종가·거래량)와 cap(시총·거래대금)을 날짜로 outer-join 병합(순수·테스트가능).

    close는 ohlcv에서만, market_cap/trading_value는 cap에서만 온다(volume 충돌 없음).
    cap이 None이면 시총·거래대금은 null.
    """
    _require_columns(ohlcv, _OHLCV_MAP.keys(), "ohlcv")
    if cap is not None:
        _require_columns(cap, _CAP_MAP.keys(), "cap")

    by_date: dict[str, dict[str, Any]] = {}
    _fill(by_date, ohlcv, _OHLCV_MAP)
    _fill(by_date, cap, _CAP_MAP)
    rows = []
    for date in sorted(by_date):
        row = {"date": date, "close": None, "volume": None,
               "trading_value": None, "market_cap": None}
        row.update(by_date[date])
        rows.append(row)
    return rows


def _require_columns(df: Any, cols: Any, name: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise KrxAdapterError(f"{name} 응답에 필요한 컬럼 없음: {missing} (pykrx 스키마 변경?)")


def _fill(acc: dict, df: Any, colmap: dict[str, str]) -> None:
    if df is None:
        return
    for idx, series in df.iterrows():
        date_iso = _to_iso(idx)
        bucket = acc.setdefault(date_iso, {"date": date_iso})
        for kcol, field in colmap.items():
            if kcol in series.index:
                bucket[field] = _to_int(series[kcol])


def _to_iso(idx: Any) -> str:
    """Timestamp/문자열 인덱스를 YYYY-MM-DD로(타임존 제거)."""
    if hasattr(idx, "strftime"):
        return idx.strftime("%Y-%m-%d")
    s = str(idx)
    digits = s.replace("-", "")[:8]
    if len(digits) == 8 and digits.isdigit():
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    return s


def _to_int(v: Any) -> int | None:
    try:
        return None if v is None else int(v)
    except (TypeError, ValueError):
        return None
