"""Real Session/ORM history, detached-loaded row substitute, no DB/qualification."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import fact_consumption as consumption
import pytest
from pdos_next.contracts import Command, StrictModel
from pdos_next.errors import DomainError
from pdos_next.models import Confirmation
from pdos_next.service import Context, digest, material_digest
from sqlalchemy.orm import Session, attributes, make_transient_to_detached


class Payload(StrictModel):
    visibility: str = "private"
    reason: str
    confirmation_token: str | None = None
    approval_token: str | None = None


def frame(operation="quality.capa.observation.record", *, nested=False):
    pid, actor, tenant = uuid4(), uuid4(), uuid4()
    ctx = Context(tenant, actor, actor)
    tier = consumption.TIERS[operation]
    payload = Payload(
        reason="explicit synthetic ORM-history fixture",
        **{
            "approval_token" if tier == "T2" else "confirmation_token": "synthetic-token-not-real",
        },
    )
    module = SimpleNamespace(
        semantic=lambda p: p.model_dump(
            mode="json", exclude={"approval_token", "confirmation_token"}
        )
    )
    command = Command(
        command_id=uuid4(),
        idempotency_key=str(uuid4()),
        operation=operation,
        product_id=pid,
        expected_revision=7,
        source_read_set=[
            {
                "artifact_id": uuid4(),
                "expected_revision": 2,
            }
        ],
        payload=payload.model_dump(mode="json"),
    )
    snapshot = {"synthetic": "reviewed material, not owner attest"}
    proof = Confirmation(
        id=uuid4(),
        tenant_id=tenant,
        product_id=pid,
        subject_id=pid,
        actor_id=actor,
        operation=operation,
        revision=7,
        consumed=False,
        token_hash=digest("synthetic-token-not-real"),
        payload_digest=material_digest(ctx, command, payload, module),
        snapshot=snapshot,
        created_at=datetime.now(UTC) - timedelta(seconds=10),
        expires_at=datetime.now(UTC) + timedelta(minutes=3),
    )
    # This is explicitly a row substitute: no database ever returned this row.
    # SQLAlchemy still supplies real persistent state and attribute history.
    make_transient_to_detached(proof)
    s = Session(bind=SimpleNamespace())
    s.begin()
    if nested:
        s.begin_nested()
    s.add(proof)

    def no_io(*args, **kwargs):
        raise AssertionError("Consumption hook performed forbidden IO/flush/commit")

    for name in ("execute", "scalar", "scalars", "flush", "commit"):
        setattr(s, name, no_io)
    host = consumption.ConsumptionHost({operation: module})

    def bind():
        return host.bind_before_transition(
            s, ctx, command, payload, module, proof, reviewed_snapshot=snapshot
        )

    def capture(binding):
        return host.capture_after_transition(
            s, ctx, command, payload, module, proof, binding=binding
        )

    def live(original_binding, original_marker, **overrides):
        args = dict(
            s=s,
            ctx=ctx,
            command=command,
            payload=payload,
            module=module,
            proof=proof,
            binding=original_binding,
            marker=original_marker,
        )
        args.update(overrides)
        return host.require_live(**args)

    return SimpleNamespace(**locals())


@pytest.mark.parametrize("operation", tuple(consumption.TIERS))
def test_actual_history_retains_first_clock_and_common_semantic(operation):
    f = frame(operation)
    binding = f.bind()
    before = datetime.now(UTC)
    f.proof.consumed = True  # The test emulates the common consumer's assignment.
    marker = f.capture(binding)
    after = datetime.now(UTC)
    assert before <= marker.consumed_at <= after
    assert f.capture(binding) is marker
    assert f.live(binding, marker) is marker
    assert marker.tier == consumption.TIERS[operation]
    assert marker.common_intent_sha256 == digest(
        {
            "operation": operation,
            "product": f.pid,
            "payload": f.module.semantic(f.payload),
            "named_actor": f.actor,
            "source_revision": None,
            "private_owner": f.actor,
        }
    )
    assert marker.common_intent_sha256 != digest(f.module.semantic(f.payload))
    assert marker.storage_columns()["proof_consumed_at"] == marker.consumed_at
    assert "synthetic-token-not-real" not in repr(marker)


@pytest.mark.parametrize("state", ("false", "historical_true", "flushed_transition"))
def test_cannot_mint_transition_from_historical_or_flushed_state(state):
    f = frame()
    binding = f.bind()
    if state == "historical_true":
        attributes.set_committed_value(f.proof, "consumed", True)
    elif state == "flushed_transition":
        f.proof.consumed = True
        # Emulates the loss of change history AFTER a flush; no DB was called.
        attributes.set_committed_value(f.proof, "consumed", True)
    with pytest.raises(DomainError) as failure:
        f.capture(binding)
    assert failure.value.code == "FACT_ACTUAL_FALSE_TRUE_REQUIRED"


@pytest.mark.parametrize(
    "changed",
    (
        "actor",
        "operation",
        "revision",
        "snapshot",
        "token",
        "command",
        "source_read",
        "module",
    ),
)
def test_material_or_identity_change_cannot_reuse_marker(changed):
    f = frame()
    binding = f.bind()
    f.proof.consumed = True
    marker = f.capture(binding)
    overrides = {}
    if changed == "actor":
        overrides["ctx"] = Context(f.tenant, uuid4(), uuid4())
    elif changed == "operation":
        f.proof.operation = "quality.capa.verification.review"
    elif changed == "revision":
        f.proof.revision += 1
    elif changed == "snapshot":
        f.proof.snapshot = {"changed": True}
    elif changed == "token":
        f.proof.token_hash = digest("different")
    elif changed == "command":
        overrides["command"] = f.command.model_copy(update={"idempotency_key": str(uuid4())})
    elif changed == "source_read":
        overrides["command"] = f.command.model_copy(update={"source_read_set": []})
    else:
        overrides["module"] = SimpleNamespace(semantic=f.module.semantic)
    with pytest.raises(DomainError):
        f.live(binding, marker, **overrides)


def test_forged_marker_or_binding_is_not_host_issued():
    f = frame()
    binding = f.bind()
    f.proof.consumed = True
    marker = f.capture(binding)
    for overrides in ({"marker": replace(marker)}, {"binding": replace(binding)}):
        with pytest.raises(DomainError):
            f.live(binding, marker, **overrides)


@pytest.mark.parametrize("alteration", ("ended", "rollback", "new_savepoint", "failed_session"))
def test_changed_or_failed_real_transaction_rejects(alteration):
    f = frame(nested=alteration == "rollback")
    binding = f.bind()
    f.proof.consumed = True
    marker = f.capture(binding)
    if alteration == "ended":
        f.s.get_transaction().close()
    elif alteration == "rollback":
        f.s.get_nested_transaction().rollback()
    elif alteration == "new_savepoint":
        # Explicitly emulates a prior external flush, then creates a genuine
        # SAVEPOINT. The clean real ORM flush performs no DB connection/SQL.
        attributes.set_committed_value(f.proof, "consumed", True)
        attributes.instance_state(f.proof)._commit_all(f.proof.__dict__, f.s.identity_map)
        f.s.flush = Session.flush.__get__(f.s)
        f.s.begin_nested()
        f.s.flush = f.no_io
    else:
        from sqlalchemy.orm.session import SessionTransactionState

        f.s.get_transaction()._state = SessionTransactionState.DEACTIVE
    with pytest.raises(DomainError):
        f.live(binding, marker)


def test_real_savepoint_supported_without_treating_it_as_root():
    f = frame(nested=True)
    binding = f.bind()
    f.proof.consumed = True
    marker = f.capture(binding)
    assert f.live(binding, marker) is marker


@pytest.mark.parametrize("bad_clock", ("expired", "naive", "future_created"))
def test_real_capture_clock_enforces_original_expiry(bad_clock):
    f = frame()
    if bad_clock == "expired":
        f.proof.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    elif bad_clock == "naive":
        f.proof.expires_at = datetime.now()
    else:
        f.proof.created_at = datetime.now(UTC) + timedelta(days=1)
    binding = f.bind()
    f.proof.consumed = True
    with pytest.raises(DomainError) as failure:
        f.capture(binding)
    assert failure.value.code == "FACT_CONSUMPTION_CLOCK_INVALID"


def test_after_owner_io_live_check_uses_fresh_real_clock(monkeypatch):
    f = frame()
    binding = f.bind()
    f.proof.consumed = True
    marker = f.capture(binding)

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return f.proof.expires_at + timedelta(microseconds=1)

    monkeypatch.setattr(consumption, "datetime", Later)
    with pytest.raises(DomainError) as failure:
        f.live(binding, marker)
    assert failure.value.code == "FACT_CONSUMPTION_CLOCK_INVALID"


def test_expired_or_unloaded_object_cannot_trigger_lazy_sql():
    f = frame()
    f.s.expire(f.proof, ["snapshot"])
    with pytest.raises(DomainError) as failure:
        f.bind()
    assert failure.value.code == "FACT_LOADED_CONFIRMATION_REQUIRED"


def test_pending_delete_cannot_establish_a_live_proof():
    f = frame()
    f.s.delete(f.proof)
    with pytest.raises(DomainError) as failure:
        f.bind()
    assert failure.value.code == "FACT_PERSISTENT_CONFIRMATION_REQUIRED"


def test_no_host_only_import_or_old_operation_registration():
    for operation in ("quality.capa.verification.rule.import", "quality.capa.followup.link"):
        with pytest.raises(DomainError) as failure:
            consumption.ConsumptionHost({operation: SimpleNamespace(semantic=lambda p: {})})
        assert failure.value.code == "FACT_HOST_REGISTRY_REQUIRED"
