"""ECOS(한국은행 경제통계) 소스 어댑터 — macro_indicator의 writer (AD-3).

ECOS StatisticSearch REST API(requests). 지표 카탈로그(통계표·항목·주기) 내장.

프로덕션 하드닝:
  - 페이지네이션: list_total_count까지 반복 fetch(1000건 초과 구간 누락 방지).
  - 재시도/백오프/타임아웃(Session+Retry).
  - 키 redaction: 키가 URL 경로에 포함되므로 예외/로그에 URL을 절대 노출하지 않는다.
  - 지표별 복원력: 한 지표 실패가 나머지 수집을 막지 않는다.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from sqlalchemy.orm import Session
from urllib3.util.retry import Retry

from app.config import settings
from app.ingest.base import SourceAdapter
from app.repositories.macro import upsert_macro

_BASE = "https://ecos.bok.or.kr/api/StatisticSearch"
_TIMEOUT = (3.05, 20)
_PAGE = 1000  # ECOS 페이지 최대
_MIN_INTERVAL = 0.2  # 호출한도 여유

# 지표 카탈로그: (indicator, 통계표, 항목, 주기) — 라이브 탐침으로 확정
_CATALOG: tuple[tuple[str, str, str, str], ...] = (
    ("base_rate", "722Y001", "0101000", "M"),
    ("bond_3y", "817Y002", "010200000", "D"),
    ("usd_krw", "731Y001", "0000001", "D"),
    ("leading_index", "901Y067", "I16E", "M"),
)
ALLOWED_INDICATORS = tuple(c[0] for c in _CATALOG)


class EcosAdapterError(RuntimeError):
    """ECOS 어댑터 오류(키 미설정·API 오류·네트워크 실패). 키/URL을 메시지에 넣지 않는다."""


class EcosApiError(EcosAdapterError):
    """ECOS RESULT.CODE가 정상/데이터없음이 아닌 오류(키오류·포맷·시스템 등)."""


class EcosAdapter(SourceAdapter):
    source = "ecos"

    def __init__(self) -> None:
        self._session = requests.Session()
        retry = Retry(
            total=3, backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",),
        )
        self._session.mount("https://", HTTPAdapter(max_retries=retry))
        self._last = 0.0

    def fetch(self, date_from: str, date_to: str) -> dict[str, Any]:
        """카탈로그 지표를 [date_from, date_to](YYYYMMDD) 수집. 지표별 실패는 격리."""
        key = settings.ecos_api_key.get_secret_value()
        if not key:
            raise EcosAdapterError(
                "ECOS_API_KEY가 설정되지 않았습니다. .env에 ECOS_API_KEY를 넣으세요."
            )
        rows: list[dict[str, Any]] = []
        failed: list[tuple[str, str]] = []
        for indicator, stat, item, cycle in _CATALOG:
            s = date_from if cycle == "D" else date_from[:6]
            e = date_to if cycle == "D" else date_to[:6]
            try:
                ecos_rows = self._get_all(key, stat, cycle, s, e, item)
                rows.extend(_parse_rows(indicator, cycle, ecos_rows))
            except EcosAdapterError as ex:
                failed.append((indicator, str(ex)))
        return {"rows": rows, "failed": failed}

    def _get_all(
        self, key: str, stat: str, cycle: str, s: str, e: str, item: str
    ) -> list[dict[str, Any]]:
        """페이지네이션: list_total_count까지 반복 fetch. 누락 시 오류."""
        all_rows: list[dict[str, Any]] = []
        total: int | None = None
        start = 1
        while True:
            end = start + _PAGE - 1
            payload = self._get(key, stat, cycle, s, e, item, start, end)
            if payload is None:  # INFO-200: 데이터 없음
                break
            total = payload["total"]
            all_rows.extend(payload["rows"])
            if len(all_rows) >= total or not payload["rows"]:
                break
            start += _PAGE
        if total is not None and len(all_rows) != total:
            raise EcosApiError(
                f"ECOS 수집 누락: stat={stat} 기대 {total} != 수집 {len(all_rows)}"
            )
        return all_rows

    def _get(
        self, key: str, stat: str, cycle: str, s: str, e: str, item: str,
        start: int, end: int,
    ) -> dict[str, Any] | None:
        """단일 페이지 fetch. INFO-200이면 None, 그 외 오류는 EcosApiError."""
        # rate-limit 여유
        wait = _MIN_INTERVAL - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

        url = f"{_BASE}/{key}/json/kr/{start}/{end}/{stat}/{cycle}/{s}/{e}/{item}"
        try:
            resp = self._session.get(url, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as ex:
            # URL에 키가 포함 → 예외에 URL/키 절대 미노출
            raise EcosAdapterError(
                f"ECOS 요청 실패: stat={stat} ({type(ex).__name__})"
            ) from None
        if "StatisticSearch" in data:
            block = data["StatisticSearch"]
            return {
                "rows": block.get("row", []),
                "total": int(block.get("list_total_count", 0)),
            }
        code = data.get("RESULT", {}).get("CODE", "")
        if code == "INFO-200":  # 해당 데이터 없음 → 정상 빈 결과
            return None
        # INFO-100(키오류)·ERROR-* 등은 fail-fast (키/URL 미포함)
        raise EcosApiError(f"ECOS API 오류: stat={stat}, code={code}")

    def normalize(self, raw: Mapping[str, Any]) -> list[dict[str, Any]]:
        return list(raw.get("rows", []))

    def upsert(self, session: Session, records: Sequence[dict[str, Any]]) -> int:
        for rec in records:
            upsert_macro(session, rec)
        session.flush()
        return len(records)


def _parse_rows(
    indicator: str, cycle: str, ecos_rows: Sequence[Mapping[str, Any]]
) -> list[dict]:
    """ECOS row → [{indicator, date(ISO), value, frequency}]. 순수·테스트가능."""
    out = []
    for r in ecos_rows:
        date = _time_to_iso(str(r.get("TIME", "")))
        if date is None:  # 지원하지 않는 TIME 포맷·이상값은 스킵(자연키 오염 방지)
            continue
        out.append(
            {
                "indicator": indicator,
                "date": date,
                "value": _to_float(r.get("DATA_VALUE")),
                "frequency": cycle,
            }
        )
    return out


def _time_to_iso(t: str) -> str | None:
    """ECOS TIME(YYYYMM 월 / YYYYMMDD 일)을 ISO YYYY-MM-DD로(월은 01일). 형식 밖이면 None."""
    t = t.strip()
    if len(t) == 6 and t.isdigit():
        mm = t[4:6]
        if "01" <= mm <= "12":
            return f"{t[:4]}-{mm}-01"
    if len(t) == 8 and t.isdigit():
        return f"{t[:4]}-{t[4:6]}-{t[6:]}"
    return None  # 분기/반기/연 등 미지원 포맷·이상값


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    if s in ("", "-", ".", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None
