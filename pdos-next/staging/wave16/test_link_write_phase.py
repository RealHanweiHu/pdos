"""No-DB protocol tests: owner SQL and qualification are explicit test doubles.

Actual Session/UOW/ORM transition and host marker functions are exercised; no
test grants live authorization, verifies original bytes, or commits a Link.
"""

import copy
import pickle
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import link_preview_phase as preview
import link_write_phase as phase
import pytest
from pdos_next.domain.capa_verification.models import RemediationLinkRecord
from pdos_next.errors import DomainError
from pdos_next.models import Confirmation, Principal
from pdos_next.service import digest, material_digest
from sqlalchemy import inspect
from sqlalchemy.orm import Session, make_transient_to_detached
from test_link_preview_phase import NOW
from test_link_preview_phase import work as preview_work  # noqa: F401


@pytest.fixture
def work(request, monkeypatch):
    w = request.getfixturevalue("preview_work")
    w.payload = w.payload.model_copy(update={"confirmation_token": "synthetic-confirmation-" * 2})
    w.command.payload = w.payload.model_dump(mode="json")
    w.proof = None
    w.sql = {"principal": 0, "confirmation": 0}
    w.scalar_hook = None
    w.active = True

    def proof_callback(s, ctx, command, product, payload):
        w.counts["proof"] += 1
        return phase.host.require_consumed_proof(s, ctx, command, payload, tier="T1")

    w.bound = replace(w.bound, proof_callback=proof_callback)
    w.engine._pdos_capa_link_consumed_proof = proof_callback

    def scalar(statement, *args, **kwargs):
        # Only the actual host Confirmation reader and stage's exact reader are
        # replaced. Any accidental owner/effect SQL fails instead of connecting.
        assert statement.column_descriptions[0]["entity"] is Confirmation
        assert statement._for_update_arg is not None
        assert statement.get_execution_options().get("populate_existing") is True
        w.sql["confirmation"] += 1
        if w.scalar_hook:
            w.scalar_hook(statement)
        return w.proof

    def execute(statement, *args, **kwargs):
        assert all(column["entity"] is Principal for column in statement.column_descriptions)
        assert [column["name"] for column in statement.column_descriptions] == [
            "tenant_id",
            "kind",
            "active",
        ]
        w.sql["principal"] += 1
        return SimpleNamespace(one_or_none=lambda: (w.ctx.tenant_id, "human", w.active))

    monkeypatch.setattr(w.s, "scalar", scalar)
    monkeypatch.setattr(w.s, "execute", execute)
    monkeypatch.setattr(phase.host, "now", lambda: w.clock[0])
    return w


def prepare(w):
    return phase.prepare_write_review(w.s, w.ctx, w.command, w.product, w.payload)


def apply(w, prepared):
    return phase.apply_prepared_write(w.s, w.ctx, w.command, w.product, w.payload, prepared)


def consume(w, review, *, snapshot=None, expiry=None):
    """Exercise actual False->True ORM marker; database reads remain synthetic."""
    proof = Confirmation(
        id=uuid4(),
        tenant_id=w.ctx.tenant_id,
        product_id=w.product.id,
        actor_id=w.ctx.actor_id,
        subject_id=w.product.id,
        operation=phase.link.OPERATION,
        revision=w.product.revision,
        token_hash=digest(w.payload.confirmation_token),
        payload_digest=material_digest(w.ctx, w.command, w.payload, phase.link),
        snapshot=copy.deepcopy(review if snapshot is None else snapshot),
        expires_at=expiry or w.clock[0] + timedelta(minutes=7),
        consumed=False,
        created_at=NOW,
    )
    make_transient_to_detached(proof)
    w.s.add(proof)
    proof.consumed = True
    w.proof = proof
    actual = phase.host.record_consumed_confirmation(
        w.s, w.ctx, w.command, w.payload, phase.link, proof
    )
    assert actual == proof.id
    return proof


def test_one_material_load_exact_review_and_final_fresh_owners_before_actual_save_clock(work):
    prepared, review = prepare(work)
    assert review == phase.link._review(work.command, work.payload, work.bound)
    assert review["after"]["received_at"] == "server_on_save"
    proof = consume(work, review)
    original_info = copy.copy(work.s.info)

    work.clock[0] += timedelta(seconds=1)
    row, subject, visibility = apply(work, prepared)
    assert (subject, visibility) == ("capa_remediation_link", "product")
    assert work.counts == {"load": 1, "new_write": 1, "refresh": 3, "proof": 1}
    assert row.created_at == NOW + timedelta(seconds=1)
    assert row.input_snapshot["shared_proof"] == {"id": str(proof.id), "tier": "T1"}
    assert "confirmation_token" not in row.input_snapshot
    assert row.issue_revision == work.payload.expected_issue_revision
    assert row.output_snapshot["basis"] == work.bound.resolution.basis.model_dump(mode="json")
    assert row.authority_snapshot == work.bound.authority
    assert row.required_source_read_set == work.bound.reads
    assert work.s.info == original_info
    assert inspect(row).transient and row not in work.s.new
    assert inspect(proof).attrs.consumed.history.added == [True]
    assert work.sql == {"principal": 2, "confirmation": 3}
    with pytest.raises(DomainError, match="仅限一次"):
        apply(work, prepared)


def test_received_clock_is_captured_after_owner_io_not_prepare_or_confirmation(work, monkeypatch):
    def refresh(*args):
        work.refresh(*args)
        work.clock[0] += timedelta(seconds=1)

    monkeypatch.setattr(phase.link, "_refresh", refresh)
    prepared, review = prepare(work)
    proof = consume(work, review)
    prepared_at = work.clock[0]
    row, _, _ = apply(work, prepared)
    assert row.created_at == prepared_at + timedelta(seconds=1)
    assert row.created_at != proof.created_at
    assert work.counts["load"] == work.counts["new_write"] == 1


def test_no_actual_consumed_marker_blocks_and_failed_phase_cannot_be_reused(work):
    prepared, _ = prepare(work)
    with pytest.raises(DomainError) as rejected:
        apply(work, prepared)
    assert rejected.value.code == "NAMED_APPROVAL_REQUIRED"
    assert not work.s.new
    with pytest.raises(DomainError, match="失败后也不能"):
        apply(work, prepared)


@pytest.mark.parametrize("fake", [None, True, "a-client-proof-id", uuid4()])
def test_callback_uuid_or_boolean_never_replaces_actual_same_uow_consumption(work, fake):
    def callback(*args):
        return fake

    work.bound = replace(work.bound, proof_callback=callback)
    work.engine._pdos_capa_link_consumed_proof = callback
    prepared, review = prepare(work)
    consume(work, review)
    with pytest.raises(DomainError) as rejected:
        apply(work, prepared)
    assert rejected.value.code in {"INTEGRATION_REQUIRED", "NAMED_APPROVAL_REQUIRED"}
    assert not work.s.new


def test_real_marker_different_material_review_is_not_prepared_write_review(work):
    prepared, review = prepare(work)
    changed = copy.deepcopy(review)
    changed["after"]["purpose"] = "Different reviewed material"
    consume(work, review, snapshot=changed)
    with pytest.raises(DomainError) as rejected:
        apply(work, prepared)
    assert rejected.value.code == "CONFIRMATION_SCOPE_CHANGED"


@pytest.mark.parametrize(
    "field", ["snapshot", "token_hash", "payload_digest", "consumed", "actor_id"]
)
def test_consumed_confirmation_mutation_after_marker_is_rejected(work, field):
    prepared, review = prepare(work)
    proof = consume(work, review)
    changes = {
        "snapshot": {"different": True},
        "token_hash": "0" * 64,
        "payload_digest": "1" * 64,
        "consumed": False,
        "actor_id": uuid4(),
    }
    setattr(proof, field, changes[field])
    with pytest.raises(DomainError) as rejected:
        apply(work, prepared)
    assert rejected.value.code == "SOURCE_STALE"


def test_current_actor_is_checked_again_by_actual_host_guard(work):
    prepared, review = prepare(work)
    consume(work, review)
    work.active = False
    with pytest.raises(DomainError) as rejected:
        apply(work, prepared)
    assert rejected.value.code == "NAMED_DECISION_REQUIRED"


@pytest.mark.parametrize("owner_error", ["VERSION_CONFLICT", "SOURCE_UNAVAILABLE", "SOURCE_STALE"])
def test_final_owner_current_or_source_failure_preserved_without_row(
    work, monkeypatch, owner_error
):
    calls = [0]

    def refresh(*args):
        work.refresh(*args)
        calls[0] += 1
        if calls[0] == 3:
            raise DomainError(owner_error, "Synthetic final owner recheck rejected")

    monkeypatch.setattr(phase.link, "_refresh", refresh)
    prepared, review = prepare(work)
    consume(work, review)
    with pytest.raises(DomainError) as rejected:
        apply(work, prepared)
    assert rejected.value.code == owner_error
    assert work.counts["proof"] == 0
    assert not work.s.new


@pytest.mark.parametrize("mutable", ["authority", "policy", "source_basis", "reads"])
def test_nested_bound_mutation_during_final_owner_io_cannot_escape_full_binding(
    work, monkeypatch, mutable
):
    calls = [0]

    def refresh(*args):
        work.refresh(*args)
        calls[0] += 1
        if calls[0] == 3:
            target = getattr(work.bound, mutable)
            if isinstance(target, dict):
                target["epoch_drift"] = 2
            else:
                target.append({"artifact_id": str(uuid4()), "expected_revision": 1})

    monkeypatch.setattr(phase.link, "_refresh", refresh)
    prepared, review = prepare(work)
    consume(work, review)
    with pytest.raises(DomainError) as rejected:
        apply(work, prepared)
    assert rejected.value.code == "SOURCE_STALE"
    assert work.counts["proof"] == 0


@pytest.mark.parametrize("deadline", ["proof", "authority", "policy"])
def test_expiry_after_final_owner_io_rejects_instead_of_backdating_save(
    work, monkeypatch, deadline
):
    calls = [0]

    def refresh(*args):
        work.refresh(*args)
        calls[0] += 1
        if calls[0] == 3:
            work.clock[0] = NOW + timedelta(
                minutes={"proof": 7, "policy": 8, "authority": 10}[deadline]
            )

    monkeypatch.setattr(phase.link, "_refresh", refresh)
    prepared, review = prepare(work)
    consume(work, review)
    with pytest.raises(DomainError) as rejected:
        apply(work, prepared)
    assert rejected.value.code in {"SOURCE_STALE", "NAMED_APPROVAL_REQUIRED"}
    assert not work.s.new


def test_consumed_proof_expiry_during_last_database_read_is_finally_rechecked(work):
    prepared, review = prepare(work)
    consume(work, review)

    def after_actual_read(statement):
        if work.sql["confirmation"] == 3:
            work.clock[0] = NOW + timedelta(minutes=7)

    work.scalar_hook = after_actual_read
    with pytest.raises(DomainError) as rejected:
        apply(work, prepared)
    assert rejected.value.code == "NAMED_APPROVAL_REQUIRED"
    assert not work.s.new


def test_clock_cannot_regress_after_save_capture_even_if_after_prepare(work):
    prepared, review = prepare(work)
    consume(work, review)
    work.clock[0] = NOW + timedelta(seconds=2)

    def backwards(statement):
        if work.sql["confirmation"] == 3:
            work.clock[0] = NOW + timedelta(seconds=1)

    work.scalar_hook = backwards
    with pytest.raises(DomainError) as rejected:
        apply(work, prepared)
    assert rejected.value.code == "SOURCE_STALE"


@pytest.mark.parametrize(
    "field", ["command_id", "idempotency_key", "expected_revision", "token", "payload", "product"]
)
def test_full_original_write_identity_remains_bound(work, field):
    prepared, review = prepare(work)
    consume(work, review)
    if field == "token":
        work.payload = work.payload.model_copy(update={"confirmation_token": "another-token-" * 3})
        work.command.payload = work.payload.model_dump(mode="json")
    elif field == "payload":
        work.payload = work.payload.model_copy(update={"reason": "changed actual reason"})
        work.command.payload = work.payload.model_dump(mode="json")
    elif field == "product":
        work.product.revision += 1
    else:
        setattr(
            work.command,
            field,
            uuid4()
            if field == "command_id"
            else 2
            if field == "expected_revision"
            else "another-key",
        )
    with pytest.raises(DomainError):
        apply(work, prepared)
    assert work.counts["refresh"] == 2


def test_read_order_is_bound_even_if_common_material_sorts_same_read_set(work):
    first = work.command.source_read_set[0]
    second = type(first)(artifact_id=uuid4(), expected_revision=1)
    work.command.source_read_set.append(second)
    prepared, review = prepare(work)
    consume(work, review)
    work.command.source_read_set.reverse()
    with pytest.raises(DomainError) as rejected:
        apply(work, prepared)
    assert rejected.value.code == "SOURCE_STALE"


@pytest.mark.parametrize(
    "field", ["tenant_id", "actor_id", "requester_id", "run_id", "cancel_epoch"]
)
def test_full_context_identity_and_epoch_are_not_transferable(work, field):
    prepared, review = prepare(work)
    consume(work, review)
    work.ctx = replace(work.ctx, **{field: 2 if field == "cancel_epoch" else uuid4()})
    with pytest.raises(DomainError):
        apply(work, prepared)
    assert work.counts["refresh"] == 2


@pytest.mark.parametrize("change", ["main", "enter_nested", "leave_nested", "close"])
def test_no_other_uow_can_reload_expired_orm_or_use_write_phase(work, change):
    nested = work.s.begin_nested() if change == "leave_nested" else None
    prepared, _ = prepare(work)
    if change == "main":
        work.s.rollback()
        work.s.begin()
    elif change == "enter_nested":
        work.s.begin_nested()
    elif change == "leave_nested":
        nested.rollback()
    else:
        work.s.close()
    with pytest.raises(DomainError):
        apply(work, prepared)
    assert work.sql == {"principal": 0, "confirmation": 0}


def test_other_session_cannot_take_the_prepared_write(work):
    prepared, _ = prepare(work)
    with Session(bind=work.engine) as other, other.begin():
        with pytest.raises(DomainError):
            phase.apply_prepared_write(
                other, work.ctx, work.command, work.product, work.payload, prepared
            )


@pytest.mark.parametrize("runtime", ["issuer_epoch", "proof_callback", "store"])
def test_runtime_or_callback_change_during_material_phase_is_rejected(work, runtime):
    prepared, review = prepare(work)
    consume(work, review)
    if runtime == "issuer_epoch":
        work.engine._pdos_professional_issuer_epochs = {"new_issuer": 2}
    elif runtime == "proof_callback":
        work.engine._pdos_capa_link_consumed_proof = lambda *args: uuid4()
    else:
        work.engine._pdos_results_store = SimpleNamespace()
    with pytest.raises(DomainError) as rejected:
        apply(work, prepared)
    assert rejected.value.code == "SOURCE_STALE"


def test_wrong_phase_type_never_becomes_a_write_proof(work):
    old = preview.prepare_preview(work.s, work.ctx, work.command, work.product, work.payload)
    for value in (None, {"accepted": True}, uuid4(), old):
        with pytest.raises(DomainError) as rejected:
            apply(work, value)
        assert rejected.value.code == "INTEGRATION_REQUIRED"


def test_write_phase_cannot_be_constructed_copied_or_serialized(work):
    prepared, _ = prepare(work)
    for transform in (copy.copy, copy.deepcopy, pickle.dumps):
        with pytest.raises(TypeError):
            transform(prepared)
    with pytest.raises(TypeError):
        phase.WritePhase()
    with pytest.raises(AttributeError):
        prepared._spent = False


def test_original_link_uses_existing_current_guarded_common_replay_not_new_material_phase(work):
    work.bound = replace(work.bound, original=RemediationLinkRecord(id=uuid4()))
    with pytest.raises(DomainError) as rejected:
        prepare(work)
    assert rejected.value.code == "REPLAY_REQUIRED"
    assert work.counts["new_write"] == 0


def test_missing_token_or_actual_loader_never_has_a_positive_default(work, monkeypatch):
    work.payload = work.payload.model_copy(update={"confirmation_token": None})
    work.command.payload = work.payload.model_dump(mode="json")
    with pytest.raises(DomainError) as rejected:
        prepare(work)
    assert rejected.value.code == "CONFIRMATION_REQUIRED"
    assert work.counts["load"] == 0

    work.payload = work.payload.model_copy(
        update={"confirmation_token": "actual-original-token-" * 2}
    )
    work.command.payload = work.payload.model_dump(mode="json")

    def missing(*args):
        raise DomainError("INTEGRATION_REQUIRED", "Actual owner bridge unavailable", 503)

    monkeypatch.setattr(phase.link, "_load", missing)
    with pytest.raises(DomainError) as rejected:
        prepare(work)
    assert rejected.value.code == "INTEGRATION_REQUIRED"
