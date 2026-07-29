"""첨부(PDF) 파싱 — 받아둔 파일에서 밸류업 목표를 읽는다.

■ 취득은 여기 없다 (2026-07-29 결정)
    DART robots.txt가 우리가 쓰려던 경로를 전부 Disallow한다:
        /dsaf001/main.do · /report/viewer.do · /report/download.do · /pdf/download/
        · /dsae001/selectPopup.ax
    운영자가 기계가독 형식으로 명시한 지시이므로 자동 취득을 하지 않는다. 파일은 사람이
    받아 `attachments/`에 두고, 이 모듈은 **읽기만** 한다. 파이프라인의 값은 취득이 아니라
    파싱·목표추출·출처기록에 있었고, 그쪽은 전혀 막히지 않았다.

■ 파일 이름 규약 (둘 다 허용)
    1) `{rcept_no}.pdf`                 — 예: 20241127800702.pdf   (권장)
    2) `{corp_code}_{YYYY-MM-DD}.pdf`   — 예: 00164779_2024-11-27.pdf
    접수번호가 곧 공시의 신원(0015)이므로 1)이 가장 모호함이 없다. 접수번호를 아직 모르는
    공시(0015 이전 적재분)를 위해 2)를 남겨둔다.

■ 페이지 단위로 파싱하는 이유
    한 번에 전체 텍스트를 이어붙여 파싱하면 값은 얻어도 **어디서 왔는지**를 잃는다.
    이 프로젝트는 값에 출처가 따라붙는 것을 계약으로 지켜왔다(score_basis·population_basis·
    plan_disclosure_date). 첨부도 같아야 한다 — "첨부 PDF p.7"까지가 값이다.
    그래서 페이지별로 parse_targets를 돌리고, 필드가 **처음 확정된 페이지**를 근거로 남긴다.

■ 못 읽는 경우를 조용히 null로 만들지 않는다
    HWP는 순정 파서가 없고, 스캔본 PDF는 텍스트 레이어가 없다. 둘 다 "목표 미공시"가
    아니라 **"우리가 못 읽었다"**이므로 parse_error에 사유를 남긴다. 이 구분이 무너지면
    is_unrankable에서 지킨 원칙("못 읽은 걸 벌하지 않는다")이 첨부 층에서 되살아난다.

■ OCR은 자동 입력기가 아니라 후보 추출기다 (2026-07-29 결정)
    이미지 기반 PDF(우리금융 실측: 9쪽 전부, native 156자)는 OCR 없이 못 읽는다.
    native 텍스트가 빈약한 페이지에만 OCR(tesseract kor+eng)을 돌리고, OCR 유래 목표가
    하나라도 있으면 needs_review=True — merge_attachment가 채점에 태우지 않고, 사람이
    review_attachment CLI로 승인·수정·기각해야 풀린다. 첫 스파이크에서 OCR+파서가
    ROE 10.0을 맞히면서 동시에 이행 실적(배당성향 35.0)을 목표로 오인했다 — 틀린
    non-null은 null보다 위험하므로 자동 확정하지 않는다.
    OCR 스택(pymupdf·pytesseract·tesseract)이 없으면 종전대로 no_text_layer로 남긴다 —
    의존성 부재가 조용한 오동작이 되지 않게.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from app.ingest.dart_valueup import parse_targets

logger = logging.getLogger(__name__)

# 목표 필드(페이지 근거를 남기는 대상). target_pbr은 산식 미사용이지만 원값 보관은 유지.
_TARGET_FIELDS = (
    "target_roe",
    "target_payout_ratio",
    "target_total_return_ratio",
    "target_pbr",
    "period_start",
    "period_end",
    "buyback_planned",
)

_RCEPT_NAME = re.compile(r"^(\d{14})$")
_CORP_DATE_NAME = re.compile(r"^(\d{8})_(\d{4}-\d{2}-\d{2})$")

# 스캔본(텍스트 레이어 없음) 판정 임계 — 공백 제외 문자 수.
# 문서 크기에 비례시킨다: 50쪽 스캔본도 0자에 가까우므로 페이지당 하한을 두면 부분 스캔도
# 걸리고, 짧은 문서를 오탐하지 않는다.
_MIN_TEXT_CHARS = 20
_MIN_TEXT_CHARS_PER_PAGE = 5

# 페이지 단위 OCR 트리거 — native 텍스트(공백 제외)가 이 미만이면 이미지 페이지로 본다.
# 우리금융 실측: pdfplumber native가 9쪽 합계 156자(페이지당 ~17자) — 전 페이지가 걸린다.
# LG화학 같은 텍스트 PDF는 페이지당 수백 자라 걸리지 않는다.
_OCR_TRIGGER_CHARS = 50
_OCR_DPI = 220
_OCR_LANG = "kor+eng"


@dataclass
class AttachmentRef:
    """파일 이름에서 읽어낸 대상 공시 식별자. 둘 중 하나만 채워진다."""

    path: Path
    rcept_no: str | None = None
    corp_code: str | None = None
    disclosure_date: str | None = None


@dataclass
class ParsedAttachment:
    """파싱 결과 — 목표 + 필드별 근거 페이지 + 실패 사유."""

    path: Path
    sha256: str
    page_count: int | None = None
    targets: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, int] = field(default_factory=dict)  # 필드 → 페이지(1-base)
    extracted_text: str | None = None
    parse_error: str | None = None
    ocr_pages: list[int] = field(default_factory=list)  # OCR을 적용한 페이지(1-base)
    # OCR 유래 목표가 하나라도 있으면 True — 사람이 승인하기 전에는 채점에 안 들어간다.
    needs_review: bool = False

    @property
    def disclosed_axis_count(self) -> int:
        """폴백·불투명도 판정과 같은 축 셈(단일 정의처 재사용)."""
        from app.analysis.plan_selection import disclosed_axis_count

        return disclosed_axis_count(self.targets)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_filename(path: Path) -> AttachmentRef:
    """파일 이름 → 대상 공시 식별자. 규약에 안 맞으면 식별자 없이 반환(호출자가 보고)."""
    stem = path.stem.strip()
    m = _RCEPT_NAME.match(stem)
    if m:
        return AttachmentRef(path=path, rcept_no=m.group(1))
    m = _CORP_DATE_NAME.match(stem)
    if m:
        return AttachmentRef(path=path, corp_code=m.group(1), disclosure_date=m.group(2))
    return AttachmentRef(path=path)


def _page_text(page: Any) -> str:
    """페이지 텍스트 + 표 셀. 계획서는 표 중심이라 본문만 뽑으면 목표 숫자를 통째로 놓친다.

    표는 셀을 공백으로 이어 붙인다 — parse_targets의 정규식이 '라벨 … 숫자%' 형태를
    같은 줄에서 찾으므로, 행 단위로 이어야 "ROE | 10% | 2025~2027"이 매칭된다.
    """
    parts: list[str] = []
    text = page.extract_text() or ""
    if text:
        parts.append(text)
    try:
        for table in page.extract_tables() or []:
            for row in table:
                cells = [str(c).replace("\n", " ") for c in row if c]
                if cells:
                    parts.append(" ".join(cells))
    except Exception as e:  # noqa: BLE001 — 표 추출 실패가 본문 텍스트까지 버리지 않게
        logger.debug("표 추출 실패(본문은 유지): %s", type(e).__name__)
    return "\n".join(parts)


def _find_tesseract() -> str | None:
    """tesseract 실행 파일 탐색 — env 우선, PATH, Windows 기본 설치 경로 순."""
    import os
    import shutil

    env = os.environ.get("TESSERACT_CMD")
    if env and Path(env).exists():
        return env
    hit = shutil.which("tesseract")
    if hit:
        return hit
    default = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    return str(default) if default.exists() else None


def _ocr_ready() -> bool:
    """OCR 스택(pymupdf·pytesseract·tesseract 바이너리) 가용 여부.

    없으면 False — 호출자는 종전 동작(no_text_layer)으로 남긴다. 의존성 부재가
    조용한 오동작이 아니라 정직한 '못 읽음'이 되게 한다.
    """
    try:
        import fitz  # noqa: F401
        import pytesseract
    except ImportError:
        return False
    return _find_tesseract() is not None


def _ocr_page(path: Path, page_no: int) -> str:
    """페이지 하나를 렌더링해 OCR(kor+eng). page_no는 1-base."""
    import os

    import fitz
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = _find_tesseract()
    # 한국어 데이터가 시스템 tessdata에 없을 수 있어 로컬 경로를 기본값으로 보탠다.
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "tessdata"
    if "TESSDATA_PREFIX" not in os.environ and (local / "kor.traineddata").exists():
        os.environ["TESSDATA_PREFIX"] = str(local)

    import io

    from PIL import Image

    with fitz.open(str(path)) as doc:
        pix = doc[page_no - 1].get_pixmap(dpi=_OCR_DPI)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
    return pytesseract.image_to_string(img, lang=_OCR_LANG)


def parse_pdf(path: Path) -> ParsedAttachment:
    """PDF에서 목표를 읽고 필드별 근거 페이지를 남긴다.

    페이지를 순서대로 훑으며 아직 못 채운 필드만 채운다 — 계획서는 앞쪽에 요약,
    뒤쪽에 과거 실적표가 오는 구조가 흔해서 **먼저 확정된 값**을 채택하는 편이 안전하다
    (parse_targets 자체도 같은 이유로 '문서 내 앞선 위치 우선' 규칙을 쓴다).
    """
    result = ParsedAttachment(path=path, sha256=sha256_of(path))

    if path.suffix.lower() != ".pdf":
        # HWP는 순정 해법이 없다. 조용히 null로 만들지 않고 사유를 남긴다.
        result.parse_error = f"unsupported_format:{path.suffix.lower().lstrip('.')}"
        return result

    try:
        import pdfplumber
    except ImportError:
        result.parse_error = "pdfplumber_missing"
        return result

    targets: dict[str, Any] = {f: None for f in _TARGET_FIELDS}
    evidence: dict[str, int] = {}
    page_texts: list[str] = []

    try:
        with pdfplumber.open(str(path)) as pdf:
            result.page_count = len(pdf.pages)
            for idx, page in enumerate(pdf.pages, start=1):
                text = _page_text(page)
                page_texts.append(text)
                if not text.strip():
                    continue
                found = parse_targets(text)
                for f in _TARGET_FIELDS:
                    if targets[f] is None and found.get(f) is not None:
                        targets[f] = found[f]
                        evidence[f] = idx
    except Exception as e:  # noqa: BLE001 — 파일 단위 격리(한 파일이 배치를 죽이지 않게)
        logger.warning("PDF 파싱 실패 %s: %s", path.name, type(e).__name__)
        result.parse_error = f"parse_error:{type(e).__name__}"
        return result

    # ── OCR 폴백: native가 빈약한 페이지만, 아직 못 채운 필드만 ──────────────
    # native 우선(merge_attachment의 '본문 우선'과 같은 정신 — 검증된 추출이 이긴다).
    # OCR 유래 값은 후보다: needs_review=True로 표시되고 사람이 승인해야 채점에 들어간다.
    sparse = [
        i for i, t in enumerate(page_texts, start=1)
        if len(re.sub(r"\s", "", t)) < _OCR_TRIGGER_CHARS
    ]
    if sparse and any(targets[f] is None for f in _TARGET_FIELDS) and _ocr_ready():
        ocr_filled = False
        for idx in sparse:
            try:
                ocr_text = _ocr_page(path, idx)
            except Exception as e:  # noqa: BLE001 — 한 페이지 실패가 문서를 죽이지 않게
                logger.warning("OCR 실패 %s p.%d: %s", path.name, idx, type(e).__name__)
                continue
            if not ocr_text.strip():
                continue
            result.ocr_pages.append(idx)
            page_texts[idx - 1] = (
                page_texts[idx - 1] + f"\n[OCR p.{idx}]\n{ocr_text}"
            ).strip()
            found = parse_targets(ocr_text)
            for f in _TARGET_FIELDS:
                if targets[f] is None and found.get(f) is not None:
                    targets[f] = found[f]
                    evidence[f] = idx
                    ocr_filled = True
        result.needs_review = ocr_filled

    full_text = "\n".join(page_texts)
    result.extracted_text = full_text
    result.targets = targets
    result.evidence = evidence

    # 텍스트가 거의 없으면 스캔본이다 — "목표 미공시"가 아니라 "우리가 못 읽었다".
    # 단 **목표를 실제로 뽑았으면 못 읽었다고 하지 않는다** — 읽어낸 문서를 unreadable로
    # 표시하면 그 값이 하류에서 신뢰 불가로 취급되는 자기모순이 생긴다.
    # OCR이 텍스트를 얻어냈다면(ocr_pages) 이제는 읽은 문서다 — no_text_layer가 아니다.
    if result.disclosed_axis_count == 0 and not result.ocr_pages:
        chars = len(re.sub(r"\s", "", full_text))
        floor = max(_MIN_TEXT_CHARS, _MIN_TEXT_CHARS_PER_PAGE * (result.page_count or 1))
        if chars < floor:
            result.parse_error = "no_text_layer"

    return result


def scan_directory(directory: Path) -> list[AttachmentRef]:
    """attachments/ 안의 파일 목록(하위 폴더 포함). 숨김/임시 파일은 건너뛴다."""
    if not directory.exists():
        return []
    refs: list[AttachmentRef] = []
    for p in sorted(directory.rglob("*")):
        if not p.is_file() or p.name.startswith((".", "~$")):
            continue
        refs.append(parse_filename(p))
    return refs


def evidence_to_json(evidence: dict[str, int]) -> str | None:
    return json.dumps(evidence, ensure_ascii=False, sort_keys=True) if evidence else None


def today_iso() -> str:
    return date.today().isoformat()
