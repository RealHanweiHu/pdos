from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import UUID, uuid4

import pytest

from pdos_next.domain.resource_readiness.handlers import ResourceError
from pdos_next.schemas.resource_readiness.contracts import MaintenanceFact, ResourceUse

from .support import NOW, SyntheticHost, context, request, snapshot, source, staged, window


def test_preview_is_read_only_and_stage_is_not_committed_receipt():
    req = request()
    host = SyntheticHost(req)
    preview = host.handler.preview(req)
    assert preview.allowed and not host.records and not host.confirmed and not host.lock_orders
    with host.uow():
        result = host.handler.stage_formal(req, preview)
        assert result.disposition == "staged_in_caller_uow"
        assert result.reservation.state == "formal"
        assert not host.receipts
    assert not hasattr(result.reservation, "actual_start")


def test_same_semantic_run_key_alias_is_idempotent_and_changes_conflict():
    req = request()
    host = SyntheticHost(req)
    preview = host.handler.preview(req)
    with host.uow():
        host.handler.stage_formal(req, preview)
    alias = req.model_copy(update={"intent_key": "changed-command-key"})
    alias_preview = host.handler.preview(alias, expected_revision=1)
    with host.uow():
        replay = host.handler.stage_formal(alias, alias_preview, expected_revision=1)
    assert replay.replayed and len(host.records) == len(host.confirmed) == 1
    for changed in (
        req.model_copy(update={"purpose": "other"}),
        req.model_copy(update={"reservation_id": uuid4()}),
    ):
        with pytest.raises(ResourceError, match="another payload"):
            host.handler.preview(changed)


def test_key_or_record_id_attached_to_different_run_conflicts():
    req = request()
    host = SyntheticHost(req)
    staged(host, req)
    other = request()
    host.contexts[other.owner_run_id] = context(other)
    with pytest.raises(ResourceError) as error:
        host.handler.preview(other)
    assert error.value.code == "identity_conflict"


def test_tentative_unknown_records_do_not_occupy_then_formal_promotes_once():
    req = request()
    host = SyntheticHost(req)
    rid = req.uses[0].resource.id
    original = host.snapshots[rid]
    host.snapshots[rid] = original.model_copy(update={"facts": ()})
    preview = host.handler.preview(req, target_state="tentative")
    assert preview.report.status == "UNKNOWN" and preview.allowed
    with host.uow():
        host.handler.stage_tentative(req, preview)
    assert not host.occupancies(host.contexts[req.owner_run_id], (rid,))
    current = host.snapshots[rid]
    host.snapshots[rid] = current.model_copy(update={"facts": original.facts})
    preview = host.handler.preview(req, expected_revision=1)
    with host.uow():
        formal = host.handler.stage_formal(req, preview, expected_revision=1)
    assert [e.kind for e in formal.reservation.events] == ["tentative", "formal"]
    assert len(host.occupancies(host.contexts[req.owner_run_id], (rid,))) == 1


def test_tentative_can_record_missing_resource_but_formal_cannot():
    req = request()
    host = SyntheticHost(req)
    host.snapshots.clear()
    preview = host.handler.preview(req, target_state="tentative")
    with host.uow():
        value = host.handler.stage_tentative(req, preview)
    assert value.reservation.fixed_resources == ()
    assert not host.handler.preview(req, expected_revision=1).allowed


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("authorized", False, "authority_forbidden"),
        ("qualified", False, "qualification_required"),
        ("qualified", None, "qualification_required"),
        ("policy_registered", False, "policy_unavailable"),
        ("cancelled", True, "run_cancelled"),
        ("sources_current", False, "sources_stale"),
    ],
)
def test_current_authority_and_policy_revocation_rejects_staging(field, value, reason):
    req = request()
    host = SyntheticHost(req)
    preview = host.handler.preview(req)
    ctx = host.contexts[req.owner_run_id]
    host.contexts[req.owner_run_id] = ctx.model_copy(update={field: value})
    with pytest.raises(ResourceError) as error, host.uow():
        host.handler.stage_formal(req, preview)
    assert error.value.code == reason
    assert not host.records and not host.confirmed


@pytest.mark.parametrize(
    "status,expected",
    [
        ("missing", "UNKNOWN"),
        ("withdrawn", "BLOCKED"),
        ("drifted", "BLOCKED"),
    ],
)
def test_source_missing_withdrawal_and_drift_preserved(status, expected):
    req = request()
    host = SyntheticHost(req)
    ref = host.snapshots[req.uses[0].resource.id].facts[0].source
    host.sources[ref.id] = status
    preview = host.handler.preview(req)
    assert preview.report.status == expected and not preview.allowed


def test_source_withdrawn_after_preview_prevents_staging():
    req = request()
    host = SyntheticHost(req)
    preview = host.handler.preview(req)
    host.sources[source(20).id] = "withdrawn"
    with pytest.raises(ResourceError) as error, host.uow():
        host.handler.stage_formal(req, preview)
    assert error.value.code == "readset_changed"
    assert not host.confirmed


@pytest.mark.parametrize("change", ["version", "calendar", "authority_epoch", "occupancy_epoch"])
def test_fixed_readset_drift_rejects(change):
    req = request()
    host = SyntheticHost(req)
    preview = host.handler.preview(req)
    rid = req.uses[0].resource.id
    snap = host.snapshots[rid]
    if change == "version":
        host.snapshots[rid] = snap.model_copy(
            update={"ref": snap.ref.model_copy(update={"revision": 2})}
        )
    elif change == "calendar":
        host.snapshots[rid] = snap.model_copy(
            update={"calendar": snap.calendar.model_copy(update={"version": "2"})}
        )
    elif change == "authority_epoch":
        host.contexts[req.owner_run_id] = host.contexts[req.owner_run_id].model_copy(
            update={"facts_revision": "authority-2"}
        )
    else:
        host.snapshots[rid] = snap.model_copy(update={"occupancy_revision": 2})
    with pytest.raises(ResourceError) as error, host.uow():
        host.handler.stage_formal(req, preview)
    assert error.value.code == "readset_changed"
    assert not host.records


def test_unchanged_material_survives_five_minutes_but_backdated_new_reservation_fails():
    req = request()
    host = SyntheticHost(req)
    preview = host.handler.preview(req)
    host.contexts[req.owner_run_id] = host.contexts[req.owner_run_id].model_copy(
        update={"now": NOW + timedelta(minutes=5)}
    )
    with host.uow():
        host.handler.stage_formal(req, preview)
    assert host.records[req.reservation_id].state == "formal"
    host.contexts[req.owner_run_id] = host.contexts[req.owner_run_id].model_copy(
        update={"now": req.window.start + timedelta(seconds=1)}
    )
    assert not host.handler.preview(req).allowed


def test_payload_preview_mismatch_and_revision_conflict():
    req = request()
    host = SyntheticHost(req)
    preview = host.handler.preview(req)
    with pytest.raises(ResourceError) as error, host.uow():
        host.handler.stage_formal(req, preview.model_copy(update={"target_state": "tentative"}))
    assert error.value.code == "preview_mismatch"
    # CAS expected version is bound even for a first insert.
    preview = host.handler.preview(req, expected_revision=1)
    with pytest.raises(ResourceError) as error, host.uow():
        host.handler.stage_formal(req, preview, expected_revision=1)
    assert error.value.code == "version_conflict"


@pytest.mark.parametrize("state", ["released", "cancelled"])
def test_release_and_cancel_preserve_history_and_free_capacity(state):
    req = request()
    host = SyntheticHost(req)
    original = staged(host, req).reservation
    preview = host.handler.preview(
        req, expected_revision=1, target_state=state, reason="run changed"
    )
    with host.uow():
        result = host.handler.stage_terminal(req, preview, expected_revision=1)
    assert [e.kind for e in result.reservation.events] == ["formal", state]
    assert result.reservation.fixed_resources == original.fixed_resources
    assert not host.occupancies(host.contexts[req.owner_run_id], (req.uses[0].resource.id,))
    with host.uow():
        replay = host.handler.stage_terminal(req, preview, expected_revision=1)
    assert replay.replayed and len(host.confirmed) == 2
    with pytest.raises(ResourceError) as error, host.uow():
        host.handler.stage_formal(req, host.handler.preview(req, expected_revision=2), 2)
    assert error.value.code == "terminal_reservation"


def test_release_requires_reason_and_never_changes_reason_on_replay():
    req = request()
    host = SyntheticHost(req)
    staged(host, req)
    assert not host.handler.preview(req, expected_revision=1, target_state="released").allowed
    preview = host.handler.preview(req, expected_revision=1, target_state="released", reason="done")
    with host.uow():
        host.handler.stage_terminal(req, preview, 1)
    with pytest.raises(ResourceError), host.uow():
        host.handler.stage_terminal(req, preview.model_copy(update={"reason": "changed"}), 1)


def test_release_allowed_after_owner_cancelled_without_regranting_qualification():
    req = request()
    host = SyntheticHost(req)
    staged(host, req)
    host.contexts[req.owner_run_id] = host.contexts[req.owner_run_id].model_copy(
        update={"cancelled": True}
    )
    preview = host.handler.preview(
        req, expected_revision=1, target_state="cancelled", reason="stop"
    )
    assert preview.allowed
    with host.uow():
        host.handler.stage_terminal(req, preview, 1)


def test_formal_cannot_downgrade_to_tentative():
    req = request()
    host = SyntheticHost(req)
    staged(host, req)
    preview = host.handler.preview(req, expected_revision=1, target_state="tentative")
    with pytest.raises(ResourceError) as error, host.uow():
        host.handler.stage_tentative(req, preview, 1)
    assert error.value.code == "formal_downgrade"


@pytest.mark.parametrize("change", ["qualification", "maintenance", "version", "authorization"])
def test_execution_rechecks_every_resource_and_current_authority(change):
    req = request("person" if change == "qualification" else "fixture")
    host = SyntheticHost(req)
    staged(host, req)
    host.contexts[req.owner_run_id] = host.contexts[req.owner_run_id].model_copy(
        update={"now": req.window.start}
    )
    with host.uow():
        assert host.handler.recheck_execution(req).status == "READY"
    rid = req.uses[0].resource.id
    snap = host.snapshots[rid]
    if change == "qualification":
        host.snapshots[rid] = snap.model_copy(
            update={"facts": (snap.facts[0].model_copy(update={"status": "revoked"}),)}
        )
    elif change == "maintenance":
        host.snapshots[rid] = snap.model_copy(
            update={
                "maintenance": (MaintenanceFact(window=window(), source=source(), status="active"),)
            }
        )
    elif change == "version":
        host.snapshots[rid] = snap.model_copy(
            update={"ref": snap.ref.model_copy(update={"revision": 2})}
        )
    else:
        host.contexts[req.owner_run_id] = host.contexts[req.owner_run_id].model_copy(
            update={"authorized": False}
        )
    with pytest.raises(ResourceError) as error, host.uow():
        host.handler.recheck_execution(req)
    assert error.value.code == "execution_blocked"
    assert host.records[req.reservation_id].state == "formal"  # historical decision retained


@pytest.mark.parametrize("at", [NOW, NOW.replace(hour=10)])
def test_execution_outside_half_open_window_fails(at):
    req = request()
    host = SyntheticHost(req)
    staged(host, req)
    host.contexts[req.owner_run_id] = host.contexts[req.owner_run_id].model_copy(update={"now": at})
    with pytest.raises(ResourceError), host.uow():
        host.handler.recheck_execution(req)


@pytest.mark.parametrize(
    "fail_at", ["resource_stage", "sample_after_resource", "receipt_after_sample", "cas"]
)
def test_entire_caller_uow_rolls_back_resource_sample_proof_and_receipt(fail_at):
    req = request()
    host = SyntheticHost(req)
    preview = host.handler.preview(req)
    host.fail_stage = fail_at == "resource_stage"
    host.fail_cas = fail_at == "cas"
    with pytest.raises((RuntimeError, ResourceError)), host.uow():
        host.handler.stage_formal(req, preview)
        if fail_at == "sample_after_resource":
            raise RuntimeError("sample conflict after resource staging")
        host.consumed.add("synthetic-destructive-unit")
        host.receipts.append("synthetic-receipt")
        raise RuntimeError("receipt/outbox failure after sample consumption")
    assert not host.records and not host.consumed and not host.confirmed and not host.receipts
    assert host.snapshots[req.uses[0].resource.id].occupancy_revision == 1
    host.fail_stage = host.fail_cas = False
    with host.uow():
        host.handler.stage_formal(req, preview)
        host.consumed.add("synthetic-destructive-unit")
        host.receipts.append("synthetic-receipt")
    assert len(host.records) == len(host.consumed) == len(host.confirmed) == len(host.receipts) == 1


def test_cross_project_formal_capacity_cannot_disappear_due_to_view_acl():
    req = request()
    host = SyntheticHost(req)
    staged(host, req)
    other = request()
    other = other.model_copy(update={"intent_key": "other-project-intent"})
    other_context = context(other)
    host.contexts[other.owner_run_id] = other_context.model_copy(
        update={"scope": other_context.scope.model_copy(update={"project_id": uuid4()})}
    )
    preview = host.handler.preview(other)
    assert preview.report.capacity_status == "conflicted" and not preview.allowed


def test_two_competing_requests_one_winner_and_no_oversubscription():
    a = request()
    b = request().model_copy(update={"intent_key": "competing-intent"})
    host = SyntheticHost(a)
    host.contexts[b.owner_run_id] = context(b)
    previews = [host.handler.preview(r) for r in (a, b)]
    barrier = Barrier(2)

    def run(req, preview):
        barrier.wait()
        try:
            with host.uow():
                host.handler.stage_formal(req, preview)
            return "staged"
        except ResourceError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, r, p) for r, p in zip((a, b), previews, strict=True)]
        assert sorted(f.result() for f in futures) == ["conflict", "staged"]
    assert len(host.records) == 1
    assert len(host.confirmed) == 1


def test_deterministic_resource_lock_order_and_preview_resource_order_digest():
    req = request()
    second = ResourceUse(
        resource=req.uses[0].resource.model_copy(update={"id": UUID(int=2)}), units="1"
    )
    req = req.model_copy(update={"uses": (*req.uses, second)})
    host = SyntheticHost(req)
    one = request(resource_id=second.resource.id)
    host.snapshots[second.resource.id] = snapshot(one, context(req))
    preview = host.handler.preview(req)
    with host.uow():
        host.handler.stage_formal(req, preview)
    assert host.lock_orders[-1] == (UUID(int=2), UUID(int=11))


def test_verified_host_actual_start_can_stage_joint_resources_without_inventing_actual():
    req = request()
    host = SyntheticHost(req)
    host.contexts[req.owner_run_id] = context(
        req, now=req.window.start + timedelta(minutes=2), verified_actual_start=req.window.start
    )
    preview = host.handler.preview(req)
    assert preview.allowed
    with host.uow():
        record = host.handler.stage_formal(req, preview)
        # Only the host's independent verification handler records actual_start.
        assert not hasattr(record.reservation, "actual_start")
        assert host.handler.recheck_execution(req).status == "READY"


def test_tentative_cannot_bypass_server_required_units():
    req = request(units="0.5")
    host = SyntheticHost(req)
    host.contexts[req.owner_run_id] = context(req, required_resources=request(units="1").uses)
    preview = host.handler.preview(req, target_state="tentative")
    assert not preview.allowed
    with pytest.raises(ResourceError) as error, host.uow():
        host.handler.stage_tentative(req, preview)
    assert error.value.code == "required_scope_mismatch"


def test_release_does_not_require_source_regrant_and_retains_original_evidence():
    req = request()
    host = SyntheticHost(req)
    original = staged(host, req).reservation
    host.sources[source(20).id] = "withdrawn"
    preview = host.handler.preview(
        req, expected_revision=1, target_state="released", reason="invalid"
    )
    assert preview.allowed
    with host.uow():
        changed = host.handler.stage_terminal(req, preview, 1)
    assert changed.reservation.report == original.report
    assert changed.reservation.fixed_resources == original.fixed_resources


def test_sample_mutated_first_still_rolls_back_when_resource_stage_fails():
    req = request()
    host = SyntheticHost(req)
    preview = host.handler.preview(req)
    host.fail_cas = True
    with pytest.raises(ResourceError), host.uow():
        host.consumed.add("synthetic-sample-first")
        host.handler.stage_formal(req, preview)
    assert not host.consumed and not host.records and not host.confirmed


def test_counterexample_separate_uows_leave_orphan_resource_occupancy():
    """Executable counterexample: a resource-only commit breaks atomic sample reservation."""
    req = request()
    host = SyntheticHost(req)
    staged(host, req)  # Incorrect host choreography has already committed resources.
    with pytest.raises(RuntimeError), host.uow():
        host.consumed.add("synthetic-sample")
        raise RuntimeError("later sample transaction failed")
    assert not host.consumed
    assert host.records[req.reservation_id].state == "formal"  # Forbidden orphan occupancy.


def test_preview_context_tampering_cannot_replace_the_bound_readset():
    req = request()
    host = SyntheticHost(req)
    preview = host.handler.preview(req)
    extended = preview.model_copy(update={"context_revision": "fabricated-authority"})
    with pytest.raises(ResourceError) as error, host.uow():
        host.handler.stage_formal(req, extended)
    assert error.value.code == "readset_changed"
    assert not host.records and not host.confirmed


def test_formal_record_without_current_occupancy_cannot_replay_or_start():
    req = request()
    host = SyntheticHost(req)
    old = host.handler.preview(req)
    staged(host, req)
    host.occupancies = lambda ctx, ids: ()
    with pytest.raises(ResourceError) as error, host.uow():
        host.handler.stage_formal(req, old)
    assert error.value.code == "replay_stale"
    host.contexts[req.owner_run_id] = context(req, now=req.window.start)
    with pytest.raises(ResourceError) as error, host.uow():
        host.handler.recheck_execution(req)
    assert error.value.code == "execution_blocked"
