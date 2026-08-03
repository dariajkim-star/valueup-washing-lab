"""DART 지분공시 어댑터 — ownership의 writer (AD-3, source="dart").

1.5(자유서식)와 달리 **구조화 JSON** 두 엔드포인트를 쓴다(1.2 재무제표 패턴에 가깝다):
  - hyslrSttus.json        : 최대주주 현황 → largest_shareholder_pct (보통주 "계"행)
  - stockTotqySttus.json   : 주식의 총수 현황 → treasury_stock_pct (자기주식/발행총수)

JSON 응답이라 dart.py의 `_get`(status 000/013) 패턴을 미러한 `_get_json`을 쓴다(1.5의
document.xml ZIP 경로 불필요). HTTP 하드닝·키 미노출·수량 파싱은 dart.py 재사용.

코드리뷰 반영(null>오값): 요약행 결측·이상 포맷에선 틀린 non-null 대신 None.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from sqlalchemy import text
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
logger = logging.getLogger(__name__)

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

    ■ [2026-08-03] 자기주식수 칸의 '-'는 **미공시가 아니라 보유 없음(0주)**이다.
        실측: 대덕·콜마홀딩스·현대지에프·동원산업 모두 **합계행이 있고 발행주식총수도
        정상 보고**(35,102,507 등)인데 자기주식 칸만 '-'다. 표 자체는 제출됐고 다른 칸은
        채워져 있으므로, 이 '-'는 "안 알려줬다"가 아니라 "없다"로 읽는 것이 사실에 맞다.
        (같은 판단을 2026-07-31 자사주 취득/처분 표에서 이미 했다 — DART 표의 '-'를
        미공시로 읽어 239개사의 "안 했다"가 "판단 불가"로 세탁되고 있었다.)

        null로 두면 ownership_score가 죽고 **M&A 점수 전체가 null이 된다** — 실측 54종목
        (삼성바이오로직스·LG에너지솔루션·현대글로비스·롯데칠성 등)이 오직 이 한 칸 때문에
        점수를 못 받고 있었다.

        ⚠ 단, 이 판정은 **반증 가능**하다. 재무제표에 자사주 **순매입(매입−소각) > 0**이
        있으면 연말 보유가 0일 수 없다 — 그런 종목은 여기서 0으로 확정하지 않는다.
        그 대조는 DB가 필요하므로 순수 함수인 여기가 아니라 `upsert`가 수행한다
        (`_contradicts_zero_treasury`). 이 함수는 "표가 '-'라고 말했다"는 사실만 남긴다.
    """
    total = [r for r in rows if str(r.get("se", "")).strip() == "합계"]
    if not total:
        return None
    target = total[0]
    istc = _parse_amount(target.get("istc_totqy"))
    tesstk = _parse_amount(target.get("tesstk_co"))
    if not istc:  # 발행총수 0/None → 0 나눗셈 방어(이건 진짜 미상)
        return None
    if tesstk is None:
        # 발행총수는 정상인데 자기주식만 '-' → 보유 없음(0). 위 주석의 반증은 upsert에서.
        return 0.0
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
            _apply_zero_treasury_gate(session, rec)
            upsert_ownership(session, rec)
        session.flush()
        return len(records)


def _net_buyback(session: Session, corp_code: str, year: int) -> int | None:
    """해당 연도 자사주 **순매입**(매입 − 소각, 주). 재무 행이 없으면 None."""
    row = session.execute(
        text(
            "SELECT COALESCE(buyback_amount, 0) - COALESCE(buyback_retired_amount, 0) "
            "FROM financials WHERE corp_code = :c AND year = :y"
        ),
        {"c": corp_code, "y": year},
    ).first()
    return None if row is None else int(row[0])


def _apply_zero_treasury_gate(session: Session, rec: dict[str, Any]) -> None:
    """자사주 0 판정의 **반증 검사** — 순매입 > 0이면 0을 취소하고 null로 되돌린다.

    `_treasury_stock_pct`는 "표의 자기주식 칸이 '-'였다"는 사실만 0으로 남긴다. 그런데
    그 해에 자사주를 **소각한 것보다 많이 사들였다면** 연말 보유가 0일 수 없다 —
    실측에서 콜마홀딩스가 그랬다(매입 4,621,897 − 소각 2,473,261 = +2,148,636주).

    **소각만 했거나 매입=소각인 종목은 반증이 아니다** — 소각은 자사주를 없애는 행위라
    오히려 0을 지지한다(부광약품·롯데렌탈·롯데이노베이트). 처음에 "자사주 활동 있음"으로
    잡았을 땐 반증이 4건이었는데, 순매입 기준으로 좁히니 **1건**이 됐다.

    되돌린 값은 null이다 — "재보니 0이 아니다"까지만 알고 실제 보유량은 모르기 때문이다
    (틀린 non-null 대신 null, NFR2).
    """
    if rec.get("treasury_stock_pct") != 0.0:
        return  # 0 판정이 아닌 값(실수치·None)은 건드리지 않는다
    as_of = str(rec.get("as_of") or "")
    if len(as_of) < 4 or not as_of[:4].isdigit():
        return
    net = _net_buyback(session, rec["corp_code"], int(as_of[:4]))
    if net is not None and net > 0:
        logger.info(
            "자사주 0 판정 취소(순매입 %s주 > 0) corp_code=%s %s",
            net, rec["corp_code"], as_of,
        )
        rec["treasury_stock_pct"] = None
