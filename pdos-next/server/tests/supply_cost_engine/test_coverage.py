from copy import deepcopy
from decimal import Decimal
from random import Random

import pytest

from pdos_next.engines.supply_cost import CoverageRequest, calculate_coverage

from .helpers import bom_item, pool, ref


def run(payload):
    return calculate_coverage(CoverageRequest.model_validate(payload))


def reservation(identity="r", **changes):
    result = dict(
        reservation_id=identity,
        ref=ref(identity),
        pool=pool()["key"],
        build_id="build",
        bom_item_id="a",
        quantity="5",
        unit="ea",
    )
    result.update(changes)
    return result


def alternate(**changes):
    result = dict(
        qualification_id="q",
        ref=ref("q"),
        status="externally_verified",
        target_material_id="part",
        alternate_material_id="alternate",
        target_unit="ea",
        alternate_unit="ea",
        alternate_quantity_per_target="2",
        build_id="build",
        bom_sha256="a" * 64,
        configuration_sha256="a" * 64,
    )
    result.update(changes)
    return result


def test_unreserved_stock_is_a_candidate_and_duplicate_views_do_not_add_stock(coverage):
    coverage["basis"]["bom"]["items"].append(bom_item("b", critical=False))
    coverage["pools"] *= 3
    result = run(coverage)
    assert len(result.pools) == 1
    assert [row.demand.required_quantity for row in result.lines] == [Decimal(10), Decimal(10)]
    assert [row.known_potential_quantity for row in result.lines] == [Decimal(10), Decimal(0)]
    assert result.secured_ready is False and result.potential_ready is False
    assert result.critical_secured_ready is False


def test_own_and_other_build_reservations_reduce_shared_capacity_once(coverage):
    coverage["reservations"] = [reservation(), reservation("other", build_id="other", quantity="4")]
    coverage["reservations"].append(deepcopy(coverage["reservations"][0]))
    result = run(coverage)
    line = result.lines[0]
    assert result.pools[0].reserved_quantity == 9
    assert line.known_secured_quantity == 5
    assert line.known_potential_quantity == 6
    assert line.secured_gap == 5 and line.potential_gap == 4


def test_partial_actual_receipt_requires_released_quality_and_matching_reservation(coverage):
    coverage["pools"][0].update(stage="received", quantity="6")
    coverage["reservations"] = [reservation(quantity="6")]
    partial = run(coverage)
    assert partial.lines[0].secured_gap == 4
    coverage["pools"][0]["quantity"] = "10"
    coverage["reservations"][0]["quantity"] = "10"
    assert run(coverage).secured_ready is True


@pytest.mark.parametrize("stage", ["commitment", "in_transit"])
def test_promises_and_transit_never_count_as_arrival(coverage, stage):
    coverage["pools"][0].update(stage=stage, expected_at="2026-01-01T00:00:00Z")
    coverage["reservations"] = [reservation(quantity="10")]
    result = run(coverage)
    assert result.potential_ready is False
    assert result.lines[0].known_potential_quantity == 0
    assert result.lines[0].potential_gap == 10
    assert "not_actual_stock" in {note.code for note in result.pools[0].issues}


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("quality", "frozen", False),
        ("availability", "unavailable", False),
        ("quality", "unknown", None),
        ("availability", "unknown", None),
        ("quantity", None, None),
        ("unit", "box", None),
    ],
)
def test_unusable_and_unknown_are_distinct(coverage, field, value, expected):
    coverage["pools"][0][field] = value
    result = run(coverage)
    assert result.potential_ready is expected
    assert result.lines[0].known_potential_quantity == 0


def test_stale_snapshot_and_incomplete_reservation_scope_never_claim_full_stock(coverage):
    coverage["supply_scope_complete"] = False
    assert run(coverage).potential_ready is None
    coverage["supply_scope_complete"] = True
    coverage["pools"][0]["ref"]["valid_until"] = coverage["as_of"]
    assert run(coverage).potential_ready is None


def test_conflicting_physical_pool_versions_and_overreservation_are_excluded(coverage):
    duplicate = deepcopy(coverage["pools"][0])
    duplicate["quantity"] = "20"
    coverage["pools"].append(duplicate)
    assert run(coverage).potential_ready is None
    coverage["pools"].pop()
    coverage["reservations"] = [reservation(quantity="11")]
    result = run(coverage)
    assert result.potential_ready is None
    assert "pool_overreserved" in {note.code for note in result.issues}


@pytest.mark.parametrize(
    "changes", [{"quantity": None}, {"unit": "box"}, {"ref": ref("r", state="stale")}]
)
def test_unknown_active_reservation_prevents_free_capacity_claim(coverage, changes):
    coverage["reservations"] = [reservation(**changes)]
    assert run(coverage).potential_ready is None


def test_conflicting_reservation_cannot_hide_its_second_pool(coverage):
    second = pool("second")
    coverage["pools"].append(second)
    coverage["reservations"] = [reservation(), reservation(pool=second["key"])]
    result = run(coverage)
    assert all(row.unreserved_usable_quantity is None for row in result.pools)
    assert result.potential_ready is None


def test_mass_conversion_preserves_quantities_and_units(coverage):
    coverage["basis"]["bom"]["items"][0].update(unit="g", quantity_per_parent="100")
    coverage["pools"][0].update(unit="kg", quantity="0.5")
    result = run(coverage)
    assert result.lines[0].potential_gap == 0
    assert result.lines[0].uses[0].quantity_in_pool_unit == Decimal("0.5")
    assert result.lines[0].uses[0].quantity_in_demand_unit == 500


def test_verified_alternate_consumes_one_shared_pool_across_two_materials(coverage):
    stock = pool(quantity="20")
    stock["key"]["material_id"] = "alternate"
    coverage["pools"] = [stock]
    coverage["basis"]["bom"]["items"].append(bom_item("b", material_id="alternate", critical=False))
    coverage["alternates"] = [alternate()]
    result = run(coverage)
    assert result.lines[0].known_potential_quantity == 10
    assert result.lines[0].uses[0].qualification_id == "q"
    assert result.lines[1].known_potential_quantity == 0
    assert result.potential_ready is False


@pytest.mark.parametrize(
    "changes", [{"status": "unverified"}, {"build_id": "other"}, {"configuration_sha256": "b" * 64}]
)
def test_unverified_or_wrong_scope_alternate_cannot_cover_demand(coverage, changes):
    coverage["pools"][0]["key"]["material_id"] = "alternate"
    coverage["pools"][0]["quantity"] = "20"
    coverage["alternates"] = [alternate(**changes)]
    assert run(coverage).potential_ready is False


def test_unknown_demand_and_empty_bom_do_not_claim_ready(coverage):
    coverage["basis"]["bom"]["items"][0]["quantity_per_parent"] = None
    assert run(coverage).secured_ready is None
    coverage["basis"]["bom"]["items"] = []
    result = run(coverage)
    assert result.secured_ready is None and result.critical_secured_ready is None


def test_critical_priority_is_stable_under_input_order(coverage):
    coverage["basis"]["bom"]["items"] = [bom_item("z", critical=False), bom_item("a")]
    before = run(coverage)
    coverage["basis"]["bom"]["items"].reverse()
    after = run(coverage)
    assert before.lines == after.lines
    assert before.lines[0].demand.critical


def test_missing_reserved_pool_is_unknown_despite_claimed_complete_scope(coverage):
    coverage["pools"] = []
    coverage["reservations"] = [reservation(quantity="10")]
    result = run(coverage)
    assert result.lines[0].secured_gap is None
    assert result.lines[0].potential_gap is None


def test_conflicting_verified_alternate_ratios_are_not_chosen_arbitrarily(coverage):
    coverage["pools"][0]["key"]["material_id"] = "alternate"
    coverage["alternates"] = [
        alternate(),
        alternate(qualification_id="other", alternate_quantity_per_target="3"),
    ]
    result = run(coverage)
    assert result.potential_ready is None
    assert result.lines[0].known_potential_quantity == 0


def test_qualified_alternate_reservation_is_usable_and_still_deducted_from_free_stock(coverage):
    coverage["pools"][0]["key"]["material_id"] = "alternate"
    coverage["pools"][0]["quantity"] = "20"
    coverage["alternates"] = [alternate()]
    coverage["reservations"] = [reservation(pool=coverage["pools"][0]["key"], quantity="20")]
    result = run(coverage)
    assert result.secured_ready is True
    assert result.lines[0].known_secured_quantity == 10
    assert result.lines[0].uses[0].quantity_in_pool_unit == 20
    assert result.pools[0].unreserved_usable_quantity == 0


def test_pool_conservation_for_50_fixed_generated_cases(coverage):
    generator = Random(7301)
    for _ in range(50):
        count = generator.randint(1, 8)
        stock = generator.randint(0, 100)
        other_held = generator.randint(0, stock)
        coverage["basis"]["build"]["quantity"] = "1"
        quantities = [generator.randint(1, 30) for _ in range(count)]
        coverage["basis"]["bom"]["items"] = [
            bom_item(str(i), quantity_per_parent=str(q)) for i, q in enumerate(quantities)
        ]
        coverage["pools"] = [pool(quantity=str(stock))] * generator.randint(1, 4)
        coverage["reservations"] = [reservation(build_id="other", quantity=str(other_held))]
        result = run(coverage)
        consumed = sum(use.quantity_in_pool_unit for line in result.lines for use in line.uses)
        assert consumed <= stock - other_held
        assert sum(line.known_potential_quantity for line in result.lines) == min(
            sum(quantities), stock - other_held
        )
        assert result.potential_ready is (sum(quantities) <= stock - other_held)


def test_omitted_bom_branch_cannot_make_a_partial_kit_ready(coverage):
    coverage["basis"]["bom"]["items"].append(bom_item("b", supply_required=False))
    coverage["reservations"] = [reservation(quantity="10")]
    result = run(coverage)
    assert result.secured_ready is None and result.potential_ready is None
    assert result.lines[1].demand.required_quantity is None
    assert "uncovered_bom_path" in {note.code for note in result.issues}


def test_unselected_cycle_is_still_a_conflict_in_the_fixed_bom(coverage):
    coverage["basis"]["bom"]["items"].append(
        bom_item("b", parent_item_id="b", supply_required=False)
    )
    coverage["reservations"] = [reservation(quantity="10")]
    result = run(coverage)
    assert result.secured_ready is None
    assert "invalid_bom_hierarchy" in {note.code for note in result.issues}


def test_substitution_candidate_is_explicitly_not_a_feasibility_proof(coverage):
    # A->C and B->A is feasible, but primary-first selects A->A. The result must
    # describe the policy and must never advertise an optimal/unsatisfiable proof.
    coverage["basis"]["bom"]["items"] = [bom_item("a"), bom_item("b", material_id="B")]
    coverage["pools"] = [pool(quantity="10"), pool("C", quantity="10")]
    coverage["pools"][1]["key"]["material_id"] = "C"
    coverage["alternates"] = [
        alternate(alternate_material_id="C", alternate_quantity_per_target="1"),
        alternate(
            qualification_id="B-to-A",
            target_material_id="B",
            alternate_material_id="part",
            alternate_quantity_per_target="1",
        ),
    ]
    result = run(coverage)
    assert result.potential_ready is False
    assert result.potential_is_feasibility_proof is False
    assert result.candidate_policy == "critical-then-item-primary-then-alternate.v1"
