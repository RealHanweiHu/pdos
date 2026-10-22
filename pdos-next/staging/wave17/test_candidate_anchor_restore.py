"""Real persistent ORM/UOW and actual owner; raw SQL/bytes/authority substitutes.

A detached-loaded row attached to a no-connect Session is not a real DB proof.
"""

from copy import copy, deepcopy
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import candidate_anchor_restore as restore
import candidate_commands as commands
import candidate_write as writer
import pytest
import test_candidate_prepare as owners
from pdos_next.contracts import Command
from pdos_next.errors import DomainError
from pdos_next.models import Confirmation, Product
from pdos_next.service import Context, digest, material_digest
from sqlalchemy import inspect
from sqlalchemy.orm import make_transient_to_detached
from test_anchor_storage import uid


@pytest.fixture
def world(monkeypatch):
    generator = owners.origin_sample.__wrapped__(monkeypatch)
    w = next(generator)
    actual = owners.source_owner.__wrapped__(w, monkeypatch)
    data = owners.work.__wrapped__(actual, monkeypatch)
    payload = data.payload.model_copy(
        update={"confirmation_token": "synthetic-original-proof-token"}
    )
    data.payload = payload
    phase = owners.run(data)
    command = Command(
        command_id=uid("restoring-command"),
        idempotency_key="restoring-original-command",
        operation=commands.OPERATION,
        product_id=w.pid,
        expected_revision=w.memory.first(Product).revision,
        source_read_set=[r.model_dump(mode="json") for r in phase.required_source_read_set],
        payload=payload.model_dump(mode="json"),
    )
    proof = Confirmation(
        id=uid("restoring-proof"),
        tenant_id=w.ctx.tenant_id,
        product_id=w.pid,
        actor_id=w.ctx.actor_id,
        subject_id=w.pid,
        operation=commands.OPERATION,
        revision=command.expected_revision,
        token_hash=digest(payload.confirmation_token),
        payload_digest=material_digest(w.ctx, command, payload, commands),
        snapshot=writer.reviewed_prepared_candidate(phase),
        consumed=False,
        created_at=w.clock.at - timedelta(seconds=1),
        expires_at=w.clock.at + timedelta(minutes=10),
    )
    make_transient_to_detached(proof)
    w.s.add(proof)
    database = {k: deepcopy(getattr(proof, k)) for k in restore.PROOF_COLUMNS}
    state = SimpleNamespace(sql_calls=0, sql_hook=None)

    def execute(query):
        assert query.is_select and query._limit_clause.value == 2
        assert query.get_execution_options().get("autoflush") is False
        assert {c.key for c in query.selected_columns} == set(restore.PROOF_COLUMNS)
        assert len(query._where_criteria) == 3
        state.sql_calls += 1
        if state.sql_hook:
            state.sql_hook(state.sql_calls)
        value = deepcopy(database)
        # Emulate exact tenant/product/id WHERE, not a general identity success.
        for clause in query._where_criteria:
            if value[clause.left.key] != clause.right.value:
                return SimpleNamespace(mappings=lambda: [])
        return SimpleNamespace(mappings=lambda: [value])

    monkeypatch.setattr(w.s, "execute", execute)
    monkeypatch.setattr(restore, "_clock", lambda: w.clock.at)
    host = restore.CandidateAnchorRestoreHost(commands)
    output = SimpleNamespace(
        w=w,
        data=data,
        actual=actual,
        phase=phase,
        command=command,
        payload=payload,
        proof=proof,
        database=database,
        host=host,
        state=state,
        monkeypatch=monkeypatch,
    )
    yield output
    w.s.rollback()
    try:
        next(generator)
    except StopIteration:
        pass


def run(f, **changes):
    return f.host.restore(
        changes.get("s", f.w.s),
        changes.get("ctx", f.w.ctx),
        changes.get("command", f.command),
        changes.get("payload", f.payload),
        changes.get("proof", f.proof),
    )


def rejected(code, action):
    with pytest.raises(DomainError) as caught:
        action()
    assert caught.value.code == code
    return caught.value


def commit_substitute(f):
    """Replace the explicit saved SQL image and loaded ORM committed attributes.

    This fixture helper never performs SQL/commit or pretends it did.
    """
    from sqlalchemy.orm import attributes

    for key, value in f.database.items():
        attributes.set_committed_value(f.proof, key, deepcopy(value))


def test_restore_uses_persistent_entire_snapshot_and_actual_owner_without_consuming(world):
    f = world
    out = run(f)
    assert out.anchor.model_dump(mode="json") == f.database["snapshot"]["stable_anchor"]
    assert out.reviewed_snapshot == f.database["snapshot"]
    assert out.proof_sha256 == digest(f.database)
    assert out.material_sha256 == f.proof.payload_digest
    assert out.command_sha256 == digest(f.command.model_dump(mode="json"))
    assert out.checked_at == f.w.clock.at and out.expires_at == f.proof.expires_at
    assert f.state.sql_calls == 2
    assert inspect(f.proof).persistent and f.proof.consumed is False
    assert not f.w.s.dirty and not f.w.s.new
    assert out.anchor.full_failure_proofs_sha256 == f.phase.anchor.full_failure_proofs_sha256
    assert any(k == "bridge" for k, _ in f.actual.log)


def test_restart_old_result_runtime_stamp_does_not_reseal_original_full_anchor(world):
    f = world
    old = deepcopy(f.database["snapshot"]["stable_anchor"])
    previous = f.w.s.get_bind()._pdos_quality_result_bridge

    def restarted(*args, **kwargs):
        return previous(*args, **kwargs)

    f.w.s.get_bind()._pdos_quality_result_bridge = restarted
    out = run(f)
    assert out.anchor.model_dump(mode="json") == old
    assert out.anchor.anchor_sha256 == old["anchor_sha256"]
    assert out.anchor.failures[0].result.source_basis[
        "runtime_stamp"
    ] != restore.anchor_owner._runtime_stamp(f.w.s)
    assert f.proof.consumed is False


@pytest.mark.parametrize(
    "input_module",
    [
        None,
        {},
        SimpleNamespace(
            OPERATION=commands.OPERATION,
            semantic=commands.semantic,
            CandidateRecordPayload=commands.CandidateRecordPayload,
        ),
    ],
)
def test_startup_requires_actual_module_not_client_configuration(input_module):
    rejected(
        "CANDIDATE_ACTUAL_SEMANTIC_OWNER_REQUIRED",
        lambda: restore.CandidateAnchorRestoreHost(input_module),
    )


def test_module_function_replacement_after_config_is_rejected(world, monkeypatch):
    monkeypatch.setattr(commands, "semantic", lambda _: {})
    # The host and commands point to the same module; actual implementation is
    # fixed below by expected configuration identity, not merely an attribute.
    rejected("CANDIDATE_ACTUAL_SEMANTIC_OWNER_REQUIRED", lambda: run(world))


def test_startup_payload_class_replacement_is_rejected(world, monkeypatch):
    monkeypatch.setattr(commands, "CandidateRecordPayload", type(world.payload).__base__)
    rejected("CANDIDATE_ACTUAL_SEMANTIC_OWNER_REQUIRED", lambda: run(world))


def test_transient_and_detached_proofs_are_not_persistent_truth(world):
    raw = Confirmation(**deepcopy(world.database))
    rejected("FACT_PERSISTENT_CONFIRMATION_REQUIRED", lambda: run(world, proof=raw))
    world.w.s.expunge(world.proof)
    rejected("FACT_PERSISTENT_CONFIRMATION_REQUIRED", lambda: run(world))


def test_expired_or_unloaded_proof_is_rejected_without_loading_or_sql(world):
    world.w.s.expire(world.proof, ["snapshot"])
    rejected("FACT_LOADED_CONFIRMATION_REQUIRED", lambda: run(world))
    assert world.state.sql_calls == 0


def test_consumed_or_dirty_proof_never_restores_old_authority(world):
    world.proof.consumed = True
    rejected("CANDIDATE_UNCONSUMED_CLEAN_PROOF_REQUIRED", lambda: run(world))
    assert world.state.sql_calls == 0


def test_deep_untracked_snapshot_mutation_is_caught_by_raw_persisted_columns(world):
    world.proof.snapshot["payload_semantic"]["reason"] = "dirty untracked text"
    assert not inspect(world.proof).attrs.snapshot.history.has_changes()
    rejected("CANDIDATE_PERSISTED_PROOF_CHANGED", lambda: run(world))
    assert world.state.sql_calls == 1


@pytest.mark.parametrize(
    "field", ["token_hash", "payload_digest", "subject_id", "actor_id", "revision"]
)
def test_exact_proof_binding_fields_cannot_be_substituted(world, field):
    f = world
    f.database[field] = (
        uid("wrong binding")
        if field.endswith("_id")
        else (1 if field == "revision" else digest("wrong binding"))
    )
    commit_substitute(f)
    rejected("CANDIDATE_PROOF_BINDING_MISMATCH", lambda: run(f))


def test_changed_reason_same_token_is_not_same_material(world):
    payload = world.payload.model_copy(update={"reason": "another semantic intent"})
    command = world.command.model_copy(update={"payload": payload.model_dump(mode="json")})
    rejected(
        "CANDIDATE_PROOF_BINDING_MISMATCH", lambda: run(world, command=command, payload=payload)
    )


def test_product_watermark_is_independent_of_issue_revision(world):
    world.w.memory.first(Product).revision += 1
    rejected("VERSION_CONFLICT", lambda: run(world))


@pytest.mark.parametrize("change", ["missing", "extra", "operation"])
def test_review_has_exact_thirteen_keys_and_operation(world, change):
    raw = world.database["snapshot"]
    if change == "missing":
        del raw["policy_snapshot"]
    elif change == "extra":
        raw["approved"] = True
    else:
        raw["operation"] = "quality.capa.followup.link"
    commit_substitute(world)
    rejected(
        "CANDIDATE_REVIEW_MATERIAL_CHANGED"
        if change == "operation"
        else "CANDIDATE_REVIEW_SNAPSHOT_REQUIRED",
        lambda: run(world),
    )


def test_raw_source_keyset_not_whitened_by_typed_null_defaults(world):
    world.database["snapshot"]["raw_source_basis"][0]["original"] = None
    commit_substitute(world)
    rejected("CANDIDATE_REVIEW_MATERIAL_CHANGED", lambda: run(world))


def test_wrong_full_anchor_hash_is_not_rebuilt_from_stable_material(world):
    world.database["snapshot"]["stable_anchor"]["anchor_sha256"] = "f" * 64
    commit_substitute(world)
    rejected("CANDIDATE_REVIEW_SNAPSHOT_REQUIRED", lambda: run(world))


def test_resealed_basis_cannot_change_actual_completed_action_material(world):
    raw = world.database["snapshot"]
    basis = raw["binding"]["basis"]
    basis["actions"][0]["action_sha256"] = digest("unperformed alternative action")
    basis["basis_sha256"] = digest({k: v for k, v in basis.items() if k != "basis_sha256"})
    raw["inspection"]["binding"] = deepcopy(raw["binding"])
    raw["inspection"]["inspection_sha256"] = digest(
        {
            k: v
            for k, v in raw["inspection"].items()
            if k not in {"inspection_sha256", "candidate_ref"}
        }
    )
    commit_substitute(world)
    rejected("CANDIDATE_REVIEW_MATERIAL_CHANGED", lambda: run(world))


def test_actual_original_source_change_blocks_restore(world):
    world.data.raw[0]["hash"] = digest("withdrawn or changed raw source")
    rejected("SOURCE_STALE", lambda: run(world))


def test_current_successor_remains_missing_without_limited_lineage_owner(world, monkeypatch):
    original = restore.anchor_owner.read_anchor_from_actual_owner

    def successor(*args):
        value = original(*args)
        return value.model_copy(update={"needs_lineage_owner": True})

    monkeypatch.setattr(restore.anchor_owner, "read_anchor_from_actual_owner", successor)
    assert rejected("CANDIDATE_LINEAGE_OWNER_REQUIRED", lambda: run(world)).status == 503


def test_last_raw_sql_proof_change_is_not_hidden_by_identity_map(world):
    def change(call):
        if call == 2:
            world.database["consumed"] = True

    world.state.sql_hook = change
    rejected("CANDIDATE_PERSISTED_PROOF_CHANGED", lambda: run(world))
    assert world.proof.consumed is False


def test_last_raw_sql_snapshot_change_is_rejected_even_when_loaded_orm_unchanged(world):
    world.state.sql_hook = lambda call: (
        world.database["snapshot"].update(policy_snapshot={"changed": True}) if call == 2 else None
    )
    rejected("CANDIDATE_PERSISTED_PROOF_CHANGED", lambda: run(world))


def test_runtime_issuer_revoke_restore_aba_during_source_io_is_rejected(world):
    world.data.state.source_hook = lambda: setattr(
        world.w.s.get_bind(), "_pdos_quality_policy_epochs", {"issuer": 2}
    )
    rejected("SOURCE_STALE", lambda: run(world))


def test_post_io_final_grant_clock_crossing_proof_expiry_is_rejected(world):
    clock = world.w.clock
    # At the final proof SQL all owner reads have finished; advance only there.
    world.state.sql_hook = lambda call: (
        setattr(clock, "at", world.proof.expires_at) if call == 2 else None
    )
    rejected("CANDIDATE_PROOF_EXPIRED", lambda: run(world))


def test_final_caller_write_permission_change_is_rejected(world):
    world.state.sql_hook = lambda call: (
        setattr(world.w.grant, "can_write", False) if call == 2 else None
    )
    rejected("FORBIDDEN_SCOPE", lambda: run(world))


def test_nested_uow_changed_by_raw_proof_query_is_rejected(world):
    world.state.sql_hook = lambda call: world.w.s.begin_nested() if call == 2 else None
    rejected("FACT_CALLER_UOW_CHANGED", lambda: run(world))


def test_registered_restore_cannot_be_constructed_copied_or_used_by_other_host(world):
    out = run(world)
    for false in (copy(out), replace(out)):
        rejected(
            "CANDIDATE_RESTORED_OWNER_REQUIRED",
            lambda false=false: world.host.require_restored(
                world.w.s, world.w.ctx, world.command, world.payload, world.proof, false
            ),
        )
    other = restore.CandidateAnchorRestoreHost(commands)
    rejected(
        "CANDIDATE_RESTORED_OWNER_REQUIRED",
        lambda: other.require_restored(
            world.w.s, world.w.ctx, world.command, world.payload, world.proof, out
        ),
    )


def test_registered_original_uow_cannot_be_replaced_with_a_new_savepoint(world):
    out = run(world)
    world.w.s.begin_nested()
    object.__setattr__(out, "uow", restore.guards._uow(world.w.s))
    rejected(
        "CANDIDATE_RESTORED_BINDING_CHANGED",
        lambda: world.host.require_restored(
            world.w.s, world.w.ctx, world.command, world.payload, world.proof, out
        ),
    )


def test_post_io_final_grant_query_clock_crossing_expiry_is_rejected(world, monkeypatch):
    old = restore.guards._one
    grant_queries = []

    def advancing(s, model, *where):
        value = old(s, model, *where)
        if model is restore.Grant and world.state.sql_calls == 2:
            grant_queries.append(value)
            world.w.clock.at = value.expires_at
        return value

    monkeypatch.setattr(restore.guards, "_one", advancing)
    rejected("CANDIDATE_PROOF_EXPIRED", lambda: run(world))
    assert len(grant_queries) == 1


def test_final_principal_inactivation_cannot_restore_current_human_binding(world):
    principal = world.w.memory.first(restore.Principal)
    world.state.sql_hook = lambda call: setattr(principal, "active", False) if call == 2 else None
    rejected("FORBIDDEN_SCOPE", lambda: run(world))


def test_restored_full_command_order_key_and_original_snapshot_binding_remains_exact(world):
    out = run(world)
    changed = world.command.model_copy(update={"idempotency_key": "different-original-key"})
    rejected(
        "CANDIDATE_RESTORED_BINDING_CHANGED",
        lambda: world.host.require_restored(
            world.w.s, world.w.ctx, changed, world.payload, world.proof, out
        ),
    )
    assert world.proof.consumed is False


def test_require_restored_independently_reads_owner_and_preserves_original(world):
    out = run(world)
    before = world.state.sql_calls
    fresh = world.host.require_restored(
        world.w.s, world.w.ctx, world.command, world.payload, world.proof, out
    )
    assert fresh is out and world.state.sql_calls == before + 2
    assert out.anchor.model_dump(mode="json") == world.database["snapshot"]["stable_anchor"]


def test_restore_intrusion_and_changed_caller_cannot_reuse_registration(world):
    out = run(world)
    object.__setattr__(out, "expires_at", out.expires_at + timedelta(days=1))
    rejected(
        "CANDIDATE_RESTORED_BINDING_CHANGED",
        lambda: world.host.require_restored(
            world.w.s, world.w.ctx, world.command, world.payload, world.proof, out
        ),
    )
    clean = run(world)
    other = Context(world.w.ctx.tenant_id, uid("another human"), uid("another human"))
    rejected(
        "CANDIDATE_RESTORED_BINDING_CHANGED",
        lambda: world.host.require_restored(
            world.w.s, other, world.command, world.payload, world.proof, clean
        ),
    )
