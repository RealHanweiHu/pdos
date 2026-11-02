"""Compare server-loaded fixed configuration views; never infer actual observations."""

import json
from copy import deepcopy
from decimal import Decimal


def _pin(view):
    return {key: view[key] for key in ("id", "revision")}


def _indexed(rows):
    result = {}
    for row in rows:
        key = row["key"]
        if key in result:
            raise ValueError("Duplicate fixed configuration key")
        result[key] = row
    return result


def _number(value):
    if value is None:
        return None
    if isinstance(value, (bool, float)):
        raise ValueError("Configuration quantities require exact decimal values")
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("Non-finite fixed configuration quantity")
    value = format(number, "f")
    return value.rstrip("0").rstrip(".") if "." in value else value


def _line(row):
    if row is None:
        return None
    return {
        key: _number(row.get(key)) if key in {"quantity", "loss_rate"} else deepcopy(row.get(key))
        for key in (
            "part_id",
            "expected_part_revision",
            "quantity",
            "unit",
            "loss_rate",
            "critical",
            "notes",
        )
    }


def _operation(row):
    if row is None:
        return None
    value = {
        key: deepcopy(row.get(key))
        for key in (
            "name",
            "kind",
            "sop",
            "acceptance_criterion",
            "notes",
        )
    }
    value["cycle_time_minutes"] = _number(row.get("cycle_time_minutes"))
    for key in ("depends_on", "bom_line_keys"):
        value[key] = sorted(row.get(key, []))
    value["resource_requirements"] = sorted(
        deepcopy(row.get("resource_requirements", [])),
        key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
    )
    return value


def compare_configurations(
    planned_engineering, planned_manufacturing, actual_engineering, actual_manufacturing
):
    """Stable paths represent complete changed objects, including explicit unknowns.

    Inputs must already pass current scope and source checks. This comparison does
    not establish real use, correctness, approval or test applicability. Evidence,
    names of owners, timestamps and source status cannot rewrite historical meaning.
    """
    differences = []

    def add(path, before, after, label):
        if before != after:
            differences.append(
                {
                    "path": path,
                    "before": deepcopy(before),
                    "after": deepcopy(after),
                    "label": label,
                }
            )

    add(
        "engineering.configuration",
        _pin(planned_engineering),
        _pin(actual_engineering),
        "工程配置版本",
    )
    add(
        "manufacturing.configuration",
        _pin(planned_manufacturing),
        _pin(actual_manufacturing),
        "制造配置版本",
    )
    for prefix, label in (("definition", "型号定义版本"), ("bom", "BOM版本")):
        add(
            f"engineering.{prefix}",
            {
                "id": planned_engineering[f"{prefix}_id"],
                "revision": planned_engineering[f"{prefix}_revision"],
            },
            {
                "id": actual_engineering[f"{prefix}_id"],
                "revision": actual_engineering[f"{prefix}_revision"],
            },
            label,
        )
    for key, label in (
        ("mechanical", "机械设计引用"),
        ("electronic", "电子设计引用"),
        ("firmware", "固件制品引用"),
    ):
        add(
            f"engineering.design_versions.{key}",
            planned_engineering["design_versions"].get(key),
            actual_engineering["design_versions"].get(key),
            label,
        )
    before_lines = _indexed(planned_engineering["bom"]["lines"])
    after_lines = _indexed(actual_engineering["bom"]["lines"])
    for key in sorted(before_lines.keys() | after_lines.keys()):
        add(
            f"engineering.bom.lines.{key}",
            _line(before_lines.get(key)),
            _line(after_lines.get(key)),
            f"BOM行 {key}",
        )
    for key, label in (("site", "制造场地"), ("line", "制造产线")):
        add(
            f"manufacturing.{key}",
            planned_manufacturing.get(key),
            actual_manufacturing.get(key),
            label,
        )
    before_operations = _indexed(planned_manufacturing["operations"])
    after_operations = _indexed(actual_manufacturing["operations"])
    add(
        "manufacturing.operation_order", list(before_operations), list(after_operations), "工序顺序"
    )
    for key in sorted(before_operations.keys() | after_operations.keys()):
        add(
            f"manufacturing.operations.{key}",
            _operation(before_operations.get(key)),
            _operation(after_operations.get(key)),
            f"工序 {key}",
        )
    return differences
