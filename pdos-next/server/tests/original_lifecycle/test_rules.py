from dataclasses import FrozenInstanceError, replace
from datetime import timedelta

import pytest

from pdos_next.original_lifecycle import (
    DecisionReason,
    Disposition,
    LifecycleFailure,
    ParseState,
    UploadState,
    evaluate_purge,
    evaluate_quarantine,
    evaluate_restore,
)

from .helpers import fixture


def test_only_authoritatively_failed_unregistered_unreferenced_expired_original_is_orphan():
    clock, store, _, service, _ = fixture()
    decision = evaluate_quarantine(store.original, store.refs, service.policy, clock.now())
    assert decision.eligible and decision.reasons == ()
    assert decision.not_before == store.original.upload_terminal_at + timedelta(days=7)
    with pytest.raises(FrozenInstanceError):
        decision.eligible = False


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("registered", True, DecisionReason.REGISTERED_ORIGINAL),
        ("registered", None, DecisionReason.REGISTRATION_UNKNOWN),
        ("manual_hold", True, DecisionReason.MANUAL_HOLD),
        ("manual_hold", None, DecisionReason.HOLD_UNKNOWN),
        ("upload_state", UploadState.PENDING, DecisionReason.UPLOAD_NOT_TERMINAL),
        ("upload_state", UploadState.SUCCEEDED, DecisionReason.UPLOAD_NOT_TERMINAL),
        ("upload_state", UploadState.UNKNOWN, DecisionReason.UPLOAD_NOT_TERMINAL),
        ("upload_terminal_at", None, DecisionReason.UPLOAD_TIME_UNKNOWN),
        ("parse_state", ParseState.UNKNOWN, DecisionReason.PARSE_UNKNOWN),
        ("parse_state", ParseState.QUEUED, DecisionReason.PARSE_IN_PROGRESS),
        ("parse_state", ParseState.RUNNING, DecisionReason.PARSE_IN_PROGRESS),
        ("parse_state", ParseState.PARSED, DecisionReason.DERIVATION_PRESENT),
        ("parse_state", ParseState.NEEDS_OCR, DecisionReason.DERIVATION_PRESENT),
        ("retention_until", None, DecisionReason.RETENTION_UNKNOWN),
        ("disposition", Disposition.UNKNOWN, DecisionReason.STATE_UNKNOWN),
        ("disposition", Disposition.PURGED, DecisionReason.STATE_UNKNOWN),
        ("disposition", Disposition.QUARANTINED, DecisionReason.WRONG_DISPOSITION),
    ],
)
def test_unknown_protected_live_or_derived_facts_never_become_orphans(field, value, reason):
    clock, store, _, service, _ = fixture()
    decision = evaluate_quarantine(
        replace(store.original, **{field: value}), store.refs, service.policy, clock.now()
    )
    assert not decision.eligible and reason in decision.reasons


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("reference_count", None, DecisionReason.REFERENCE_UNKNOWN),
        ("reference_count", 1, DecisionReason.REFERENCED),
        ("formal_history", None, DecisionReason.REFERENCE_UNKNOWN),
        ("formal_history", True, DecisionReason.FORMAL_HISTORY),
    ],
)
def test_authoritative_refs_and_formal_history_protect_even_expired_failed_uploads(
    field, value, reason
):
    clock, store, _, service, _ = fixture()
    refs = replace(store.refs, **{field: value})
    decision = evaluate_quarantine(store.original, refs, service.policy, clock.now())
    assert not decision.eligible and reason in decision.reasons


def test_terminal_failure_grace_and_extended_retention_are_both_required():
    clock, store, _, service, _ = fixture()
    original = replace(store.original, upload_terminal_at=clock.now() - timedelta(hours=1))
    decision = evaluate_quarantine(original, store.refs, service.policy, clock.now())
    assert decision.not_before == clock.now() + timedelta(days=7) - timedelta(hours=1)
    assert DecisionReason.RETENTION_NOT_ELAPSED in decision.reasons
    original = replace(store.original, retention_until=clock.now() + timedelta(days=20))
    assert evaluate_quarantine(original, store.refs, service.policy, clock.now()).not_before == (
        original.retention_until
    )


def test_future_facts_are_invalid_but_old_observation_time_is_not_a_material_deadline():
    clock, store, _, service, _ = fixture()
    for changed in (
        replace(store.original, created_at=clock.now() + timedelta(days=1)),
        replace(store.original, upload_terminal_at=clock.now() + timedelta(hours=1)),
    ):
        decision = evaluate_quarantine(changed, store.refs, service.policy, clock.now())
        assert not decision.eligible and DecisionReason.FACT_TIME_INVALID in decision.reasons
    refs = replace(store.refs, observed_at=clock.now() - timedelta(hours=1))
    assert evaluate_quarantine(store.original, refs, service.policy, clock.now()).eligible


def test_exact_object_and_tenant_product_binding_cannot_be_mixed():
    clock, store, _, service, _ = fixture()
    _, other, _, _, _ = fixture()
    for refs in (
        replace(store.refs, reference=other.reference),
        replace(store.refs, scope=other.scope),
    ):
        with pytest.raises(LifecycleFailure) as exc:
            evaluate_quarantine(store.original, refs, service.policy, clock.now())
        assert exc.value.code == "BINDING_MISMATCH"


def test_recovery_preserves_referenced_held_history_but_unknown_or_purged_bytes_block():
    clock, store, _, service, _ = fixture()
    original = replace(
        store.original,
        disposition=Disposition.QUARANTINED,
        quarantined_at=clock.now() - timedelta(days=1),
        manual_hold=True,
        registered=True,
    )
    refs = replace(store.refs, reference_count=2, formal_history=True)
    assert evaluate_restore(original, refs, service.policy, clock.now()).eligible
    for unknown in (replace(refs, formal_history=None), replace(refs, reference_count=None)):
        assert not evaluate_restore(original, unknown, service.policy, clock.now()).eligible
    assert not evaluate_restore(
        replace(original, disposition=Disposition.PURGED), refs, service.policy, clock.now()
    ).eligible


def test_purge_only_reports_eligibility_after_both_retention_clocks_and_current_protection():
    clock, store, _, service, _ = fixture()
    original = replace(
        store.original,
        disposition=Disposition.QUARANTINED,
        quarantined_at=clock.now(),
    )
    assert not evaluate_purge(original, store.refs, service.policy, clock.now()).eligible
    clock.value += timedelta(days=30)
    original = replace(original, observed_at=clock.now())
    refs = replace(store.refs, observed_at=clock.now())
    assert evaluate_purge(original, refs, service.policy, clock.now()).eligible
    for protected in (replace(refs, reference_count=1), replace(refs, formal_history=True)):
        assert not evaluate_purge(original, protected, service.policy, clock.now()).eligible
    assert not evaluate_purge(
        replace(original, manual_hold=True), refs, service.policy, clock.now()
    ).eligible


@pytest.mark.parametrize(
    ("location", "field", "value"),
    [
        ("original", "revision", True),
        ("original", "registered", 1),
        ("original", "manual_hold", "false"),
        ("original", "upload_state", "failed"),
        ("refs", "reference_count", True),
        ("refs", "formal_history", 0),
        ("refs", "read_version", ""),
    ],
)
def test_strict_facts_reject_coercion_of_trusted_fields(location, field, value):
    _, store, _, _, _ = fixture()
    with pytest.raises(ValueError):
        replace(store.original if location == "original" else store.refs, **{field: value})


def test_request_cannot_inject_permission_fields_and_naive_times_fail():
    _, store, _, service, _ = fixture()
    with pytest.raises(TypeError, match="unexpected keyword"):
        replace(store.original, authorized=True)
    with pytest.raises(ValueError, match="timezone"):
        replace(store.original, observed_at=store.original.observed_at.replace(tzinfo=None))
    with pytest.raises(ValueError, match="bounded"):
        replace(service.policy, effect_timeout=timedelta(days=1))
    with pytest.raises(ValueError, match="positive"):
        replace(service.policy, failed_upload_grace=timedelta(0))
