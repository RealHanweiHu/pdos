"""BOM version difference shared by the configuration page and the Excel export (D282).

Pure functions over the line dicts that ``get_bom`` (or an import candidate)
already returns; reading and authorization stay with the caller. Lines are
matched by their key, the stable identity a BOM series keeps across versions.
"""

from decimal import Decimal, InvalidOperation

FIELDS = (
    ("part", "物料"),
    ("part_revision", "物料版本"),
    ("quantity", "用量"),
    ("unit", "单位"),
    ("loss_rate", "损耗率"),
    ("critical", "关键件"),
    ("notes", "备注"),
    ("reference_designators", "位号"),
    ("alternates", "替代料"),
)
LISTS = ("reference_designators", "alternates")
TITLES = dict(FIELDS)


def part_label(line: dict) -> str:
    part = line.get("part") or {}
    label = " / ".join(str(v) for v in (part.get("internal_number"), part.get("name")) if v)
    return label or str(line.get("part_id") or "")


def alternate_label(alternate: dict) -> str:
    return part_label(alternate)


def snapshot(line: dict) -> dict:
    """The comparable values of one BOM line, in display form."""
    return {
        "part": part_label(line),
        "part_id": line.get("part_id"),
        "part_revision": line.get("expected_part_revision"),
        "quantity": line.get("quantity"),
        "unit": line.get("unit"),
        "loss_rate": line.get("loss_rate"),
        "critical": line.get("critical"),
        "notes": line.get("notes"),
        "reference_designators": list(line.get("reference_designators") or ()),
        # Declared alternates only; a declaration is not a qualification (P113).
        "alternates": [alternate_label(a) for a in line.get("alternates") or ()],
        "alternate_ids": [a.get("part_id") for a in line.get("alternates") or ()],
    }


def _same_number(left, right) -> bool:
    if left is None or right is None:
        return left is right
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except InvalidOperation:
        return str(left) == str(right)


def _changed(field, before, after) -> bool:
    if field in {"quantity", "loss_rate"}:
        return not _same_number(before.get(field), after.get(field))
    if field == "alternates":
        if all(before.get("alternate_ids") or ()) and all(after.get("alternate_ids") or ()):
            return before.get("alternate_ids") != after.get("alternate_ids")
        return before["alternates"] != after["alternates"]
    if field == "part":
        # A reused part keeps its ID; a new draft (no ID yet) is compared by label.
        if before.get("part_id") and after.get("part_id"):
            return before["part_id"] != after["part_id"]
        return before["part"] != after["part"]
    return before.get(field) != after.get(field)


def _members(before, after, field):
    old, new = before[field], after[field]
    return {
        "added": [value for value in new if value not in old],
        "removed": [value for value in old if value not in new],
    }


def compare(before_lines, after_lines) -> dict:
    """Added, removed and changed lines with per-field values; unchanged lines are counted."""
    old = {line["key"]: snapshot(line) for line in before_lines or ()}
    new = {line["key"]: snapshot(line) for line in after_lines or ()}
    rows, summary = [], {"added": 0, "removed": 0, "changed": 0, "unchanged": 0}
    for key in sorted(old.keys() | new.keys()):
        before, after = old.get(key), new.get(key)
        if before is not None and after is not None:
            fields = [field for field, _ in FIELDS if _changed(field, before, after)]
            if not fields:
                summary["unchanged"] += 1
                continue
            change = "changed"
        else:
            fields, change = [], "added" if before is None else "removed"
        summary[change] += 1
        row = {"key": key, "change": change, "fields": fields, "before": before, "after": after}
        if change == "changed" and "reference_designators" in fields:
            row["designators"] = _members(before, after, "reference_designators")
        if change == "changed" and "alternates" in fields:
            row["alternates"] = _members(before, after, "alternates")
        rows.append(row)
    return {"summary": summary, "lines": rows}


def header(view: dict | None) -> dict | None:
    if view is None:
        return None
    return {
        "id": view.get("id"),
        "name": view["name"],
        "revision": view["revision"],
        "visibility": view.get("visibility"),
        "reason": view.get("reason"),
        "created_at": view.get("created_at"),
        "source_status": view.get("source_status"),
        "lines": len(view["lines"]),
    }


def get_bom_review(s, ctx, product_id, bom_id) -> dict:
    """The page view: this version, its fixed predecessor, their difference and the rule card.

    Both sides go through ``get_bom`` (named human and product grant); the
    predecessor is the one fixed by ``previous_id``, never "the latest".
    """
    from .bom_alternates import approved_alternates
    from .bom_rules import rule_card
    from .service import get_bom

    row, after = get_bom(s, ctx, product_id, bom_id)
    before = get_bom(s, ctx, product_id, row.previous_id)[1] if row.previous_id else None
    return {
        "bom": header(after),
        "previous": header(before),
        "diff": compare(before["lines"] if before else (), after["lines"]),
        "rules": rule_card(after["lines"], approved_alternates(s, ctx, product_id, row)),
        "import_basis": after.get("import_basis"),
    }
