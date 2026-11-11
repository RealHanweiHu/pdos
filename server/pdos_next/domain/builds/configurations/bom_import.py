"""BOM import from a parsed XLSX/CSV original (P79 D98, B13/F37).

The original is uploaded and parsed by the existing isolated parser; this module
only reads the derived text and its cell/line locator, never the raw bytes. The
conversion is deterministic code: header matching, value parsing, part matching
and line keys follow fixed rules, so the server can repeat it at confirmation and
refuse lines that differ. A model may later suggest a column mapping; it never
converts rows (D430).

Rows the code cannot take as they are wait for a named per-row disposition
(skip, new part, or link an existing part). Part identity stays per product: an
equal internal number reuses the visible part as the existing BOM command
requires; an equal ERP number is only a hint (P79).
"""

import csv
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError
from sqlalchemy import select

from pdos_next.errors import DomainError

from .bom_diff import compare, header
from .bom_rules import rule_card
from .models import PartIdentity
from .schemas import DESIGNATOR_PATTERN, BomImportBasis, BomLineInput

CONVERTER = "bom-import.v1"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_LINES = 2000
HEADER_SCAN_ROWS = 30
FIELDS = (
    "key",
    "internal_number",
    "name",
    "erp_number",
    "customer_number",
    "quantity",
    "unit",
    "loss_rate",
    "critical",
    "notes",
    "reference_designators",
    "alternates",
)
FIELD_TITLES = {
    "key": "行标识",
    "internal_number": "内部研发编号",
    "name": "物料名称",
    "erp_number": "ERP 料号",
    "customer_number": "客户料号",
    "quantity": "每份用量",
    "unit": "单位",
    "loss_rate": "损耗率",
    "critical": "关键件",
    "notes": "备注",
    "reference_designators": "位号",
    "alternates": "替代料",
}
# Exact matches after normalisation only; no fuzzy or model guessing.
SYNONYMS = {
    "key": ("行标识", "行号", "项次", "序号", "item", "itemno", "findnumber", "findno", "line"),
    "internal_number": (
        "内部研发编号",
        "研发编号",
        "内部编号",
        "物料编码",
        "物料编号",
        "料号",
        "零件号",
        "partnumber",
        "partno",
        "p/n",
        "pn",
        "internalnumber",
    ),
    "name": ("物料名称", "名称", "品名", "描述", "物料描述", "name", "partname", "description"),
    "erp_number": ("erp料号", "erp编号", "erp编码", "erp", "erpnumber", "erpp/n"),
    "customer_number": ("客户料号", "客户编号", "customernumber", "customerp/n", "cpn"),
    "quantity": ("每份用量", "用量", "数量", "单机用量", "qty", "quantity", "qtyper"),
    "unit": ("单位", "uom", "unit"),
    "loss_rate": ("损耗率", "损耗", "loss", "scrap", "scraprate", "attrition"),
    "critical": ("关键件", "关键", "critical", "ctq"),
    "notes": ("备注", "说明", "notes", "note", "remark", "remarks", "comment"),
    "reference_designators": (
        "位号",
        "位置号",
        "refdes",
        "referencedesignator",
        "referencedesignators",
        "designator",
        "designators",
    ),
    "alternates": (
        "替代料",
        "替代料号",
        "替代物料",
        "替代编号",
        "alternate",
        "alternates",
        "altp/n",
        "altpn",
        "substitute",
    ),
}
_NORMALISE = re.compile(r"[\s_\-.:：()（）\[\]【】]+")
_KEY_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")
_DESIGNATOR_SPLIT = re.compile(r"[,;，；、\s]+")
_DESIGNATOR_RANGE = re.compile(r"^([A-Za-z]+)(\d+)-(?:\1)?(\d+)$")
_KEY = re.compile(r"^[a-zA-Z0-9_-]+$")
TRUE = {"是", "y", "yes", "true", "1", "关键", "√", "✓", "x"}
FALSE = {"否", "n", "no", "false", "0", "-", "/"}


def _norm(text: str) -> str:
    return _NORMALISE.sub("", text.strip().casefold())


LOOKUP = {_norm(word): name for name, words in SYNONYMS.items() for word in words}


@dataclass(frozen=True)
class Cell:
    text: str
    line: int
    kind: str = "text"


@dataclass
class Table:
    format: str
    sheets: tuple
    cells: dict  # sheet (None for CSV) -> row -> column -> Cell
    artifact_id: object = None
    artifact_revision: int = 0
    issues: list = field(default_factory=list)


def _xlsx_table(lines, locator_map):
    cells, sheets = {}, []
    for entry in locator_map or ():
        location = entry.get("location") or {}
        if location.get("kind") != "cell":
            continue
        sheet = location.get("sheet")
        start, end = entry["derived_line_start"], entry["derived_line_end"]
        text = "\n".join(lines[start - 1 : end])
        if sheet not in cells:
            cells[sheet] = {}
            sheets.append(sheet)
        cells[sheet].setdefault(location["row"], {})[location["column"]] = Cell(
            text, start, entry.get("value_kind") or "text"
        )
    return Table("xlsx", tuple(sheets), cells)


def _delimiter(lines):
    first = next((line for line in lines if line.strip()), "")
    counts = {mark: first.count(mark) for mark in (",", "\t", ";")}
    return max(counts, key=lambda mark: (counts[mark], mark == ","))


def _csv_table(lines):
    rows, issues = {}, []
    delimiter = _delimiter(lines)
    for number, line in enumerate(lines, start=1):
        if number == 1:
            line = line.removeprefix("\ufeff")
        if not line.strip():
            continue
        if line.count('"') % 2:
            issues.append(
                {
                    "code": "csv_multiline_cell",
                    "row": number,
                    "message": f"第 {number} 行引号未闭合（单元格内换行），"
                    "无法按行定位，请在原件中去掉换行。",
                }
            )
            continue
        values = next(csv.reader([line], delimiter=delimiter))
        rows[number] = {
            column: Cell(value.strip(), number)
            for column, value in enumerate(values, start=1)
            if value.strip()
        }
    table = Table("csv", (None,), {None: rows})
    table.issues = issues
    return table


def read_table(s, ctx, product_id, artifact_id, expected_revision) -> Table:
    """The parsed table of one original, through its current ACL and security state."""
    from pdos_next.core.service import source_for
    from pdos_next.originals.access import require_original
    from pdos_next.originals.security import require_safe

    artifact = source_for(s, ctx, product_id, artifact_id, expected_revision)
    if artifact.revision != expected_revision:
        raise DomainError("SOURCE_STALE", "导入原件的派生资料已有新版本，请重新选择。")
    if artifact.original_id is None:
        raise DomainError(
            "ORIGINAL_REQUIRED", "BOM 导入须来自已上传的原件，手写资料不能替代。", 422
        )
    original = require_original(s, ctx, product_id, artifact.original_id)
    require_safe(s, ctx, original, lock=not s.info.get("read_snapshot", False))
    if original.status != "parsed":
        raise DomainError("SOURCE_UNAVAILABLE", "原件尚未形成可定位的解析结果。")
    lines = artifact.content.splitlines()
    if original.media_type == XLSX:
        table = _xlsx_table(lines, original.locator_map)
    elif original.media_type == "text/plain" and original.filename.lower().endswith(".csv"):
        table = _csv_table(lines)
    else:
        raise DomainError("UNSUPPORTED_MEDIA_TYPE", "BOM 导入只接受 XLSX 或 CSV 原件。", 422)
    if not any(table.cells.values()):
        raise DomainError("EMPTY_CONTENT", "原件没有可导入的单元格。", 422)
    table.artifact_id, table.artifact_revision = artifact.id, artifact.revision
    return table


def _recognised(row_cells):
    return {
        column: LOOKUP[_norm(cell.text)]
        for column, cell in row_cells.items()
        if _norm(cell.text) in LOOKUP
    }


def suggest_header(rows) -> int | None:
    best, best_count = None, 1
    for number in sorted(rows)[:HEADER_SCAN_ROWS]:
        count = len(set(_recognised(rows[number]).values()))
        if count > best_count:
            best, best_count = number, count
    return best


def suggest_columns(header_cells) -> list[dict]:
    chosen, used = [], set()
    for column in sorted(header_cells):
        name = LOOKUP.get(_norm(header_cells[column].text))
        if name and name not in used:
            used.add(name)
            chosen.append({"field": name, "column": column})
    return chosen


def visible_parts(s, ctx, product_id):
    """Parts of this product the requester may reuse; others only block their number."""
    rows = s.scalars(
        select(PartIdentity).where(
            PartIdentity.tenant_id == ctx.tenant_id, PartIdentity.product_id == product_id
        )
    ).all()
    return [
        {
            "id": str(row.id),
            "revision": row.revision,
            "name": row.name,
            "internal_number": row.internal_number,
            "erp_number": row.erp_number,
            "customer_number": row.customer_number,
            "visibility": row.visibility,
            "visible": row.visibility != "private" or row.owner_id == ctx.requester_id,
        }
        for row in sorted(rows, key=lambda row: str(row.id))
    ]


def _issue(code, message, column=None):
    value = {"code": code, "message": message}
    if column is not None:
        value["column"] = column
    return value


def _decimal(text):
    from .service import _decimal as display

    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    exponent = value.as_tuple().exponent
    if not value.is_finite() or not isinstance(exponent, int) or abs(exponent) > 32:
        return None
    return Decimal(display(value))


def _designators(text):
    values, problems = [], []
    for token in (t for t in _DESIGNATOR_SPLIT.split(text) if t):
        match = _DESIGNATOR_RANGE.match(token)
        if match:
            prefix, first, last = match.group(1), int(match.group(2)), int(match.group(3))
            if first > last or last - first >= 1000:
                problems.append(token)
                continue
            values.extend(f"{prefix}{number}" for number in range(first, last + 1))
        else:
            values.append(token)
    pattern = re.compile(DESIGNATOR_PATTERN)
    problems.extend(value for value in values if len(value) > 40 or not pattern.match(value))
    return values, problems


def _parse(cells, columns):
    """Field values and blocking issues of one original row."""
    raw = {name: cells.get(column) for name, column in columns.items()}
    text = {name: cell.text.strip() for name, cell in raw.items() if cell and cell.text.strip()}
    values, issues = {}, []
    for name in ("internal_number", "erp_number", "customer_number"):
        if name in text:
            if len(text[name]) > 100 or "\n" in text[name]:
                issues.append(
                    _issue(
                        "identity_invalid",
                        f"{FIELD_TITLES[name]}超过 100 字或含换行。",
                        columns[name],
                    )
                )
            values[name] = text[name]
    if "name" in text:
        if len(text["name"]) > 200:
            issues.append(_issue("name_invalid", "物料名称超过 200 字。", columns["name"]))
        values["name"] = " ".join(text["name"].split())
    if "key" in text:
        if not _KEY.match(text["key"]) or len(text["key"]) > 80:
            issues.append(
                _issue(
                    "key_invalid",
                    "行标识只能用字母、数字、下划线和短横线，最长 80。",
                    columns["key"],
                )
            )
        values["key"] = text["key"]
    for name in ("quantity", "loss_rate"):
        if name not in text:
            continue
        cell = raw[name]
        if cell.kind == "formula":
            issues.append(
                _issue(
                    "formula",
                    f"{FIELD_TITLES[name]}是未求值的公式，请在原件中存为数值。",
                    columns[name],
                )
            )
            values[f"{name}_text"] = text[name]
            continue
        source = text[name]
        percent = name == "loss_rate" and source.endswith("%")
        number = _decimal(source.removesuffix("%").strip() if percent else source)
        if number is None:
            issues.append(
                _issue(f"{name}_invalid", f"{FIELD_TITLES[name]}无法识别为数字。", columns[name])
            )
            values[f"{name}_text"] = source
            continue
        if percent:
            number = _decimal(str(number / 100))
        if name == "quantity" and number <= 0:
            issues.append(_issue("quantity_non_positive", "数量须为正数。", columns[name]))
        if name == "loss_rate" and not 0 <= number <= 1:
            issues.append(
                _issue("loss_rate_range", "损耗率须在 0–1 之间，或写成百分数。", columns[name])
            )
        values[name] = number
        values[f"{name}_text"] = source
    if "unit" in text:
        if len(text["unit"]) > 80:
            issues.append(_issue("unit_invalid", "单位超过 80 字。", columns["unit"]))
        values["unit"] = text["unit"]
    if "quantity" in values and "unit" not in values:
        issues.append(_issue("unit_missing", "有用量必须有单位。", columns.get("quantity")))
    if "critical" in text:
        flag = text["critical"].casefold()
        if flag in TRUE:
            values["critical"] = True
        elif flag in FALSE:
            values["critical"] = False
        else:
            issues.append(
                _issue(
                    "critical_invalid", "关键件只接受 是/否、Y/N、true/false。", columns["critical"]
                )
            )
    if "notes" in text:
        values["notes"] = text["notes"][:2000]
    if "reference_designators" in text:
        designators, problems = _designators(text["reference_designators"])
        if problems:
            issues.append(
                _issue(
                    "designator_invalid",
                    "位号无法识别：" + "、".join(problems[:5]),
                    columns["reference_designators"],
                )
            )
        values["reference_designators"] = designators
    if "alternates" in text:
        tokens = [token for token in _DESIGNATOR_SPLIT.split(text["alternates"]) if token]
        if any(len(token) > 100 for token in tokens) or len(tokens) > 20:
            issues.append(
                _issue(
                    "alternate_invalid",
                    "替代料编号超过 100 字或多于 20 个。",
                    columns["alternates"],
                )
            )
        values["alternates"] = list(dict.fromkeys(tokens))
    if not any(values.get(n) for n in ("internal_number", "name", "erp_number", "customer_number")):
        issues.append(_issue("identity_missing", "这一行没有物料编号或名称。"))
    return values, issues


def _part_label(part):
    return " / ".join(v for v in (part.get("internal_number"), part.get("name")) if v)


def _safe_key(text):
    return _KEY_UNSAFE.sub("-", text).strip("-")[:80]


def convert(table, basis, *, previous_lines=(), parts=(), visibility="private") -> dict:
    """Deterministic conversion of one parsed table under one basis."""
    issues = list(table.issues)
    rows = table.cells.get(basis["sheet"]) if table.format == "xlsx" else table.cells.get(None)
    if rows is None:
        raise DomainError("VALIDATION_FAILED", "所选工作表不在原件中。", 422)
    header_cells = rows.get(basis["header_row"], {})
    columns = {entry["field"]: entry["column"] for entry in basis["columns"]}
    dispositions = {entry["row"]: entry for entry in basis.get("dispositions") or ()}
    mapped = set(columns.values())
    unmapped = sorted(
        {
            column
            for number, cells in rows.items()
            if number >= basis["header_row"]
            for column in cells
        }
        - mapped
    )
    by_number = {}
    for part in parts:
        if part["internal_number"]:
            by_number.setdefault(part["internal_number"], []).append(part)
    by_erp = {}
    for part in parts:
        if part["erp_number"] and part["visible"]:
            by_erp.setdefault(part["erp_number"], []).append(part)
    by_id = {part["id"]: part for part in parts if part["visible"]}

    def eligible(part):
        return part["visible"] and not (
            visibility == "category" and part["visibility"] != "category"
        )

    reports, candidates, seen_new_numbers, ignored = [], [], {}, 0
    data_rows = [number for number in sorted(rows) if number > basis["header_row"]]
    for number in data_rows:
        cells = {column: cell for column, cell in rows[number].items() if column in mapped}
        if not cells:
            ignored += 1
            continue
        values, row_issues = _parse(cells, columns)
        report = {
            "row": number,
            "status": "ready",
            "issues": row_issues,
            "hints": [],
            "allowed": ["skip"],
            "values": {k: (str(v) if isinstance(v, Decimal) else v) for k, v in values.items()},
        }
        number_value = values.get("internal_number")
        resolution, part = "new_part", None
        if number_value and number_value in by_number:
            matches = by_number[number_value]
            usable = [p for p in matches if eligible(p)]
            if not all(p["visible"] for p in matches):
                row_issues.append(
                    _issue("identity_forbidden", "该内部编号无法办理，请核对授权与声明范围。")
                )
            elif not usable:
                row_issues.append(
                    _issue(
                        "identity_private",
                        "同编号物料是私有物料，不能用于共享 BOM；请先改为私有导入。",
                    )
                )
            else:
                resolution, part = "matched_internal", usable[0]
        elif number_value and number_value in seen_new_numbers:
            row_issues.append(
                _issue(
                    "identity_repeated",
                    f"同一内部编号已在第 {seen_new_numbers[number_value]} 行作为新物料；"
                    "请在原件中合并为一行（位号写在一起）或跳过本行。",
                )
            )
        if resolution == "new_part" and values.get("erp_number") in by_erp:
            report["hints"] = [
                {"part_id": p["id"], "revision": p["revision"], "label": _part_label(p)}
                for p in by_erp[values["erp_number"]]
                if eligible(p)
            ]
        disposition = dispositions.pop(number, None)
        report["disposition"] = disposition
        if not row_issues:
            report["allowed"] = (
                ["skip", "new_part", "reuse"]
                if report["hints"]
                else ["skip", "accept", "new_part", "reuse"]
                if resolution == "new_part"
                else ["skip", "accept"]
            )
        if disposition is not None:
            action = disposition["action"]
            if action == "skip":
                report["status"] = "skipped"
                reports.append(report)
                continue
            if action not in report["allowed"]:
                row_issues.append(_issue("disposition_invalid", "这一行只能跳过或在原件中改正。"))
            elif action == "reuse":
                chosen = by_id.get(str(disposition["part_id"]))
                if chosen is None or chosen["revision"] != disposition["expected_part_revision"]:
                    row_issues.append(_issue("disposition_part", "关联的物料不可见或版本已变化。"))
                elif not eligible(chosen):
                    row_issues.append(_issue("disposition_part", "私有物料不能用于共享 BOM。"))
                else:
                    resolution, part = "reuse", chosen
        elif report["hints"] and not row_issues:
            report["status"] = "needs_disposition"
            report["reason"] = "ERP 料号与已有物料一致，请选择关联已有物料、建新物料或跳过。"
        # Declared alternates name existing parts by internal number; a declaration
        # is never a qualification (P113), so nothing here approves anything.
        own, resolved, unresolved = (part or {}).get("id"), [], []
        for token in values.get("alternates") or ():
            usable = [p for p in by_number.get(token, ()) if eligible(p)]
            if token == number_value or (usable and usable[0]["id"] == own):
                unresolved.append({"value": token, "reason": "与本行物料相同"})
            elif not usable:
                unresolved.append({"value": token, "reason": "不是本型号已有、可用的物料"})
            elif usable[0]["id"] not in {a["part_id"] for a in resolved}:
                resolved.append(
                    {"part_id": usable[0]["id"], "expected_part_revision": usable[0]["revision"]}
                )
        values["alternates"] = resolved
        report["alternates"] = {
            "resolved": [part_for({"part_id": a["part_id"]}, parts) for a in resolved],
            "unresolved": unresolved,
        }
        dropped = bool(disposition and disposition.get("drop_unresolved_alternates"))
        if unresolved and not dropped and not row_issues:
            report["status"] = "needs_disposition"
            report["reason"] = (
                "替代料未能对应本型号已有物料："
                + "、".join(f"{u['value']}（{u['reason']}）" for u in unresolved)
                + "。可选择不导入这些替代料，或先建立物料后重新转换。"
            )
        report["dropped_alternates"] = unresolved if dropped else []
        if row_issues:
            report["status"] = "needs_disposition"
            report["reason"] = "这一行不能按原样导入，请跳过或在原件中改正后重新转换。"
            report["allowed"] = ["skip"]
        report["resolution"] = resolution
        if resolution == "new_part" and number_value and not row_issues:
            seen_new_numbers.setdefault(number_value, number)
        report["part"] = (
            _part_label(part) if part else _part_label(values) or values.get("erp_number")
        )
        if report["status"] == "ready":
            candidates.append((report, values, part))
        reports.append(report)
    for row in sorted(dispositions):
        issues.append(_issue("disposition_unknown", f"第 {row} 行不是可导入的数据行，处置无效。"))

    previous_keys = {}
    for line in previous_lines or ():
        previous_keys.setdefault(line.get("part_id"), []).append(line["key"])
    used, lines = set(), []
    for report, values, part in candidates:
        explicit = values.get("key")
        if explicit:
            key = explicit
            if key in used:
                report["issues"].append(
                    _issue("key_repeated", "行标识与前面的行重复。", columns.get("key"))
                )
                report.update(status="needs_disposition", allowed=["skip"], reason="行标识重复。")
                continue
        else:
            inherited = previous_keys.get(part["id"]) if part else None
            options = [inherited[0]] if inherited and len(inherited) == 1 else []
            for value in (
                values.get("internal_number"),
                values.get("erp_number"),
                values.get("customer_number"),
            ):
                if value and _safe_key(value):
                    options.append(_safe_key(value))
            options.append(f"row-{report['row']}")
            base = next(option for option in options if option not in used)
            key, suffix = base, 2
            while key in used:
                key, suffix = f"{base[:76]}-{suffix}", suffix + 1
        used.add(key)
        line = {
            "key": key,
            "part_id": part["id"] if part else None,
            "expected_part_revision": part["revision"] if part else None,
            "part": None
            if part
            else {
                "name": values.get("name")
                or values.get("internal_number")
                or values.get("erp_number")
                or values.get("customer_number"),
                "internal_number": values.get("internal_number"),
                "erp_number": values.get("erp_number"),
                "customer_number": values.get("customer_number"),
                "mapping_version": None,
                "external_design_refs": [],
            },
            "quantity": str(values["quantity"]) if "quantity" in values else None,
            "unit": values.get("unit"),
            "loss_rate": str(values["loss_rate"]) if "loss_rate" in values else None,
            "critical": values.get("critical", False),
            "notes": values.get("notes"),
            "reference_designators": values.get("reference_designators", []),
            "alternates": values.get("alternates", []),
        }
        try:
            BomLineInput.model_validate(line)
        except ValidationError as error:
            detail = "；".join(e["msg"] for e in error.errors()[:3])
            report["issues"].append(_issue("line_invalid", f"不符合 BOM 行格式：{detail}"))
            report.update(
                status="needs_disposition", allowed=["skip"], reason="不符合 BOM 行格式。"
            )
            used.discard(key)
            continue
        report["key"] = key
        lines.append({**line, "row": report["row"]})
    if len(lines) > MAX_LINES:
        issues.append(_issue("too_many_lines", f"一次最多导入 {MAX_LINES} 行，请拆分原件。"))
    counts = {"ready": 0, "skipped": 0, "needs_disposition": 0, "ignored": ignored}
    for report in reports:
        counts[report["status"]] += 1
    complete = not issues and not counts["needs_disposition"] and bool(lines)
    by_row = {line["row"]: line for line in lines}
    rule_lines = [
        {
            "key": report.get("key") or f"row-{report['row']}",
            "row": report["row"],
            "quantity": report["values"].get("quantity_text"),
            "unit": report["values"].get("unit"),
            "reference_designators": report["values"].get("reference_designators") or [],
            "alternates": [
                {"part_id": a["part_id"], "part": part_for(a, parts)}
                for a in by_row.get(report["row"], {}).get("alternates", ())
            ],
        }
        for report in reports
        if report["status"] != "skipped"
    ]
    return {
        "columns": [
            {
                "field": entry["field"],
                "column": entry["column"],
                "header": header_cells[entry["column"]].text
                if entry["column"] in header_cells
                else None,
            }
            for entry in sorted(basis["columns"], key=lambda e: e["column"])
        ],
        "unmapped_columns": [
            {
                "column": column,
                "header": header_cells[column].text if column in header_cells else None,
            }
            for column in unmapped
        ],
        "rows": reports,
        "counts": counts,
        "issues": issues,
        "complete": complete,
        "lines": lines,
        "rules": rule_card(rule_lines),
        "diff": compare(
            previous_lines,
            [
                {
                    **line,
                    "part": line["part"] or {**part_for(line, parts)},
                    "alternates": [{**a, "part": part_for(a, parts)} for a in line["alternates"]],
                }
                for line in lines
            ],
        ),
        "header_cells": header_cells,
    }


def part_for(line, parts):
    part = next((p for p in parts if p["id"] == line["part_id"]), None) or {}
    return {"name": part.get("name"), "internal_number": part.get("internal_number")}


def _source_reference(table, basis, header_cells):
    identity = next(
        (
            entry["column"]
            for name in ("internal_number", "name", "erp_number", "key")
            for entry in basis["columns"]
            if entry["field"] == name and entry["column"] in header_cells
        ),
        None,
    )
    cell = header_cells.get(identity) if identity else None
    if cell is None:
        return None
    quote = cell.text.split("\n", 1)[0].strip()
    if not quote:
        return None
    return {
        "artifact_id": str(table.artifact_id),
        "expected_revision": table.artifact_revision,
        "line": cell.line,
        "quote": quote[:4000],
    }


def record(table, basis, result) -> dict:
    """What a BOM revision stores about its import: basis plus per-row outcome."""
    return {
        "converter": CONVERTER,
        **basis,
        "rows": {line["key"]: line["row"] for line in result["lines"]},
        "skipped": [
            {"row": r["row"], "reason": (r["disposition"] or {}).get("reason")}
            for r in result["rows"]
            if r["status"] == "skipped"
        ],
        "ignored_rows": result["counts"]["ignored"],
        "dropped_alternates": [
            {"row": r["row"], "alternates": r["dropped_alternates"]}
            for r in result["rows"]
            if r.get("dropped_alternates") and r["status"] != "skipped"
        ],
        "unmapped_columns": result["unmapped_columns"],
    }


def payload_lines(result):
    return [{k: v for k, v in line.items() if k != "row"} for line in result["lines"]]


def basis_dict(basis: BomImportBasis) -> dict:
    value = basis.model_dump(mode="json")
    value["columns"] = sorted(value["columns"], key=lambda entry: entry["field"])
    value["dispositions"] = sorted(value["dispositions"], key=lambda entry: entry["row"])
    return value


def verify(s, ctx, product_id, payload, previous_view) -> dict:
    """Repeat the conversion at confirmation; the payload lines must be its exact output."""
    from .service import semantic

    basis = basis_dict(payload.import_basis)
    table = read_table(
        s, ctx, product_id, payload.import_basis.artifact_id, basis["expected_revision"]
    )
    if table.format != basis["format"]:
        raise DomainError("VALIDATION_FAILED", "导入格式与原件不一致。", 422)
    result = convert(
        table,
        basis,
        previous_lines=previous_view["lines"] if previous_view else (),
        parts=visible_parts(s, ctx, product_id),
        visibility=payload.visibility,
    )
    if not result["complete"]:
        raise DomainError("VALIDATION_FAILED", "导入仍有未处置的行或无效映射，请重新转换。", 422)
    expected = type(payload).model_validate(
        {**payload.model_dump(mode="json"), "lines": payload_lines(result)}
    )
    if semantic(expected)["lines"] != semantic(payload)["lines"]:
        raise DomainError(
            "VALIDATION_FAILED", "BOM 行须与原件按所选映射转换的结果一致，请重新转换。", 422
        )
    return record(table, basis, result)


def inputs(s, ctx, product_id, request) -> dict:
    """READ: the conversion of one parsed original for review; writes nothing."""
    from .service import _human, _version, get_bom

    _human(s, ctx, product_id)
    table = read_table(s, ctx, product_id, request.artifact_id, request.expected_revision)
    if table.format == "xlsx":
        sheet = request.sheet or next(
            (name for name in table.sheets if suggest_header(table.cells[name])), table.sheets[0]
        )
        if sheet not in table.cells:
            raise DomainError("VALIDATION_FAILED", "所选工作表不在原件中。", 422)
    else:
        if request.sheet is not None:
            raise DomainError("VALIDATION_FAILED", "CSV 原件没有工作表。", 422)
        sheet = None
    rows = table.cells[sheet]
    header_row = request.header_row or suggest_header(rows) or min(rows, default=1)
    suggested = request.columns is None
    columns = (
        [c.model_dump(mode="json") for c in request.columns]
        if request.columns is not None
        else suggest_columns(rows.get(header_row, {}))
    )
    previous = None
    if request.previous_id is not None:
        row, previous = get_bom(s, ctx, product_id, request.previous_id)
        _version(row, request.expected_previous_revision)
    headers = [
        {"column": column, "text": cell.text}
        for column, cell in sorted(rows.get(header_row, {}).items())
    ]
    response = {
        "converter": CONVERTER,
        "format": table.format,
        "sheets": [name for name in table.sheets if name is not None],
        "sheet": sheet,
        "header_row": header_row,
        "headers": headers,
        "fields": [{"field": name, "title": FIELD_TITLES[name]} for name in FIELDS],
        "suggested": suggested,
        "previous": header(previous),
        "artifact": {"id": str(table.artifact_id), "revision": table.artifact_revision},
    }
    try:
        basis = BomImportBasis.model_validate(
            {
                "artifact_id": table.artifact_id,
                "expected_revision": table.artifact_revision,
                "format": table.format,
                "sheet": sheet,
                "header_row": header_row,
                "columns": columns,
                "dispositions": [d.model_dump(mode="json") for d in request.dispositions],
            }
        )
    except ValidationError as error:
        message = "；".join(e["msg"].removeprefix("Value error, ") for e in error.errors()[:3])
        return {**response, "columns": columns, "complete": False, "basis_error": message}
    basis_value = basis_dict(basis)
    result = convert(
        table,
        basis_value,
        previous_lines=previous["lines"] if previous else (),
        parts=visible_parts(s, ctx, product_id),
        visibility=request.visibility,
    )
    header_cells = result.pop("header_cells")
    reference = _source_reference(table, basis_value, header_cells)
    if result["complete"] and reference is None:
        result["issues"].append(
            _issue("header_missing", "映射的物料列没有可引用的表头，请选择正确的表头行。")
        )
        result["complete"] = False
    response.update(result)
    response["payload"] = (
        {
            "lines": payload_lines(result),
            "import_basis": basis.model_dump(mode="json"),
            "sources": [reference],
            "required_source_read_set": [
                {
                    "artifact_id": str(table.artifact_id),
                    "expected_revision": table.artifact_revision,
                }
            ],
            "record": record(table, basis_value, result),
        }
        if result["complete"]
        else None
    )
    return response
