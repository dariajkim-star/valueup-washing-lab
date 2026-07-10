"""DART 지분공시 어댑터 — ownership의 writer (AD-3, source="dart").

1.5(자유서식)와 달리 **구조화 JSON** 두 엔드포인트를 쓴다(1.2 재무제표 패턴에 가깝다):
  - hyslrSttus.json        : 최대주주 현황 → largest_shareholder_pct (보통주 "계"행)
  - stockTotqySttus.json   : 주식의 총수 현황 → treasury_stock_pct (자기주식/발행총수)

JSON 응답이라 dart.py의 `_get`(status 000/013) 패턴을 미러한 `_get_json`을 쓴다(1.5의
document.xml ZIP 경로 불필요). HTTP 하드닝·키 미노출·수량 파싱은 dart.py 재사용.

코드리뷰 반영(null>오값): 요약행 결측·이상 포맷에선 틀린 non-null 대신 None.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from sqlalchemy.orm import Session
from urllib3.util.retry import Retry

from app.config import settings
from app.ingest.base import SourceAdapter
from app.ingest.dart import (
    _BASE,
    _MIN_INTERVAL,
    _REPRT_QUARTER,
    _TIMEOUT,
    _YEAR_RE,
    DartAdapterError,
    _parse_amount,
    _RateLimiter,
)
from app.repositories.ownership import upsert_ownership

# reprt_code → 기간말(as_of). 분기/사업보고서가 같은 연말로 뭉쳐 자연키 충돌하는 것 방지.
_REPRT_ASOF = {"11013": "03-31", "11012": "06-30", "11014": "09-30", "11011": "12-31"}
_SUMMARY_NM = ("계", "소계", "합계")  # 요약행(개별합 폴백에서 제외해 이중집계 방지)


def _parse_ratio(raw: Any) -> float | None:
    """지분율 문자열(예: "12.34", "12.34%")을 float로. "-"·""·미공시·nan/inf·실패는 None."""
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "").replace(" ", "").rstrip("%")
    if s in ("", "-", "△", "−"):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def _is_common(r: Mapping[str, Any]) -> bool:
    return "보통" in str(r.get("stock_knd", ""))


def _is_summary(r: Mapping[str, Any]) -> bool:
    # 정확 일치만(부분일치 금지: "특수관계인"에 "계"가 들어가 오탐되던 문제)
    return str(r.get("nm", "")).strip() in _SUMMARY_NM


def _largest_shareholder_pct(rows: Sequence[Mapping[str, Any]]) -> float | None:
    """보통주 기준 최대주주+특수관계인 합계 지분율(우선주 무의결권 제외)."""
    if not rows:
        return None

    def _rt(r: Mapping[str, Any]) -> float | None:
        return _parse_ratio(r.get("trmend_posesn_stock_qota_rt"))

    # 1) 보통주 '계' 행 — 유효 지분율일 때만(값 없으면 폴백으로)
    for r in rows:
        if str(r.get("nm", "")).strip() == "계" and _is_common(r):
            v = _rt(r)
            if v is not None:
                return v
    # 2) 주식종류 미표기 단일 '계'
    for r in rows:
        if str(r.get("nm", "")).strip() == "계":
            v = _rt(r)
            if v is not None:
                return v
    # 3) 폴백: 요약행 제외 개별 보통주 지분율 합(소계/합계 중복 가산 방지)
    vals = [
        v for r in rows
        if _is_common(r) and not _is_summary(r)
        for v in (_rt(r),) if v is not None
    ]
    return round(sum(vals), 2) if vals else None


def _treasury_stock_pct(rows: Sequence[Mapping[str, Any]]) -> float | None:
    """자사주 비중 = 자기주식수 / 발행주식총수 * 100. **정확한 '합계' 행**만 사용.

    합계행이 없으면(부분/종류별만) None — 단일 종류로 종목 전체 비중을 오산하지 않는다.
    """
    total = [r for r in rows if str(r.get("se", "")).strip() == "합계"]
    if not total:
        return None
    target = total[0]
    istc = _parse_amount(target.get("istc_totqy"))
    tesstk = _parse_amount(target.get("tesstk_co"))
    if not istc or tesstk is None:  # 발행총수 0/None → 0 나눗셈 방어
        return None
    pct = round(tesstk * 100.0 / istc, 2)
    if not (0.0 <= pct <= 100.0):  # 데이터오류(음수·>100%) 방어 → null
        return None
    return pct


class DartOwnershipAdapter(SourceAdapter):
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
        self, corp_code: str, bsns_year: str, reprt_code: str = "11011"
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

        params = {
            "crtfc_key": key,
            "corp_code": corp_code,
            "bsns_year": bsns_year,
            "reprt_code": reprt_code,
        }
        hyslr = self._get_json("hyslrSttus.json", params, allow_no_data=True)
        stock = self._get_json("stockTotqySttus.json", params, allow_no_data=True)
        return {
            "corp_code": corp_code,
            "as_of": f"{bsns_year}-{_REPRT_ASOF[reprt_code]}",  # reprt별 기간말
            "rows_hyslr": hyslr.get("list") or [],
            "rows_stock": stock.get("list") or [],
        }

    def _get_json(
        self, endpoint: str, params: Mapping[str, Any], allow_no_data: bool = False
    ) -> dict[str, Any]:
        """JSON 엔드포인트. dart.py `_get`과 동일한 status(000/013) 처리. 키 미노출.

        비JSON 200(HTML 점검페이지 등)의 `resp.json()` ValueError도 DartAdapterError로 래핑.
        """
        self._limiter.acquire()
        try:
            resp = self._session.get(
                f"{_BASE}/{endpoint}", params=params, timeout=_TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            raise DartAdapterError(
                f"DART 요청 실패: endpoint={endpoint} ({type(e).__name__})"
            ) from None
        status = data.get("status")
        if status == "000":
            return data
        if allow_no_data and status == "013":  # 조회된 데이터 없음
            return {"list": []}
        raise DartAdapterError(
            f"DART API 오류: endpoint={endpoint}, status={status}, "
            f"msg={data.get('message')}"
        )

    # ── normalize (순수, 테스트 가능) ──
    def normalize(self, raw: Mapping[str, Any]) -> list[dict[str, Any]]:
        hyslr = raw.get("rows_hyslr") or []
        stock = raw.get("rows_stock") or []
        # 완전 미공시(양 엔드포인트 모두 빈 응답) → 행 미생성(1.2 no-data 교훈)
        if not hyslr and not stock:
            return []
        lsp = _largest_shareholder_pct(hyslr)
        tsp = _treasury_stock_pct(stock)
        # 행은 있으나 두 지표 모두 파싱 실패 → 무의미한 all-NULL 행 대신 no-data 취급
        if lsp is None and tsp is None:
            return []
        return [
            {
                "corp_code": raw["corp_code"],
                "as_of": raw["as_of"],
                "largest_shareholder_pct": lsp,
                "treasury_stock_pct": tsp,
            }
        ]

    # ── upsert (멱등) ──
    def upsert(self, session: Session, records: Sequence[dict[str, Any]]) -> int:
        for rec in records:
            upsert_ownership(session, rec)
        session.flush()
        return len(records)
