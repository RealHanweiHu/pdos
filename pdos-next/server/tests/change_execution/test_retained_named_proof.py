"""Retained named decisions use their real consumed Confirmation; no database."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next import change_implementation_owner as owner
from pdos_next import change_order_service
from pdos_next.errors import DomainError
from pdos_next.models import Confirmation
from pdos_next.service import Context, digest

OPERATIONS = (
    "change.selection.decide",
    "change.order.approve",
    "change.order.prepare",
    "change.implementation.record",
)
AT = datetime(2026, 10, 17, 12, tzinfo=UTC)


def retained(monkeypatch, operation, expires_at):
    tenant_id, product_id, actor_id, command_id = (uuid4() for _ in range(4))
    ctx = Context(tenant_id, actor_id, actor_id)
    review = {"actual_material": "fixed reviewed original", "revision": 3}
    proof = Confirmation(
        id=uuid4(),
        tenant_id=tenant_id,
        product_id=product_id,
        actor_id=actor_id,
        subject_id=product_id,
        operation=operation,
        revision=7,
        token_hash=digest("named consumed token"),
        payload_digest=digest(review),
        snapshot=deepcopy(review),
        created_at=AT - timedelta(minutes=2),
        expires_at=expires_at,
        consumed=True,
    )
    atom = SimpleNamespace(
        shared_proof_id=proof.id,
        shared_proof_revision=proof.revision,
        actor_id=actor_id,
        operation=operation,
        token_sha256=proof.token_hash,
        material_sha256=proof.payload_digest,
        input_snapshot={"review": deepcopy(review)},
        proof_consumed_at=AT - timedelta(seconds=1),
        created_at=AT,
        proof_expires_at=expires_at,
        command_id=command_id,
        intent_digest=digest({"operation": operation, "review": review}),
    )
    group = {
        "receipt": {
            "command_id": command_id,
            "intent_digest": atom.intent_digest,
            "actor_id": actor_id,
        }
    }
    session, reads = object(), []

    def one(s, model, *where):
        assert s is session and model is Confirmation
        assert {clause.left.name: clause.right.value for clause in where} == {
            "tenant_id": tenant_id,
            "product_id": product_id,
            "id": proof.id,
        }
        reads.append(proof.id)
        return proof

    monkeypatch.setattr(change_order_service, "_one", one)
    return SimpleNamespace(
        session=session,
        ctx=ctx,
        product_id=product_id,
        proof=proof,
        atom=atom,
        group=group,
        reads=reads,
    )


def verify(work):
    result = owner._atom_proof(work.session, work.ctx, work.product_id, work.atom, work.group)
    assert work.reads == [work.proof.id]
    return result


@pytest.mark.parametrize("operation", OPERATIONS[:2])
def test_retained_named_t2_decision_accepts_consumed_proof_without_ttl(monkeypatch, operation):
    work = retained(monkeypatch, operation, None)

    assert verify(work) is None
    assert work.proof.consumed is True
    assert work.proof.expires_at is work.atom.proof_expires_at is None


@pytest.mark.parametrize("operation", OPERATIONS[2:])
def test_retained_t1_confirmation_still_requires_deadline(monkeypatch, operation):
    work = retained(monkeypatch, operation, None)

    with pytest.raises(DomainError) as error:
        verify(work)
    assert error.value.reason == "IMPLEMENTATION_GROUP_MISMATCH"


@pytest.mark.parametrize("operation", OPERATIONS)
def test_retained_explicit_deadline_still_rejects_expired_proof(monkeypatch, operation):
    # The confirmation was current when consumed, but expired before the saved
    # atom. A named decision's optional declared deadline is still binding.
    work = retained(monkeypatch, operation, AT - timedelta(microseconds=1))

    with pytest.raises(DomainError) as error:
        verify(work)
    assert error.value.reason == "IMPLEMENTATION_GROUP_MISMATCH"


@pytest.mark.parametrize("mismatch", ["consumption", "material", "review", "command"])
def test_no_ttl_selection_still_requires_exact_consumed_material_and_receipt(monkeypatch, mismatch):
    work = retained(monkeypatch, "change.selection.decide", None)
    if mismatch == "consumption":
        work.proof.consumed = False
    elif mismatch == "material":
        work.proof.payload_digest = digest("different material")
    elif mismatch == "review":
        work.proof.snapshot = {"actual_material": "different original", "revision": 3}
    else:
        work.group["receipt"]["command_id"] = uuid4()

    with pytest.raises(DomainError) as error:
        verify(work)
    assert error.value.reason == "IMPLEMENTATION_GROUP_MISMATCH"
