import hashlib
import io
import subprocess
import sys
import time
import zipfile
from dataclasses import replace

import pytest

from pdos_next.evidence_processing import ParseFailure, ParseLimits, parse_original
from pdos_next.evidence_processing.isolation import _communicate
from pdos_next.evidence_processing.parsers import XLSX


def assert_failure(content, media, code, **kwargs):
    with pytest.raises(ParseFailure) as error:
        parse_original(content, media_type=media, **kwargs)
    assert error.value.code == code
    assert content.decode("utf-8", errors="ignore") not in error.value.message or len(content) < 5


def test_utf8_retains_original_newlines_and_exact_source_lines():
    content = "\n合成记录（非真实工厂数据）\r\n\n试模数量：12 件\n".encode()
    result = parse_original(content, media_type="text/plain")
    assert result.text.encode() == content
    assert result.source_sha256 == hashlib.sha256(content).hexdigest()
    assert [segment.location.line for segment in result.segments] == [1, 2, 3, 4]
    assert result.segments[2].text == ""
    assert result.segments[3].text == "试模数量：12 件"
    assert result.scan_status == "not_scanned"
    assert result.as_dict()["segments"][3]["location"]["line"] == 4


@pytest.mark.parametrize(
    ("content", "media", "code"),
    [
        (b"\xff\xfeunsafe", "text/plain", "INVALID_ENCODING"),
        (b"safe\x00text", "text/plain", "MEDIA_TYPE_MISMATCH"),
        (b"%PDF-1.7\n", "text/plain", "MEDIA_TYPE_MISMATCH"),
        (b"PK\x03\x04source", "text/markdown", "MEDIA_TYPE_MISMATCH"),
        (b"original", "application/x-python", "UNSUPPORTED_MEDIA_TYPE"),
        (b"not a PDF", "application/pdf", "MEDIA_TYPE_MISMATCH"),
        (b"not a workbook", XLSX, "MEDIA_TYPE_MISMATCH"),
        (b" \n\t ", "text/plain", "EMPTY_CONTENT"),
    ],
)
def test_failure_classifications(content, media, code):
    assert_failure(content, media, code)


def test_input_output_and_line_budgets():
    assert_failure(b"abcdef", "text/plain", "FILE_TOO_LARGE", limits=ParseLimits(max_input_bytes=5))
    assert_failure(b"abcdef", "text/plain", "OUTPUT_LIMIT", limits=ParseLimits(max_text_chars=5))
    assert_failure(b"a\nb\nc", "text/plain", "OUTPUT_LIMIT", limits=ParseLimits(max_segments=2))


def test_timeout_is_isolated_and_never_falls_back_to_parent_parser():
    assert_failure(
        b"Synthetic source",
        "text/plain",
        "PARSER_TIMEOUT",
        limits=ParseLimits(timeout_seconds=0.001),
    )


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin uses the independent RSS watchdog")
def test_rss_watchdog_kills_and_reaps_real_oversized_child():
    process = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys,time; sys.stdin.buffer.read(); "
            "allocation=bytearray(80_000_000); time.sleep(10)",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={"LANG": "C.UTF-8"},
        start_new_session=True,
    )
    started = time.monotonic()
    with pytest.raises(ParseFailure) as failure:
        _communicate(process, b"synthetic", ParseLimits(memory_bytes=40_000_000, timeout_seconds=3))
    assert failure.value.code == "RESOURCE_LIMIT"
    assert process.poll() is not None and process.returncode < 0
    assert time.monotonic() - started < 3


def workbook_bytes():
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "合成测量"
    sheet["A1"] = "样件"
    sheet["B2"] = 12
    sheet["C3"] = "=SUM(B2,4)"
    sheet["D4"] = True
    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def alter_archive(content, updates):
    stream = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(content)) as source,
        zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as destination,
    ):
        for entry in source.infolist():
            destination.writestr(entry.filename, updates.pop(entry.filename, source.read(entry)))
        for name, value in updates.items():
            destination.writestr(name, value)
    return stream.getvalue()


def test_xlsx_preserves_cells_formula_and_source_identity():
    content = workbook_bytes()
    result = parse_original(content, media_type=XLSX)
    cells = {segment.location.cell: segment for segment in result.segments}
    assert set(cells) == {"A1", "B2", "C3", "D4"}
    assert cells["B2"].text == "12"
    assert cells["B2"].location.sheet == "合成测量"
    assert cells["B2"].location.row == 2 and cells["B2"].location.column == 2
    assert cells["C3"].text == "=SUM(B2,4)" and cells["C3"].value_kind == "formula"
    assert cells["D4"].text == "true" and cells["D4"].value_kind == "boolean"
    assert result.source_sha256 == hashlib.sha256(content).hexdigest()
    assert "without evaluation" in " ".join(result.warnings)
    assert result.scan_status == "not_scanned"


@pytest.mark.parametrize(
    ("name", "value", "code"),
    [
        ("xl/vbaProject.bin", b"macro original", "ACTIVE_CONTENT"),
        ("xl/externalLinks/externalLink1.xml", b"<link/>", "EXTERNAL_CONTENT"),
        ("../outside.xml", b"<outside/>", "INVALID_ARCHIVE"),
        (
            "xl/unsafe.xml",
            b'<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><r>&x;</r>',
            "ACTIVE_CONTENT",
        ),
        ("xl/bomb.xml", b"0" * 50_000, "ARCHIVE_LIMIT"),
    ],
)
def test_workbook_active_content_and_expansion_are_rejected(name, value, code):
    content = alter_archive(workbook_bytes(), {name: value})
    assert_failure(content, XLSX, code)


def test_workbook_cells_cannot_hide_behind_false_dimension():
    content = workbook_bytes()
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        source = archive.read("xl/worksheets/sheet1.xml")
    source = source.replace(b'ref="A1:D4"', b'ref="A1:A1"')
    content = alter_archive(content, {"xl/worksheets/sheet1.xml": source})
    result = parse_original(content, media_type=XLSX)
    assert len(result.segments) == 4
    assert_failure(content, XLSX, "DOCUMENT_LIMIT", limits=ParseLimits(max_rows_per_sheet=3))


def pdf_bytes(*, empty=False, javascript=False, encrypted=False, page_count=1):
    from pypdf import PdfWriter
    from pypdf.actions import JavaScript
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    for _ in range(page_count):
        page = writer.add_blank_page(width=300, height=300)
        if not empty:
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
            page[NameObject("/Resources")] = DictionaryObject(
                {
                    NameObject("/Font"): DictionaryObject(
                        {NameObject("/F1"): writer._add_object(font)}
                    ),
                }
            )
            stream = DecodedStreamObject()
            stream.set_data(b"BT /F1 12 Tf 20 200 Td (Synthetic pressure 150 PSI) Tj ET")
            page[NameObject("/Contents")] = writer._add_object(stream)
    if javascript:
        writer.add_open_action(JavaScript("app.alert('unsafe source')"))
    if encrypted:
        writer.encrypt("synthetic-password")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_extracts_exact_page_and_leaves_original_bytes_separate():
    content = pdf_bytes(page_count=2)
    result = parse_original(content, media_type="application/pdf")
    assert [segment.location.page for segment in result.segments] == [1, 2]
    assert "Synthetic pressure 150 PSI" in result.segments[0].text
    assert result.source_sha256 == hashlib.sha256(content).hexdigest()
    assert result.scan_status == "not_scanned"


def test_pdf_empty_page_is_needs_ocr_without_fabrication():
    result = parse_original(pdf_bytes(empty=True), media_type="application/pdf")
    assert result.status == "needs_ocr" and result.text == "" and result.segments == ()
    assert "OCR was not performed" in result.warnings[0]


def test_pdf_active_encrypted_and_page_budgets():
    assert_failure(pdf_bytes(javascript=True), "application/pdf", "ACTIVE_CONTENT")
    assert_failure(pdf_bytes(encrypted=True), "application/pdf", "ENCRYPTED_DOCUMENT")
    assert_failure(
        pdf_bytes(page_count=2),
        "application/pdf",
        "DOCUMENT_LIMIT",
        limits=ParseLimits(max_pdf_pages=1),
    )
    assert_failure(b"%PDF-1.7\n malformed", "application/pdf", "MALFORMED_DOCUMENT")


def test_parse_limits_reject_unbounded_server_configuration():
    with pytest.raises(ValueError):
        replace(ParseLimits(), timeout_seconds=120)
    with pytest.raises(ValueError):
        replace(ParseLimits(), max_zip_expanded_bytes=1_000_000_000)
