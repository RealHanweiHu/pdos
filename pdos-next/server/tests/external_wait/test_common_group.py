"""Server-owned run correlation must survive retained shared receipt verification."""

from types import SimpleNamespace as N
from uuid import uuid4

import pytest

from pdos_next import change_implementation_owner as owner
from pdos_next import change_order_service
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Outbox, Receipt


@pytest.mark.parametrize("kind", ["human", "legacy_run", "agent_run"])
def test_common_group_uses_actual_receipt_correlation(monkeypatch, kind):
    tenant, person, pid, identity, rid, command, legacy, agent = [uuid4() for _ in range(8)]
    receipt = N(
        id=rid,
        tenant_id=tenant,
        product_id=pid,
        actor_id=person,
        requester_id=person,
        command_id=command,
        operation="work.external_wait.record",
        subject_type="external_wait",
        subject_id=identity,
        subject_revision=1,
        intent_digest="intent",
        request_digest="request",
        visibility="category",
        result={"id": str(identity), "revision": 1},
        created_at=None,
        run_id=legacy if kind == "legacy_run" else None,
        agent_run_id=agent if kind == "agent_run" else None,
    )
    correlation = receipt.agent_run_id or receipt.run_id or command
    values = {
        Receipt: receipt,
        Audit: N(id=uuid4(), receipt_id=rid, actor_id=person, operation=receipt.operation),
        Outbox: N(
            id=uuid4(),
            receipt_id=rid,
            type="external_wait.recorded",
            actor_id=person,
            correlation_id=correlation,
            subject_id=identity,
            subject_revision=1,
        ),
    }
    monkeypatch.setattr(change_order_service, "_one", lambda s, model, *args: values[model])
    s = N(scalars=lambda *a: [object()])
    row = N(id=identity, revision=1, visibility="category")
    ctx = N(tenant_id=tenant, actor_id=person)
    result = owner.common_group(
        s, ctx, pid, row, operation=receipt.operation, event="external_wait.recorded"
    )
    assert result["outbox"]["correlation_id"] == correlation
    values[Outbox].correlation_id = uuid4()
    with pytest.raises(DomainError):
        owner.common_group(
            s, ctx, pid, row, operation=receipt.operation, event="external_wait.recorded"
        )
