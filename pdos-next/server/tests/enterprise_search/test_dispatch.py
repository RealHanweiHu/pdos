"""Projection delivery identities and failure propagation, without a Temporal service."""

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from pdos_next.dispatch.outbox import Envelope
from pdos_next.enterprise_search.events import ProjectionSender
from pdos_next.enterprise_search.workflow import EnterpriseProjection
from pdos_next.workflows.transport import TemporalSender


def envelope(kind="artifact.registered"):
    return Envelope(
        **{
            key: str(uuid4())
            for key in (
                "event_id",
                "tenant_id",
                "category_id",
                "subject_id",
                "correlation_id",
                "lease_id",
                "actor_id",
                "requester_id",
            )
        },
        product_id=None,
        subject_revision=1,
        event_type=kind,
        schema_version=1,
    )


def test_projection_ack_keeps_durable_identity_and_replay_is_idempotent():
    class Client:
        calls = []

        async def start_workflow(self, target, reference, **options):
            self.calls.append((target, reference, options))
            if len(self.calls) > 1:
                raise WorkflowAlreadyStartedError(options["id"], "EnterpriseProjection")

    client, event = Client(), envelope()
    sender = TemporalSender(client, projection_sender=ProjectionSender(client))
    first, second = asyncio.run(sender(event)), asyncio.run(sender(event))
    assert first == second == f"pdos-enterprise-projection:{event.tenant_id}:{event.event_id}"
    target, reference, options = client.calls[0]
    assert target == EnterpriseProjection.run
    assert reference["event_id"] == event.event_id and "text" not in reference
    assert options["id_conflict_policy"] is WorkflowIDConflictPolicy.USE_EXISTING
    assert options["id_reuse_policy"] is WorkflowIDReusePolicy.REJECT_DUPLICATE
    assert asyncio.run(sender(replace(event, event_type="unrelated.event"))) is None


def test_projection_start_failure_remains_unknown_for_outbox_retry():
    class Client:
        async def start_workflow(self, *_args, **_kwargs):
            raise OSError("Synthetic connection uncertainty")

    sender = TemporalSender(Client(), projection_sender=ProjectionSender(Client()))
    with pytest.raises(OSError):
        asyncio.run(sender(envelope()))


def test_security_workflow_identity_is_preserved_alongside_projection():
    class Client:
        calls = []

        async def start_workflow(self, _target, _reference, **options):
            self.calls.append(options["id"])

    client, event = Client(), envelope("original.scan_requested")
    sender = TemporalSender(client, projection_sender=ProjectionSender(client))
    result = asyncio.run(sender(event))
    assert len(client.calls) == 2
    assert client.calls[0].startswith("pdos-enterprise-projection:")
    assert result == client.calls[1] == f"pdos-security-scan:{event.tenant_id}:{event.subject_id}"
