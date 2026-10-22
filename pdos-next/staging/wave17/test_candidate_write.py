"""Real Session/UOW/ORM history with explicit no-database owner substitutes.

The simulated common assignment below is not an actual SQL consumption or a
public qualification. Actual owner/consumer functions run; database SELECTs,
original bytes and professional facts use the already declared prepare fixture.
"""

from copy import copy, deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import candidate_commands as commands
import candidate_prepare as prepare
import candidate_write as writer
import fact_consumption as consumption
import pytest
import test_anchor_storage as stored
import test_candidate_prepare as owners
from pdos_next.contracts import Command
from pdos_next.domain.capa_verification.models import CapaVerificationEvidence
from pdos_next.errors import DomainError
from pdos_next.models import Confirmation, Product
from pdos_next.service import Context, digest, material_digest
from sqlalchemy import inspect
from sqlalchemy.orm import Session, make_transient_to_detached
from test_anchor_storage import uid


@pytest.fixture
def world(monkeypatch):
    generator = owners.origin_sample.__wrapped__(monkeypatch)
    w = next(generator)
    actual = owners.source_owner.__wrapped__(w, monkeypatch)
    data = owners.work.__wrapped__(actual, monkeypatch)

    class DateTimeType(type):
        def __instancecheck__(cls, value):
            return isinstance(value, datetime)

    class Clock(datetime, metaclass=DateTimeType):
        @classmethod
        def now(cls, tz=None):
            return w.clock.at if tz is not None else w.clock.at.replace(tzinfo=None)

    monkeypatch.setattr(consumption, "datetime", Clock)
    monkeypatch.setattr(writer, "datetime", Clock)
    data.payload = data.payload.model_copy(
        update={"confirmation_token": "explicit-synthetic-confirmation-token"}
    )
    phase = owners.run(data)
    product = w.memory.first(Product)
    # A SQL row is fully loaded. Detached attachment otherwise expires every
    # unassigned default and could issue IO in this deliberately DB-free fixture.
    for column in inspect(Product).columns:
        if column.key not in vars(product):
            setattr(product, column.key, None)
    make_transient_to_detached(product)
    w.s.add(product)
    command = Command(
        command_id=uid("actual-candidate-command"),
        idempotency_key="actual-candidate-original-key",
        operation=writer.OPERATION,
        product_id=w.pid,
        expected_revision=product.revision,
        source_read_set=[v.model_dump(mode="json") for v in phase.required_source_read_set],
        payload=data.payload.model_dump(mode="json"),
    )
    review = writer.reviewed_prepared_candidate(phase)
    proof = Confirmation(
        id=uid("actual-candidate-proof"),
        tenant_id=w.ctx.tenant_id,
        product_id=w.pid,
        actor_id=w.ctx.actor_id,
        subject_id=w.pid,
        operation=writer.OPERATION,
        revision=product.revision,
        token_hash=digest(data.payload.confirmation_token),
        payload_digest=material_digest(w.ctx, command, data.payload, commands),
        snapshot=deepcopy(review),
        consumed=False,
        created_at=w.clock.at - timedelta(seconds=10),
        expires_at=w.clock.at + timedelta(minutes=3),
    )
    make_transient_to_detached(proof)
    w.s.add(proof)
    host = consumption.ConsumptionHost({writer.OPERATION: commands})
    binding = host.bind_before_transition(
        w.s, w.ctx, command, data.payload, commands, proof, reviewed_snapshot=review
    )
    # Explicit pure substitute for the trusted common consumer's actual action.
    # Capture checks real ORM loaded history, but no SQL or public consumer runs.
    proof.consumed = True
    marker = host.capture_after_transition(
        w.s, w.ctx, command, data.payload, commands, proof, binding=binding
    )
    added = []
    original_add = w.s.add

    def add(row):
        assert isinstance(row, CapaVerificationEvidence)
        added.append(row)
        original_add(row)

    def no_database(*args, **kwargs):
        pytest.fail("Candidate writer must not flush, commit or open a connection")

    monkeypatch.setattr(w.s, "add", add)
    monkeypatch.setattr(w.s, "flush", no_database)
    monkeypatch.setattr(w.s, "commit", no_database)
    monkeypatch.setattr(w.s, "connection", no_database)
    out = SimpleNamespace(
        data=data,
        w=w,
        product=product,
        phase=phase,
        command=command,
        proof=proof,
        host=host,
        binding=binding,
        marker=marker,
        added=added,
        review=review,
    )
    yield out
    generator.close()


def apply(world, **changes):
    values = {
        "s": world.w.s,
        "ctx": world.w.ctx,
        "command": world.command,
        "product": world.product,
        "payload": world.data.payload,
        "phase": world.phase,
        "consumption_host": world.host,
        "module": commands,
        "proof": world.proof,
        "consumption_binding": world.binding,
        "consumption_marker": world.marker,
    }
    values.update(changes)
    return writer.apply_prepared_candidate(**values)


def rejected(world, action, codes=None):
    with pytest.raises(DomainError) as caught:
        action()
    if codes is not None:
        assert caught.value.code in codes, caught.value.code
    assert world.added == []
    return caught.value


def phase_invalid(world):
    with pytest.raises(DomainError) as caught:
        prepare.reviewed_candidate(world.phase)
    assert caught.value.code == "CANDIDATE_PREPARED_OWNER_REQUIRED"


def test_one_pending_row_with_real_identity_history_exact_material_and_flat_hashes(world):
    before_issue = deepcopy(world.w.row.issue_snapshot)
    before_pointer = (world.w.pointer.issue_version_id, world.w.pointer.issue_revision)
    original_anchor = world.phase.anchor.model_dump(mode="json")
    old_owner_reads = world.data.state.basis_calls
    row, subject, visibility = apply(world)
    assert world.added == [row] and row in world.w.s.new
    assert subject == "capa_verification_candidate" and visibility == "product"
    assert (row.owner_id, row.writer_id) == (world.w.row.owner_id, world.w.ctx.actor_id)
    assert row.owner_id != row.writer_id
    assert row.status == "candidate" and row.result == "indeterminate"
    assert row.applicable is row.independently_verified is row.observation_complete is None
    assert row.revision == 1 and row.created_at == world.w.clock.at
    assert row.issue_version_id == world.w.ref.id and row.issue_revision == world.w.ref.revision
    assert set(row.input_snapshot) == {
        "semantic",
        "shared_proof",
        "proof_consumed_at",
        "stable_anchor",
    }
    assert row.input_snapshot["stable_anchor"] == original_anchor
    assert row.input_snapshot["semantic"] == commands.semantic(world.data.payload)
    assert "confirmation_token" not in str(row.input_snapshot)
    assert row.input_snapshot["shared_proof"] == {"id": str(world.proof.id), "tier": "T1"}
    assert row.input_snapshot["proof_consumed_at"] == world.marker.consumed_at.isoformat()
    assert row.intent_digest == world.marker.common_intent_sha256
    assert row.intent_digest != digest(commands.semantic(world.data.payload))
    assert row.binding_sha256 == digest(row.candidate_binding)
    assert row.action_result == {
        "candidate_binding_sha256": row.binding_sha256,
        "inspection_sha256": row.inspection_sha256,
    }
    assert not hasattr(row, "receipt_id")
    assert "action_result" not in inspect(CapaVerificationEvidence).columns
    assert world.data.state.basis_calls > old_owner_reads
    assert world.w.row.issue_snapshot == before_issue
    assert (world.w.pointer.issue_version_id, world.w.pointer.issue_revision) == before_pointer
    assert tuple(inspect(world.proof).attrs.consumed.history.deleted) == (False,)
    assert tuple(inspect(world.proof).attrs.consumed.history.added) == (True,)
    phase_invalid(world)


def test_successful_phase_cannot_append_twice(world):
    apply(world)
    with pytest.raises(DomainError) as caught:
        apply(world)
    assert caught.value.code == "CANDIDATE_PREPARED_OWNER_REQUIRED"
    assert len(world.added) == 1


@pytest.mark.parametrize("fake", [None, True, SimpleNamespace(require_live=lambda *_a, **_k: True)])
def test_only_actual_consumption_host_can_enter_and_failure_invalidates_phase(world, fake):
    rejected(
        world,
        lambda: apply(world, consumption_host=fake),
        {"FACT_ACTUAL_CONSUMPTION_HOST_REQUIRED"},
    )
    phase_invalid(world)


@pytest.mark.parametrize("marker", ["copy", "constructed", "bool", "none"])
def test_only_original_host_issued_marker_can_enter(world, marker):
    forged = {
        "copy": copy(world.marker),
        "constructed": consumption.LiveConsumption(**vars(world.marker)),
        "bool": True,
        "none": None,
    }[marker]
    rejected(
        world, lambda: apply(world, consumption_marker=forged), {"FACT_ACTUAL_FALSE_TRUE_REQUIRED"}
    )
    phase_invalid(world)


@pytest.mark.parametrize("field", ["idempotency_key", "command_id", "payload", "readset_order"])
def test_full_original_command_binding_includes_key_token_and_readset_order(world, field):
    if field == "idempotency_key":
        world.command.idempotency_key = "different-actual-key"
    elif field == "command_id":
        world.command.command_id = uid("different-command")
    elif field == "payload":
        world.command.payload = {
            **world.command.payload,
            "confirmation_token": "different-valid-token-value",
        }
    else:
        assert len(world.command.source_read_set) > 1
        world.command.source_read_set.reverse()
    rejected(
        world,
        lambda: apply(world),
        {
            "FACT_LIVE_CONSUMPTION_REQUIRED",
            "FACT_COMMAND_PAYLOAD_MISMATCH",
            "FACT_CONSUMPTION_MATERIAL_CHANGED",
        },
    )
    phase_invalid(world)


@pytest.mark.parametrize("field", ["snapshot", "expires_at", "actor_id", "consumed"])
def test_persistent_proof_fields_or_false_true_history_cannot_be_replaced(world, field):
    if field == "snapshot":
        world.proof.snapshot["owner_id"] = str(uid("other-proof-owner"))
    elif field == "expires_at":
        world.proof.expires_at += timedelta(hours=1)
    elif field == "actor_id":
        world.proof.actor_id = uid("other-proof-actor")
    else:
        world.proof.consumed = False
    rejected(
        world,
        lambda: apply(world),
        {"FACT_CONSUMPTION_MATERIAL_CHANGED", "FACT_ACTUAL_FALSE_TRUE_REQUIRED"},
    )
    phase_invalid(world)


def test_historical_consumed_row_cannot_replace_this_real_loaded_transition(world):
    replacement = Confirmation(
        **{key: deepcopy(getattr(world.proof, key)) for key in consumption.FIELDS}, consumed=True
    )
    rejected(
        world,
        lambda: apply(world, proof=replacement),
        {"FACT_LIVE_CONSUMPTION_REQUIRED", "FACT_PERSISTENT_CONFIRMATION_REQUIRED"},
    )
    phase_invalid(world)


@pytest.mark.parametrize("attribute", ["tenant_id", "revision"])
def test_actual_loaded_product_scope_and_revision_are_guarded(world, attribute):
    if attribute == "tenant_id":
        world.product.tenant_id = uid("other-tenant")
        code = "FORBIDDEN_SCOPE"
    else:
        world.product.revision += 1
        code = "VERSION_CONFLICT"
    rejected(world, lambda: apply(world), {code})
    phase_invalid(world)


def test_transient_product_cannot_claim_the_shared_locked_orm_identity(world):
    product = Product(
        id=world.product.id, tenant_id=world.product.tenant_id, revision=world.product.revision
    )
    rejected(world, lambda: apply(world, product=product), {"CANDIDATE_LOADED_PRODUCT_REQUIRED"})


def test_copied_or_constructed_prepare_dto_is_not_a_factory_registered_phase(world):
    for phase in (copy(world.phase), replace(world.phase)):
        rejected(
            world,
            lambda phase=phase: apply(world, phase=phase),
            {"CANDIDATE_PREPARED_OWNER_REQUIRED"},
        )
    assert prepare.reviewed_candidate(world.phase) == owners.prepare.reviewed_candidate(world.phase)


def test_nested_prepared_material_mutation_is_rejected_without_substituting_new_anchor(world):
    world.phase.raw_source_basis[0]["content_hash"] = digest("changed source bytes")
    rejected(world, lambda: apply(world), {"CANDIDATE_PREPARED_BINDING_CHANGED"})
    phase_invalid(world)


def test_expired_loaded_product_never_performs_implicit_refresh_io(world):
    world.w.s.expire(world.product, ["revision"])
    rejected(world, lambda: apply(world), {"CANDIDATE_LOADED_PRODUCT_REQUIRED"})
    phase_invalid(world)


def test_expired_proof_attribute_never_performs_implicit_refresh_io(world):
    world.w.s.expire(world.proof, ["expires_at"])
    rejected(world, lambda: apply(world), {"FACT_LOADED_CONFIRMATION_REQUIRED"})
    phase_invalid(world)


def test_rollback_then_replacement_transaction_cannot_reuse_original_phase(world):
    world.w.s.rollback()
    world.w.s.begin()
    rejected(world, lambda: apply(world), {"FACT_CALLER_UOW_CHANGED"})
    phase_invalid(world)


def test_other_real_session_cannot_reuse_proof_or_prepared_owner(world):
    with Session(bind=world.w.s.get_bind()) as other:
        other.begin()
        rejected(world, lambda: apply(world, s=other), {"FACT_LIVE_CONSUMPTION_REQUIRED"})
    phase_invalid(world)


def test_removed_owner_refresh_port_still_rejects_a_valid_live_marker(world):
    world.w.s.get_bind()._pdos_quality_result_refresh = None
    rejected(world, lambda: apply(world), {"SOURCE_STALE"})
    phase_invalid(world)


def test_withdrawn_source_owner_cannot_be_bypassed_by_valid_proof(world):
    def revoked():
        raise DomainError("SOURCE_UNAVAILABLE", "synthetic withdrawn source", 409)

    world.data.state.source_hook = revoked
    rejected(world, lambda: apply(world), {"SOURCE_UNAVAILABLE"})
    phase_invalid(world)


def test_owner_runtime_replacement_during_refresh_blocks_actual_append(world):
    def changed(values, count):
        world.w.s.get_bind()._pdos_quality_result_refresh = lambda *_a, **_k: None
        return values

    world.data.state.basis_hook = changed
    rejected(world, lambda: apply(world), {"SOURCE_STALE"})
    phase_invalid(world)


def test_nested_bound_change_during_real_owner_io_is_rechecked_before_append(world):
    def changed(value, count):
        world.phase.authority_snapshot["facts_revision"] = digest("mutated prior phase")
        return value

    world.data.state.authority_hook = changed
    rejected(world, lambda: apply(world), {"SOURCE_STALE", "CANDIDATE_PREPARED_BINDING_CHANGED"})
    phase_invalid(world)


def test_proof_replacement_after_owner_io_is_rechecked_before_append(world):
    def changed(value, count):
        world.proof.actor_id = uid("changed after owner io")
        return value

    world.data.state.policy_hook = changed
    rejected(world, lambda: apply(world), {"FACT_CONSUMPTION_MATERIAL_CHANGED"})
    phase_invalid(world)


def test_refresh_preserves_first_full_anchor_with_new_actual_saved_clock(world):
    old_anchor = world.phase.anchor.model_dump(mode="json")
    old_capture = world.marker.consumed_at
    world.w.clock.at += timedelta(seconds=1)
    row, _, _ = apply(world)
    assert row.input_snapshot["stable_anchor"] == old_anchor
    assert row.input_snapshot["proof_consumed_at"] == old_capture.isoformat()
    assert row.created_at > old_capture


def test_other_actual_module_cannot_replace_the_host_registered_semantic_owner(world):
    fake_module = SimpleNamespace(semantic=commands.semantic)
    rejected(world, lambda: apply(world, module=fake_module), {"FACT_HOST_REGISTRY_MISMATCH"})
    phase_invalid(world)


def test_current_pointer_changes_during_final_real_owner_refresh_reject(world):
    stored.successor(world.w)
    rejected(world, lambda: apply(world), {"CANDIDATE_LINEAGE_OWNER_REQUIRED"})
    phase_invalid(world)


def test_new_source_security_epoch_during_owner_refresh_rejects_before_add(world):
    def change(values, count):
        values[0]["hash"] = digest("changed current source bytes")
        return values

    world.data.state.basis_hook = change
    rejected(world, lambda: apply(world), {"SOURCE_STALE"})
    phase_invalid(world)


@pytest.mark.parametrize("kind", ["professional", "policy"])
def test_authority_or_policy_aba_material_change_is_not_hidden_by_true_flags(world, kind):
    def changed(value, count):
        value["facts_revision"] = digest("withdraw restore new epoch")
        return value

    setattr(
        world.data.state, "authority_hook" if kind == "professional" else "policy_hook", changed
    )
    rejected(world, lambda: apply(world), {"SOURCE_STALE"})
    phase_invalid(world)


def test_last_owner_io_crossing_real_proof_expiry_is_not_saved_at_an_earlier_clock(world):
    # Gate succeeds initially. The actual owner call then takes time; do not
    # backdate the saved_at to the earlier proof capture or phase clock.
    def delayed(values, count):
        world.w.clock.at = world.proof.expires_at
        return values

    world.data.state.basis_hook = delayed
    rejected(world, lambda: apply(world), {"FACT_CONSUMPTION_CLOCK_INVALID"})
    assert world.proof.consumed is True
    phase_invalid(world)


def test_final_saved_clock_checks_prepared_professional_activation_boundary(world, monkeypatch):
    original = world.host.require_live
    calls = 0

    def advancing(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 2:
            world.w.clock.at = world.phase.valid_until
        return result

    monkeypatch.setattr(world.host, "require_live", advancing)
    rejected(world, lambda: apply(world), {"SOURCE_STALE"})
    phase_invalid(world)


def test_actual_session_rollback_or_changed_caller_cannot_reuse_consumption(world):
    ctx = Context(world.w.ctx.tenant_id, uid("other-caller"), uid("other-caller"))
    rejected(world, lambda: apply(world, ctx=ctx), {"FACT_CALLER_UOW_CHANGED"})


def test_missing_cross_preview_original_full_anchor_seam_is_explicit_503(world, monkeypatch):
    # A valid common marker can bind its own stored older material. That does
    # not let a newly read anchor substitute the persistent preview full proof.
    older = deepcopy(world.review)
    older["stable_anchor"]["anchor_sha256"] = digest("different first full anchor")
    world.proof.snapshot = older
    # Rebind is deliberately via actual host before any simulated assignment,
    # not by forging a LiveConsumption marker or client-supplied anchor.
    from sqlalchemy.orm.attributes import set_committed_value

    set_committed_value(world.proof, "consumed", False)
    world.host = consumption.ConsumptionHost({writer.OPERATION: commands})
    world.binding = world.host.bind_before_transition(
        world.w.s,
        world.w.ctx,
        world.command,
        world.data.payload,
        commands,
        world.proof,
        reviewed_snapshot=older,
    )
    world.proof.consumed = True
    world.marker = world.host.capture_after_transition(
        world.w.s,
        world.w.ctx,
        world.command,
        world.data.payload,
        commands,
        world.proof,
        binding=world.binding,
    )
    error = rejected(world, lambda: apply(world), {"INTEGRATION_REQUIRED"})
    assert error.status == 503
    phase_invalid(world)


def test_add_failure_leaves_no_reusable_phase_and_no_self_commit(world, monkeypatch):
    def fail(row):
        assert isinstance(row, CapaVerificationEvidence)
        raise RuntimeError("synthetic caller save failure")

    monkeypatch.setattr(world.w.s, "add", fail)
    with pytest.raises(RuntimeError, match="synthetic caller save failure"):
        apply(world)
    assert world.added == [] and not world.w.s.new
    assert world.proof.consumed is True  # Outer common UOW owns rollback.
    phase_invalid(world)
