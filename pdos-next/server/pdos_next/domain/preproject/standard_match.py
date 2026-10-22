"""Ephemeral, read-only requirement checks against actual product definitions.

This is a human workbench, not an approval or a computed Claim. Request values
never become business facts. Only a verified published definition can satisfy a
requirement; overlapping numeric intervals are inconclusive, not a match.
"""

from decimal import Decimal
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import text

from pdos_next.schema_base import StrictModel
from pdos_next.service import digest

from . import category_service, spec_compare
from .schemas import SpecItem

VERSION = "standard-match/v1"


class StandardMatchInput(StrictModel):
    product_ids: list[UUID] = Field(min_length=1)
    requirements: list[SpecItem] = Field(min_length=1)

    @model_validator(mode="after")
    def distinct_products(self):
        if len(set(self.product_ids)) != len(self.product_ids):
            raise ValueError("Product IDs must be distinct")
        return self


def interval(value):
    """Missing endpoints stay open. Tolerance expands an exact value only."""
    if value.get("value") is not None:
        point = Decimal(str(value["value"]))
        tolerance = Decimal(str(value.get("tolerance") or 0))
        return point - tolerance, point + tolerance
    return (
        Decimal(str(value["lower"])) if value.get("lower") is not None else Decimal("-Infinity"),
        Decimal(str(value["upper"])) if value.get("upper") is not None else Decimal("Infinity"),
    )


def check_values(requirement, observation):
    if requirement["value_type"] in {"number", "range"}:
        low, high = interval(requirement)
        actual_low, actual_high = interval(observation)
        if low <= actual_low and actual_high <= high:
            return "meets", []
        if actual_high < low or actual_low > high:
            return "differs", ["outside_required_bounds"]
        return "unknown", ["partially_overlapping_bounds"]
    required = requirement["text_value"]
    actual = observation.get("text_value")
    if requirement["value_type"] == "boolean":
        actual = "true" if observation.get("value") is True else "false"
    return ("meets", []) if actual == required else ("differs", ["value_differs"])


def requirement_view(s, ctx, requirement):
    data = requirement.model_dump(mode="json")
    reasons = []
    if requirement.availability != "known":
        reasons.append("requirement_unknown")
    if requirement.item_status == "expert_pending":
        reasons.append("requirement_expert_pending")
    if requirement.exceptions or requirement.applicable_variants:
        reasons.append("applicability_requires_review")
    if requirement.modality == "prohibited":
        reasons.append("prohibition_requires_review")
    if requirement.tolerance and requirement.value is None:
        reasons.append("range_tolerance_requires_review")
    if requirement.parameter_id is None:
        reasons.append("unmapped_parameter")
        return data, reasons
    parameter = category_service.parameter_version(
        s, ctx, requirement.parameter_id, requirement.parameter_version
    )
    # Labels come from the actual fixed dictionary version. Missing customer
    # units and conditions are deliberately never inferred.
    data.update(key=parameter.key, parameter=parameter.name)
    if requirement.value_type != parameter.value_type:
        reasons.append("value_type_mismatch")
    if (
        requirement.value_type == "enum"
        and parameter.enum_values is not None
        and requirement.text_value not in parameter.enum_values
    ):
        reasons.append("enum_value_unmapped")
    if requirement.value_type in {"number", "range"}:
        if not requirement.unit:
            reasons.append("unit_missing")
        elif parameter.unit != requirement.unit:
            reasons.append("unit_differs")
        if not data["condition_note"] and not requirement.test_conditions:
            reasons.append("condition_missing")
    return data, reasons


def check_requirement(required, reasons, subject, groups):
    identity = subject["id"]
    rows = [
        (group, row)
        for group in groups
        for row in group["observations"]
        if row["subject"]["id"] == identity
        and group["parameter_id"] == required.get("parameter_id")
    ]
    matches = [
        row
        for group, row in rows
        if all(
            group[key] == required.get(key)
            for key in ("parameter_version", "unit", "condition_note", "test_conditions")
        )
    ]
    if subject.get("baseline_kind") != "published":
        reasons = [*reasons, "published_definition_required"]
    if subject.get("issues"):
        reasons = [*reasons, "source_unavailable"]
    if subject.get("unavailable_definition_count"):
        reasons = [*reasons, "newer_definition_unavailable"]
    if not matches:
        reasons = [*reasons, "different_parameter_or_conditions" if rows else "spec_missing"]
    if len(matches) > 1:
        reasons = [*reasons, "multiple_spec_values"]
    actual = matches[0] if len(matches) == 1 else None
    if actual is not None:
        reasons = [*reasons, *actual["reasons"]]
        if not actual["comparable"]:
            reasons.append("spec_not_comparable")
        if actual["value_type"] != required["value_type"]:
            reasons.append("value_type_mismatch")
        if actual.get("exceptions") or actual.get("applicable_variants"):
            reasons.append("applicability_requires_review")
        if actual.get("modality") == "prohibited":
            reasons.append("prohibition_requires_review")
        if Decimal(str(actual.get("tolerance") or 0)) and actual.get("value") is None:
            reasons.append("range_tolerance_requires_review")
        for key in ("verification_method", "acceptance_criterion"):
            if required.get(key) and actual.get(key) != required[key]:
                reasons.append("verification_basis_differs")
    if reasons:
        return {"status": "unknown", "reasons": sorted(set(reasons)), "observation": actual}
    status, reasons = check_values(required, actual)
    return {"status": status, "reasons": reasons, "observation": actual}


def match(s, ctx, payload, *, before_definition_read=None):
    payload = StandardMatchInput.model_validate(payload)
    comparison = spec_compare.compare(
        s,
        ctx,
        {"subjects": [{"type": "product", "id": item} for item in payload.product_ids]},
        **({"before_definition_read": before_definition_read} if before_definition_read else {}),
    )
    requirements = [requirement_view(s, ctx, item) for item in payload.requirements]
    products = []
    for subject in comparison["subjects"]:
        checks = [
            {
                "requirement_index": index,
                **check_requirement(req, reasons, subject, comparison["groups"]),
            }
            for index, (req, reasons) in enumerate(requirements)
        ]
        counts = {
            status: sum(c["status"] == status for c in checks)
            for status in ("meets", "differs", "unknown")
        }
        products.append(
            {
                "product_id": subject["id"],
                "name": subject["label"],
                "definition_id": subject.get("definition_id"),
                "definition_revision": subject.get("definition_revision"),
                "baseline_kind": subject.get("baseline_kind"),
                "status": "has_differences"
                if counts["differs"]
                else ("needs_review" if counts["unknown"] else "selected_specs_meet"),
                "counts": counts,
                "checks": checks,
            }
        )
    result = {
        "engine_version": VERSION,
        "requirements": [item for item, _ in requirements],
        "products": products,
        "comparison_digest": comparison["input_digest"],
        "as_of": s.scalar(text("SELECT transaction_timestamp()")).isoformat(),
        "next_step": "confirm_full_scope_then_crm",
    }
    result["input_digest"] = digest({"request": payload.model_dump(mode="json"), "result": result})
    return result
