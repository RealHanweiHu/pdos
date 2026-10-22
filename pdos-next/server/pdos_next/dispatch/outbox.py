"""Metadata delivery through the isolated dispatcher role, without business table access."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text

from pdos_next.database import tenant_session

CONSUMER = "temporal-work-v1"


@dataclass(frozen=True)
class Envelope:
    event_id: str
    tenant_id: str
    category_id: str
    product_id: str | None
    subject_id: str
    subject_revision: int
    event_type: str
    schema_version: int
    correlation_id: str
    lease_id: str
    actor_id: str
    requester_id: str


def claim_events(engine, tenant_id: UUID, limit=20) -> list[Envelope]:
    with tenant_session(engine, tenant_id) as s:
        rows = s.execute(
            text("SELECT * FROM claim_domain_events(:tenant,:limit)"),
            {"tenant": tenant_id, "limit": limit},
        ).mappings()
        return [
            Envelope(
                **{
                    key: str(value) if isinstance(value, UUID) else value
                    for key, value in row.items()
                }
            )
            for row in rows
        ]


def _finish(engine, event, workflow_id, unknown):
    with tenant_session(engine, UUID(event.tenant_id)) as s:
        return s.scalar(
            text("SELECT finish_domain_delivery(:tenant,:event,:lease,:workflow,:unknown)"),
            {
                "tenant": UUID(event.tenant_id),
                "event": UUID(event.event_id),
                "lease": UUID(event.lease_id),
                "workflow": workflow_id,
                "unknown": unknown,
            },
        )


def acknowledge(engine, event: Envelope, *, workflow_id=None, ignored=False):
    return _finish(engine, event, None if ignored else workflow_id, False)


def delivery_unknown(engine, event: Envelope):
    # Preserve the lease and original workflow identity after an uncertain send.
    return _finish(engine, event, None, True)


async def dispatch_once(engine, tenant_id, sender):
    delivered = unknown = 0
    for event in claim_events(engine, tenant_id):
        try:
            workflow_id = await sender(event)
        except Exception:
            delivery_unknown(engine, event)
            unknown += 1
        else:
            delivered += int(
                acknowledge(engine, event, workflow_id=workflow_id, ignored=workflow_id is None)
            )
    return {"delivered": delivered, "unknown": unknown}
