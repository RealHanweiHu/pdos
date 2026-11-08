"""xlsx layout, AI labels and label metadata (D56); no database."""

import json
from datetime import UTC, datetime
from io import BytesIO

from openpyxl import load_workbook

from pdos_next.domain.exports.workbook import (
    AI_LABEL,
    HUMAN_LABEL,
    PARTIAL_LABEL,
    Column,
    ExportView,
    Sheet,
    SheetRow,
    render,
)

AT = datetime(2026, 11, 8, 9, 30, tzinfo=UTC)


def view(rows):
    return ExportView(
        view="project",
        title="项目：合成项目",
        scope={"project_id": "p"},
        sheets=(Sheet("任务", (Column("title", "任务"), Column("goal", "目标")), tuple(rows)),),
    )


def opened(rendered):
    return load_workbook(BytesIO(rendered.content))


def test_rows_cells_and_counts_carry_explicit_ai_labels():
    rendered = render(
        view(
            [
                SheetRow({"title": "人工任务", "goal": "人工目标"}),
                SheetRow({"title": "AI 任务", "goal": "AI 目标"}, ai_row=True),
                SheetRow(
                    {"title": "人工名称", "goal": "AI 起草的目标"}, ai_fields=frozenset({"goal"})
                ),
            ]
        ),
        export_id="e1",
        exporter="合成读者",
        exported_at=AT,
    )
    assert (rendered.row_count, rendered.ai_row_count, rendered.ai_cell_count) == (3, 1, 1)
    assert rendered.contains_ai and rendered.sheet_rows == {"任务": 3}
    book = opened(rendered)
    assert book.sheetnames == ["说明", "任务"]
    sheet = book["任务"]
    assert [c.value for c in sheet[1]] == ["来源", "任务", "目标", "AI 起草字段"]
    assert [sheet.cell(r, 1).value for r in (2, 3, 4)] == [HUMAN_LABEL, AI_LABEL, PARTIAL_LABEL]
    assert sheet.cell(4, 4).value == "目标" and sheet.cell(4, 3).comment.text == AI_LABEL
    assert sheet.cell(4, 2).comment is None and sheet.cell(2, 4).value is None
    cover = {row[0].value: row[1].value for row in book["说明"].iter_rows() if row[0].value}
    assert book["说明"].cell(1, 1).value.startswith("本文件含 AI 生成内容")
    assert cover["数据行数"] == 3 and cover["AI 起草行数"] == 1 and cover["AI 起草单元格数"] == 1
    assert cover["导出人"] == "合成读者" and cover["导出编号"] == "e1"


def test_implicit_metadata_follows_content():
    for rows, label in (
        ([SheetRow({"title": "x"}, ai_row=True)], "1"),
        ([SheetRow({"title": "x"})], "0"),
    ):
        book = opened(render(view(rows), export_id="e2", exporter="r", exported_at=AT))
        props = {p.name: p.value for p in book.custom_doc_props.props}
        aigc = json.loads(props["AIGC"])
        assert aigc["Label"] == label and aigc["ProduceID"] == "e2"
        assert aigc["ContentProducer"] == "PDOS" and props["PDOS.ExportId"] == "e2"
        assert props["PDOS.AIDraftRows"] == (1 if label == "1" else 0)
        assert ("AIGC" in (book.properties.keywords or "")) is (label == "1")


def test_formula_like_and_control_text_stays_inert_text():
    rendered = render(
        view([SheetRow({"title": '=HYPERLINK("http://x","y")', "goal": "a\x07b"})]),
        export_id="e3",
        exporter="r",
        exported_at=AT,
    )
    sheet = opened(rendered)["任务"]
    assert sheet.cell(2, 2).value == '=HYPERLINK("http://x","y")'
    assert sheet.cell(2, 2).data_type == "s"
    assert sheet.cell(2, 3).value == "ab"


def test_empty_view_is_a_valid_human_only_workbook():
    rendered = render(view([]), export_id="e4", exporter="r", exported_at=AT)
    assert (rendered.row_count, rendered.contains_ai) == (0, False)
    book = opened(rendered)
    assert book["任务"].max_row == 1 and book["说明"].cell(1, 1).value == "导出内容"
