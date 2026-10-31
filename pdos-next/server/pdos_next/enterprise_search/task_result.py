"""Finite task tables over currently verified extraction proofs, never model facts."""

import json

from pydantic import ValidationError

from .assistant_schemas import TaskResultDraft
from .locations import span

FORMATS = {
    "blockers": (
        "阻塞清单",
        (
            ("conclusion", "当前结论"),
            ("blocker", "阻塞事项"),
            ("owner", "责任人"),
            ("next_step", "下一步"),
            ("decision", "待决定事项"),
        ),
    ),
    "cases": (
        "案例表",
        (
            ("case", "相似案例"),
            ("root_cause", "根因"),
            ("measures", "措施"),
            ("verification", "验证结果"),
            ("conditions_and_differences", "适用条件与差异"),
        ),
    ),
    "review": (
        "评审清单",
        (
            ("key_changes", "关键变化"),
            ("unresolved_issues", "未解决问题"),
            ("decisions", "需决定事项"),
        ),
    ),
    "commitments": (
        "承诺表",
        (
            ("current_commitment", "当前承诺"),
            ("deviation", "偏差"),
            ("related_objects", "相关对象"),
            ("follow_up", "需跟进事项"),
        ),
    ),
}
UNKNOWN = {"not_recorded": "未记录", "to_confirm": "待确认", "unspecified": "未指定"}
RESPONSIBILITY_FIELDS = frozenset({"owner_id", "responsible_id", "executor_id"})
DATE_FIELDS = frozenset(
    {
        "at",
        "expected_at",
        "promised_at",
        "next_check_at",
        "observation_until",
        "planned_start",
        "planned_end",
        "occurred_at",
        "received_at",
        "effective_at",
        "completed_at",
        "actual_start",
        "actual_end",
    }
)


def _unknown(key, status="to_confirm"):
    if key == "owner":
        status = "unspecified"
    return {"status": status, "text": UNKNOWN[status]}


def _field(values, path):
    # Source identities, source_refs and policy descriptions are not business facts.
    if path[0] not in {"facts", "content"}:
        raise ValueError("A recorded business field is required")
    value = values
    for key in path:
        if isinstance(value, dict) and isinstance(key, str):
            value = value[key]
        elif isinstance(value, list) and type(key) is int:
            value = value[key]
        else:
            raise ValueError("Invalid structured field")
    if value is None or value == "" or value == {} or value == []:
        raise ValueError("A nonempty recorded field is required")
    text = (
        value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, allow_nan=False)
    )
    if len(text) > 1000:
        raise ValueError("Recorded field exceeds the bounded cell")
    return text


def _cell(draft, key, evidence, actual):
    if draft.status != "recorded":
        return _unknown(key, draft.status), None
    cid = str(draft.citation_id)
    source = actual.get(cid)
    rows = [row for row in evidence if row["citation_id"] == cid]
    if source is None or not rows:
        raise ValueError("This citation has no verified extraction")
    if key == "owner" and draft.text is not None:
        raise ValueError("Responsibility cannot be supplied by analysis")
    if draft.field_path is not None:
        row = next((row for row in rows if "values" in row), None)
        if row is None or row["values"] != source["structured"]:
            raise ValueError("The structured field was not extracted")
        if key == "owner" and draft.field_path[-1] not in RESPONSIBILITY_FIELDS:
            raise ValueError("A named actor is not necessarily responsible")
        if draft.field_path[-1] in DATE_FIELDS and draft.text is not None:
            raise ValueError("A recorded date cannot be overridden by analysis")
        text = _field(row["values"], draft.field_path)
        pointer = "/" + "/".join(
            str(part).replace("~", "~0").replace("/", "~1") for part in draft.field_path
        )
        locator = {"json_pointer": pointer}
        proof = {"citation_id": cid, "quote": row["quote"], "locator": locator}
    else:
        if key == "owner":
            raise ValueError("Responsibility must select its recorded field")
        text = draft.quote
        row = next((row for row in rows if "values" not in row and text in row["quote"]), None)
        if row is None or text not in source["body"]:
            raise ValueError("The literal cell was not extracted")
        first = row.get("locator", {}).get("char_start")
        if (
            not isinstance(first, int)
            or source["body"][first : first + len(row["quote"])] != row["quote"]
        ):
            raise ValueError("The extracted quote has no fixed span")
        start = first + row["quote"].index(text)
        locator = span(source, start, start + len(text))
        proof = {"citation_id": cid, "quote": text, "locator": locator}
    return {
        "status": "recorded",
        "text": draft.text or text,
        "content_kind": "analysis" if draft.text is not None else "recorded",
        "basis_text": text,
        "citation_id": cid,
        "locator": locator,
        "source_revision": source["source_revision"],
        "currentness": "current"
        if source["is_current"] and not source.get("updated")
        else "history",
        "read_basis_status": source["read_basis_status"],
    }, proof


def assemble(proposed, evidence, actual):
    """Return the checked table, additional source proofs, and visible validation gaps."""
    if proposed is None:
        return None, [], []
    try:
        draft = TaskResultDraft.model_validate(proposed)
        title, columns = FORMATS[draft.format]
        allowed = {key for key, _label in columns}
        if any(set(row.cells) - allowed for row in draft.rows):
            raise ValueError("Unregistered table fields")
    except (ValidationError, ValueError):
        return None, [], ["任务结果结构未通过核对，请按已登记结构重新整理。"]
    rows, proofs, rejected = [], [], []
    # An empty model table is visible as an unknown row, never an empty success.
    for index, row in enumerate(draft.rows or [None]):
        cells = {}
        for key, label in columns:
            cell = row.cells.get(key) if row else None
            if cell is None:
                cells[key] = _unknown(key)
                continue
            try:
                cells[key], proof = _cell(cell, key, evidence, actual)
                if proof is not None:
                    proofs.append(proof)
            except (ValueError, KeyError, IndexError, TypeError):
                cells[key] = _unknown(key)
                rejected.append(f"第 {index + 1} 行“{label}”未通过引用或登记字段核对。")
        rows.append({"cells": cells})
    return (
        {
            "version": 1,
            "format": draft.format,
            "title": title,
            "columns": [{"key": key, "label": label} for key, label in columns],
            "rows": rows,
            "verified": not rejected,
            "unknown_count": sum(
                cell["status"] != "recorded" for row in rows for cell in row["cells"].values()
            ),
        },
        proofs,
        rejected[:10],
    )


def markdown(value):
    """Save the same verified cells and explicit unknowns as a private work product."""
    columns = value["columns"]

    def escaped(text):
        return str(text).replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")

    citations = list(
        dict.fromkeys(
            cell["citation_id"]
            for row in value["rows"]
            for cell in row["cells"].values()
            if cell["status"] == "recorded"
        )
    )
    lines = [
        value["title"],
        "",
        "| " + " | ".join(item["label"] for item in columns) + " |",
        "| " + " | ".join("---" for _item in columns) + " |",
    ]
    for row in value["rows"]:
        fields = []
        for column in columns:
            cell = row["cells"][column["key"]]
            text = escaped(cell["text"])
            if cell["status"] == "recorded":
                if cell["content_kind"] == "analysis":
                    text = "分析：" + text + "<br>依据：" + escaped(cell["basis_text"])
                text += f" 〔{citations.index(cell['citation_id']) + 1}〕"
            fields.append(text)
        lines.append("| " + " | ".join(fields) + " |")
    if citations:
        lines.append("\n固定版本来源：")
        lines.extend(f"〔{index + 1}〕 {cid}" for index, cid in enumerate(citations))
    if value["unknown_count"]:
        lines.append(f"\n{value['unknown_count']} 项未记录或待确认；责任人与日期以已有登记为准。")
    return "\n".join(lines)
