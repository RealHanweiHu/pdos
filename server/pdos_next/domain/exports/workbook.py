"""Render one permission-filtered view as an xlsx workbook (D56; F41, C16).

The rows come from the same server read the page uses; this module only lays
them out. Every AI-origin row or field carries the explicit "AI 起草" label, and
the workbook carries implicit label metadata in its document properties.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.comments import Comment
from openpyxl.packaging.custom import IntProperty, StringProperty
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

AI_LABEL = "AI 起草"
HUMAN_LABEL = "人工"
PARTIAL_LABEL = "部分 AI 起草"
MARKER_VERSION = "pdos-ai-label/v1"
SOURCE_TITLE = "来源"
AI_FIELDS_TITLE = "AI 起草字段"
COVER_TITLE = "说明"
_AI_FILL = PatternFill("solid", fgColor="FFF4E5")
_HEAD_FILL = PatternFill("solid", fgColor="F1F1F1")
_MAX_CELL = 32767  # Excel's cell text limit.


@dataclass(frozen=True)
class Column:
    key: str
    title: str
    width: int = 18


@dataclass(frozen=True)
class SheetRow:
    values: dict
    ai_row: bool = False
    ai_fields: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Sheet:
    name: str
    columns: tuple[Column, ...]
    rows: tuple[SheetRow, ...]


@dataclass(frozen=True)
class ExportView:
    """One view as the reader may see it; `scope` names what was exported."""

    view: str
    title: str
    scope: dict
    sheets: tuple[Sheet, ...]
    as_of: datetime | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Rendered:
    content: bytes
    row_count: int
    ai_row_count: int
    ai_cell_count: int
    sheet_rows: dict = field(default_factory=dict)

    @property
    def contains_ai(self) -> bool:
        return bool(self.ai_row_count or self.ai_cell_count)


def _text(value) -> object:
    if value is None:
        return None
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        value = "、".join(str(v) for v in value if v is not None)
    elif isinstance(value, dict):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    text = ILLEGAL_CHARACTERS_RE.sub("", str(value))
    return text[:_MAX_CELL]


def _put(ws, row, col, value):
    cell = ws.cell(row=row, column=col)
    cell.value = _text(value)
    # A leading "=" would make openpyxl write a formula; exported text stays text.
    if isinstance(cell.value, str):
        cell.data_type = "s"
    return cell


def _counts(view: ExportView):
    rows = sum(len(s.rows) for s in view.sheets)
    ai_rows = sum(1 for s in view.sheets for r in s.rows if r.ai_row)
    ai_cells = sum(
        len(r.ai_fields & {c.key for c in s.columns})
        for s in view.sheets
        for r in s.rows
        if not r.ai_row
    )
    return rows, ai_rows, ai_cells


def _sheet_name(name: str, used: set[str]) -> str:
    clean = "".join("_" if ch in "[]:*?/\\" else ch for ch in name)[:31] or "数据"
    base, n = clean, 2
    while clean in used or clean == COVER_TITLE:
        suffix = f"_{n}"
        clean, n = base[: 31 - len(suffix)] + suffix, n + 1
    used.add(clean)
    return clean


def render(view: ExportView, *, export_id: str, exporter: str, exported_at: datetime) -> Rendered:
    rows, ai_rows, ai_cells = _counts(view)
    contains_ai = bool(ai_rows or ai_cells)
    wb = Workbook()
    cover = wb.active
    cover.title = COVER_TITLE
    lines = [
        ("导出内容", view.title),
        ("导出范围", view.scope),
        ("导出人", exporter),
        ("导出时间", exported_at),
        ("数据截至", view.as_of or exported_at),
        ("导出编号", export_id),
        ("数据行数", rows),
        ("AI 起草行数", ai_rows),
        ("AI 起草单元格数", ai_cells),
        (
            "标识说明",
            f"“{AI_LABEL}”表示该行由小Pai（AI 身份）写入或起草后经人确认；“{PARTIAL_LABEL}”的行，"
            f"“{AI_FIELDS_TITLE}”列与带批注的单元格是 AI 起草的部分；其余为人工内容。"
            "本文件只含导出人导出时有权查看的内容。",
        ),
    ]
    first = 1
    if contains_ai:
        banner = _put(cover, 1, 1, f"本文件含 AI 生成内容（{AI_LABEL}），使用前请核对。")
        banner.font = Font(bold=True, color="C2410C")
        first = 3
    for offset, (label, value) in enumerate(lines):
        _put(cover, first + offset, 1, label).font = Font(bold=True)
        _put(cover, first + offset, 2, value).alignment = Alignment(wrap_text=True, vertical="top")
    for offset, note in enumerate(view.notes, start=first + len(lines) + 1):
        _put(cover, offset, 1, "备注").font = Font(bold=True)
        _put(cover, offset, 2, note).alignment = Alignment(wrap_text=True, vertical="top")
    cover.column_dimensions["A"].width = 16
    cover.column_dimensions["B"].width = 80

    used: set[str] = set()
    sheet_rows = {}
    for sheet in view.sheets:
        ws = wb.create_sheet(_sheet_name(sheet.name, used))
        titles = [SOURCE_TITLE, *(c.title for c in sheet.columns), AI_FIELDS_TITLE]
        for col, title in enumerate(titles, start=1):
            head = _put(ws, 1, col, title)
            head.font, head.fill = Font(bold=True), _HEAD_FILL
        ws.freeze_panes = "B2"
        by_key = {c.key: c for c in sheet.columns}
        for r, item in enumerate(sheet.rows, start=2):
            marked = item.ai_fields & by_key.keys()
            label = AI_LABEL if item.ai_row else PARTIAL_LABEL if marked else HUMAN_LABEL
            source = _put(ws, r, 1, label)
            for col, column in enumerate(sheet.columns, start=2):
                cell = _put(ws, r, col, item.values.get(column.key))
                if item.ai_row or column.key in marked:
                    cell.fill = _AI_FILL
                if column.key in marked and not item.ai_row:
                    cell.comment = Comment(AI_LABEL, "PDOS")
            if item.ai_row or marked:
                source.fill, source.font = _AI_FILL, Font(bold=True, color="C2410C")
            _put(
                ws,
                r,
                len(titles),
                "、".join(by_key[k].title for k in sorted(marked, key=list(by_key).index))
                if not item.ai_row
                else None,
            )
        ws.column_dimensions["A"].width = 10
        for col, column in enumerate(sheet.columns, start=2):
            ws.column_dimensions[get_column_letter(col)].width = column.width
        ws.column_dimensions[get_column_letter(len(titles))].width = 18
        sheet_rows[ws.title] = len(sheet.rows)

    props = wb.properties
    props.creator = props.lastModifiedBy = "PDOS"
    props.title = view.title
    props.created = props.modified = exported_at.replace(tzinfo=None)
    props.keywords = "AIGC;" + AI_LABEL if contains_ai else ""
    props.description = (
        f"含 AI 生成内容（{AI_LABEL}）：{ai_rows} 行、{ai_cells} 个单元格。" if contains_ai else ""
    )
    # Implicit label metadata; element names follow GB 45438-2025 (file metadata).
    aigc = {
        "Label": "1" if contains_ai else "0",
        "ContentProducer": "PDOS",
        "ProduceID": export_id,
        "ContentPropagator": "PDOS",
        "PropagateID": export_id,
        "ReservedCode1": MARKER_VERSION,
        "ReservedCode2": "",
    }
    wb.custom_doc_props.append(StringProperty(name="AIGC", value=json.dumps(aigc)))
    wb.custom_doc_props.append(StringProperty(name="PDOS.ExportId", value=export_id))
    wb.custom_doc_props.append(StringProperty(name="PDOS.MarkerVersion", value=MARKER_VERSION))
    wb.custom_doc_props.append(IntProperty(name="PDOS.AIDraftRows", value=ai_rows))
    wb.custom_doc_props.append(IntProperty(name="PDOS.AIDraftCells", value=ai_cells))
    buffer = BytesIO()
    wb.save(buffer)
    return Rendered(buffer.getvalue(), rows, ai_rows, ai_cells, sheet_rows)
