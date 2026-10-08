from datetime import timedelta
from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError

from pdos_next.domain.supply_cost import (
    SupplyBusinessError,
    canonical_supply,
    cost_candidate,
    coverage_candidate,
    projection_freshness,
    reconcile,
)
from pdos_next.domain.supply_cost.rules import basis_binding, snapshot_freshness
from pdos_next.engines.supply_cost.common import digest
from pdos_next.engines.supply_cost.dto import (
    BomItem,
    ExchangeRate,
    ProcessOperation,
    ProcessSnapshot,
)
from pdos_next.schemas.supply_cost.dto import (
    CalculateCoveragePayload,
    Intent,
    QualityRestriction,
    ReceiptObservation,
    SupplyCommitment,
    SupplySnapshot,
    TransitObservation,
)

from .helpers import (
    AS_OF,
    SCOPE,
    alternate,
    bound_demand,
    pool,
    price,
    ref,
    reservation,
    supply,
)


def rejects(code, call):
    with pytest.raises(SupplyBusinessError) as error:
        call()
    assert error.value.code == code


@pytest.mark.parametrize("field", ["basis_sha256", "manufacturing_sha256"])
def test_demand_must_bind_exact_basis_and_manufacturing(bound, field):
    wrong = bound.model_copy(
        update={
            "demand": bound.demand.model_copy(update={field: "f" * 64}),
        }
    )
    rejects("DEMAND_BASIS_MISMATCH", lambda: basis_binding(wrong, AS_OF))


@pytest.mark.parametrize(
    "field,value",
    [
        ("required_quantity", Decimal("11")),
        ("critical", False),
        ("ancestry", ("other",)),
        ("unit", "kg"),
        ("material_id", "similar-material"),
    ],
)
def test_every_authoritative_demand_field_is_compared(bound, field, value):
    line = bound.demand.lines[0].model_copy(update={field: value})
    wrong = bound.model_copy(update={"demand": bound.demand.model_copy(update={"lines": (line,)})})
    rejects("DEMAND_EXPANSION_MISMATCH", lambda: basis_binding(wrong, AS_OF))


def test_demand_duplicates_and_omitted_lines_are_blocking(bound):
    for lines in ((), (bound.demand.lines[0], bound.demand.lines[0])):
        wrong = bound.model_copy(
            update={"demand": bound.demand.model_copy(update={"lines": lines})}
        )
        rejects("DEMAND_EXPANSION_MISMATCH", lambda wrong=wrong: basis_binding(wrong, AS_OF))


def test_original_read_set_requires_server_attestation_and_current_evidence(bound):
    rejects(
        "SOURCE_READ_SET_UNCONNECTED",
        lambda: basis_binding(bound.model_copy(update={"source_read_set_complete": False}), AS_OF),
    )
    rejects(
        "SOURCE_STALE",
        lambda: basis_binding(
            bound.model_copy(
                update={"source_read_set": (ref("original-evidence", state="withdrawn"),)}
            ),
            AS_OF,
        ),
    )


@pytest.mark.parametrize("state", ["unknown", "stale", "withdrawn"])
def test_fixed_source_state_never_becomes_ready(bound, state):
    wrong = bound.model_copy(
        update={
            "manufacturing_configuration": bound.manufacturing_configuration.model_copy(
                update={"state": state}
            ),
        }
    )
    rejects("SOURCE_STALE", lambda: basis_binding(wrong, AS_OF))


@pytest.mark.parametrize(
    "reference",
    [
        ref("manufacturing", valid_until=AS_OF),
        ref("manufacturing", captured_at=AS_OF + timedelta(seconds=1)),
    ],
)
def test_fixed_source_expiry_and_future_capture_block(bound, reference):
    wrong = bound.model_copy(update={"manufacturing_configuration": reference})
    rejects("SOURCE_STALE", lambda: basis_binding(wrong, AS_OF))


@pytest.mark.parametrize("field", ["tenant_id", "product_id", "project_id", "audience"])
def test_coverage_rejects_port_scope_drift(bound, snapshot, field):
    wrong = snapshot.model_copy(update={"scope": SCOPE.model_copy(update={field: "outside"})})
    rejects("FORBIDDEN_SCOPE", lambda: coverage_candidate(bound, wrong, (), AS_OF))


@pytest.mark.parametrize("field", ["build", "bom", "engineering_configuration", "demand"])
def test_coverage_rejects_fixed_version_drift(bound, snapshot, field):
    wrong = snapshot.model_copy(
        update={
            "binding": snapshot.binding.model_copy(update={field: ref(field, version="2")}),
        }
    )
    rejects("FIXED_INPUT_MISMATCH", lambda: coverage_candidate(bound, wrong, (), AS_OF))


def test_same_physical_pool_is_one_balance_even_when_repeated(bound, snapshot):
    repeated = snapshot.model_copy(update={"pools": (snapshot.pools[0], snapshot.pools[0])})
    result = coverage_candidate(bound, repeated, (), AS_OF)
    assert len(result.result.pools) == 1
    assert result.result.lines[0].known_potential_quantity == Decimal("10")
    assert result.supply_sha256 == digest(canonical_supply(snapshot))


@pytest.mark.parametrize("field", ["pools", "reservations", "commitments", "receipts"])
def test_conflicting_stable_record_identifiers_block(snapshot, field):
    key = snapshot.pools[0].key
    row = {
        "pools": snapshot.pools[0],
        "reservations": reservation(key),
        "commitments": SupplyCommitment(
            record_id="promise",
            ref=ref("promise"),
            supplier_id="supplier",
            material_id="material",
            quantity="10",
            unit="ea",
            note="Supplier promise",
        ),
        "receipts": ReceiptObservation(
            record_id="receipt",
            ref=ref("receipt"),
            pool=key,
            quantity="5",
            unit="ea",
            note="Partial receipt",
            received_at=AS_OF - timedelta(hours=1),
        ),
    }[field]
    wrong = snapshot.model_copy(
        update={
            field: (row, row.model_copy(update={"quantity": Decimal("99")})),
        }
    )
    rejects("CONFLICTING_SNAPSHOT", lambda: canonical_supply(wrong))


def test_snapshot_duplicate_is_replay_but_reused_id_is_conflict(snapshot):
    duplicate = reconcile(snapshot, snapshot)
    assert duplicate.duplicate and duplicate.deltas == ()
    assert duplicate.previous_sha256 == duplicate.current_sha256
    rejects(
        "SNAPSHOT_ID_CONFLICT",
        lambda: reconcile(snapshot, snapshot.model_copy(update={"note": "different observation"})),
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"previous_snapshot_id": "other"},
        {"previous_revision": 9},
        {"revision": 3},
    ],
)
def test_snapshot_previous_pointer_and_sequence_are_optimistic_guards(snapshot, updates):
    next_snapshot = snapshot.model_copy(
        update={
            "snapshot_id": "supply-2",
            "revision": 2,
            "previous_snapshot_id": snapshot.snapshot_id,
            "previous_revision": snapshot.revision,
            "ref": ref("supply-2", captured_at=AS_OF - timedelta(minutes=30)),
            **updates,
        }
    )
    rejects("SNAPSHOT_VERSION_CONFLICT", lambda: reconcile(snapshot, next_snapshot))


def test_new_snapshot_must_be_later_and_first_starts_at_one(snapshot):
    wrong = snapshot.model_copy(
        update={
            "snapshot_id": "supply-2",
            "revision": 2,
            "previous_snapshot_id": snapshot.snapshot_id,
            "previous_revision": 1,
            "ref": ref("supply-2", captured_at=snapshot.ref.captured_at),
        }
    )
    rejects("SNAPSHOT_OUT_OF_ORDER", lambda: reconcile(snapshot, wrong))
    rejects(
        "SNAPSHOT_VERSION_CONFLICT",
        lambda: reconcile(None, snapshot.model_copy(update={"revision": 2})),
    )


def test_reconciliation_preserves_previous_values_and_source_delta(snapshot):
    old_hash = digest(snapshot)
    current = snapshot.model_copy(
        update={
            "snapshot_id": "supply-2",
            "revision": 2,
            "previous_snapshot_id": snapshot.snapshot_id,
            "previous_revision": 1,
            "ref": ref("supply-2", captured_at=AS_OF - timedelta(minutes=30)),
            "pools": (pool(quantity="5"),),
        }
    )
    result = reconcile(snapshot, current)
    quantity_delta = next(delta for delta in result.deltas if delta.entity == "pools")
    assert quantity_delta.before["quantity"] == "10"
    assert quantity_delta.after["quantity"] == "5"
    assert any(delta.entity == "snapshot" and delta.identity == "source" for delta in result.deltas)
    assert digest(snapshot) == old_hash
    assert result.previous == snapshot


def test_partial_receipt_promise_and_transit_are_separate_not_additive(bound):
    actual = pool(quantity="5")
    snapshot = supply(
        bound,
        pools=(actual,),
        commitments=(
            SupplyCommitment(
                record_id="promise",
                ref=ref("promise"),
                supplier_id="supplier",
                material_id="material",
                quantity="10",
                unit="ea",
                expected_at=AS_OF - timedelta(days=1),
                note="Overdue promise",
            ),
        ),
        in_transit=(
            TransitObservation(
                record_id="transit",
                ref=ref("transit"),
                commitment_id="promise",
                pool=actual.key,
                quantity="5",
                unit="ea",
                note="Remaining half is on the way",
            ),
        ),
        receipts=(
            ReceiptObservation(
                record_id="receipt",
                ref=ref("receipt"),
                commitment_id="promise",
                pool=actual.key,
                quantity="5",
                unit="ea",
                received_at=AS_OF - timedelta(hours=1),
                note="Half received",
            ),
        ),
    )
    result = coverage_candidate(bound, snapshot, (), AS_OF).result
    assert result.lines[0].known_potential_quantity == Decimal("5")
    assert result.lines[0].potential_gap == Decimal("5")
    assert result.lines[0].known_secured_quantity == 0
    assert result.potential_ready is False


def test_frozen_quality_cannot_supply_even_with_balance(bound):
    frozen = pool(quality="frozen", availability="unavailable")
    restriction = QualityRestriction(
        record_id="hold",
        ref=ref("hold"),
        pool=frozen.key,
        quality="frozen",
        availability="unavailable",
        affected_quantity="10",
        unit="ea",
        note="Inspection hold",
    )
    result = coverage_candidate(
        bound, supply(bound, pools=(frozen,), restrictions=(restriction,)), (), AS_OF
    )
    assert result.result.lines[0].known_potential_quantity == 0
    assert result.result.lines[0].potential_gap == 10
    assert any(note.code == "quality_frozen" for note in result.result.issues)


def test_quality_restriction_cannot_disagree_with_pool_partition(snapshot):
    restriction = QualityRestriction(
        record_id="hold",
        ref=ref("hold"),
        pool=snapshot.pools[0].key,
        quality="frozen",
        availability="unavailable",
        affected_quantity="5",
        unit="ea",
        note="Partition unresolved",
    )
    rejects(
        "QUALITY_PROJECTION_CONFLICT",
        lambda: canonical_supply(snapshot.model_copy(update={"restrictions": (restriction,)})),
    )


def test_active_restriction_needs_exact_authoritative_partition(bound):
    frozen = pool(quality="frozen", availability="unavailable")
    restriction = QualityRestriction(
        record_id="hold",
        ref=ref("hold"),
        pool=frozen.key,
        quality="frozen",
        availability="unavailable",
        affected_quantity="5",
        unit="ea",
        note="Half held",
    )
    rejects(
        "QUALITY_PROJECTION_CONFLICT",
        lambda: canonical_supply(supply(bound, pools=(frozen,), restrictions=(restriction,))),
    )


def test_stale_quality_evidence_blocks_coverage_despite_released_balance(bound):
    released = pool()
    restriction = QualityRestriction(
        record_id="release",
        ref=ref("release", state="withdrawn"),
        pool=released.key,
        quality="released",
        availability="available",
        affected_quantity="10",
        unit="ea",
        note="Release evidence withdrawn",
    )
    rejects(
        "SOURCE_STALE",
        lambda: coverage_candidate(
            bound, supply(bound, pools=(released,), restrictions=(restriction,)), (), AS_OF
        ),
    )


def test_other_build_occupancy_subtracts_from_shared_pool(bound, snapshot):
    key = snapshot.pools[0].key
    snapshot = snapshot.model_copy(
        update={
            "reservations": (
                reservation(key),
                reservation(key, identity="other", build_id="other-build", quantity="3"),
            )
        }
    )
    result = coverage_candidate(bound, snapshot, (), AS_OF).result
    line = result.lines[0]
    assert line.known_secured_quantity == 4
    assert line.known_potential_quantity == 7
    assert line.secured_gap == 6 and line.potential_gap == 3
    assert result.pools[0].reserved_quantity == 7
    assert sum(use.quantity_in_pool_unit for use in line.uses) == 7


@pytest.mark.parametrize(
    "qualification",
    [
        alternate(status="unverified"),
        alternate(build_id="another-build"),
        alternate(bom_sha256="f" * 64),
        alternate(configuration_sha256="f" * 64),
    ],
)
def test_alternate_is_accepted_only_from_exact_verified_server_port(bound, snapshot, qualification):
    rejects(
        "QUALIFICATION_PORT_REJECTED",
        lambda: coverage_candidate(bound, snapshot, (qualification,), AS_OF),
    )


def test_missing_quote_is_unknown_not_zero(bound, costs):
    incomplete = costs.model_copy(update={"prices": ()})
    result = cost_candidate(bound, incomplete, AS_OF).result
    assert result.complete_in_selected_scope is False
    assert result.build_candidate is None and result.per_product_candidate is None
    assert result.lines[0].build_candidate is None
    assert result.known_build_subtotal == Decimal("0")
    assert result.lines[0].issues


def test_decimal_candidate_is_unrounded_and_caller_context_independent(bound, costs):
    with localcontext() as context:
        context.prec = 2
        result = cost_candidate(
            bound, costs.model_copy(update={"prices": (price(amount="0.12345678"),)}), AS_OF
        )
    assert result.result.build_candidate == Decimal("1.23456780")
    assert result.result.per_product_candidate == Decimal("0.24691356")
    assert result.result.currency == "USD"
    assert result.binding == basis_binding(bound, AS_OF)


def test_cost_scope_and_fixed_manufacturing_binding_are_required(bound, costs):
    outside = costs.model_copy(update={"scope": SCOPE.model_copy(update={"project_id": "outside"})})
    rejects("FORBIDDEN_SCOPE", lambda: cost_candidate(bound, outside, AS_OF))
    wrong = costs.model_copy(
        update={
            "binding": costs.binding.model_copy(
                update={
                    "manufacturing_configuration": ref("manufacturing", version="2"),
                }
            )
        }
    )
    rejects("FIXED_INPUT_MISMATCH", lambda: cost_candidate(bound, wrong, AS_OF))


def test_selected_process_scope_without_process_is_explicitly_incomplete(bound, costs):
    inputs = costs.model_copy(
        update={
            "cost_scope": costs.cost_scope.model_copy(update={"coverage": "materials_and_process"}),
        }
    )
    result = cost_candidate(bound, inputs, AS_OF).result
    assert result.complete_in_selected_scope is False and result.build_candidate is None
    assert result.known_build_subtotal == 1
    assert any(note.code == "process_missing" for note in result.issues)


def test_process_cost_mapping_must_cover_exact_fixed_operation_ids(bound, costs):
    process = ProcessSnapshot(
        ref=ref("process"),
        assumption="Explicit manufacturing quantities per good product",
        operations=(
            ProcessOperation(
                operation_id="op-a",
                quantity_per_product="1",
                unit="ea",
                loss_rate="0",
                price_id=None,
            ),
        ),
    )
    inputs = costs.model_copy(update={"process": process})
    rejects("PROCESS_MAPPING_UNCONNECTED", lambda: cost_candidate(bound, inputs, AS_OF))
    for keys in ((), ("op-b",), ("op-a", "op-a"), ("op-a", "op-b")):
        rejects(
            "PROCESS_MAPPING_MISMATCH",
            lambda keys=keys: cost_candidate(
                bound.model_copy(update={"manufacturing_operation_ids": keys}), inputs, AS_OF
            ),
        )
    result = cost_candidate(
        bound.model_copy(update={"manufacturing_operation_ids": ("op-a",)}), inputs, AS_OF
    )
    assert result.result.input_snapshot.process == process


def test_source_change_marks_projection_for_recalculation_without_rewriting(bound, snapshot):
    projection = coverage_candidate(bound, snapshot, (), AS_OF)
    old_hash = digest(projection)
    changed = snapshot.model_copy(update={"ref": ref("supply-1", version="2")})
    status = projection_freshness(projection, bound, AS_OF, supply=changed)
    assert status.state == "requires_recalculation"
    assert "supply_snapshot_changed" in status.reasons
    assert digest(projection) == old_hash
    assert (
        projection_freshness(projection, bound, AS_OF, supply=changed, historical=True).state
        == "historical"
    )


def test_changed_fixed_build_and_missing_supply_are_explicit(bound, snapshot):
    projection = coverage_candidate(bound, snapshot, (), AS_OF)
    current = bound_demand(quantity="6")
    status = projection_freshness(projection, current, AS_OF)
    assert set(status.reasons) == {"fixed_basis_changed", "current_supply_unconnected"}


def test_original_read_set_version_change_requires_projection_recalculation(bound, snapshot):
    projection = coverage_candidate(bound, snapshot, (), AS_OF)
    current = bound.model_copy(update={"source_read_set": (ref("original-evidence", version="2"),)})
    status = projection_freshness(projection, current, AS_OF, supply=snapshot)
    assert "fixed_basis_changed" in status.reasons


def test_snapshot_supersession_and_historical_label_keep_saved_input_immutable(bound, snapshot):
    original_hash = digest(snapshot)
    current = snapshot.model_copy(
        update={
            "snapshot_id": "supply-2",
            "revision": 2,
            "previous_snapshot_id": snapshot.snapshot_id,
            "previous_revision": 1,
            "ref": ref("supply-2", captured_at=AS_OF - timedelta(minutes=30)),
        }
    )
    status = snapshot_freshness(snapshot, bound, AS_OF, current_snapshot=current)
    assert status.state == "requires_recalculation"
    assert status.reasons == ("supply_snapshot_superseded",)
    historical = snapshot_freshness(
        snapshot, bound, AS_OF, current_snapshot=current, historical=True
    )
    assert historical.state == "historical" and historical.reasons == status.reasons
    assert digest(snapshot) == original_hash
    assert snapshot_freshness(snapshot, bound, AS_OF, current_snapshot=None).reasons == (
        "current_supply_unconnected",
    )


@pytest.mark.parametrize("source", ["snapshot", "pool", "reservation", "quality"])
def test_snapshot_input_expiry_is_rechecked_for_each_current_material_evidence(
    bound, snapshot, source
):
    expires = AS_OF + timedelta(seconds=1)
    if source == "snapshot":
        snapshot = snapshot.model_copy(update={"ref": ref("supply-1", valid_until=expires)})
    elif source == "pool":
        snapshot = snapshot.model_copy(
            update={
                "pools": (
                    snapshot.pools[0].model_copy(
                        update={"ref": ref("pool:lot", valid_until=expires)}
                    ),
                )
            }
        )
    elif source == "reservation":
        held = reservation(snapshot.pools[0].key).model_copy(
            update={
                "ref": ref("reservation:own", valid_until=expires),
            }
        )
        snapshot = snapshot.model_copy(update={"reservations": (held,)})
    else:
        release = QualityRestriction(
            record_id="release",
            ref=ref("release", valid_until=expires),
            pool=snapshot.pools[0].key,
            quality="released",
            availability="available",
            affected_quantity="10",
            unit="ea",
            note="Current inspection release",
        )
        snapshot = snapshot.model_copy(update={"restrictions": (release,)})
    assert snapshot_freshness(snapshot, bound, AS_OF, current_snapshot=snapshot).state == "current"
    status = snapshot_freshness(snapshot, bound, expires, current_snapshot=snapshot)
    assert status.state == "requires_recalculation"
    assert status.reasons == ("source_expired_or_unavailable",)


def test_qualification_must_be_rechecked_when_reading_alternate_projection(bound, snapshot):
    verified = alternate(bound)
    projection = coverage_candidate(bound, snapshot, (verified,), AS_OF)
    status = projection_freshness(projection, bound, AS_OF, supply=snapshot)
    assert "qualification_recheck_unconnected" in status.reasons
    changed = projection_freshness(projection, bound, AS_OF, supply=snapshot, alternates=())
    assert "qualification_changed" in changed.reasons
    assert (
        projection_freshness(
            projection, bound, AS_OF, supply=snapshot, alternates=(verified,)
        ).state
        == "current"
    )


def test_cost_freshness_checks_aggregate_and_quote_expiry(bound, costs):
    inputs = costs.model_copy(update={"prices": (price(valid_until=AS_OF + timedelta(minutes=5)),)})
    projection = cost_candidate(bound, inputs, AS_OF)
    later = AS_OF + timedelta(minutes=6)
    status = projection_freshness(projection, bound, later, cost=inputs)
    assert "quote_validity_changed" in status.reasons
    withdrawn = inputs.model_copy(update={"ref": ref("cost-1", state="withdrawn")})
    status = projection_freshness(projection, bound, AS_OF, cost=withdrawn)
    assert {"cost_inputs_changed", "cost_source_unavailable"} <= set(status.reasons)


def test_cost_rate_age_is_rechecked_at_read_time(bound, costs):
    rate = ExchangeRate(
        rate_id="rate",
        ref=ref("rate", captured_at=AS_OF - timedelta(days=7)),
        from_currency="EUR",
        to_currency="USD",
        rate="1.2",
        purpose="budget",
    )
    inputs = costs.model_copy(update={"prices": (price(currency="EUR"),), "rates": (rate,)})
    projection = cost_candidate(bound, inputs, AS_OF)
    assert projection.result.complete_in_selected_scope
    status = projection_freshness(projection, bound, AS_OF + timedelta(seconds=1), cost=inputs)
    assert "rate_age_limit_exceeded" in status.reasons


@pytest.mark.parametrize(
    "field,value",
    [
        ("scope", SCOPE.model_dump()),
        ("alternates", []),
        ("externally_verified", True),
    ],
)
def test_payload_cannot_claim_authority(field, value):
    with pytest.raises(ValidationError):
        CalculateCoveragePayload.model_validate(
            {
                "build_id": "build",
                "expected_build_revision": 1,
                "supply_snapshot_id": "supply-1",
                "expected_supply_revision": 1,
                field: value,
            }
        )


def test_snapshot_rejects_unpaired_previous_and_binary_float(snapshot):
    for updates in (
        {"previous_snapshot_id": "old"},
        {
            "pools": [
                {
                    **snapshot.pools[0].model_dump(mode="python"),
                    "quantity": 1.5,
                }
            ]
        },
    ):
        with pytest.raises(ValidationError):
            SupplySnapshot.model_validate({**snapshot.model_dump(mode="python"), **updates})


def test_operation_and_payload_cannot_be_mixed():
    with pytest.raises(ValidationError):
        Intent(
            command_id="command",
            idempotency_key="idempotency-key",
            operation="supply.cost.estimate",
            payload=CalculateCoveragePayload(
                build_id="build",
                expected_build_revision=1,
                supply_snapshot_id="supply-1",
                expected_supply_revision=1,
            ),
        )


def test_demand_order_is_not_greedy_coverage_order():
    bound = bound_demand(
        items=(
            BomItem(
                item_id="a",
                material_id="material",
                quantity_per_parent="1",
                unit="ea",
                loss_rate="0",
                supply_required=True,
                critical=False,
            ),
            BomItem(
                item_id="z",
                material_id="material",
                quantity_per_parent="1",
                unit="ea",
                loss_rate="0",
                supply_required=True,
                critical=True,
            ),
        )
    )
    reordered = bound.model_copy(
        update={
            "demand": bound.demand.model_copy(
                update={
                    "lines": tuple(reversed(bound.demand.lines)),
                }
            )
        }
    )
    result = coverage_candidate(reordered, supply(bound), (), AS_OF)
    assert [line.demand.item_id for line in result.result.lines] == ["z", "a"]
    assert result.result.potential_ready is True
