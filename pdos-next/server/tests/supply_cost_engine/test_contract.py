from copy import deepcopy
from decimal import ROUND_DOWN, Decimal, localcontext

import pytest
from pydantic import ValidationError

from pdos_next.engines.supply_cost import (
    CostRequest,
    CostResult,
    CoverageRequest,
    CoverageResult,
    calculate_cost,
    calculate_coverage,
    expand_bom,
)

from .helpers import bom_item


@pytest.mark.parametrize(
    "request_type,fixture_name", [(CostRequest, "cost"), (CoverageRequest, "coverage")]
)
def test_float_naive_time_unknown_field_and_mutation_are_rejected(
    request, request_type, fixture_name
):
    payload = request.getfixturevalue(fixture_name)
    changed = deepcopy(payload)
    changed["basis"]["build"]["quantity"] = 0.1
    with pytest.raises(ValidationError, match="binary floats"):
        request_type.model_validate(changed)
    changed = deepcopy(payload)
    changed["as_of"] = "2026-01-02T00:00:00"
    with pytest.raises(ValidationError, match="timezone"):
        request_type.model_validate(changed)
    changed = deepcopy(payload)
    changed["approved"] = True
    with pytest.raises(ValidationError, match="Extra inputs"):
        request_type.model_validate(changed)
    dto = request_type.model_validate(payload)
    with pytest.raises(ValidationError, match="frozen"):
        dto.basis.build.quantity = Decimal(1)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "0"])
def test_build_quantities_are_finite_positive_or_explicitly_unknown(cost, value):
    cost["basis"]["build"]["quantity"] = value
    with pytest.raises(ValidationError):
        CostRequest.model_validate(cost)


@pytest.mark.parametrize(
    "kind",
    ["cycle", "missing_parent", "duplicate", "dimension_parent", "overlapping_demand", "too_deep"],
)
def test_invalid_hierarchy_has_explanations_and_no_usable_demand(coverage, kind):
    first = coverage["basis"]["bom"]["items"][0]
    if kind == "cycle":
        first["parent_item_id"] = "a"
    elif kind == "missing_parent":
        first["parent_item_id"] = "absent"
    elif kind == "duplicate":
        coverage["basis"]["bom"]["items"].append(deepcopy(first))
    elif kind in {"dimension_parent", "overlapping_demand"}:
        first["parent_item_id"] = "parent"
        coverage["basis"]["bom"]["items"].append(
            bom_item(
                "parent",
                unit="kg" if kind == "dimension_parent" else "ea",
                supply_required=kind == "overlapping_demand",
            )
        )
    else:
        first["parent_item_id"] = "p0"
        coverage["basis"]["bom"]["items"].extend(
            bom_item(f"p{i}", parent_item_id=f"p{i + 1}" if i < 63 else None, supply_required=False)
            for i in range(64)
        )
    result = calculate_coverage(CoverageRequest.model_validate(coverage))
    assert result.secured_ready is not True
    assert result.lines[0].demand.required_quantity is None
    assert result.issues


def test_exact_bounded_bom_expansion_and_money_ignore_host_decimal_settings(cost, coverage):
    for payload in (cost, coverage):
        payload["basis"]["bom"]["items"][0]["quantity_per_parent"] = "1234567890123456.12345678"
    unchanged = deepcopy(cost)
    cost_dto, coverage_dto = (
        CostRequest.model_validate(cost),
        CoverageRequest.model_validate(coverage),
    )
    with localcontext() as ctx:
        ctx.prec = 5
        ctx.rounding = ROUND_DOWN
        ctx.Emax = 9
        low_cost, low_supply = calculate_cost(cost_dto), calculate_coverage(coverage_dto)
    with localcontext() as ctx:
        ctx.prec = 100
        high_cost, high_supply = calculate_cost(cost_dto), calculate_coverage(coverage_dto)
    assert low_cost == high_cost and low_supply == high_supply
    assert cost == unchanged
    assert low_supply.lines[0].demand.required_quantity == Decimal("6172839450617280.61728390")
    assert CostResult.model_validate_json(low_cost.model_dump_json()) == low_cost
    assert CoverageResult.model_validate_json(low_supply.model_dump_json()) == low_supply


def test_nested_quantity_expansion_is_exact_before_cost_precision(cost):
    cost["basis"]["bom"]["items"] = [
        bom_item("parent", quantity_per_parent="1234567890123456.12345678", supply_required=False),
        bom_item(parent_item_id="parent", quantity_per_parent="1234567890123456.12345678"),
    ]
    dto = CostRequest.model_validate(cost)
    rows, _ = expand_bom(dto.basis, dto.as_of)
    with localcontext() as ctx:
        ctx.prec = 100
        expected = Decimal("1234567890123456.12345678") ** 2 * 5
    assert rows[0].required_quantity == expected


def test_input_digest_uses_decimal_value_and_utc_time_not_representation(cost):
    before = calculate_cost(CostRequest.model_validate(cost))
    cost["prices"][0]["amount"] = "0.10000000"
    cost["as_of"] = "2026-01-01T16:00:00-08:00"
    after = calculate_cost(CostRequest.model_validate(cost))
    assert before.input_sha256 == after.input_sha256


@pytest.mark.parametrize("value", ["0e1000000", "0e-1000000", "0" * 1000, True])
def test_decimal_representation_cannot_bypass_bounds_with_zero(cost, value):
    cost["prices"][0]["amount"] = value
    with pytest.raises(ValidationError):
        CostRequest.model_validate(cost)
