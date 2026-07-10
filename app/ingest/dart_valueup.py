"""DART 밸류업 계획공시 어댑터 — valueup_plan의 writer (AD-3, source="dart").

"기업가치 제고 계획"은 구조화 재무 API가 없는 **자유서식 공시**라 2단계로 수집한다:
  1) list.json(공시검색, JSON)  → report_nm 매칭으로 밸류업 공시 발견(다중·다중페이지)
  2) document.xml(ZIP 바이너리) → 압축 해제·태그 스트립으로 원문 raw_text 확보

정확성 계약의 핵심 = **raw_text 보존 + 멱등 upsert**. 목표 필드(ROE·배당성향·PBR·기간·자사주)는
best-effort 정규식이며 **애매하면 null**(틀린 non-null 값 금지 — 코드리뷰 반영).

설계 규약(코드리뷰 반영):
- **문서별 격리**: 한 문서/후반 페이지 실패가 그 종목의 이미 모은 공시를 날리지 않는다.
- **성공/실패 구분**: 유효 문서를 파싱한 결과만 upsert(권위) → repository가 목표필드를 null 포함
  전체 교체. 문서 fetch 실패(비ZIP·HTTP오류·빈 응답)는 upsert하지 않아 기존 레코드를 보존한다.
- ⚠️ document.xml은 ZIP 바이너리 → dart.py의 `_get`(resp.json) 재사용 금지. `_fetch_document`는
  `resp.content`를 쓰고, 실패는 DartDocumentError로 격리. HTTP 하드닝·키 미노출은 dart.py 재사용.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Mapping, Sequence
from datetime import datetime
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
    _TIMEOUT,
    DartAdapterError,
    _RateLimiter,
)
from app.repositories.valueup_plan import upsert_valueup_plan

# report_nm 매칭(공백 제거 후 부분일치). pblntf_ty로 좁히지 않는다(과대필터 방지).
_REPORT_KEYWORD = "기업가치제고계획"
_MAX_PAGES = 50  # 페이지네이션 상한(과대 total_page 방어)
_MAX_ZIP_BYTES = 20 * 1024 * 1024  # 문서 ZIP 원본 크기 상한
_MAX_MEMBER_BYTES = 10 * 1024 * 1024  # 멤버 압축해제 크기 상한(zip-bomb 방어)
_TEXT_EXTS = (".xml", ".html", ".htm", ".txt")  # 텍스트 멤버만(바이너리 오탐 방지)
_PBR_MAX = 100.0  # 현실적 PBR 상한(연도·페이지번호 오탐 배제)

# ── best-effort 파싱 패턴 ──
# 값 뒤에 p/P/포(인트)가 오면 '퍼센트포인트'(증감)라 절대목표 아님 → 제외.
_PCT = r"(\d+(?:\.\d+)?)\s*%(?![pP포])"
# 라벨-값 gap은 **개행을 넘지 못한다**(표 셀/문단 경계 보존 → 인접 지표 % 침범 방지).
_ROE_RE = re.compile(r"ROE[^0-9%\n]{0,15}?" + _PCT, re.IGNORECASE)
# '배당성향'만 매칭(주주환원율은 다른 지표라 target_payout_ratio에 넣지 않음).
_PAYOUT_RE = re.compile(r"배당성향[^0-9%\n]{0,15}?" + _PCT)
# PBR은 '배' 단위 **필수**(연도·페이지번호를 PBR로 오탐하는 것 차단).
_PBR_RE = re.compile(r"PBR[^0-9\n]{0,15}?(\d+(?:\.\d+)?)\s*배", re.IGNORECASE)
_PERIOD_RE = re.compile(r"(20\d{2})\s*년?\s*[~\-–∼]\s*(20\d{2})")
_BUYBACK_RE = re.compile(r"(자기주식|자사주)[^\n]{0,15}?(취득|매입|소각)")
# 부정·과거(계획 아님) 문맥 → False 판정.
_BUYBACK_NEG_RE = re.compile(r"(없음|없이|아니|않|미실시|미계획|계획\s*없|완료|기실시)")


class DartDocumentError(DartAdapterError):
    """문서(document.xml) 다운로드/해제 실패 — 종목 전체가 아니라 그 문서만 격리."""


def _safe_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _parse_date(yyyymmdd: str | None) -> str | None:
    """YYYYMMDD → ISO YYYY-MM-DD. strptime으로 엄격 검증, 무효면 None(적재 제외용)."""
    s = (yyyymmdd or "").strip()
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return datetime.strptime(s, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _strip_tags(s: str) -> str:
    """DART 전용 XML 마크업 태그 제거. 태그 자리를 **개행으로 치환**해 셀/문단 경계를 보존한다
    (라벨과 인접 지표 값이 한 줄로 뭉쳐 오탐되는 것 방지)."""
    text = re.sub(r"<[^>]+>", "\n", s)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)  # 공백류만 축약(개행은 유지)
    text = re.sub(r"\n[ \t]*", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _zip_to_text(content: bytes) -> str:
    """document.xml ZIP → 평문. 비ZIP/빈/추출실패는 DartDocumentError(성공값과 구분).

    텍스트 멤버(.xml/.html/.txt)만, 사이즈 상한으로 읽는다(바이너리 오탐·zip-bomb 방어).
    """
    if not content:
        raise DartDocumentError("빈 문서 응답")
    if len(content) > _MAX_ZIP_BYTES:
        raise DartDocumentError("문서 ZIP 크기 상한 초과")
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        # 비ZIP = DART 오류 HTML/XML 응답 → 실패로 격리(빈 원문으로 오인 금지)
        raise DartDocumentError("ZIP 아님(오류 응답 가능)") from None
    parts: list[str] = []
    with zf:
        for info in zf.infolist():
            if not info.filename.lower().endswith(_TEXT_EXTS):
                continue
            if info.file_size > _MAX_MEMBER_BYTES:
                continue
            parts.append(_decode(zf.read(info)))
    text = _strip_tags("\n".join(parts))
    if not text:
        raise DartDocumentError("문서에서 텍스트 추출 실패")
    return text


def parse_targets(raw_text: str | None) -> dict[str, Any]:
    """유효 문서 원문에서 목표 필드 best-effort 추출. 못 찾으면 해당 필드 None.

    보수적: 애매하면 null(틀린 non-null 값 금지). 값 뒤 p(포인트)·단위없는 PBR·범위이상·부정 자사주 배제.
    """
    text = raw_text or ""

    def _num(rx: re.Pattern[str]) -> float | None:
        m = rx.search(text)
        return float(m.group(1)) if m else None

    pbr = _num(_PBR_RE)
    if pbr is not None and not (0 < pbr <= _PBR_MAX):
        pbr = None  # 연도·비현실적 값 배제

    period_start = period_end = None
    pm = _PERIOD_RE.search(text)
    if pm and int(pm.group(1)) <= int(pm.group(2)):  # start<=end만 인정
        period_start, period_end = pm.group(1), pm.group(2)

    buyback: bool | None = None
    bm = _BUYBACK_RE.search(text)
    if bm:
        window = text[max(0, bm.start() - 10) : bm.end() + 15]
        buyback = False if _BUYBACK_NEG_RE.search(window) else True

    return {
        "target_roe": _num(_ROE_RE),
        "target_payout_ratio": _num(_PAYOUT_RE),
        "target_pbr": pbr,
        "period_start": period_start,
        "period_end": period_end,
        "buyback_planned": buyback,
    }


class DartValueupAdapter(SourceAdapter):
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
    def fetch(self, corp_code: str, bgn_de: str, end_de: str) -> dict[str, Any]:
        key = settings.dart_api_key.get_secret_value()
        if not key:
            raise DartAdapterError(
                "DART_API_KEY가 설정되지 않았습니다. .env에 DART_API_KEY를 넣으세요."
            )
        plans: list[dict[str, Any]] = []
        failed: list[tuple[str | None, str]] = []
        page_no = 1
        while page_no <= _MAX_PAGES:
            try:
                data = self._get_json(
                    "list.json",
                    {
                        "crtfc_key": key,
                        "corp_code": corp_code,
                        "bgn_de": bgn_de,
                        "end_de": end_de,
                        "page_no": page_no,
                        "page_count": 100,
                    },
                    allow_no_data=True,
                )
            except DartAdapterError as e:
                # 후반 페이지 실패 시 이미 모은 plan은 보존하고 중단(부분결과 보존)
                failed.append((f"list.json#p{page_no}", type(e).__name__))
                break
            for item in data.get("list") or []:
                report_nm = str(item.get("report_nm") or "")
                if _REPORT_KEYWORD not in report_nm.replace(" ", ""):
                    continue
                disclosure_date = _parse_date(item.get("rcept_dt"))
                rcept_no = item.get("rcept_no")
                if disclosure_date is None:
                    failed.append((rcept_no, "무효 rcept_dt"))
                    continue
                if not rcept_no:
                    failed.append((None, "rcept_no 없음"))
                    continue
                try:
                    raw_text = self._fetch_document(key, rcept_no)  # 문서별 격리
                except DartDocumentError as e:
                    failed.append((rcept_no, type(e).__name__))
                    continue
                plans.append(
                    {
                        "disclosure_date": disclosure_date,
                        "report_nm": report_nm,
                        "raw_text": raw_text,
                    }
                )
            total_page = _safe_int(data.get("total_page"), 1)
            if page_no >= total_page:
                break
            page_no += 1
        return {"corp_code": corp_code, "plans": plans, "failed": failed}

    def _get_json(
        self, endpoint: str, params: Mapping[str, Any], allow_no_data: bool = False
    ) -> dict[str, Any]:
        """list.json 등 JSON 엔드포인트. dart.py `_get`과 동일한 status 처리. 키 미노출."""
        self._limiter.acquire()
        try:
            resp = self._session.get(
                f"{_BASE}/{endpoint}", params=params, timeout=_TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
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

    def _fetch_document(self, key: str, rcept_no: str) -> str:
        """document.xml(ZIP 바이너리) 다운로드 → 평문. 실패는 DartDocumentError로 격리."""
        self._limiter.acquire()
        try:
            resp = self._session.get(
                f"{_BASE}/document.xml",
                params={"crtfc_key": key, "rcept_no": rcept_no},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            content = resp.content  # 바이너리(ZIP) — resp.json 금지
        except requests.RequestException as e:
            raise DartDocumentError(
                f"문서 다운로드 실패 ({type(e).__name__})"
            ) from None
        return _zip_to_text(content)  # 비ZIP/빈/추출실패 → DartDocumentError

    # ── normalize (순수, 테스트 가능) ──
    def normalize(self, raw: Mapping[str, Any]) -> list[dict[str, Any]]:
        corp_code = raw["corp_code"]
        recs: list[dict[str, Any]] = []
        for plan in raw.get("plans", []):
            rec: dict[str, Any] = {
                "corp_code": corp_code,
                "disclosure_date": plan["disclosure_date"],
                "raw_text": plan.get("raw_text"),
            }
            rec.update(parse_targets(plan.get("raw_text")))
            recs.append(rec)
        return recs

    # ── upsert (멱등, 유효 문서 기반 전체 교체) ──
    def upsert(self, session: Session, records: Sequence[dict[str, Any]]) -> int:
        for rec in records:
            upsert_valueup_plan(session, rec)
        session.flush()
        return len(records)
