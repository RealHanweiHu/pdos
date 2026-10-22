"""Parser-declared location inventories across the isolated protocol; synthetic bytes."""

import io
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from pdos_next.agent_kernel.extract_read_ledger import ParseManifest
from pdos_next.agent_kernel.extract_sources import _manifest
from pdos_next.errors import DomainError
from pdos_next.evidence_processing import parse_original
from pdos_next.originals import _parse_manifest
from tests.evidence_processing.test_documents import pdf_bytes, workbook_bytes

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def mixed_pdf(text_pages=(True, False)):
    writer = PdfWriter()
    for has_text in text_pages:
        page = writer.add_blank_page(width=300, height=300)
        if has_text:
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
                    )
                }
            )
            stream = DecodedStreamObject()
            stream.set_data(b"BT /F1 12 Tf 20 200 Td (Synthetic page text) Tj ET")
            page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_text_inventory_covers_every_line_across_the_isolated_protocol():
    result = parse_original(b"first line\nsecond line\nthird line\n", media_type="text/plain")
    assert result.status == "parsed"
    assert [location.line for location in result.expected_locations] == [1, 2, 3]
    assert [segment.location.line for segment in result.segments] == [1, 2, 3]
    manifest = _parse_manifest(result)
    assert manifest["basis"] == "line" and manifest["parser_version"] == result.parser_version
    assert [item["line"] for item in manifest["expected_locations"]] == [1, 2, 3]


def test_xlsx_inventory_covers_every_emitted_cell():
    result = parse_original(workbook_bytes(), media_type=XLSX)
    assert result.status == "parsed"
    assert {location.cell for location in result.expected_locations} == {"A1", "B2", "C3", "D4"}
    assert all(location.sheet == "合成测量" for location in result.expected_locations)
    assert _parse_manifest(result)["basis"] == "cell"


def test_pdf_inventory_includes_pages_without_extracted_text():
    result = parse_original(mixed_pdf(), media_type="application/pdf")
    assert result.status == "parsed"
    assert [location.page for location in result.expected_locations] == [1, 2]
    assert [segment.location.page for segment in result.segments] == [1]
    assert any("Page 2" in warning for warning in result.warnings)


def test_blank_pdf_keeps_page_extent_with_needs_ocr():
    result = parse_original(pdf_bytes(empty=True, page_count=2), media_type="application/pdf")
    assert result.status == "needs_ocr"
    assert result.segments == ()
    assert [location.page for location in result.expected_locations] == [1, 2]


def test_mixed_or_empty_inventory_is_not_a_manifest():
    mixed = SimpleNamespace(
        parser_version="v",
        expected_locations=(
            SimpleNamespace(kind="line"),
            SimpleNamespace(kind="page"),
        ),
    )
    with pytest.raises(DomainError) as error:
        _parse_manifest(mixed)
    assert error.value.code == "VALIDATION_FAILED" and error.value.reason == "INTEGRITY_MISMATCH"
    assert _parse_manifest(SimpleNamespace(parser_version="v", expected_locations=())) is None


def test_seal_manifest_requires_the_checked_shape():
    assert _manifest(SimpleNamespace(parse_manifest=None)) is None
    good = {
        "parser_version": "pdos-evidence-v1",
        "basis": "line",
        "expected_locations": [
            {"kind": "line", "line": 1, "page": None, "sheet": None, "row": None, "column": None,
             "cell": None}
        ],
    }
    manifest = _manifest(SimpleNamespace(parse_manifest=good))
    assert isinstance(manifest, ParseManifest) and manifest.basis == "line"
    with pytest.raises(DomainError) as error:
        _manifest(
            SimpleNamespace(
                parse_manifest={
                    "parser_version": "pdos-evidence-v1",
                    "basis": "row",
                    "expected_locations": [],
                }
            )
        )
    assert error.value.code == "VALIDATION_FAILED" and error.value.reason == "INTEGRITY_MISMATCH"
    with pytest.raises(DomainError):
        _manifest(SimpleNamespace(parse_manifest={"parser_version": "v"}))
