"""첨부(PDF) 파싱 — 목표 추출 + 페이지 근거 + 못 읽음 구분.

테스트용 PDF는 reportlab 없이 **최소 PDF를 직접 조립**해 만든다(의존성 추가 회피).
한글은 내장 폰트로 못 그리므로 본문은 ASCII 라벨(ROE/PBR)과 숫자로 검증하고,
한글 라벨 경로는 parse_targets 자체 테스트가 이미 덮는다.
"""

from __future__ import annotations

import zlib
from pathlib import Path

import pytest

from app.ingest.attachment import (
    parse_filename,
    parse_pdf,
    scan_directory,
    sha256_of,
)


def _make_pdf(path: Path, pages: list[str]) -> None:
    """페이지별 텍스트를 담은 최소 PDF 작성(내장 Helvetica, 압축 스트림).

    객체 번호를 **고정 순서**로 미리 정한다(앞선 구현은 번호를 뒤늦게 계산해 /Parent가
    엉켰고 pdfplumber가 TypeError로 죽었다):
        1 = Catalog · 2 = Pages · 3 = Font · 4..3+N = Page · 4+N..3+2N = Contents
    """
    n = len(pages)
    catalog_id, pages_id, font_id = 1, 2, 3
    first_page_id = 4
    first_content_id = first_page_id + n

    objs: dict[int, bytes] = {}
    objs[catalog_id] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = b" ".join(f"{first_page_id + i} 0 R".encode() for i in range(n))
    objs[pages_id] = (
        b"<< /Type /Pages /Kids [" + kids + b"] /Count " + str(n).encode() + b" >>"
    )
    objs[font_id] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    for i, text in enumerate(pages):
        parts = [b"BT /F1 12 Tf 40 750 Td 14 TL"]
        for ln in text.split("\n"):
            esc = ln.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
            parts.append(b"(" + esc.encode("latin-1", "replace") + b") Tj T*")
        parts.append(b"ET")
        stream = zlib.compress(b"\n".join(parts))
        objs[first_content_id + i] = (
            b"<< /Length " + str(len(stream)).encode() + b" /Filter /FlateDecode >>\n"
            b"stream\n" + stream + b"\nendstream"
        )
        objs[first_page_id + i] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents "
            + str(first_content_id + i).encode() + b" 0 R >>"
        )

    total = 3 + 2 * n
    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for num in range(1, total + 1):
        offsets[num] = len(out)
        out += str(num).encode() + b" 0 obj\n" + objs[num] + b"\nendobj\n"
    xref_pos = len(out)
    out += b"xref\n0 " + str(total + 1).encode() + b"\n0000000000 65535 f \n"
    for num in range(1, total + 1):
        out += f"{offsets[num]:010d} 00000 n \n".encode()
    out += (b"trailer\n<< /Size " + str(total + 1).encode()
            + b" /Root 1 0 R >>\nstartxref\n" + str(xref_pos).encode() + b"\n%%EOF\n")
    path.write_bytes(bytes(out))


class TestFilenameConvention:
    def test_rcept_no_form(self):
        ref = parse_filename(Path("attachments/20241127800702.pdf"))
        assert ref.rcept_no == "20241127800702"
        assert ref.corp_code is None

    def test_corp_and_date_form(self):
        ref = parse_filename(Path("attachments/00164779_2024-11-27.pdf"))
        assert ref.corp_code == "00164779"
        assert ref.disclosure_date == "2024-11-27"

    def test_unrecognised_name_yields_no_identifier(self):
        """규약에 안 맞으면 조용히 추측하지 않는다 — 배치가 사유와 함께 건너뛴다."""
        ref = parse_filename(Path("attachments/하이닉스 밸류업.pdf"))
        assert ref.rcept_no is None and ref.corp_code is None


class TestParsePdf:
    def test_extracts_targets_with_page_evidence(self, tmp_path):
        """목표가 3페이지에 있으면 근거 페이지도 3으로 남는다 — '첨부 PDF p.3'의 근거."""
        pdf = tmp_path / "20241127800702.pdf"
        _make_pdf(pdf, [
            "Value-up Plan",           # p1 표지
            "Business overview",       # p2
            "ROE 12.5% target",        # p3 목표
        ])
        r = parse_pdf(pdf)
        assert r.parse_error is None
        assert r.page_count == 3
        assert r.targets["target_roe"] == 12.5
        assert r.evidence["target_roe"] == 3

    def test_first_occurrence_wins(self, tmp_path):
        """앞 페이지의 목표가 뒤 페이지 값에 밀리지 않는다(계획서는 앞이 요약, 뒤가 실적표)."""
        pdf = tmp_path / "20241127800703.pdf"
        _make_pdf(pdf, ["ROE 10.0% target", "ROE 3.0% target"])
        r = parse_pdf(pdf)
        assert r.targets["target_roe"] == 10.0
        assert r.evidence["target_roe"] == 1

    def test_pdf_without_targets_is_not_an_error(self, tmp_path):
        """읽었는데 목표가 없는 것과 못 읽은 것은 다르다 — 전자는 parse_error 없음."""
        pdf = tmp_path / "20241127800704.pdf"
        _make_pdf(pdf, ["This document contains only narrative text about strategy."])
        r = parse_pdf(pdf)
        assert r.parse_error is None
        assert r.targets["target_roe"] is None
        assert r.disclosed_axis_count == 0

    def test_hwp_is_reported_not_silently_nulled(self, tmp_path):
        """HWP는 순정 파서가 없다 — '미공시'가 아니라 '지원하지 않는 형식'으로 남긴다."""
        hwp = tmp_path / "20241127800705.hwp"
        hwp.write_bytes(b"\xd0\xcf\x11\xe0 fake hwp")
        r = parse_pdf(hwp)
        assert r.parse_error == "unsupported_format:hwp"
        assert r.targets == {}

    def test_scanned_pdf_reports_no_text_layer(self, tmp_path):
        """텍스트 레이어가 없는 스캔본 → '우리가 못 읽었다'로 기록."""
        pdf = tmp_path / "20241127800706.pdf"
        _make_pdf(pdf, [""])
        r = parse_pdf(pdf)
        assert r.parse_error == "no_text_layer"

    def test_sha256_changes_when_file_changes(self, tmp_path):
        """재파싱 멱등성의 기준 — 내용이 같으면 같은 해시."""
        a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
        _make_pdf(a, ["ROE 10.0% target"])
        _make_pdf(b, ["ROE 10.0% target"])
        assert sha256_of(a) == sha256_of(b)
        _make_pdf(b, ["ROE 11.0% target"])
        assert sha256_of(a) != sha256_of(b)


class TestScanDirectory:
    def test_skips_hidden_and_temp_files(self, tmp_path):
        (tmp_path / ".DS_Store").write_text("x")
        (tmp_path / "~$draft.pdf").write_text("x")
        _make_pdf(tmp_path / "20241127800702.pdf", ["ROE 10.0% target"])
        refs = scan_directory(tmp_path)
        assert [r.path.name for r in refs] == ["20241127800702.pdf"]

    def test_missing_directory_is_empty_not_error(self, tmp_path):
        assert scan_directory(tmp_path / "nope") == []


@pytest.mark.parametrize("page_text,expected", [
    ("ROE 12.0% target", 12.0),
    ("target ROE 8.5 %", 8.5),
])
def test_roe_variants(tmp_path, page_text, expected):
    pdf = tmp_path / "20241127800707.pdf"
    _make_pdf(pdf, [page_text])
    assert parse_pdf(pdf).targets["target_roe"] == expected
