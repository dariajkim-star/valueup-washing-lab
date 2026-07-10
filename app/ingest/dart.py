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
        include_buyback: bool = True,
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
        buyback_ok = True  # buyback 시도 실패 시 False(재무는 계속, run.py가 degraded 표시)
        # 데이터 없음(빈 accounts)과 계정 누락을 구분: 데이터 없으면 재무 period를 만들지 않음.
        # buyback만 있고 accounts 없는 종목은 period 미생성 → buyback 미적재(드묾, 한계 문서화).
        if accounts:
            # 자기주식 취득/처분 현황(1.8) — buyback_amount·buyback_retired_amount 신호원.
            # financials 단일 writer(AD-3) 유지: 별도 어댑터 아니라 이 fetch가 함께 수집.
            # 재무 period가 생길 때만 호출(빈 accounts에 rate-limit 호출 낭비 방지, 리뷰 Med).
            # 보조 원천이라 실패해도 재무 수집을 막지 않는다(리뷰 High: 쿼터 020 등에서
            # 이미 성공한 재무까지 유실되던 회귀 격리). None=미상/실패, []=미공시(013).
            buyback_rows: list[Any] | None = None
            if include_buyback:
                try:
                    bb = self._get(
                        "tesstkAcqsDspsSttus.json",
                        {
                            "crtfc_key": key,
                            "corp_code": corp_code,
                            "bsns_year": bsns_year,
                            "reprt_code": reprt_code,
                        },
                        allow_no_data=True,
                    )
                    rows = bb.get("list") or []
                    if isinstance(rows, list):
                        buyback_rows = rows
                    else:  # 형태 이탈(list가 dict/str 등) → unknown 처리(리뷰 Med)
                        buyback_ok = False
                except DartAdapterError:
                    buyback_ok = False  # 보조 원천 실패 → 재무는 계속(degraded)
            periods.append(
                {
                    "year": int(bsns_year),
                    "quarter": _REPRT_QUARTER[reprt_code],
                    "accounts": accounts,
                    "total_debt": total_debt,
                    "fs_div": used_fs_div,
                    "buyback_rows": buyback_rows,
                }
            )
        return {"company": company, "periods": periods, "buyback_ok": buyback_ok}

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
        except (requests.RequestException, ValueError) as e:
            # 예외 메시지에 params(crtfc_key 포함 URL)를 넣지 않는다 — 키 노출 방지.
            # ValueError = 비JSON 200(HTML 점검페이지 등)의 resp.json() 실패(공통 defer 해소).
            raise DartAdapterError(
                f"DART 요청 실패: endpoint={endpoint} ({type(e).__name__})"
            ) from None
        if not isinstance(data, dict):  # JSON이지만 dict 아님(배열/문자열) → 명확한 에러
            raise DartAdapterError(f"DART 응답 형태 오류: endpoint={endpoint}")
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
            # 자사주 취득/소각 신호(1.8): tesstkAcqsDspsSttus 행에서 집계(수량, 액 아님).
            # buyback_rows None(미상/실패)·[](미공시) 모두 (None, None) → 기존값 보존.
            rec["buyback_amount"], rec["buyback_retired_amount"] = _buyback_totals(
                period.get("buyback_rows")
            )
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


# 자기주식 취득/처분 행 분류(코드리뷰 2026-07-10: 자체+GPT 교차검증 반영).
# 총계/합계 = 최상위 총계(권위 소스), 소계 = 중간 집계(계층 검증 불가 → 단독으론 미사용).
_BUYBACK_TOTAL_LABELS = ("총계", "합계")
_BUYBACK_SUBTOTAL_LABELS = ("소계",)
_BUYBACK_MTH_KEYS = ("acqs_mth1", "acqs_mth2", "acqs_mth3")


def _norm_label(v: Any) -> str:
    """라벨 정규화: 모든 공백 제거('총 계' 표기 변형 대응) 후 비교.

    정확일치 원칙 유지(1.6 "특수관계인"의 "계" 부분일치 오탐 교훈) —
    공백 제거는 _parse_amount의 수치 정규화와 동일한 수준의 표기 방어일 뿐.
    """
    return "".join(str(v).split())


def _buyback_row_kind(row: Mapping[str, Any]) -> str:
    """행 분류: 'total'(총계/합계) / 'subtotal'(소계) / 'leaf'(개별 취득방법)."""
    for k in _BUYBACK_MTH_KEYS:
        label = _norm_label(row.get(k, ""))
        if label in _BUYBACK_TOTAL_LABELS:
            return "total"
        if label in _BUYBACK_SUBTOTAL_LABELS:
            return "subtotal"
    return "leaf"


def _parse_quantity(raw: Any) -> int | None:
    """수량(주) 파싱. 음수는 수량 도메인에 없음 → None(null>오값).

    _parse_amount는 KRW용이라 회계 음수 표기(△·괄호)를 음수로 해석하는데,
    수량 합산에서 음수가 섞이면 상쇄로 '활동 없음(0)'이 조작될 수 있어(GPT 리뷰) 거부.
    """
    v = _parse_amount(raw)
    return v if v is not None and v >= 0 else None


def _buyback_field_total(
    rows: Sequence[Any], field: str
) -> int | None:
    """한 필드(change_qy_acqs/change_qy_incnr)의 기간 수량 합계. 필드별 독립 판정.

    우선순위(이중집계·부분손실 방지, 애매하면 null — AC3):
      1) 총계/합계 행이 있으면 그것이 권위 소스:
         - 유일하면 그 값.
         - 여러 행이고 stock_knd가 전부 다르면(보통주/우선주 등 종류별 파티션) 합산.
         - 여러 행이고 값이 전부 같으면(합계·총계 중복 표기) 그 값.
         - 그 외(상충 총계) → None.
      2) 총계 없으면 leaf 행 합(0 가능 → '활동 0' 확정).
      3) 소계만 있으면 None — 소계 중첩/부분 계층을 검증할 수 없어 합산하지 않는다.
    """
    totals: list[tuple[str, int]] = []
    leaves: list[int] = []
    for row in rows:
        if not isinstance(row, Mapping):  # 형태 이탈 요소(비dict) 방어
            continue
        v = _parse_quantity(row.get(field))
        if v is None:
            continue
        kind = _buyback_row_kind(row)
        if kind == "total":
            totals.append((_norm_label(row.get("stock_knd", "")), v))
        elif kind == "leaf":
            leaves.append(v)
        # subtotal은 수집하지 않음(계층 불명 → 단독 사용 금지)
    if totals:
        if len(totals) == 1:
            return totals[0][1]
        kinds = [k for k, _ in totals]
        if all(kinds) and len(set(kinds)) == len(kinds):
            return sum(v for _, v in totals)  # 종류별 총계 파티션 합
        values = {v for _, v in totals}
        if len(values) == 1:
            return values.pop()  # 중복 표기 일치(합계=총계)
        return None  # 상충 총계 → 애매 → null
    if leaves:
        return sum(leaves)
    return None  # 소계만/파싱값 전무 → null(미공시·불명과 동일 취급)


def _buyback_totals(
    rows: Sequence[Any] | None,
) -> tuple[int | None, int | None]:
    """tesstkAcqsDspsSttus 행 → (취득 수량, 소각 수량). 수량(주), 액 아님.

    필드별 독립 판정(취득은 leaf에, 소각은 총계에만 있어도 각각 채움 — 리뷰 High 반영).
    None(미공시/실패/애매)과 0(공시된 활동 없음)을 구분(NFR2 "null > 틀린 값").
    """
    safe_rows = rows or []
    return (
        _buyback_field_total(safe_rows, "change_qy_acqs"),
        _buyback_field_total(safe_rows, "change_qy_incnr"),
    )


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
