"""Deterministic fixed-demand coverage; no database or external services."""

from copy import deepcopy
from decimal import Decimal, localcontext
from typing import Any

import pytest

from app.domain.material_coverage import CoverageSelection, calculate
from app.domain.material_exceptions import _assessment


def fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    lines = [
        dict(
            bom_item_id="a",
            material_reference="part",
            part_number="P",
            unit="个",
            required_quantity="6",
            critical=True,
        ),
        dict(
            bom_item_id="b",
            material_reference="part",
            part_number="P",
            unit="个",
            required_quantity="4",
            critical=False,
        ),
    ]
    source = dict(
        id="snapshot",
        source_system="ERP",
        external_pool_id="pool",
        external_item_id="part",
        unit="个",
        quantity="10",
        supply_kind="on_hand",
        quality_status="released",
        expected_date=None,
        lead_time_days=15,
    )
    allocation = dict(
        id="allocation",
        revision_id="revision",
        bom_item_id="a",
        source_system="ERP",
        external_pool_id="pool",
        external_item_id="part",
        remaining_quantity="5",
        qualified_received_quantity="0",
        received_lots=[],
    )
    data = dict(
        lines=lines,
        allocations=[allocation],
        revision=dict(id="revision", content_digest="d" * 64),
        build=dict(id="build", status="planned"),
        pools=[
            dict(
                source=source,
                pool_key=["ERP", "pool", "part"],
                state="current",
                available_quantity="5",
                reserved_quantity="5",
            )
        ],
        pool_limit_reached=False,
        as_of="2020-01-01T12:00:00+00:00",
    )
    schedule = dict(
        times=dict(baseline=dict(state="available", local_start_date="2020-01-05")),
        calendar=dict(today="2020-01-01", evidence=dict(timezone="UTC")),
    )
    return data, schedule


def test_shared_pool_is_counted_once_but_unallocated_stock_does_not_make_kit_ready() -> None:
    data, schedule = fixture()
    result = calculate(data, schedule, CoverageSelection())
    row = result["materials"][0]
    assert row["required"] == "10"
    assert row["observed_on_hand_gap"] == "0"
    assert row["allocated_on_hand_gap"] == "5"
    assert not result["kit"]["ready"]
    assert result["kit"]["critical_ready_count"] == 0
    assert result["kit"]["material_count"] == 1


def test_partial_qualified_arrival_updates_original_exception_basis_to_ready() -> None:
    data, schedule = fixture()
    selection = CoverageSelection()
    before = calculate(data, schedule, selection)
    key = before["materials"][0]["material_key"]
    original = _assessment(before, key)
    data["allocations"][0]["qualified_received_quantity"] = "5"
    data["pools"][0]["available_quantity"] = "0"
    after = calculate(data, schedule, selection)
    recovered = _assessment(after, key)
    assert after["kit"]["ready"]
    assert after["materials"][0]["allocated_on_hand_gap"] == "0"
    assert recovered["basis"]["material_key"] == original["basis"]["material_key"]
    assert recovered["digest"] != original["digest"]


@pytest.mark.parametrize("state", ["stale", "quality_frozen", "current_source_unreadable"])
def test_unusable_allocations_cannot_count_as_qualified_supply(state: str) -> None:
    data, schedule = fixture()
    data["allocations"][0]["remaining_quantity"] = "10"
    data["pools"][0]["state"] = state
    if state == "current_source_unreadable":
        data["pools"][0]["source"] = None
    result = calculate(data, schedule, CoverageSelection())
    assert not result["kit"]["ready"]
    assert result["materials"][0]["allocated_on_hand"] == "0"


def test_expected_same_day_and_overdue_supply_stay_out_of_ready_kit() -> None:
    data, schedule = fixture()
    source = data["pools"][0]["source"]
    source.update(supply_kind="expected_receipt", expected_date="2020-01-05")
    selection = CoverageSelection(expected_date_timezone_confirmed=True, date_basis="原件UTC")
    result = calculate(data, schedule, selection)
    assert result["materials"][0]["allocated_same_day"] == "5"
    assert result["materials"][0]["observed_before_date_gap"] is None
    assert not result["kit"]["ready"]
    source["expected_date"] = "2019-12-31"
    result = calculate(data, schedule, selection)
    assert result["materials"][0]["allocated_overdue"] == "5"
    assert not result["kit"]["ready"]


def test_unmapped_unit_conflict_and_empty_demand_never_claim_coverage() -> None:
    data, schedule = fixture()
    data["lines"][0]["material_reference"] = None
    data["pools"][0]["source"]["unit"] = "盒"
    data["pools"][0]["state"] = "unit_conflict"
    result = calculate(data, schedule, CoverageSelection())
    assert result["kit"]["material_count"] == 2
    assert not result["kit"]["ready"]
    data["lines"] = []
    result = calculate(data, schedule, CoverageSelection())
    assert not result["kit"]["ready"]
    assert result["kit"]["critical_ready"] is None


def test_decimal_context_cannot_change_fixed_quantity_or_basis_digest() -> None:
    data, schedule = fixture()
    data["lines"][0]["required_quantity"] = "1234567890123456.12345678"
    data["lines"][1]["required_quantity"] = "0.00000001"
    unchanged = deepcopy(data)
    with localcontext() as arithmetic:
        arithmetic.prec = 8
        low = calculate(data, schedule, CoverageSelection())
    with localcontext() as arithmetic:
        arithmetic.prec = 64
        high = calculate(data, schedule, CoverageSelection())
    assert low == high
    assert Decimal(low["materials"][0]["required"]) == Decimal("1234567890123456.12345679")
    assert data == unchanged
