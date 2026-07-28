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
# 계획이 아닌 공시 제외(1.10, F9 실증): 이행현황(사후보고)·철회는 목표 공시가 아님.
# 정정([기재정정] 등)은 유지 — 최신 정정이 권위 있는 목표(2.1 최신공시 채택 규칙과 정합).
_REPORT_EXCLUDE = ("이행현황", "철회")


def _is_plan_report(report_nm: str | None) -> bool:
    """report_nm이 '계획' 공시인지 판정(공백 제거 부분일치 + 부정 키워드 제외)."""
    compact = str(report_nm or "").replace(" ", "")
    if _REPORT_KEYWORD not in compact:
        return False
    return not any(kw in compact for kw in _REPORT_EXCLUDE)
_MAX_PAGES = 50  # 페이지네이션 상한(과대 total_page 방어)
_MAX_ZIP_BYTES = 20 * 1024 * 1024  # 문서 ZIP 원본 크기 상한
_MAX_MEMBER_BYTES = 10 * 1024 * 1024  # 멤버 압축해제 크기 상한(zip-bomb 방어)
_MAX_TOTAL_BYTES = 50 * 1024 * 1024  # 누적 압축해제 상한(일괄리뷰 Med: 멤버별 한도 우회 방어)
_MAX_MEMBERS = 200  # 텍스트 멤버 수 상한
_TEXT_EXTS = (".xml", ".html", ".htm", ".txt")  # 텍스트 멤버만(바이너리 오탐 방지)
_PBR_MAX = 100.0  # 현실적 PBR 상한(연도·페이지번호 오탐 배제)

# ── best-effort 파싱 패턴 ──
# 값 뒤에 p/P/포(인트)가 오면 '퍼센트포인트'(증감)라 절대목표 아님 → 제외.
_PCT = r"(\d+(?:\.\d+)?)\s*%(?![pP포])"
# ROE 별칭(1.10, 실샘플 6건: '자기자본이익률' 표기).
_ROE_LABEL = r"(?:ROE|자기자본이익률)"
# 경쟁 지표 라벨(일괄리뷰 2026-07-13 High): gap이 다른 지표를 가로질러 그 지표의 %를
# 훔쳐오는 오탐 차단 — 라벨별로 "자신이 아닌" 지표들을 배제한다.
_OTHERS_FOR_ROE = r"배당성향|주주환원|PBR|영업이익|부채비율"
_OTHERS_FOR_PAYOUT = r"ROE|자기자본이익률|주주환원|PBR|영업이익|부채비율"
# 주주환원율 라벨이 자기 자신이므로 배제 목록에서 빼고, 배당성향을 경쟁 지표로 넣는다.
_OTHERS_FOR_RETURN = r"ROE|자기자본이익률|배당성향|PBR|영업이익|부채비율"


def _plain_gap(others: str) -> str:
    """라벨-값 gap: 개행·숫자·%·경쟁 지표 금지 + 괄호 한정어 1개 허용.

    괄호 안은 숫자·백틱 허용(실샘플 `목표(\\`24~\\`30년 평균)`)하되 **%·경쟁 지표는 금지**
    (일괄리뷰 High: `ROE(2024년 5%) 배당성향 30%`가 30을 ROE로 훔치던 오탐 차단).
    """
    pre = rf"(?:(?!{others})[^0-9%\n(]){{0,15}}"
    paren = rf"(?:\((?:(?!%|{others})[^)\n]){{0,25}}\)\s*[:：]?\s*)?"
    tail = rf"(?:(?!{others})[^0-9%\n]){{0,10}}?"
    return pre + paren + tail


_ROE_RE = re.compile(_ROE_LABEL + _plain_gap(_OTHERS_FOR_ROE) + _PCT, re.IGNORECASE)
# '배당성향'만 매칭(주주환원율은 다른 지표라 target_payout_ratio에 넣지 않음).
_PAYOUT_RE = re.compile(r"배당성향" + _plain_gap(_OTHERS_FOR_PAYOUT) + _PCT)
# 총주주환원율(배당+자사주매입)/순이익 — **배당성향과 다른 지표**라 별도 필드로 받는다(5-1).
# 이 구분은 처음부터 의도된 것이었고(위 주석), 빠져 있던 건 받아줄 필드였다.
_RETURN_LABEL = r"(?:총\s*주주환원율|주주환원율|총주주환원)"
# **목표 표지 필수**(5-1 실샘플 검증). 주주환원율은 계획 공시에서 목표만큼이나 자주
# *이행 실적*으로 등장한다 — "'25년 총 주주환원율 268.0%", "총주주환원율 72.8%",
# "3년 평균 주주환원율 78%(현황)". 라벨+숫자만 보면 13건 중 5건이 과거 실적이었다.
# 값 뒤 짧은 구간에 목표를 뜻하는 말이 와야만 채택한다(같은 절 안 — 개행은 넘지 않는다).
# 보수적으로 놓치는 쪽을 택한다: 애매하면 null(NFR2).
# **경쟁 지표 라벨 배제**(교차리뷰 2026-07-23 CONFIRMED): 표지 창이 다른 지표의 목표 표지를
# 훔쳐오는 오탐 차단. `_plain_gap`은 값 앞 gap에서만 경쟁 라벨을 막았고 이 룩어헤드(값 뒤)는
# 막지 않아, "주주환원율 50% ROE 목표 12%"가 ROE의 '목표'를 빌려 50을 총주주환원율 목표로
# 오채택했다(틀린 non-null → NFR2 위반). 표지 앞에 경쟁 라벨이 끼면 매칭을 끊는다.
_TARGET_MARK = (
    rf"(?=(?:(?!{_OTHERS_FOR_RETURN})[^\n]){{0,12}}?(?:목표|지향|이상|확대|원칙|수준|계획))"
)
_RETURN_RE = re.compile(
    _RETURN_LABEL + _plain_gap(_OTHERS_FOR_RETURN) + _PCT + _TARGET_MARK
)


def _arrow_tail(others: str) -> str:
    """"현재 X% → 목표 Y%" 화살표 체인(우변 채택). 좌변 gap은 숫자 허용(연도 서술 통과)
    하되 **경쟁 지표 라벨은 금지**(일괄리뷰 High: 남의 화살표를 훔치던 오탐 차단), 개행 금지."""
    seg_l = rf"(?:(?!{others})[^%\n]){{0,30}}?"
    seg_m = rf"(?:(?!{others})[^\n%]){{0,25}}?"
    return (
        seg_l + r"(\d+(?:\.\d+)?)\s*%"
        + seg_m + r"(?:→|⇒|➔)\s*" + seg_m + r"(\d+(?:\.\d+)?)\s*%(?![pP포])"
    )


_ROE_ARROW_RE = re.compile(_ROE_LABEL + _arrow_tail(_OTHERS_FOR_ROE), re.IGNORECASE)
_PAYOUT_ARROW_RE = re.compile(r"배당성향" + _arrow_tail(_OTHERS_FOR_PAYOUT))
_RETURN_ARROW_RE = re.compile(_RETURN_LABEL + _arrow_tail(_OTHERS_FOR_RETURN) + _TARGET_MARK)
# PBR은 '배' 단위 **필수**(연도·페이지번호를 PBR로 오탐하는 것 차단).
_PBR_RE = re.compile(r"PBR[^0-9\n]{0,15}?(\d+(?:\.\d+)?)\s*배", re.IGNORECASE)
_PERIOD_RE = re.compile(r"(20\d{2})\s*년?\s*[~\-–∼]\s*(20\d{2})")
# 1.10: 백틱/따옴표 표식이 붙은 2자리 연도 범위(실샘플 `24~`30년) → 20xx 확장.
# 표식·'년' 필수(24~26개월 같은 비연도 오탐 방지).
_PERIOD2_RE = re.compile(r"[`'‘’]\s*(\d{2})\s*[~\-–∼]\s*[`'‘’]?\s*(\d{2})\s*년")
# 기간 후보 선택 앵커(일괄리뷰 Med: 과거 비교기간을 계획기간으로 오인 방지).
# '기간'은 제외 — "비교기간"에도 들어가 과거 범위를 앵커시키는 역효과.
_PERIOD_CTX_RE = re.compile(r"(계획|목표|향후|중장기)")


def _select_period(text: str) -> tuple[str | None, str | None]:
    """문서 내 모든 연도범위 후보 중 계획 문맥에 앵커된 것을 선택(일괄리뷰 Med).

    규칙: (1) 후보 직전 20자에 계획·목표·향후·중장기가 있으면 그 첫 후보,
    (2) 앵커 없고 후보가 전부 같은 범위면 그 값(단일 후보 포함 — 기존 recall 유지),
    (3) 앵커 없이 상이한 범위 다수면 애매 → null(NFR2).
    """
    cands: list[tuple[int, str, str]] = []
    for m in _PERIOD_RE.finditer(text):
        if int(m.group(1)) <= int(m.group(2)):
            cands.append((m.start(), m.group(1), m.group(2)))
    for m in _PERIOD2_RE.finditer(text):
        start, end = f"20{m.group(1)}", f"20{m.group(2)}"
        if int(start) <= int(end):
            cands.append((m.start(), start, end))
    if not cands:
        return None, None
    cands.sort()
    anchored = [
        c for c in cands
        if _PERIOD_CTX_RE.search(text[max(0, c[0] - 20): c[0]])
    ]
    if anchored:
        return anchored[0][1], anchored[0][2]
    if len({(s, e) for _, s, e in cands}) == 1:
        return cands[0][1], cands[0][2]
    return None, None
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
    total_bytes = 0
    members = 0
    with zf:
        for info in zf.infolist():
            if not info.filename.lower().endswith(_TEXT_EXTS):
                continue
            if info.file_size > _MAX_MEMBER_BYTES:
                continue
            members += 1
            total_bytes += info.file_size
            if members > _MAX_MEMBERS or total_bytes > _MAX_TOTAL_BYTES:
                raise DartDocumentError("문서 누적 압축해제 상한 초과(멤버 수/총 크기)")
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

    def _num_with_arrow(arrow_rx: re.Pattern[str], plain_rx: re.Pattern[str]) -> float | None:
        """화살표 체인(현재→목표)은 우변(목표) 채택 — 단 **문서 내 위치가 앞선 쪽 우선**
        (일괄리뷰 Med: 앞의 명시 목표가 뒤쪽 과거실적 표의 화살표에 밀리지 않게).
        같은 위치(같은 clause)에서 화살표가 있으면 화살표 우변이 목표."""
        am = arrow_rx.search(text)
        pm = plain_rx.search(text)
        if am is not None and (pm is None or am.start() <= pm.start()):
            return float(am.group(2))
        return float(pm.group(1)) if pm else None

    pbr = _num(_PBR_RE)
    if pbr is not None and not (0 < pbr <= _PBR_MAX):
        pbr = None  # 연도·비현실적 값 배제

    # 기간: 전체 후보 중 계획 문맥 앵커 우선(일괄리뷰 Med — 과거 비교기간 오인 방지)
    period_start, period_end = _select_period(text)

    buyback: bool | None = None
    bm = _BUYBACK_RE.search(text)
    if bm:
        window = text[max(0, bm.start() - 10) : bm.end() + 15]
        buyback = False if _BUYBACK_NEG_RE.search(window) else True

    return {
        "target_roe": _num_with_arrow(_ROE_ARROW_RE, _ROE_RE),
        "target_payout_ratio": _num_with_arrow(_PAYOUT_ARROW_RE, _PAYOUT_RE),
        "target_total_return_ratio": _num_with_arrow(_RETURN_ARROW_RE, _RETURN_RE),
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
            page_items = data.get("list")
            if page_items is None:
                page_items = []
            if not isinstance(page_items, list):  # 형태 이탈 → 페이지 실패로 격리
                failed.append((f"list.json#p{page_no}", "list 형태 오류"))
                break
            for item in page_items:
                if not isinstance(item, Mapping):  # malformed 항목 격리(일괄리뷰 High)
                    continue
                report_nm = str(item.get("report_nm") or "")
                if not _is_plan_report(report_nm):  # 1.10: 이행현황·철회 제외(F9)
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
        except (requests.RequestException, ValueError) as e:
            # ValueError=비JSON 200(dart.py `_get`과 동일 처리, 일괄리뷰 High)
            raise DartAdapterError(
                f"DART 요청 실패: endpoint={endpoint} ({type(e).__name__})"
            ) from None
        if not isinstance(data, dict):
            # 비-dict JSON(list/str)이 AttributeError로 누출되면 페이지 격리 계약이
            # 깨진다(DartAdapterError만 부분결과 보존 경로를 탄다, 일괄리뷰 High)
            raise DartAdapterError(f"DART 응답 형태 오류: endpoint={endpoint}")
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
