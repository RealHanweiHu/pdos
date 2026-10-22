from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.preproject.standard_match import (
    StandardMatchInput,
    check_requirement,
    check_values,
)


@pytest.mark.parametrize(
    "requested,actual,status",
    [
        ({"upper": "75"}, {"value": "70"}, "meets"),
        ({"upper": "75"}, {"value": "75"}, "meets"),
        ({"upper": "75"}, {"value": "76"}, "differs"),
        ({"lower": "100"}, {"value": "150"}, "meets"),
        ({"lower": "100"}, {"upper": "150"}, "unknown"),
        ({"upper": "75"}, {"lower": "70", "upper": "80"}, "unknown"),
        ({"lower": "0", "upper": "5"}, {"value": "0"}, "meets"),
        ({"value": "0"}, {"value": "0"}, "meets"),
        ({"value": "5", "tolerance": "1"}, {"value": "6"}, "meets"),
        ({"upper": "75"}, {"value": "74", "tolerance": "2"}, "unknown"),
        ({"upper": "75"}, {"value": "78", "tolerance": "2"}, "differs"),
        ({"upper": "0"}, {"lower": "1"}, "differs"),
        ({"lower": "0"}, {"lower": "5"}, "meets"),
    ],
)
def test_numeric_bounds_are_guaranteed_containment_not_overlap(requested, actual, status):
    assert check_values({"value_type": "number", **requested}, actual)[0] == status


@pytest.mark.parametrize(
    "kind,required,actual,status",
    [
        ("boolean", "false", {"value": False}, "meets"),
        ("boolean", "false", {"value": True}, "differs"),
        ("enum", "small", {"text_value": "small"}, "meets"),
        ("text", "small", {"text_value": "Small"}, "differs"),
    ],
)
def test_non_numeric_values_use_exact_values(kind, required, actual, status):
    assert check_values({"value_type": kind, "text_value": required}, actual)[0] == status


def test_empty_ambiguous_or_caller_policy_inputs_are_rejected():
    product = str(uuid4())
    spec = {"key": "noise", "parameter": "Noise", "value_type": "number"}
    valid = {"product_ids": [product], "requirements": [spec]}
    for changed in (
        {"product_ids": []},
        {"product_ids": [product, product]},
        {"requirements": []},
        {"tenant_id": str(uuid4())},
        {"category_id": str(uuid4())},
        {"requirements": [{**spec, "availability": "known", "value": "NaN"}]},
    ):
        with pytest.raises(ValidationError):
            StandardMatchInput.model_validate({**valid, **changed})


def test_old_readable_publication_does_not_replace_an_unavailable_newer_definition():
    required = {
        "parameter_id": str(uuid4()),
        "parameter_version": 1,
        "unit": "dB",
        "condition_note": "one meter",
        "test_conditions": [],
        "value_type": "number",
        "upper": "75",
    }
    subject = {"id": str(uuid4()), "baseline_kind": "published", "issues": []}
    observation = {
        "subject": {"id": subject["id"]},
        "value_type": "number",
        "upper": "70",
        "value": None,
        "comparable": True,
        "reasons": [],
        "tolerance": "0E-12",
    }
    groups = [{**required, "observations": [observation]}]
    assert check_requirement(required, [], subject, groups)["status"] == "meets"
    current = check_requirement(
        required, [], {**subject, "unavailable_definition_count": 1}, groups
    )
    assert current["status"] == "unknown"
    assert "newer_definition_unavailable" in current["reasons"]
