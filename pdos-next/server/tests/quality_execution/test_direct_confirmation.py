"""Pure common-confirmation protocol; actual ACL/CAS/rollback are tested separately."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next import service as common
from pdos_next.contracts import Command
from pdos_next.domain.quality_execution import service
from pdos_next.domain.quality_execution.schemas import IssueTriagePayload
from pdos_next.errors import DomainError


def material():
    ctx = common.Context(uuid4(), uuid4(), uuid4(), category_id=uuid4())
    payload = IssueTriagePayload(
        issue_id=uuid4(), expected_issue_revision=1, reason="Named direct triage"
    )
    command = Command(
        command_id=uuid4(),
        idempotency_key=str(uuid4()),
        operation="quality.issue.triage",
        category_id=ctx.category_id,
        product_id=uuid4(),
        expected_revision=1,
        source_read_set=[{"artifact_id": uuid4(), "expected_revision": 1}],
        payload=payload.model_dump(mode="json"),
    )
    return ctx, command, payload


@pytest.mark.parametrize("changed", ["payload", "issue", "issue_revision", "read", "actor"])
def test_material_digest_binds_direct_payload_object_reads_and_actual_actor(changed):
    ctx, command, payload = material()
    original = common.material_digest(ctx, command, payload, service)
    if changed == "payload":
        payload = payload.model_copy(update={"reason": "A different named decision"})
    elif changed == "issue":
        payload = payload.model_copy(update={"issue_id": uuid4()})
    elif changed == "issue_revision":
        payload = payload.model_copy(update={"expected_issue_revision": 2})
    elif changed == "read":
        command = command.model_copy(update={"source_read_set": []})
    else:
        ctx = replace(ctx, actor_id=uuid4())
    assert common.material_digest(ctx, command, payload, service) != original


def test_material_identity_ignores_only_transport_keys_and_the_confirmation_token():
    ctx, command, payload = material()
    original = common.material_digest(ctx, command, payload, service)
    renamed = command.model_copy(update={"command_id": uuid4(), "idempotency_key": str(uuid4())})
    confirmed = payload.model_copy(update={"confirmation_token": "t" * 32})
    assert common.material_digest(ctx, renamed, confirmed, service) == original


def proof(monkeypatch):
    ctx, command, payload = material()
    payload = payload.model_copy(update={"confirmation_token": "t" * 32})
    command = command.model_copy(update={"payload": payload.model_dump(mode="json")})
    owner_material = {"contract": "s0.direct-quality.v1", "mutation": {"saved": True}}
    confirmation = SimpleNamespace(
        consumed=False,
        payload_digest=common.material_digest(ctx, command, payload, service),
        snapshot={"contract": "s0.direct-confirmation.v1", "owner_material": owner_material},
    )
    monkeypatch.setattr(
        common,
        "confirmation_subject",
        lambda *args: ("quality_issue", payload.issue_id, payload.expected_issue_revision),
    )
    monkeypatch.setattr(common, "confirmation_for", lambda *args, **kwargs: confirmation)
    return ctx, command, payload, confirmation, owner_material


@pytest.mark.parametrize("invalid", ["digest", "null", "contract", "owner_material"])
def test_unbound_saved_preview_is_rejected_before_owner_preparation(monkeypatch, invalid):
    ctx, command, payload, confirmation, _ = proof(monkeypatch)
    if invalid == "digest":
        confirmation.payload_digest = "0" * 64
    elif invalid == "null":
        confirmation.snapshot = None
    elif invalid == "contract":
        confirmation.snapshot["contract"] = "unregistered-preview"
    else:
        confirmation.snapshot["owner_material"] = []

    def unexpected(*args):
        raise AssertionError("Unbound preview must not prepare or apply a mutation")

    module = SimpleNamespace(semantic=service.semantic, prepare_confirmed=unexpected)
    with pytest.raises(DomainError) as raised:
        common.consume_direct_confirmation(
            object(), ctx, command, SimpleNamespace(id=command.product_id), payload, module
        )
    assert raised.value.reason == "CONFIRMATION_SCOPE_CHANGED"
    assert confirmation.consumed is False


def test_owner_current_failure_preserves_unconsumed_confirmation(monkeypatch):
    ctx, command, payload, confirmation, _ = proof(monkeypatch)
    failure = DomainError("SOURCE_STALE", "The actual direct source changed")

    def rejected(*args):
        assert confirmation.consumed is False
        raise failure

    module = SimpleNamespace(semantic=service.semantic, prepare_confirmed=rejected)
    with pytest.raises(DomainError) as raised:
        common.consume_direct_confirmation(
            object(), ctx, command, SimpleNamespace(id=command.product_id), payload, module
        )
    assert raised.value is failure
    assert confirmation.consumed is False


def test_owner_receives_exact_saved_mutation_before_common_consumes(monkeypatch):
    ctx, command, payload, confirmation, saved = proof(monkeypatch)
    session, product, phase = object(), SimpleNamespace(id=command.product_id), object()
    original = deepcopy(saved)

    def prepare(s, caller, submitted, target, data, owner_material):
        assert (s, caller, submitted, target, data) == (session, ctx, command, product, payload)
        assert owner_material is saved and owner_material == original
        assert confirmation.consumed is False
        return phase

    module = SimpleNamespace(semantic=service.semantic, prepare_confirmed=prepare)
    assert (
        common.consume_direct_confirmation(session, ctx, command, product, payload, module) is phase
    )
    assert confirmation.consumed is True
    assert saved == original
