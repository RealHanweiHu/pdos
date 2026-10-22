from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier, Event
from uuid import uuid4

import pytest

from pdos_next.original_lifecycle import (
    ActorKind,
    DecisionReason,
    Disposition,
    EffectOutcome,
    IntentState,
    LifecycleAction,
    LifecycleFailure,
    UnavailableReversibleLifecycleAdapter,
)

from .helpers import confirm, fixture, preview, record, start


def failure(code, callback):
    with pytest.raises(LifecycleFailure) as exc:
        callback()
    assert exc.value.code == code


def test_substantive_preview_is_stored_and_confirmation_only_stages_pending_intent():
    _, store, _, service, physical = fixture()
    candidate = preview(store, service)
    view = candidate.as_dict()
    assert view["eligible"] is True
    assert view["reference_read_version"] == "references:1"
    assert "server_storage_key" not in view and "scan_status" not in view
    assert store.candidates[candidate.id] == candidate
    intent = confirm(store, service, candidate)
    assert intent.state == IntentState.PENDING
    assert store.original.pending_intent_id == intent.id
    assert store.original.disposition == Disposition.ACTIVE
    assert store.original.revision == 2
    assert physical.apply_calls == 0


def test_same_key_and_cross_key_replays_preserve_one_named_intent_even_after_preview_expiry():
    clock, store, authority, service, _ = fixture()
    candidate = preview(store, service)
    first = confirm(store, service, candidate)
    clock.value += timedelta(minutes=6)
    assert confirm(store, service, candidate) == first
    assert confirm(store, service, candidate, key="confirm:alias") == first
    assert first.named_decider_id == authority.actor_id
    assert len(store.intents) == 1 and len(store.events) == 1
    authority.denied = True
    failure("FORBIDDEN_SCOPE", lambda: confirm(store, service, candidate))


def test_same_key_cannot_change_substantive_preview():
    _, store, _, service, _ = fixture()
    candidate = preview(store, service)
    confirm(store, service, candidate)
    different = preview(store, service)
    failure("IDEMPOTENCY_CONFLICT", lambda: confirm(store, service, different))
    assert len(store.intents) == 1


def test_new_authoritative_reference_invalidates_preview_and_is_never_recycled():
    _, store, _, service, physical = fixture()
    candidate = preview(store, service)
    store.add_reference()
    failure("PREVIEW_STALE", lambda: confirm(store, service, candidate))
    assert not store.intents and physical.apply_calls == 0
    protected = preview(store, service)
    assert DecisionReason.REFERENCED in protected.decision.reasons
    failure("RETENTION_PROTECTED", lambda: confirm(store, service, protected))


@pytest.mark.parametrize("context", ["agent", "service"])
def test_ai_or_worker_cannot_supply_named_human_confirmation(context):
    _, store, _, service, _ = fixture()
    candidate = preview(store, service)
    failure(
        "NAMED_CONFIRMATION_REQUIRED", lambda: confirm(store, service, candidate, context=context)
    )
    assert not store.intents


def test_wrong_scope_authorization_and_tampered_digest_fail_before_any_write():
    _, store, authority, service, _ = fixture()
    candidate = preview(store, service)
    authority.wrong_scope = True
    failure("FORBIDDEN_SCOPE", lambda: confirm(store, service, candidate))
    authority.wrong_scope = False
    with store.command_transaction():
        failure("PREVIEW_MISMATCH", lambda: service.confirm("human", candidate.id, "a" * 64, "key"))
    store.candidates[candidate.id] = replace(candidate, digest="a" * 64)
    failure("PREVIEW_CORRUPT", lambda: confirm(store, service, candidate))
    assert not store.intents


def test_material_age_does_not_expire_candidate_but_changed_policy_requires_review():
    clock, store, _, service, _ = fixture()
    candidate = preview(store, service)
    clock.value += timedelta(minutes=6)
    assert confirm(store, service, candidate).state.value == "pending"
    clock, store, _, service, _ = fixture()
    candidate = preview(store, service)
    service.policy = replace(service.policy, failed_upload_grace=timedelta(days=8))
    failure("POLICY_CHANGED", lambda: confirm(store, service, candidate))
    assert not store.intents


def test_protection_fact_change_without_version_bump_is_also_detected():
    _, store, _, service, _ = fixture()
    candidate = preview(store, service)
    store.original = replace(store.original, manual_hold=True)
    failure("PREVIEW_STALE", lambda: confirm(store, service, candidate))


def test_stage_failure_rolls_back_pending_intent_request_preview_consumption_and_outbox():
    _, store, _, service, _ = fixture()
    candidate = preview(store, service)
    store.fail_stage = True
    with pytest.raises(RuntimeError, match="Outbox"):
        confirm(store, service, candidate)
    assert store.original.revision == 1 and store.original.pending_intent_id is None
    assert not store.requests and not store.intents and not store.consumed and not store.events
    store.fail_stage = False
    assert confirm(store, service, candidate).state == IntentState.PENDING


def test_bad_transaction_port_ack_cannot_be_treated_as_success_and_caller_rolls_back():
    _, store, _, service, _ = fixture()
    candidate = preview(store, service)
    store.bad_ack = True
    failure("PORT_RESULT_MISMATCH", lambda: confirm(store, service, candidate))
    assert not store.intents and store.original.pending_intent_id is None


def test_candidate_is_consumed_once_under_concurrent_confirmation_and_blocks_new_ref():
    _, store, _, service, _ = fixture()
    candidate = preview(store, service)
    barrier = Barrier(2)

    def confirm_parallel(key):
        barrier.wait()
        return confirm(store, service, candidate, key=key)

    with ThreadPoolExecutor(max_workers=2) as executor:
        calls = [executor.submit(confirm_parallel, f"concurrent:{i}") for i in range(2)]
        results = [call.result(timeout=5) for call in calls]
    assert results[0].id == results[1].id and len(store.intents) == 1
    failure("REFERENCE_BLOCKED", store.add_reference)


def test_known_quarantine_preserves_exact_bytes_and_restore_rechecks_acl_and_preserves_facts():
    _, store, authority, service, physical = fixture()
    original = store.original
    intent = confirm(store, service, preview(store, service))
    permit = start(store, service, intent)
    result = record(store, service, intent, physical.apply_once(permit))
    assert result.state == IntentState.APPLIED and not result.recovery_required
    assert store.original.disposition == Disposition.QUARANTINED
    assert store.original.reference == original.reference
    assert store.original.upload_state == original.upload_state
    assert store.original.parse_state == original.parse_state
    failure("REFERENCE_BLOCKED", store.add_reference)
    restoration = preview(store, service, action=LifecycleAction.RESTORE)
    assert restoration.decision.eligible
    authority.denied = True
    failure("FORBIDDEN_SCOPE", lambda: confirm(store, service, restoration, key="restore:1"))
    authority.denied = False
    restore_intent = confirm(store, service, restoration, key="restore:1")
    restore_permit = start(store, service, restore_intent)
    record(store, service, restore_intent, physical.apply_once(restore_permit))
    assert store.original.disposition == Disposition.ACTIVE
    assert (
        store.original.reference == original.reference and store.content == physical.store.content
    )
    assert store.original.manual_hold == original.manual_hold
    assert store.original.retention_until == original.retention_until
    assert "scan_status" not in restoration.as_dict()


def test_known_effect_receipt_replay_is_idempotent_but_conflicting_receipt_is_rejected():
    _, store, _, service, physical = fixture()
    intent = confirm(store, service, preview(store, service))
    permit = start(store, service, intent)
    receipt = physical.apply_once(permit)
    result = record(store, service, intent, receipt)
    assert record(store, service, intent, receipt) == result
    conflicting = replace(receipt, transport_revision="different:observation")
    failure("EFFECT_RESULT_CONFLICT", lambda: record(store, service, intent, conflicting))
    assert physical.apply_calls == 1


def test_unknown_after_effect_cannot_retry_or_cancel_and_read_only_observation_recovers():
    _, store, _, service, physical = fixture()
    intent = confirm(store, service, preview(store, service))
    permit = start(store, service, intent)
    physical.mode = "unknown_after_applied"
    unknown = record(store, service, intent, physical.apply_once(permit))
    assert unknown.state == IntentState.UNKNOWN
    assert store.original.pending_intent_id == intent.id
    failure("EFFECT_ALREADY_ATTEMPTED", lambda: start(store, service, intent))
    with store.command_transaction():
        failure("EFFECT_ALREADY_ATTEMPTED", lambda: service.cancel_pending("human", intent.id))
    known = record(store, service, intent, physical.observe(permit))
    assert known.state == IntentState.APPLIED and physical.apply_calls == 1
    assert physical.observe_calls == 1 and store.original.pending_intent_id is None


def test_expired_in_flight_is_unknown_without_asserting_no_effect_or_releasing_protection():
    clock, store, _, service, physical = fixture()
    intent = confirm(store, service, preview(store, service))
    permit = start(store, service, intent)
    with store.command_transaction():
        failure("EFFECT_NOT_EXPIRED", lambda: service.mark_unknown("service", intent.id))
    clock.value += timedelta(seconds=31)
    with store.command_transaction():
        unknown = service.mark_unknown("service", intent.id)
    assert unknown.state == IntentState.UNKNOWN and unknown.permit == permit
    assert store.original.pending_intent_id == intent.id and physical.apply_calls == 0
    failure("EFFECT_ALREADY_ATTEMPTED", lambda: physical.apply_once(permit))
    assert physical.observe(permit).outcome == EffectOutcome.UNKNOWN


def test_confirmed_no_effect_requires_a_new_preview_for_another_attempt():
    _, store, _, service, physical = fixture()
    candidate = preview(store, service)
    intent = confirm(store, service, candidate)
    permit = start(store, service, intent)
    physical.mode = "not_applied"
    result = record(store, service, intent, physical.apply_once(permit))
    assert result.state == IntentState.NOT_APPLIED and store.original.pending_intent_id is None
    assert confirm(store, service, candidate) == result
    failure("EFFECT_ALREADY_ATTEMPTED", lambda: start(store, service, intent))
    fresh = confirm(store, service, preview(store, service), key="explicit:retry")
    assert fresh.id != intent.id and fresh.state == IntentState.PENDING


def test_not_started_intent_can_be_cancelled_and_replaying_returns_original_cancellation():
    _, store, _, service, physical = fixture()
    candidate = preview(store, service)
    intent = confirm(store, service, candidate)
    with store.command_transaction():
        cancelled = service.cancel_pending("human", intent.id)
    assert cancelled.state == IntentState.CANCELLED and store.original.pending_intent_id is None
    assert confirm(store, service, candidate) == cancelled
    assert physical.apply_calls == 0


def test_hold_change_then_revert_still_invalidates_fixed_post_confirmation_revision():
    _, store, _, service, physical = fixture()
    intent = confirm(store, service, preview(store, service))
    # Two legitimate protection updates, leaving the same fact value (ABA).
    store.original = replace(store.original, manual_hold=True, revision=3)
    store.original = replace(store.original, manual_hold=False, revision=4)
    failure("PREVIEW_STALE", lambda: start(store, service, intent))
    assert physical.apply_calls == 0


@pytest.mark.parametrize("mutation", ["hold", "retention", "reference", "policy", "acl", "epoch"])
def test_new_protection_after_permit_commit_is_rechecked_under_gate_before_physical_effect(
    mutation,
):
    clock, store, authority, service, physical = fixture()
    intent = confirm(store, service, preview(store, service))
    permit = start(store, service, intent)
    if mutation == "hold":
        store.original = replace(store.original, manual_hold=True, revision=4)
    elif mutation == "retention":
        store.original = replace(
            store.original, retention_until=clock.now() + timedelta(days=10), revision=4
        )
    elif mutation == "reference":
        store.refs = replace(store.refs, read_version="references:2", reference_count=1)
    elif mutation == "policy":
        service.policy = replace(service.policy, quarantine_grace=timedelta(days=60))
    elif mutation == "acl":
        authority.denied = True
    else:
        store.original = replace(store.original, revision=5)
    with pytest.raises(LifecycleFailure):
        physical.apply_once(permit)
    assert physical.apply_calls == 0 and physical.disposition == Disposition.ACTIVE
    assert store.original.pending_intent_id == intent.id


def test_even_unversioned_new_hold_is_fail_closed_before_physical_effect():
    _, store, _, service, physical = fixture()
    intent = confirm(store, service, preview(store, service))
    permit = start(store, service, intent)
    store.original = replace(store.original, manual_hold=True)
    failure("RETENTION_PROTECTED", lambda: physical.apply_once(permit))
    assert physical.apply_calls == 0


def test_unexpected_reference_after_physical_effect_records_known_location_and_recovery_needed():
    _, store, _, service, physical = fixture()
    intent = confirm(store, service, preview(store, service))
    permit = start(store, service, intent)
    receipt = physical.apply_once(permit)
    # Simulates a broken external reference writer, violating the common gate.
    store.refs = replace(store.refs, reference_count=1, read_version="unexpected-reference:2")
    completed = record(store, service, intent, receipt)
    assert completed.state == IntentState.APPLIED and completed.recovery_required
    assert DecisionReason.REFERENCED in completed.protection_reasons
    assert store.original.disposition == Disposition.QUARANTINED
    restoration = preview(store, service, action=LifecycleAction.RESTORE)
    assert restoration.decision.eligible


def test_unwired_transport_never_asserts_bytes_verified_or_physical_success():
    clock, store, _, service, _ = fixture()
    intent = confirm(store, service, preview(store, service))
    permit = start(store, service, intent)
    adapter = UnavailableReversibleLifecycleAdapter(clock=clock)
    receipt = adapter.apply_once(permit)
    assert receipt.outcome == EffectOutcome.UNKNOWN and receipt.integrity_verified is False
    assert receipt.error_code == "LIFECYCLE_TRANSPORT_UNAVAILABLE"
    result = record(store, service, intent, receipt)
    assert result.state == IntentState.UNKNOWN and store.original.pending_intent_id == intent.id
    assert adapter.observe(permit).outcome == EffectOutcome.UNKNOWN


def test_receipt_cannot_bind_other_bytes_scope_lease_time_or_raw_diagnostic():
    clock, store, _, service, physical = fixture()
    intent = confirm(store, service, preview(store, service))
    permit = start(store, service, intent)
    receipt = physical.apply_once(permit)
    _, other, _, _, _ = fixture()
    for changed in (
        replace(receipt, reference=other.reference),
        replace(receipt, scope=other.scope),
        replace(receipt, lease_token=uuid4()),
    ):
        failure(
            "EFFECT_BINDING_MISMATCH",
            lambda changed=changed: record(store, service, intent, changed),
        )
    for observed_at in (clock.now() + timedelta(seconds=1), clock.now() - timedelta(seconds=1)):
        failure(
            "EFFECT_OBSERVATION_STALE",
            lambda observed_at=observed_at: record(
                store, service, intent, replace(receipt, observed_at=observed_at)
            ),
        )
    with pytest.raises(ValueError, match="machine codes"):
        replace(receipt, error_code="private customer bytes or token")
    with pytest.raises(ValueError, match="verification"):
        replace(receipt, integrity_verified=False)
    assert store.get_intent(intent.id).state == IntentState.IN_FLIGHT


def test_human_or_ai_cannot_grant_themselves_worker_effect_authority():
    _, store, authority, service, physical = fixture()
    intent = confirm(store, service, preview(store, service))
    for kind in (ActorKind.HUMAN, ActorKind.AGENT):
        authority.actor_override = kind
        failure("WORKER_AUTHORITY_REQUIRED", lambda: start(store, service, intent))
    assert physical.apply_calls == 0


def test_reference_writer_cannot_enter_between_final_validation_and_physical_marker():
    _, store, _, service, physical = fixture()
    intent = confirm(store, service, preview(store, service))
    permit = start(store, service, intent)
    validated, release_effect, reference_entered, reference_finished = (
        Event(),
        Event(),
        Event(),
        Event(),
    )

    def pause_inside_gate():
        validated.set()
        assert release_effect.wait(timeout=2)

    def write_reference():
        reference_entered.set()
        try:
            store.add_reference()
        finally:
            reference_finished.set()

    physical.effect_hook = pause_inside_gate
    with ThreadPoolExecutor(max_workers=2) as executor:
        effect = executor.submit(physical.apply_once, permit)
        assert validated.wait(timeout=2)
        new_reference = executor.submit(write_reference)
        assert reference_entered.wait(timeout=2)
        assert not reference_finished.wait(timeout=0.03)
        release_effect.set()
        receipt = effect.result(timeout=2)
        failure("REFERENCE_BLOCKED", lambda: new_reference.result(timeout=2))
    assert receipt.outcome == EffectOutcome.APPLIED and store.refs.reference_count == 0


def test_clock_rollback_cannot_start_physical_effect_before_permit_issue():
    clock, store, _, service, physical = fixture()
    intent = confirm(store, service, preview(store, service))
    permit = start(store, service, intent)
    clock.value -= timedelta(seconds=1)
    failure("EFFECT_TIME_INVALID", lambda: physical.apply_once(permit))
    assert physical.apply_calls == 0 and physical.disposition == Disposition.ACTIVE
    assert store.get_intent(intent.id).state == IntentState.IN_FLIGHT


def test_applied_then_changed_location_never_becomes_historical_not_applied():
    _, store, _, service, physical = fixture()
    intent = confirm(store, service, preview(store, service))
    permit = start(store, service, intent)
    physical.mode = "unknown_after_applied"
    record(store, service, intent, physical.apply_once(permit))
    assert physical.terminal_outcomes[intent.id] == EffectOutcome.APPLIED
    # Simulates a broken external marker writer after the actual quarantine.
    physical.disposition = Disposition.ACTIVE
    observed = physical.observe(permit)
    assert observed.outcome == EffectOutcome.UNKNOWN
    assert record(store, service, intent, observed).state == IntentState.UNKNOWN
    assert store.original.pending_intent_id == intent.id and physical.apply_calls == 1


def test_current_exact_bytes_without_terminal_operation_journal_do_not_prove_no_effect():
    _, store, _, service, physical = fixture()
    intent = confirm(store, service, preview(store, service))
    permit = start(store, service, intent)
    physical.permits[intent.id] = permit
    assert physical.disposition == Disposition.ACTIVE
    assert physical.observe(permit).outcome == EffectOutcome.UNKNOWN
    assert physical.apply_calls == 0
