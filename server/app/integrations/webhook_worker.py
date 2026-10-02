"""Durable, at-least-once webhook delivery; disabled unless explicitly configured."""

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, and_, exists, or_, select, update

from app.auth.roles import Action
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, digest
from app.domain.project_webhooks import control, insert_delivery, principal
from app.domain.quality_operations import authorize
from app.domain.webhook_sources import (
    SOURCE_EVENTS,
    SilentAICompletion,
    has_explicit_send,
    notification,
)
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft
from app.integrations.webhook_protocol import (
    PROTOCOL,
    WebhookTransport,
    body_bytes,
    decrypt_key,
    root_key,
    signature,
)
from app.settings import get_settings


def abandon(c: Any, delivery: Any, code: str) -> None:
    if delivery["lease_id"]:
        a = tables.webhook_attempts
        c.execute(
            update(a)
            .where(a.c.id == delivery["lease_id"], a.c.outcome == "started")
            .values(outcome="unknown", error_code=code, finished_at=datetime.now(UTC))
        )


def worker_event(c: Any, row: Any, identity: UUID, action: str) -> None:
    EventAuditWriter(
        c, tenant_id=row["tenant_id"], project_id=row["project_id"], actor_user_id=None
    ).record(
        EventDraft(
            event_id=f"webhook:{identity}:{action}",
            event_type="WEBHOOK_RECORDED",
            source="webhook_service",
            entity_id=identity,
            payload={"record_id": str(identity), "action": action},
        ),
        AuditDraft(action=f"webhook.{action}", after_snapshot={"record_id": str(identity)}),
    )


class WebhookWorker:
    def __init__(self, engine: Engine, transport: WebhookTransport | None = None):
        self.engine = engine
        self.transport = transport or WebhookTransport()

    def dispatch(self) -> int:
        e, s, ev, controls = (
            tables.webhook_endpoints,
            tables.webhook_scans,
            tables.events,
            tables.webhook_controls,
        )
        latest = (
            select(controls.c.status)
            .where(controls.c.endpoint_id == e.c.id)
            .order_by(controls.c.version.desc())
            .limit(1)
            .scalar_subquery()
        )
        count = 0
        with self.engine.begin() as c:
            endpoints = (
                c.execute(
                    select(e)
                    .where(
                        latest == "active",
                        e.c.expires_at > datetime.now(UTC),
                        e.c.auto_start_at.is_not(None),
                    )
                    .order_by(e.c.last_scanned_at.asc().nulls_first(), e.c.id)
                    .limit(10)
                    .with_for_update(skip_locked=True)
                )
                .mappings()
                .all()
            )
            for row in endpoints:
                c.execute(
                    update(e)
                    .where(e.c.id == row["id"])
                    .values(last_scanned_at=datetime.now(UTC), dispatch_error=None)
                )
                try:
                    context = principal(self.engine, row)
                    authorize(c, context, row["project_id"], Action.INTEGRATION_PROJECT_MANAGE)
                    authorize(c, context, row["project_id"], Action.INTEGRATION_PROJECT_SEND)
                except (ProductWorkError, PermissionError):
                    c.execute(
                        update(e)
                        .where(e.c.id == row["id"])
                        .values(dispatch_error="principal_unavailable")
                    )
                    continue
                # Per-event markers keep late commits discoverable.
                events = (
                    c.execute(
                        select(ev.c.id)
                        .where(
                            ev.c.tenant_id == row["tenant_id"],
                            ev.c.project_id == row["project_id"],
                            ev.c.timestamp >= row["auto_start_at"],
                            ev.c.event_type.in_(SOURCE_EVENTS),
                            ~exists(
                                select(s.c.id).where(
                                    s.c.endpoint_id == row["id"], s.c.source_event_id == ev.c.id
                                )
                            ),
                        )
                        .order_by(ev.c.id)
                        .limit(100)
                    )
                    .scalars()
                    .all()
                )
                for event_id in events:
                    delivery = None
                    try:
                        basis = notification(c, context, row, event_id, automated=True)
                    except (ProductWorkError, PermissionError):
                        pass
                    else:
                        delivery = insert_delivery(
                            c,
                            context,
                            row,
                            basis,
                            uuid4(),
                            digest(
                                {
                                    "endpoint": str(row["id"]),
                                    "event": event_id,
                                    "basis": basis["digest"],
                                }
                            ),
                            "按具名启用的端点范围自动登记原事件通知",
                            automated=True,
                        )
                        count += 1
                    c.execute(
                        s.insert().values(
                            id=uuid4(),
                            tenant_id=row["tenant_id"],
                            project_id=row["project_id"],
                            endpoint_id=row["id"],
                            source_event_id=event_id,
                            delivery_id=delivery["id"] if delivery else None,
                            result="queued" if delivery else "not_applicable_or_unavailable",
                            created_at=datetime.now(UTC),
                        )
                    )
        return count

    def claim(self) -> UUID | None:
        e, q, a = tables.webhook_endpoints, tables.webhook_deliveries, tables.webhook_attempts
        controls = tables.webhook_controls
        latest = (
            select(controls.c.status)
            .where(controls.c.endpoint_id == q.c.endpoint_id)
            .order_by(controls.c.version.desc())
            .limit(1)
            .scalar_subquery()
        )
        now = datetime.now(UTC)
        eligible = or_(
            and_(q.c.status.in_(["queued", "retry_wait"]), q.c.next_attempt_at <= now),
            and_(q.c.status == "sending", q.c.lease_until <= now),
        )
        with self.engine.begin() as c:
            candidates = (
                c.execute(
                    select(q.c.id, q.c.endpoint_id)
                    .where(eligible, latest == "active")
                    .order_by(q.c.next_attempt_at, q.c.id)
                    .limit(100)
                )
                .mappings()
                .all()
            )
            for candidate in candidates:
                ep = (
                    c.execute(
                        select(e)
                        .where(e.c.id == candidate["endpoint_id"])
                        .with_for_update(skip_locked=True)
                    )
                    .mappings()
                    .one_or_none()
                )
                if ep is None:
                    continue
                row = (
                    c.execute(
                        select(q)
                        .where(q.c.id == candidate["id"], eligible)
                        .with_for_update(skip_locked=True)
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    continue
                state = control(c, ep["tenant_id"], ep["id"])
                if not state or state["status"] != "active":
                    continue
                abandon(c, row, "lease_expired_result_unknown")
                if ep["expires_at"] <= now or row["attempt_count"] >= row["attempt_limit"]:
                    c.execute(
                        update(q)
                        .where(q.c.id == row["id"])
                        .values(
                            status="failed",
                            lease_id=None,
                            lease_until=None,
                            last_error="endpoint_expired"
                            if ep["expires_at"] <= now
                            else "attempt_limit",
                        )
                    )
                    continue
                identity = uuid4()
                c.execute(
                    update(q)
                    .where(q.c.id == row["id"])
                    .values(
                        status="sending",
                        attempt_count=row["attempt_count"] + 1,
                        lease_id=identity,
                        lease_until=now + timedelta(seconds=120),
                    )
                )
                c.execute(
                    a.insert().values(
                        id=identity,
                        tenant_id=row["tenant_id"],
                        project_id=row["project_id"],
                        delivery_id=row["id"],
                        control_id=state["id"],
                        number=row["attempt_count"] + 1,
                        signed_timestamp=int(now.timestamp()),
                        body_digest=row["payload_digest"],
                        outcome="started",
                        started_at=now,
                    )
                )
                return identity
        return None

    def deliver(self, attempt_id: UUID) -> str:
        e, q, a = tables.webhook_endpoints, tables.webhook_deliveries, tables.webhook_attempts
        with self.engine.begin() as c:
            attempt = c.execute(select(a).where(a.c.id == attempt_id)).mappings().one()
            original = c.execute(select(q).where(q.c.id == attempt["delivery_id"])).mappings().one()
            # Same endpoint -> delivery lock order as pause/revoke. A bounded POST holds this lock.
            ep = (
                c.execute(select(e).where(e.c.id == original["endpoint_id"]).with_for_update())
                .mappings()
                .one()
            )
            row = (
                c.execute(select(q).where(q.c.id == original["id"]).with_for_update())
                .mappings()
                .one()
            )
            if row["lease_id"] != attempt_id or row["status"] != "sending":
                return "superseded"
            state = control(c, ep["tenant_id"], ep["id"])
            status, outcome, code = "retry_wait", "abandoned", "endpoint_paused"
            http_status, response_digest = None, None
            now = datetime.now(UTC)
            if ep["expires_at"] <= now:
                status, code = "failed", "endpoint_expired"
            elif not get_settings().webhook_delivery_enabled:
                code = "delivery_disabled"
            elif not state or state["status"] != "active" or state["id"] != attempt["control_id"]:
                if state and state["status"] == "revoked":
                    status, code = "cancelled", "endpoint_revoked"
            elif (
                row["lease_until"] <= now
                or abs(int(now.timestamp()) - attempt["signed_timestamp"]) > 240
            ):
                outcome, code = "unknown", "lease_expired_result_unknown"
            else:
                try:
                    context = principal(self.engine, ep)
                    authorize(c, context, ep["project_id"], Action.INTEGRATION_PROJECT_MANAGE)
                    basis = notification(
                        c,
                        context,
                        ep,
                        row["source_event_id"],
                        automated=not has_explicit_send(c, row),
                    )
                    if basis["digest"] != row["basis_digest"]:
                        raise ProductWorkError("source changed")
                    body = body_bytes(row["payload"])
                    if sha256(body).hexdigest() != row["payload_digest"]:
                        raise ProductWorkError("body changed")
                except SilentAICompletion:
                    status, outcome, code = "cancelled", "abandoned", "silent_ai_success"
                except (ProductWorkError, PermissionError):
                    status, outcome, code = (
                        "source_changed",
                        "abandoned",
                        "source_or_principal_changed",
                    )
                else:
                    try:
                        secret = decrypt_key(ep)
                    except ProductWorkError:
                        status, outcome, code = "failed", "abandoned", "signing_key_unavailable"
                    else:
                        headers = {
                            "X-PDOS-Webhook-Version": PROTOCOL,
                            "X-PDOS-Delivery-ID": str(row["id"]),
                            "X-PDOS-Attempt-ID": str(attempt_id),
                            "X-PDOS-Timestamp": str(attempt["signed_timestamp"]),
                            "X-PDOS-Signature": signature(
                                secret, attempt["signed_timestamp"], row["id"], attempt_id, body
                            ),
                        }
                        try:
                            http_status, response = self.transport.post(ep["url"], body, headers)
                        except ProductWorkError:
                            status, outcome, code = "failed", "failed", "destination_not_public"
                        except (OSError, TimeoutError, ValueError):
                            status, outcome, code = (
                                "retry_wait",
                                "unknown",
                                "transport_result_unknown",
                            )
                        except Exception:
                            status, outcome, code = (
                                "retry_wait",
                                "unknown",
                                "transport_result_unknown",
                            )
                        else:
                            response_digest = sha256(response).hexdigest()
                            try:
                                acknowledgement = json.loads(response)
                            except (ValueError, UnicodeError):
                                acknowledgement = None
                            valid_ack = (
                                isinstance(acknowledgement, dict)
                                and acknowledgement.get("delivery_id") == str(row["id"])
                                and acknowledgement.get("event_id") == row["payload"]["event_id"]
                                and acknowledgement.get("accepted") is True
                            )
                            if 200 <= http_status < 300 and valid_ack:
                                status, outcome, code = "delivered", "delivered", "acknowledged"
                            elif http_status in {408, 425, 429} or http_status >= 500:
                                status, outcome, code = (
                                    "retry_wait",
                                    "retryable",
                                    "receiver_temporarily_unavailable",
                                )
                            elif 200 <= http_status < 300:
                                status, outcome, code = (
                                    "retry_wait",
                                    "unknown",
                                    "acknowledgement_missing_or_mismatched",
                                )
                            else:
                                status, outcome, code = (
                                    "failed",
                                    "failed",
                                    "receiver_rejected_or_redirected",
                                )
            if status == "retry_wait" and row["attempt_count"] >= row["attempt_limit"]:
                status = "failed"
            c.execute(
                update(a)
                .where(a.c.id == attempt_id, a.c.outcome == "started")
                .values(
                    outcome=outcome,
                    http_status=http_status,
                    response_digest=response_digest,
                    error_code=code,
                    finished_at=datetime.now(UTC),
                )
            )
            c.execute(
                update(q)
                .where(q.c.id == row["id"])
                .values(
                    status=status,
                    lease_id=None,
                    lease_until=None,
                    last_error=None if status == "delivered" else code,
                    next_attempt_at=datetime.now(UTC)
                    + timedelta(seconds=min(3600, 15 * 2 ** min(row["attempt_count"], 10))),
                )
            )
            worker_event(c, row, attempt_id, outcome)
            return status

    def run_once(self) -> dict[str, Any]:
        if not get_settings().webhook_delivery_enabled:
            return {"status": "disabled"}
        root_key()
        queued = self.dispatch()
        attempt = self.claim()
        status = self.deliver(attempt) if attempt else "idle"
        return {"status": status, "queued": queued, "attempt_id": str(attempt) if attempt else None}
