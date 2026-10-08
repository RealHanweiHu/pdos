from copy import deepcopy
from decimal import Decimal

import pytest

from pdos_next.engines.supply_cost import CostRequest, calculate_cost

from .helpers import bom_item, price, ref


def run(payload):
    return calculate_cost(CostRequest.model_validate(payload))


def test_decimal_totals_preserve_full_snapshot_and_do_not_round_display_currency(cost):
    result = run(cost)
    assert result.complete_in_selected_scope
    assert result.per_product_candidate == Decimal("0.2")
    assert result.build_candidate == Decimal("1.0")
    assert result.lines[0].quantity_for_build == 10
    assert result.input_snapshot.prices[0].ref.version == "v1"
    assert result.input_snapshot.basis.bom.ref.sha256 == "a" * 64
    assert result.nre_candidate is None and result.including_amortized_nre is None


def test_parent_relative_quantity_and_loss_are_compounded(cost):
    cost["basis"]["bom"]["items"] = [
        bom_item("parent", quantity_per_parent="3", supply_required=False, loss_rate="0.1"),
        bom_item(parent_item_id="parent", quantity_per_parent="2", loss_rate="0.2"),
    ]
    result = run(cost)
    assert result.complete_in_selected_scope
    assert result.lines[0].quantity_per_product == Decimal("7.92")
    assert result.build_candidate == Decimal("3.960")
    assert {row.code for row in result.sensitive_items} == {"material_loss_uplift"}


def test_parent_package_or_children_can_be_priced_but_overlaps_are_excluded(cost):
    cost["basis"]["bom"]["items"] = [
        bom_item("parent", quantity_per_parent="1", supply_required=False),
        bom_item(parent_item_id="parent"),
    ]
    cost["material_prices"] = [dict(bom_item_id="parent", price_id="price")]
    assert run(cost).complete_in_selected_scope
    cost["material_prices"].append(dict(bom_item_id="a", price_id="price"))
    result = run(cost)
    assert not result.complete_in_selected_scope
    assert result.known_build_subtotal == 0
    assert result.build_candidate is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount", None),
        ("currency", None),
        ("price_quantity", None),
        ("unit", "box"),
        ("unit", "kg"),
        ("tax_basis", "unknown"),
        ("freight_basis", "excluded"),
    ],
)
def test_missing_or_incomparable_price_does_not_invent_total(cost, field, value):
    cost["prices"][0][field] = value
    result = run(cost)
    assert not result.complete_in_selected_scope
    assert result.build_candidate is None and result.per_product_candidate is None
    assert result.known_build_subtotal == 0
    assert result.issues


def test_partial_subtotal_does_not_hide_unpriced_leaf(cost):
    cost["basis"]["bom"]["items"].append(bom_item("b", material_id="other"))
    result = run(cost)
    assert result.build_candidate is None
    assert result.known_build_subtotal == 1
    assert "unpriced_bom_item" in {note.code for note in result.issues}


def test_duplicate_selection_and_conflicting_price_version_cannot_inflate_subtotal(cost):
    cost["material_prices"] *= 2
    result = run(cost)
    assert result.known_build_subtotal == 0
    assert "duplicate_material_price" in {note.code for note in result.issues}
    cost["material_prices"].pop()
    conflicting = deepcopy(cost["prices"][0])
    conflicting["amount"] = "9"
    cost["prices"].append(conflicting)
    assert run(cost).known_build_subtotal == 0


def test_quote_tier_uses_converted_price_units_instead_of_bom_unit(cost):
    cost["basis"]["bom"]["items"][0].update(quantity_per_parent="100", unit="g")
    cost["prices"][0].update(
        stage="quote",
        unit="kg",
        amount="4",
        minimum_quantity="0.5",
        maximum_quantity="1",
        valid_from="2026-01-01T00:00:00Z",
        valid_until="2026-01-03T00:00:00Z",
    )
    result = run(cost)
    assert result.complete_in_selected_scope
    assert result.lines[0].quantity_in_price_unit == Decimal("0.5")
    assert result.build_candidate == Decimal(2)
    cost["prices"][0]["minimum_quantity"] = "1"
    assert run(cost).build_candidate is None


def test_quote_validity_is_explicit_and_end_is_exclusive(cost):
    cost["prices"][0].update(
        stage="quote",
        minimum_quantity="1",
        valid_from="2026-01-01T00:00:00Z",
        valid_until=cost["as_of"],
    )
    assert "quote_not_valid" in {note.code for note in run(cost).issues}


def test_currency_requires_one_direct_rate_with_source_time_and_purpose(cost):
    cost["prices"][0]["currency"] = "EUR"
    assert run(cost).build_candidate is None
    rate = dict(
        rate_id="fx",
        ref=ref("fx"),
        from_currency="EUR",
        to_currency="USD",
        rate="1.25",
        purpose="budget",
    )
    cost["rates"] = [rate]
    result = run(cost)
    assert result.build_candidate == Decimal("1.25")
    assert result.lines[0].rate_id == "fx"
    cost["rates"] = [dict(rate, from_currency="USD", to_currency="EUR")]
    assert run(cost).build_candidate is None
    cost["rates"] = [dict(rate, purpose="spot")]
    assert run(cost).build_candidate is None
    cost["rates"] = [dict(rate, ref=ref("fx", captured_at="2025-12-01T00:00:00Z"))]
    assert run(cost).build_candidate is None
    cost["rates"] = [rate, dict(rate, rate_id="second")]
    assert run(cost).build_candidate is None


def test_tax_conversion_requires_rate_and_retains_original_amount(cost):
    cost["prices"][0].update(tax_basis="inclusive", amount="0.12")
    assert run(cost).build_candidate is None
    cost["prices"][0]["tax_rate"] = "0.2"
    result = run(cost)
    assert result.build_candidate == 1
    assert result.lines[0].original_build_amount == Decimal("1.2")


def test_process_cost_uses_fixed_version_time_units_and_explicit_loss(cost):
    cost["scope"]["coverage"] = "materials_and_process"
    assert run(cost).build_candidate is None
    cost["process"] = dict(
        ref=ref("process"),
        assumption="Minutes per finished good",
        operations=[
            dict(
                operation_id="labor",
                quantity_per_product="30",
                unit="min",
                loss_rate="0",
                price_id="labor",
            )
        ],
    )
    cost["prices"].append(
        price("labor", amount="2", unit="h", subject_kind="process", subject_id="labor")
    )
    result = run(cost)
    assert result.complete_in_selected_scope
    assert result.build_candidate == 6  # 1 material + 5 units * 0.5 hour * 2 USD
    assert result.lines[1].quantity_in_price_unit == Decimal("2.5")
    cost["process"]["operations"][0]["loss_rate"] = None
    assert run(cost).build_candidate is None


def test_nre_is_separate_until_explicit_volume_is_supplied(cost):
    cost["scope"]["nre_policy"] = "separate"
    assert run(cost).build_candidate is None
    cost["prices"].append(
        price("tool", basis="nre", unit="item", amount="100", subject_kind="nre", subject_id="tool")
    )
    cost["nre_price_ids"] = ["tool"]
    result = run(cost)
    assert result.per_product_candidate == Decimal("0.2") and result.nre_candidate == 100
    assert result.including_amortized_nre is None
    cost["scope"]["nre_policy"] = "amortize"
    assert run(cost).build_candidate is None
    cost["scope"]["nre_volume"] = "100"
    assert run(cost).including_amortized_nre == Decimal("1.2")


@pytest.mark.parametrize(
    "path,field", [("build", "quantity"), ("item", "loss_rate"), ("item", "unit")]
)
def test_unknown_quantity_or_loss_or_unit_never_becomes_zero_cost(cost, path, field):
    container = cost["basis"]["build"] if path == "build" else cost["basis"]["bom"]["items"][0]
    container[field] = None
    result = run(cost)
    assert result.build_candidate is None and result.known_build_subtotal == 0


def test_stale_bom_or_revised_price_source_cannot_return_complete_cost(cost):
    cost["basis"]["bom"]["ref"]["state"] = "stale"
    assert run(cost).build_candidate is None


@pytest.mark.parametrize("changes", [{"subject_id": "other-part"}, {"subject_kind": "process"}])
def test_unrelated_quote_cannot_price_selected_material(cost, changes):
    cost["prices"][0].update(changes)
    result = run(cost)
    assert result.known_build_subtotal == 0 and result.build_candidate is None
    assert "price_subject_mismatch" in {note.code for note in result.issues}


def test_two_quote_versions_of_one_nre_fee_do_not_double_the_subtotal(cost):
    cost["scope"]["nre_policy"] = "separate"
    cost["prices"].extend(
        [
            price(
                "tool-v1",
                basis="nre",
                unit="item",
                amount="100",
                subject_kind="nre",
                subject_id="tooling-fee",
            ),
            price(
                "tool-v2",
                basis="nre",
                unit="item",
                amount="150",
                subject_kind="nre",
                subject_id="tooling-fee",
            ),
        ]
    )
    cost["nre_price_ids"] = ["tool-v1", "tool-v2"]
    result = run(cost)
    assert result.known_nre_subtotal == 0 and result.nre_candidate is None
    assert "duplicate_nre_subject" in {note.code for note in result.issues}
    cost["basis"]["bom"]["ref"]["state"] = "current"
    cost["prices"][0]["ref"]["state"] = "withdrawn"
    assert run(cost).build_candidate is None
