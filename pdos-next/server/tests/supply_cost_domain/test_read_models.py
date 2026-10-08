from datetime import timedelta
from decimal import Decimal

import pytest

from pdos_next.domain.supply_cost import (
    SupplyBusinessError,
    cost_candidate,
    coverage_candidate,
    reconcile,
)
from pdos_next.domain.supply_cost.read_models import (
    binding_view,
    projection_view,
    reconciliation_view,
    snapshot_view,
)
from pdos_next.engines.supply_cost.common import digest
from pdos_next.schemas.supply_cost.dto import Freshness, SupplyCommitment

from .helpers import AS_OF, bound_demand, ref

HISTORICAL = Freshness(state="historical", reasons=("source_changed",))


def test_history_view_requires_original_build_basis(bound, snapshot):
    with pytest.raises(SupplyBusinessError) as error:
        snapshot_view(snapshot, bound_demand(quantity="6").basis, HISTORICAL)
    assert error.value.code == "FIXED_INPUT_MISMATCH"
    assert binding_view(snapshot.binding, bound.basis)["basis"]["build"]["quantity"] == "5"


def test_snapshot_view_preserves_unknown_promise_and_distinguishes_current_pool(bound, snapshot):
    promise = SupplyCommitment(
        record_id="promise",
        ref=ref("promise"),
        supplier_id="supplier",
        material_id="material",
        quantity=None,
        unit=None,
        note="Quantity is still unknown",
    )
    snapshot = snapshot.model_copy(
        update={
            "commitments": (promise,),
            "pools": (snapshot.pools[0].model_copy(update={"stage": "on_hand"}),),
        }
    )
    view = snapshot_view(snapshot, bound.basis, HISTORICAL)
    assert view["freshness"] == "historical" and view["freshness_reasons"] == ["source_changed"]
    assert view["records"][0]["record_kind"] == "commitment"
    assert view["records"][0]["quantity"] is None and view["records"][0]["unit"] is None
    assert view["pools"][0]["quantity"] == "10"
    inventory = next(row for row in view["records"] if row["record_kind"] == "inventory")
    assert inventory["quantity"] == "10"
    assert inventory["pool_id"] == snapshot.pools[0].key.pool_id
    assert view["sha256"] == digest(snapshot)
    assert any(source["source_id"] == "original-evidence" for source in view["source_refs"])


def test_reconciliation_display_keeps_values_without_cross_unit_subtraction(bound, snapshot):
    current = snapshot.model_copy(
        update={
            "snapshot_id": "supply-2",
            "revision": 2,
            "previous_snapshot_id": snapshot.snapshot_id,
            "previous_revision": 1,
            "ref": ref("supply-2", captured_at=AS_OF - timedelta(minutes=30)),
            "pools": (
                snapshot.pools[0].model_copy(update={"quantity": Decimal("5"), "unit": "kg"}),
            ),
        }
    )
    reconciled = reconcile(snapshot, current)
    view = reconciliation_view(reconciled)
    quantity = next(delta for delta in view["deltas"] if delta["field"] == "来源数量")
    assert quantity["before"] == "10" and quantity["after"] == "5"
    assert all(delta["difference"] is None for delta in view["deltas"])
    assert view["before_sha256"] == digest(snapshot) and view["after_sha256"] == digest(current)
    assert snapshot_view(current, bound.basis, HISTORICAL, reconciled)["reconciliation"] == view


def test_reconciliation_cannot_be_attached_to_different_snapshot(bound, snapshot):
    current = snapshot.model_copy(
        update={
            "snapshot_id": "supply-2",
            "revision": 2,
            "previous_snapshot_id": snapshot.snapshot_id,
            "previous_revision": 1,
            "ref": ref("supply-2", captured_at=AS_OF - timedelta(minutes=30)),
        }
    )
    with pytest.raises(SupplyBusinessError) as error:
        snapshot_view(snapshot, bound.basis, HISTORICAL, reconcile(snapshot, current))
    assert error.value.code == "SNAPSHOT_VERSION_CONFLICT"
    assert reconciliation_view(reconcile(None, snapshot)) is None


@pytest.mark.parametrize("kind", ["coverage", "cost"])
def test_projection_display_preserves_exact_calculation_snapshot_and_unknowns(
    bound, snapshot, costs, kind
):
    projection = (
        coverage_candidate(bound, snapshot, (), AS_OF)
        if kind == "coverage"
        else cost_candidate(bound, costs.model_copy(update={"prices": ()}), AS_OF)
    )
    view = projection_view(
        projection, record_id="saved", revision=1, created_at=AS_OF, freshness=HISTORICAL
    )
    assert view["result"] == projection.result.model_dump(mode="json")
    assert view["id"] == "saved" and view["revision"] == "1"
    assert view["freshness"] == "historical"
    if kind == "cost":
        assert view["result"]["build_candidate"] is None
        assert view["result"]["lines"][0]["build_candidate"] is None
