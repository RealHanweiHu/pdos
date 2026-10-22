"""No-connect ORM history and clock checks; no real T2 or publication is issued."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, make_transient_to_detached
from sqlalchemy.orm.attributes import set_committed_value

from pdos_next.contracts import Command
from pdos_next.domain.manufacturing_baseline import consumption
from pdos_next.domain.manufacturing_baseline import publication_rules as rules
from pdos_next.domain.manufacturing_baseline import publication_schemas as schemas
from pdos_next.errors import DomainError
from pdos_next.models import Confirmation
from pdos_next.service import Context, digest, material_digest

from .test_preparation import frame as preparation_frame


def frame(*, expiry=None, created=None):
    tenant, actor, product, category = (uuid4() for _ in range(4))
    ctx = Context(tenant, actor, actor, category_id=category)
    source = {"artifact_id": uuid4(), "expected_revision": 1, "line": 1, "quote": "固定原文"}
    payload = schemas.PublishPayload(
        project_id=uuid4(),
        baseline={"kind": "manufacturing_baseline", "id": uuid4(), "revision": 1},
        purpose="固定用途",
        applicability={"sources": [source]},
        reason="具名固定本轮资料",
        sources=[source],
        approval_token="explicit-pure-approval-token-substitute",
    )
    command = Command(
        command_id=uuid4(),
        idempotency_key=str(uuid4()),
        operation=schemas.OPERATION,
        category_id=category,
        product_id=product,
        expected_revision=4,
        source_read_set=[{"artifact_id": source["artifact_id"], "expected_revision": 1}],
        payload=payload.model_dump(mode="json"),
    )
    proof = Confirmation(
        id=uuid4(),
        tenant_id=tenant,
        product_id=product,
        actor_id=actor,
        subject_id=product,
        operation=command.operation,
        revision=4,
        consumed=False,
        token_hash=digest(payload.approval_token),
        payload_digest=material_digest(ctx, command, payload, rules),
        snapshot={"explicit": "owner IO is outside this no-connect check"},
        created_at=created or datetime.now(UTC) - timedelta(seconds=1),
        expires_at=expiry,
    )
    make_transient_to_detached(proof)  # An ORM-history substitute, not a database read.
    s = Session(bind=SimpleNamespace())
    s.begin()
    s.add(proof)
    host = consumption.ConsumptionHost({schemas.OPERATION: rules})

    def no_io(*args, **kwargs):
        raise AssertionError("Consumption hooks must not perform IO or COMMIT")

    for method in ("execute", "scalar", "scalars", "flush", "commit"):
        setattr(s, method, no_io)

    def bind():
        return host.bind_before_transition(
            s, ctx, command, payload, rules, proof, reviewed_snapshot=proof.snapshot
        )

    def capture(binding):
        return host.capture_after_transition(
            s, ctx, command, payload, rules, proof, binding=binding
        )

    def live(binding, marker, **updates):
        args = dict(
            s=s,
            ctx=ctx,
            command=command,
            payload=payload,
            module=rules,
            proof=proof,
            binding=binding,
            marker=marker,
        )
        return host.require_live(**(args | updates))

    return SimpleNamespace(**locals())


@pytest.mark.parametrize("finite", [False, True])
def test_t2_actual_false_true_history_retains_optional_declared_deadline(finite):
    expiry = datetime.now(UTC) + timedelta(minutes=5) if finite else None
    f = frame(expiry=expiry)
    binding = f.bind()
    f.proof.consumed = True
    marker = f.capture(binding)
    assert f.live(binding, marker) is marker
    assert marker.tier == "T2" and marker.expires_at == expiry
    assert marker.storage_columns()["proof_expires_at"] == expiry
    assert marker.proof_id == f.proof.id and marker.token_sha256 == digest(f.payload.approval_token)
    assert f.capture(binding) is marker  # Keeps the first transition clock.


@pytest.mark.parametrize("invalid", ["expired", "naive", "future_creation"])
def test_t2_declared_bad_clock_is_not_ignored(invalid):
    at = datetime.now(UTC)
    f = frame(
        expiry=at - timedelta(seconds=1)
        if invalid == "expired"
        else (at.replace(tzinfo=None) if invalid == "naive" else None),
        created=at + timedelta(hours=1) if invalid == "future_creation" else None,
    )
    binding = f.bind()
    f.proof.consumed = True
    with pytest.raises(DomainError, match="活动事务绑定") as error:
        f.capture(binding)
    assert error.value.reason == "FACT_CONSUMPTION_CLOCK_INVALID"


def test_t1_cannot_omit_its_confirmation_deadline():
    f = preparation_frame()
    set_committed_value(f.proof, "expires_at", None)
    binding = f.bind()
    f.proof.consumed = True
    with pytest.raises(DomainError) as error:
        f.capture(binding)
    assert error.value.reason == "FACT_CONSUMPTION_CLOCK_INVALID"


def test_t2_bound_but_untransitioned_history_is_not_consumption():
    f = frame()
    binding = f.bind()
    with pytest.raises(DomainError) as error:
        f.capture(binding)
    assert error.value.reason == "FACT_ACTUAL_FALSE_TRUE_REQUIRED"


def test_t2_historical_consumed_row_does_not_grant_this_invocation_a_marker():
    f = frame()
    set_committed_value(f.proof, "consumed", True)
    with pytest.raises(DomainError) as error:
        f.bind()
    assert error.value.reason == "FACT_UNCONSUMED_MATERIAL_BINDING_REQUIRED"


def test_t2_unbounded_deadline_does_not_skip_context_and_material_binding():
    f = frame()
    binding = f.bind()
    f.proof.consumed = True
    marker = f.capture(binding)
    another = Context(f.tenant, uuid4(), f.actor, category_id=f.category)
    with pytest.raises(DomainError):
        f.live(binding, marker, ctx=another)
    f.proof.snapshot["different"] = "saved material changed"
    with pytest.raises(DomainError) as error:
        f.live(binding, marker)
    assert error.value.reason == "FACT_CONSUMPTION_MATERIAL_CHANGED"


def test_t2_expiry_crossed_after_owner_io_is_still_rejected(monkeypatch):
    instant = datetime.now(UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant

    monkeypatch.setattr(consumption, "datetime", Clock)
    # Clock is also used as the isinstance target in the hook.
    created = Clock.fromisoformat((instant - timedelta(seconds=1)).isoformat())
    f = frame(expiry=instant + timedelta(seconds=1), created=created)
    binding = f.bind()
    f.proof.consumed = True
    marker = f.capture(binding)
    instant += timedelta(seconds=2)  # Explicit pure substitute for elapsed owner IO.
    with pytest.raises(DomainError) as error:
        f.live(binding, marker)
    assert error.value.reason == "FACT_CONSUMPTION_CLOCK_INVALID"
