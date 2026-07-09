"""DART(전자공시) 소스 어댑터 — company·financials의 writer (AD-3).

OpenDART REST API(requests)를 사용한다:
  - company.json          : 기업개황(회사명·종목코드·시장구분·업종)
  - fnlttSinglAcntAll.json : 단일회사 전체 재무제표(계정명→금액)

프로덕션 하드닝: 재시도/백오프, rate-limit(100/min), 키 redaction, connect/read timeout 분리.
fetch: REST 호출(키 필요). normalize: 계정명 매핑(순수, 테스트 가능). upsert: 멱등 적재.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Mapping, Sequence
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from sqlalchemy.orm import Session
from urllib3.util.retry import Retry

from app.config import settings
from app.ingest.base import SourceAdapter
from app.repositories.financials import upsert_company, upsert_financial

_BASE = "https://opendart.fss.or.kr/api"
_TIMEOUT = (3.05, 20)  # (connect, read)
_MIN_INTERVAL = 0.65  # 100 req/min 여유(초당 <2)

_MARKET = {"Y": "KOSPI", "K": "KOSDAQ", "N": "KONEX", "E": "기타"}
_REPRT_QUARTER = {"11013": 1, "11012": 2, "11014": 3, "11011": 4}
_YEAR_RE = re.compile(r"^\d{4}$")

# 단일 값 계정(첫 매칭). 총차입금은 별도 합산 규칙 사용.
_ACCOUNT_MAP: dict[str, tuple[str, ...]] = {
    "revenue": ("매출액", "수익(매출액)", "영업수익"),
    "net_income": ("당기순이익", "당기순이익(손실)", "분기순이익"),
    "operating_income": ("영업이익", "영업이익(손실)"),
    "depreciation": ("감가상각비", "유형자산감가상각비"),
    "equity": ("자본총계",),
    "total_assets": ("자산총계",),
    "total_liabilities": ("부채총계",),
    "cash": ("현금및현금성자산",),
}
# 총차입금(이자성 부채) = 아래 라벨에 매칭되는 '모든 행'의 합.
# 회사마다 라벨이 다르고(삼성: 단기/장기차입금·사채, 하이닉스: 차입금),
# 같은 라벨이 유동/비유동에 중복 등장하므로 dedup이 아니라 전체 합산해야 한다.
_DEBT_LABELS = (
    "차입금", "단기차입금", "장기차입금", "유동성장기부채", "사채", "리스부채",
)


class DartAdapterError(RuntimeError):
    """DART 어댑터 오류(키 미설정·API 오류·네트워크 실패 등). 키/URL을 메시지에 넣지 않는다."""


class _RateLimiter:
    """단순 최소간격 rate limiter(스레드 안전)."""

    def __init__(self, min_interval: float) -> None:
        self._min = min_interval
        self._last = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            wait = self._min - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()


class DartAdapter(SourceAdapter):
    source = "dart"

    def __init__(self) -> None:
        self._session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        self._session.mount("https://", HTTPAdapter(max_retries=retry))
        self._limiter = _RateLimiter(_MIN_INTERVAL)

    # ── fetch (라이브, 키 필요) ──
    def fetch(
        self,
        corp_code: str,
        bsns_year: str,
        reprt_code: str = "11011",
        fs_div: str = "CFS",
    ) -> dict[str, Any]:
        key = settings.dart_api_key.get_secret_value()
        if not key:
            raise DartAdapterError(
                "DART_API_KEY가 설정되지 않았습니다. .env에 DART_API_KEY를 넣으세요."
            )
        if reprt_code not in _REPRT_QUARTER:
            raise DartAdapterError(f"지원하지 않는 reprt_code: {reprt_code}")
        if not _YEAR_RE.match(str(bsns_year)):
            raise DartAdapterError(f"잘못된 bsns_year(YYYY 아님): {bsns_year!r}")

        company = self._fetch_company(key, corp_code)
        accounts, total_debt, used_fs_div = self._fetch_accounts(
            key, corp_code, bsns_year, reprt_code, fs_div
        )
        periods: list[dict[str, Any]] = []
        # 데이터 없음(빈 accounts)과 계정 누락을 구분: 데이터 없으면 재무 period를 만들지 않음
        if accounts:
            periods.append(
                {
                    "year": int(bsns_year),
                    "quarter": _REPRT_QUARTER[reprt_code],
                    "accounts": accounts,
                    "total_debt": total_debt,
                    "fs_div": used_fs_div,
                }
            )
        return {"company": company, "periods": periods}

    def _fetch_company(self, key: str, corp_code: str) -> dict[str, Any]:
        data = self._get("company.json", {"crtfc_key": key, "corp_code": corp_code})
        return {
            "corp_code": corp_code,
            "stock_code": data.get("stock_code") or None,
            "corp_name": data.get("corp_name", ""),
            "market": _MARKET.get(data.get("corp_cls", ""), None),
            "sector": data.get("induty_code") or None,
        }

    def _fetch_accounts(
        self, key: str, corp_code: str, bsns_year: str, reprt_code: str, fs_div: str
    ) -> tuple[dict[str, int], int | None, str | None]:
        """(단일값 계정 dict, 총차입금 합, 사용한 fs_div) 반환."""
        for div in (fs_div, "OFS" if fs_div == "CFS" else None):
            if div is None:
                break
            params = {
                "crtfc_key": key,
                "corp_code": corp_code,
                "bsns_year": bsns_year,
                "reprt_code": reprt_code,
                "fs_div": div,
            }
            data = self._get(
                "fnlttSinglAcntAll.json", params, allow_no_data=True
            )
            rows = data.get("list") or []
            if rows:
                accounts: dict[str, int] = {}
                for row in rows:
                    name = row.get("account_nm", "")
                    val = _parse_amount(row.get("thstrm_amount"))
                    if val is not None and name not in accounts:
                        accounts[name] = val
                # 총차입금은 dedup 전 '모든 행'에서 합산(중복 라벨·유동/비유동 포함)
                total_debt = _sum_debt(rows)
                return accounts, total_debt, div
        return {}, None, None

    def _get(
        self, endpoint: str, params: Mapping[str, Any], allow_no_data: bool = False
    ) -> dict[str, Any]:
        self._limiter.acquire()
        try:
            resp = self._session.get(
                f"{_BASE}/{endpoint}", params=params, timeout=_TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            # 예외 메시지에 params(crtfc_key 포함 URL)를 넣지 않는다 — 키 노출 방지
            raise DartAdapterError(
                f"DART 요청 실패: endpoint={endpoint} ({type(e).__name__})"
            ) from None
        status = data.get("status")
        if status == "000":
            return data
        if allow_no_data and status == "013":  # 조회된 데이터 없음
            return {"list": []}
        raise DartAdapterError(
            f"DART API 오류: endpoint={endpoint}, status={status}, msg={data.get('message')}"
        )

    # ── normalize (순수, 테스트 가능) ──
    def normalize(
        self, raw: Mapping[str, Any]
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        company = dict(raw["company"])
        corp_code = company["corp_code"]
        fin_recs: list[dict[str, Any]] = []
        for period in raw.get("periods", []):
            accounts: Mapping[str, Any] = period.get("accounts", {})
            rec: dict[str, Any] = {
                "corp_code": corp_code,
                "year": period["year"],
                "quarter": period["quarter"],
                "fs_div": period.get("fs_div"),
            }
            for col, labels in _ACCOUNT_MAP.items():
                rec[col] = _pick(accounts, labels)
            # total_debt는 fetch에서 '모든 차입 행' 합산(중복 라벨 포함)해 넘겨받음
            rec["total_debt"] = period.get("total_debt")
            # 환원 항목은 전체 재무제표에 없음 → best-effort(있으면 사용, 없으면 null)
            rec["dividend_total"] = period.get("dividend_total")
            rec["buyback_amount"] = period.get("buyback_amount")
            rec["buyback_retired_amount"] = period.get("buyback_retired_amount")
            fin_recs.append(rec)
        return company, fin_recs

    # ── upsert (멱등) ──
    def upsert(
        self, session: Session, records: tuple[dict[str, Any], Sequence[dict[str, Any]]]
    ) -> int:
        company_rec, fin_recs = records
        upsert_company(session, company_rec)
        for rec in fin_recs:
            upsert_financial(session, rec)
        session.flush()
        return len(fin_recs)


def _parse_amount(raw: Any) -> int | None:
    """DART 금액 문자열을 정수로. 회계 음수(괄호·△·유니코드 마이너스) 처리. 빈값/'-'는 None."""
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "").replace(" ", "")
    if s in ("", "-", "△", "-"):
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):  # (3000) = -3000
        negative, s = True, s[1:-1]
    if s and s[0] in "△-−":  # 삼각형·하이픈·유니코드 마이너스
        negative, s = True, s[1:]
    if not s.isdigit():
        return None
    val = int(s)
    return -val if negative else val


def _pick(accounts: Mapping[str, Any], labels: tuple[str, ...]) -> int | None:
    """후보 라벨 중 처음 '유효하게 파싱되는' 값을 반환. 실패하면 다음 후보로 계속."""
    for label in labels:
        if label in accounts:
            v = accounts[label]
            if isinstance(v, int):
                return v
            parsed = _parse_amount(v)
            if parsed is not None:
                return parsed
    return None


def _sum_debt(rows: Sequence[Mapping[str, Any]]) -> int | None:
    """총차입금 = 차입 라벨에 매칭되는 '모든 행'의 합(중복 라벨·유동/비유동 포함).

    dedup dict가 아니라 원본 rows에서 계산 — 같은 '차입금'이 유동/비유동에 각각
    등장하는 경우(하이닉스 등)를 모두 합산한다. 하나도 없으면 None.
    """
    total = 0
    found = False
    for row in rows:
        name = row.get("account_nm", "")
        if name in _DEBT_LABELS:
            v = _parse_amount(row.get("thstrm_amount"))
            if v is not None:
                total += v
                found = True
    return total if found else None
