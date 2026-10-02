"""Current-source recovery eligibility; pure projections, no database access."""

from copy import deepcopy
from typing import Any

import pytest

from app.domain.material_coverage import CoverageSelection, calculate
from app.domain.material_exceptions import _assessment, closure_readiness
from tests.test_material_coverage import fixture


def recovery(*, full: bool = False) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    data, schedule = fixture()
    if full:
        data["allocations"][0]["remaining_quantity"] = "6"
        other = {
            **deepcopy(data["allocations"][0]),
            "id": "second",
            "bom_item_id": "b",
            "remaining_quantity": "4",
        }
        data["allocations"].append(other)
        data["pools"][0]["available_quantity"] = "0"
        data["pools"][0]["reserved_quantity"] = "10"
    coverage = calculate(data, schedule, CoverageSelection())
    assessment = _assessment(coverage, coverage["materials"][0]["material_key"])
    return data, schedule, assessment


def test_unallocated_known_inventory_and_partial_arrival_do_not_allow_closure() -> None:
    data, schedule, original = recovery()
    assert original["basis"]["material"]["observed_on_hand_gap"] == "0"
    latest = {"disposition": "supply_ready", "snapshot": original}
    assert not closure_readiness(original, latest)["ready"]
    data["allocations"][0]["remaining_quantity"] = "2"
    data["allocations"][0]["qualified_received_quantity"] = "3"
    current = calculate(data, schedule, CoverageSelection())
    assert not current["kit"]["ready"]
    assessment = _assessment(current, original["basis"]["material_key"])
    assert not closure_readiness(assessment, latest)["ready"]


def test_arrival_keeps_original_key_and_needs_new_named_recovery_review() -> None:
    _, _, original = recovery()
    _, _, restored = recovery(full=True)
    assert original["basis"]["material_key"] == restored["basis"]["material_key"]
    assert not closure_readiness(restored, {"disposition": "follow_up", "snapshot": original})[
        "ready"
    ]
    result = closure_readiness(restored, {"disposition": "supply_ready", "snapshot": restored})
    assert result["ready"] and result["review_current"]


@pytest.mark.parametrize(
    "state", ["quality_frozen", "stale", "source_changed", "current_source_unreadable"]
)
def test_changed_or_unusable_supply_invalidates_a_retained_ready_review(state: str) -> None:
    data, schedule, original = recovery(full=True)
    data["pools"][0]["state"] = state
    if state == "current_source_unreadable":
        data["pools"][0]["source"] = None
    coverage = calculate(data, schedule, CoverageSelection())
    current = _assessment(coverage, original["basis"]["material_key"])
    assert not coverage["kit"]["ready"]
    assert not closure_readiness(current, {"disposition": "supply_ready", "snapshot": original})[
        "ready"
    ]


def test_forecast_date_refresh_does_not_replace_supplier_source_review() -> None:
    data, schedule, original = recovery(full=True)
    schedule["times"]["baseline"]["local_start_date"] = "2020-01-06"
    coverage = calculate(data, schedule, CoverageSelection())
    current = _assessment(coverage, original["basis"]["material_key"])
    assert current["digest"] != original["digest"]
    result = closure_readiness(current, {"disposition": "supply_ready", "snapshot": original})
    assert result["ready"] and result["review_current"]


def test_scope_change_requires_an_actual_fixed_revision_and_named_scope_review() -> None:
    _, _, original = recovery(full=True)
    moved = deepcopy(original)
    moved["basis"]["material"] = None
    moved["basis"]["allocations"] = []
    assert not closure_readiness(moved, {"disposition": "supply_ready", "snapshot": original})[
        "ready"
    ]
    assert closure_readiness(moved, {"disposition": "scope_changed", "snapshot": moved})["ready"]
    moved["basis"]["revision_id"] = None
    assert not closure_readiness(moved, {"disposition": "scope_changed", "snapshot": moved})[
        "ready"
    ]
