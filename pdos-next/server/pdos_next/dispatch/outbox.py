from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import or_, select

from pdos_next.database import tenant_session
from pdos_next.models import Inbox, Outbox, Receipt, now

CONSUMER = "temporal-work-v1"


@dataclass(frozen=True)
class Envelope:
    event_id: str
    tenant_id: str
    product_id: str
    subject_id: str
    subject_revision: int
    event_type: str
    schema_version: int
    correlation_id: str
    lease_id: str


def claim_events(engine, tenant_id: UUID, limit=20) -> list[Envelope]:
    """A short transaction reserves delivery. No network call holds its locks."""
    claimed = []
    with tenant_session(engine, tenant_id) as s:
        events = s.scalars(
            select(Outbox)
            .where(
                Outbox.delivered_at.is_(None),
                or_(Outbox.lease_until.is_(None), Outbox.lease_until <= now()),
            )
            .order_by(Outbox.created_at, Outbox.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        for event in events:
            receipt = s.get(Receipt, event.receipt_id)
            lease = uuid4()
            event.lease_id = lease
            event.lease_until = now() + timedelta(seconds=30)
            event.attempts += 1
            inbox = s.scalar(
                select(Inbox).where(Inbox.event_id == event.id, Inbox.consumer == CONSUMER)
            )
            if not inbox:
                s.add(
                    Inbox(
                        tenant_id=tenant_id,
                        event_id=event.id,
                        product_id=receipt.product_id,
                        consumer=CONSUMER,
                    )
                )
            claimed.append(
                Envelope(
                    str(event.id),
                    str(tenant_id),
                    str(receipt.product_id),
                    str(event.subject_id),
                    event.subject_revision,
                    event.type,
                    event.schema_version,
                    str(event.correlation_id),
                    str(lease),
                )
            )
    return claimed


def acknowledge(engine, event: Envelope, *, workflow_id=None, ignored=False):
    with tenant_session(engine, UUID(event.tenant_id)) as s:
        row = s.scalar(select(Outbox).where(Outbox.id == UUID(event.event_id)).with_for_update())
        if row.lease_id != UUID(event.lease_id) or row.delivered_at:
            return False
        inbox = s.scalar(
            select(Inbox)
            .where(
                Inbox.event_id == row.id,
                Inbox.consumer == CONSUMER,
            )
            .with_for_update()
        )
        row.delivered_at = now()
        row.lease_until = None
        row.last_error = None
        inbox.status = "ignored" if ignored else "received"
        inbox.workflow_id = workflow_id
        inbox.received_at = now()
        return True


def delivery_unknown(engine, event: Envelope):
    # Retain the lease: a lost acknowledgement is retried only after expiry.
    # Temporal's workflow ID and signal event ID make that retry idempotent.
    with tenant_session(engine, UUID(event.tenant_id)) as s:
        row = s.scalar(select(Outbox).where(Outbox.id == UUID(event.event_id)).with_for_update())
        if row.lease_id == UUID(event.lease_id) and not row.delivered_at:
            row.last_error = "DELIVERY_UNKNOWN"


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
                acknowledge(
                    engine,
                    event,
                    workflow_id=workflow_id,
                    ignored=workflow_id is None,
                )
            )
    return {"delivered": delivered, "unknown": unknown}
