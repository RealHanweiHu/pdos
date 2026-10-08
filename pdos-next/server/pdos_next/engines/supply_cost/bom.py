"""Extracted parent-relative expansion, bounded to 64 levels and count-unit assemblies."""

from datetime import datetime
from decimal import Decimal

from .common import Issue, calculation_context, issue, sorted_issues, source_issues
from .dto import DemandLine, FixedBasis
from .units import UNITS


def expand_bom(
    basis: FixedBasis, as_of: datetime
) -> tuple[tuple[DemandLine, ...], tuple[Issue, ...]]:
    with calculation_context():
        return _expand(basis, as_of)


def _expand(basis: FixedBasis, as_of: datetime) -> tuple[tuple[DemandLine, ...], tuple[Issue, ...]]:
    problems = []
    for path, ref in (
        ("bom", basis.bom.ref),
        ("configuration", basis.bom.engineering_configuration),
        ("build", basis.build.ref),
    ):
        problems.extend(source_issues(ref, as_of, path))
    if not basis.bom.items:
        problems.append(issue("empty_bom", "bom", "No BOM items; empty scope is not complete"))
    if basis.build.quantity is None:
        problems.append(issue("build_quantity_unknown", "build", "Build quantity is unknown"))
    if UNITS.get(basis.build.product_unit or "", (None,))[0] != "count":
        problems.append(
            issue("product_unit_unsupported", "build", "Build unit must be a count unit")
        )
    items = {}
    duplicate = set()
    for item in basis.bom.items:
        if item.item_id in items:
            duplicate.add(item.item_id)
        items[item.item_id] = item
    for item_id in sorted(duplicate):
        problems.append(issue("duplicate_bom_item", item_id, "BOM item ID is repeated", "conflict"))
    lines = []
    for item in sorted(items.values(), key=lambda row: row.item_id):
        row_issues = list(problems)
        quantity = Decimal(1)
        ancestry = []
        current = item.item_id
        seen = set()
        while current is not None:
            if current in seen or current not in items or len(seen) >= 64:
                row_issues.append(
                    issue(
                        "invalid_bom_hierarchy",
                        item.item_id,
                        "Missing parent, cycle or hierarchy deeper than 64",
                        "conflict",
                    )
                )
                break
            seen.add(current)
            node = items[current]
            if current != item.item_id:
                ancestry.append(current)
                if UNITS.get(node.unit or "", (None,))[0] != "count":
                    row_issues.append(
                        issue(
                            "parent_unit_unsupported",
                            current,
                            "Parent-relative multiplication needs count assemblies",
                        )
                    )
                if node.supply_required and item.supply_required:
                    row_issues.append(
                        issue(
                            "overlapping_material_demand",
                            item.item_id,
                            "Parent package and child cannot both require supply",
                            "conflict",
                        )
                    )
            if node.quantity_per_parent is None:
                row_issues.append(issue("bom_quantity_unknown", current, "BOM quantity is unknown"))
            if node.loss_rate is None:
                row_issues.append(
                    issue("loss_unknown", current, "Loss uplift assumption is unknown")
                )
            if node.quantity_per_parent is not None and node.loss_rate is not None:
                quantity *= node.quantity_per_parent * (1 + node.loss_rate)
            current = node.parent_item_id
        if item.unit not in UNITS:
            row_issues.append(
                issue("unit_unsupported", item.item_id, "Missing or unsupported unit")
            )
        # Material mapping is checked by coverage, not cost package hierarchy expansion.
        known = not row_issues
        lines.append(
            DemandLine(
                item_id=item.item_id,
                material_id=item.material_id,
                unit=item.unit,
                critical=item.critical,
                ancestry=tuple(ancestry),
                quantity_per_product=quantity if known else None,
                required_quantity=quantity * basis.build.quantity
                if known and basis.build.quantity is not None
                else None,
                issues=sorted_issues(row_issues),
            )
        )
    return tuple(lines), sorted_issues(problems)
