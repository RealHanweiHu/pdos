"""BOM rule card (F35): deterministic checks over one BOM version, no model involved.

The card states findings; it neither blocks saving nor approves anything. A
model may explain a finding, never produce or overturn one ("规则给结论、AI 只解释").
Input lines are ``get_bom`` lines or import candidates; candidates may carry the
original row number and an unparsed quantity text.
"""

from decimal import Decimal, InvalidOperation

from pdos_next.domain.manufacturing.supply_cost.engine.units import UNITS

RULESET = "bom-rules.v1"
ORDER = {"not_applicable": 0, "pass": 1, "warn": 2, "fail": 3}


def _quantity(value):
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        return "invalid"
    return parsed if parsed.is_finite() else "invalid"


def _where(line):
    where = {"key": line.get("key")}
    if line.get("row") is not None:
        where["row"] = line["row"]
    return where


def _rule(code, title, items, explanation, *, applicable=True):
    if not applicable:
        status = "not_applicable"
    elif not items:
        status = "pass"
    else:
        status = "fail" if any(item.get("level") == "fail" for item in items) else "warn"
    return {
        "code": code,
        "title": title,
        "status": status,
        "count": len(items),
        "items": items,
        "explanation": explanation,
    }


def duplicate_designators(lines):
    seen = {}
    for line in lines:
        for value in line.get("reference_designators") or ():
            seen.setdefault(value.upper(), []).append(_where(line))
    items = [
        {"designator": value, "lines": places, "level": "fail"}
        for value, places in sorted(seen.items())
        if len(places) > 1
    ]
    return _rule(
        "duplicate_designator",
        "重复位号",
        items,
        "同一位号只能装一个物料；重复说明位号录错或同一位置放了两行。",
        applicable=bool(seen),
    )


def designator_count(lines):
    items, applicable = [], False
    for line in lines:
        designators = line.get("reference_designators") or ()
        quantity = _quantity(line.get("quantity"))
        if not designators or not isinstance(quantity, Decimal) or quantity <= 0:
            continue
        if UNITS.get(line.get("unit") or "", (None,))[0] != "count":
            continue
        applicable = True
        if quantity != len(designators):
            items.append(
                {
                    **_where(line),
                    "quantity": format(quantity.normalize(), "f"),
                    "designators": len(designators),
                    "level": "warn",
                }
            )
    return _rule(
        "designator_quantity_mismatch",
        "位号数与用量不符",
        items,
        "按个计数的行，位号个数应等于每份用量；不一致时以原件核对哪一边有误。",
        applicable=applicable,
    )


def missing_unit(lines):
    items = []
    for line in lines:
        if line.get("unit"):
            continue
        known = line.get("quantity") is not None
        items.append({**_where(line), "level": "fail" if known else "warn"})
    return _rule(
        "missing_unit",
        "缺单位",
        items,
        "有用量必须有单位；用量和单位都未知时保留空值，齐套会把这一行算作未知。",
    )


def quantity(lines):
    items = []
    for line in lines:
        value = _quantity(line.get("quantity"))
        if value is None:
            items.append({**_where(line), "problem": "unknown", "level": "warn"})
        elif value == "invalid" or value <= 0:
            items.append(
                {
                    **_where(line),
                    "problem": "invalid" if value == "invalid" else "non_positive",
                    "value": str(line.get("quantity")),
                    "level": "fail",
                }
            )
    return _rule(
        "quantity",
        "数量非正或未知",
        items,
        "每份用量须为正数；未知用量保持空值，不估算填补，齐套会把这一行算作未知。",
    )


RULES = (duplicate_designators, designator_count, missing_unit, quantity)


def rule_card(lines) -> dict:
    lines = list(lines or ())
    rules = [rule(lines) for rule in RULES]
    worst = max((rule["status"] for rule in rules), key=ORDER.__getitem__, default="pass")
    return {
        "ruleset": RULESET,
        "status": "pass" if worst == "not_applicable" else worst,
        "lines": len(lines),
        "rules": rules,
        "basis": "确定性规则，按本版 BOM 行计算，不经模型；结果只提示，不阻止保存。",
    }
