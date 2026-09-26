"""Stage integration of retained report bytes across all supported formats."""

from io import BytesIO
from typing import Literal

import pytest
from docx import Document
from openpyxl import load_workbook
from pptx import Presentation
from pypdf import PdfReader

from app.exports.definition_documents import Format, render_sections


@pytest.mark.parametrize("format", ["docx", "xlsx", "pptx", "pdf"])
@pytest.mark.parametrize("audience", ["internal", "customer"])
def test_generated_report_retains_long_sources_and_receipt(
    format: Format, audience: Literal["internal", "customer"]
) -> None:
    # Synthetic text exceeds each renderer's cell/paragraph/slide chunk size.
    original = "来源边界BEGIN " + "逐项原文甲乙丙1234567890" * 420 + " 来源边界END"
    formula = '=HYPERLINK("https://example.invalid/never-fetch", "原值")'
    receipt = {"编号": "synthetic-stage-export", "资料": "仅供隔离集成验证"}
    status = "历史版本 · 非真实业务结论"
    content = render_sections(
        "合成规格与质量报告",
        status,
        [("完整来源", original), ("原值记录", formula), ("缺项", "未记录；不补零")],
        format,
        receipt,
        audience=audience,
    )
    source = BytesIO(content)
    source_text: str | None = None
    if format == "docx":
        document = Document(source)
        extracted = "\n".join(p.text for p in document.paragraphs)
        footer = document.sections[0].footer.paragraphs[0].text
        assert receipt["编号"] in footer
    elif format == "xlsx":
        workbook = load_workbook(source, data_only=False)
        sheet = workbook.active
        assert sheet is not None
        extracted = "\n".join(str(cell.value) for row in sheet for cell in row)
        formula_cells = [cell for row in sheet for cell in row if cell.value == formula]
        assert len(formula_cells) == 1
        assert formula_cells[0].data_type == "s"
        assert formula_cells[0].hyperlink is None
        source_cells = [
            str(row[1].value) for row in sheet if str(row[0].value).startswith("完整来源")
        ]
        assert "".join(source_cells) == original
        source_text = "".join(source_cells)
    elif format == "pptx":
        presentation = Presentation(source)
        assert len(presentation.slides) > 4
        extracted = "\n".join(
            shape.text
            for slide in presentation.slides
            for shape in slide.shapes
            if shape.has_text_frame
        )
        source_text = "".join(
            slide.shapes[1].text
            for slide in presentation.slides
            if slide.shapes[0].text.startswith("完整来源")
        )
    else:
        document_pdf = PdfReader(source)
        assert len(document_pdf.pages) > 1
        pages = []
        for number, page in enumerate(document_pdf.pages, 1):
            text = page.extract_text()
            label = "客户" if audience == "customer" else "内部"
            footer = f"{status} · {label} · {receipt['编号']} · {number}"
            assert footer in text
            pages.append(text.replace(footer, "", 1))
        extracted = "\n".join(pages)

    compact = "".join(extracted.split())
    assert "来源边界BEGIN" in compact and "来源边界END" in compact
    retained = "".join((source_text if source_text is not None else extracted).split())
    first = retained.index("来源边界BEGIN")
    last = retained.index("来源边界END") + len("来源边界END")
    assert retained[first:last] == "".join(original.split())
    assert "".join(formula.split()) in compact
    assert receipt["编号"] in extracted
    assert "未记录；不补零" in extracted
