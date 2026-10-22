"""Source bounds remain constraints through every public specification input."""
# ruff: noqa: F811 -- pytest injects the explicitly imported pure reader fixture

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.preproject.evidence_schemas import ClaimContent
from pdos_next.domain.preproject.schemas import SpecItem
from pdos_next.schemas.products.definitions import DefinitionSpec
from pdos_next.schemas.products.derivation import SpecSnapshot
from tests.preproject.test_spec_compare import item, parameter, proposal, run
from tests.preproject.test_spec_compare import world as world


def content(model, value_type, **values):
    result = {
        "key": "noise_level",
        "parameter": "噪声",
        "value_type": value_type,
        "availability": "known",
        "unit": "dB(A)",
        "reason": "原文明确的噪声约束",
        **values,
    }
    if model is DefinitionSpec:
        result["sources"] = [
            {
                "artifact_id": str(uuid4()),
                "expected_revision": 1,
                "line": 1,
                "quote": "噪声 ≤75 dB(A)",
            }
        ]
    return result


@pytest.mark.parametrize("model", [SpecItem, DefinitionSpec, SpecSnapshot])
@pytest.mark.parametrize("value_type", ["number", "range"])
@pytest.mark.parametrize(
    "bounds",
    [
        {"upper": "75"},
        {"lower": "0"},
        {"upper": "0"},
        {"lower": "-5.25"},
        {"lower": "-5.25", "upper": "0"},
        {"lower": "0", "upper": "0"},
    ],
)
def test_explicit_single_or_ordered_bounds_keep_absent_endpoints(model, value_type, bounds):
    actual = model.model_validate(content(model, value_type, **bounds))
    assert actual.value is None
    assert actual.lower == (Decimal(bounds["lower"]) if "lower" in bounds else None)
    assert actual.upper == (Decimal(bounds["upper"]) if "upper" in bounds else None)
    assert actual.value_type == value_type and actual.availability == "known"


@pytest.mark.parametrize("model", [SpecItem, DefinitionSpec, SpecSnapshot])
@pytest.mark.parametrize("value_type", ["number", "range"])
@pytest.mark.parametrize(
    "values",
    [
        {},
        {"lower": "76", "upper": "75"},
        {"value": "0", "upper": "75"},
        {"value": "0", "lower": "0"},
        {"upper": "NaN"},
        {"lower": "Infinity"},
    ],
)
def test_empty_reversed_mixed_and_nonfinite_constraints_are_rejected(model, value_type, values):
    with pytest.raises(ValidationError):
        model.model_validate(content(model, value_type, **values))


@pytest.mark.parametrize("model", [SpecItem, DefinitionSpec, SpecSnapshot])
def test_scalar_zero_stays_scalar_and_range_does_not_accept_scalar(model):
    actual = model.model_validate(content(model, "number", value="0"))
    assert actual.value == Decimal(0) and actual.lower is None and actual.upper is None
    with pytest.raises(ValidationError):
        model.model_validate(content(model, "range", value="0"))


@pytest.mark.parametrize("model", [SpecItem, DefinitionSpec, SpecSnapshot])
@pytest.mark.parametrize("availability", ["unknown", "conflicted", "not_applicable"])
def test_unavailable_spec_does_not_acquire_a_bound(model, availability):
    with pytest.raises(ValidationError):
        model.model_validate({**content(model, "number", upper="75"), "availability": availability})


@pytest.mark.parametrize("bounds", [{"lower": "0"}, {"upper": "75"}, {"upper": "0"}])
def test_claim_keeps_known_single_bound_and_original_exception(bounds):
    exception = {"text": "启动后前三秒除外", "applies_to": "启动后前三秒"}
    actual = ClaimContent(**bounds, exceptions=[exception], modality="must")
    assert actual.value is None and actual.exceptions == [exception]
    assert actual.lower == (Decimal(bounds["lower"]) if "lower" in bounds else None)
    assert actual.upper == (Decimal(bounds["upper"]) if "upper" in bounds else None)
    with pytest.raises(ValidationError):
        ClaimContent(**bounds, value="1")


@pytest.mark.parametrize("value_type", ["number", "range"])
@pytest.mark.parametrize("bounds", [{"lower": "0"}, {"upper": "75"}])
def test_real_comparison_reader_preserves_bound_without_missing_value_diagnostic(
    world, value_type, bounds
):
    identity = parameter(world, value_type=value_type)
    target = proposal(world, [item(identity, value=None, value_type=value_type, **bounds)])
    result = run(world, [target])
    observation = result["groups"][0]["observations"][0]
    assert result["engine_version"] == "spec-compare/v2"
    assert observation["value"] is None
    assert observation["lower"] == bounds.get("lower")
    assert observation["upper"] == bounds.get("upper")
    assert "value_missing_or_invalid" not in observation["reasons"]
    assert observation["comparable"] is True


def test_bound_does_not_merge_different_conditions_or_create_scalar_plot(world):
    identity = parameter(world)
    first = proposal(world, [item(identity, value=None, upper="75", condition_note="23 C")])
    second = proposal(world, [item(identity, value=None, upper="75", condition_note="40 C")])
    result = run(world, [first, second])
    assert len(result["groups"]) == 2
    assert all(
        row["value"] is None and row["upper"] == "75"
        for group in result["groups"]
        for row in group["observations"]
    )


def test_existing_competitor_numeric_annotations_do_not_hide_the_numeric_fact():
    from pdos_next.domain.preproject.spec_compare import _value

    actual, failures = _value({"value": "75", "text": "原文标称值"}, "number")
    assert not failures and actual["value"] == Decimal(75)
    assert actual["text_value"] == "原文标称值"
