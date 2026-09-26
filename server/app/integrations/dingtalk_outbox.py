"""Durable DingTalk intents and ambiguity-aware delivery processing."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, or_, select, update
from sqlalchemy.engine import RowMapping

from app.db.schema import tables
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft
from app.integrations.dingtalk_delivery import (
    DeliveryResult,
    DingTalkDeliveryClient,
    DingTalkDeliveryError,
)
from app.settings import Settings


class DingTalkIntentError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class OutboxRecord:
    id: UUID
    tenant_id: UUID
    project_id: UUID | None
    operation: str
    status: str
    attempt_count: int
    remote_reference: str | None
    last_error_code: str | None


@dataclass(frozen=True)
class ApprovalIntent:
    id: UUID
    outbox: OutboxRecord


@dataclass(frozen=True)
class CardIntent:
    id: UUID
    out_track_id: str
    outbox: OutboxRecord


def _outbox_record(row: RowMapping) -> OutboxRecord:
    return OutboxRecord(
        id=row["id"],
        tenant_id=row["tenant_id"],
        project_id=row["project_id"],
        operation=row["operation"],
        status=row["status"],
        attempt_count=row["attempt_count"],
        remote_reference=row["remote_reference"],
        last_error_code=row["last_error_code"],
    )


class DingTalkIntentService:
    def __init__(self, engine: Engine, settings: Settings) -> None:
        self._engine = engine
        self._settings = settings

    def enqueue_group_markdown(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        title: str,
        text: str,
        idempotency_key: str,
    ) -> OutboxRecord:
        with self._engine.begin() as connection:
            channel_id = connection.execute(
                select(tables.dingtalk_project_channels.c.id).where(
                    tables.dingtalk_project_channels.c.tenant_id == tenant_id,
                    tables.dingtalk_project_channels.c.project_id == project_id,
                    tables.dingtalk_project_channels.c.status == "active",
                )
            ).scalar_one_or_none()
            if channel_id is None:
                raise DingTalkIntentError("DINGTALK_PROJECT_CHANNEL_NOT_CONFIGURED")
            return self._insert_outbox(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                operation="group_markdown",
                idempotency_key=idempotency_key,
                payload={
                    "channel_id": str(channel_id),
                    "title": title,
                    "text": self._group_text_with_project_link(
                        project_id=project_id,
                        text=text,
                    ),
                },
            )

    def enqueue_reminder_dm(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID | None,
        recipient_user_id: UUID,
        reminder_id: UUID,
        title: str,
        connection: Connection | None = None,
    ) -> OutboxRecord:
        # Dispatch shares its locked transaction; standalone callers retain an
        # owned transaction. Never borrow a second connection while holding the
        # tenant dispatch lock, which can starve a saturated connection pool.
        transaction = self._engine.begin() if connection is None else nullcontext(connection)
        with transaction as active_connection:
            staff_id = active_connection.execute(
                select(tables.dingtalk_user_bindings.c.staff_id).where(
                    tables.dingtalk_user_bindings.c.tenant_id == tenant_id,
                    tables.dingtalk_user_bindings.c.user_id == recipient_user_id,
                    tables.dingtalk_user_bindings.c.status == "active",
                )
            ).scalar_one_or_none()
            if staff_id is None:
                raise DingTalkIntentError("DINGTALK_USER_NOT_BOUND")
            return self._insert_outbox(
                active_connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                operation="reminder_dm",
                idempotency_key=f"reminder:{reminder_id}",
                payload={
                    "staff_id": staff_id,
                    "recipient_user_id": str(recipient_user_id),
                    "title": "PDOS 提醒",
                    "text": self._text_with_my_work_link(text=title),
                },
            )

    def _text_with_my_work_link(self, *, text: str) -> str:
        base_url = self._validated_public_base_url()
        return f"{text}\n\n[打开我的工作]({base_url}/my-work)"

    def list_outbox(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID | None = None,
        limit: int = 100,
    ) -> tuple[OutboxRecord, ...]:
        statement = select(tables.integration_outbox).where(
            tables.integration_outbox.c.tenant_id == tenant_id,
            tables.integration_outbox.c.provider == "dingtalk",
        )
        if project_id is not None:
            statement = statement.where(tables.integration_outbox.c.project_id == project_id)
        statement = statement.order_by(
            tables.integration_outbox.c.created_at.desc(),
            tables.integration_outbox.c.id.desc(),
        ).limit(limit)
        with self._engine.connect() as connection:
            return tuple(_outbox_record(row) for row in connection.execute(statement).mappings())

    def reconcile_outbox(
        self,
        *,
        tenant_id: UUID,
        outbox_id: UUID,
        actor_user_id: UUID,
        outcome: Literal["confirmed_delivered", "confirmed_not_delivered"],
        remote_reference: str | None,
        now: datetime | None = None,
    ) -> OutboxRecord:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(tables.integration_outbox)
                    .where(
                        tables.integration_outbox.c.tenant_id == tenant_id,
                        tables.integration_outbox.c.id == outbox_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise DingTalkIntentError("DINGTALK_OUTBOX_NOT_FOUND")
            if row["status"] != "uncertain":
                raise DingTalkIntentError("DINGTALK_RECONCILIATION_NOT_ALLOWED")
            if outcome == "confirmed_delivered":
                if remote_reference is None or not remote_reference.strip():
                    raise DingTalkIntentError("DINGTALK_REMOTE_REFERENCE_REQUIRED")
                normalized_reference = remote_reference.strip()
                status = "succeeded"
                error_code = None
                completed_at = current
                self._update_domain_delivery(
                    connection,
                    outbox_id=outbox_id,
                    operation=row["operation"],
                    remote_reference=normalized_reference,
                    succeeded=True,
                    now=current,
                )
                EventAuditWriter(
                    connection,
                    tenant_id=tenant_id,
                    project_id=row["project_id"],
                    actor_user_id=actor_user_id,
                ).record(
                    EventDraft(
                        event_id=f"dingtalk-outbox:{outbox_id}:reconciled-delivered",
                        event_type="DINGTALK_NOTIFICATION_DELIVERED",
                        source="dingtalk_connector_service",
                        entity_id=outbox_id,
                        payload={"outbox_id": str(outbox_id), "operation": row["operation"]},
                        occurred_at=current,
                    ),
                    AuditDraft(
                        action="dingtalk.outbox.reconcile",
                        before_snapshot={"status": "uncertain"},
                        after_snapshot={"status": status},
                        context={"outcome": outcome},
                    ),
                )
            else:
                normalized_reference = None
                status = "failed"
                error_code = "DINGTALK_RECONCILED_NOT_DELIVERED"
                completed_at = None
                self._update_domain_delivery(
                    connection,
                    outbox_id=outbox_id,
                    operation=row["operation"],
                    remote_reference=None,
                    succeeded=False,
                    now=current,
                )
                self._write_outbox_audit(
                    connection,
                    tenant_id=tenant_id,
                    project_id=row["project_id"],
                    actor_user_id=actor_user_id,
                    outbox_id=outbox_id,
                    action="dingtalk.outbox.reconcile",
                    before_status="uncertain",
                    after_status=status,
                    context={"outcome": outcome},
                )
            updated = (
                connection.execute(
                    update(tables.integration_outbox)
                    .where(tables.integration_outbox.c.id == outbox_id)
                    .values(
                        status=status,
                        remote_reference=normalized_reference,
                        completed_at=completed_at,
                        last_error_code=error_code,
                        last_error_message=error_code,
                        updated_at=current,
                    )
                    .returning(tables.integration_outbox)
                )
                .mappings()
                .one()
            )
        return _outbox_record(updated)

    def replay_outbox(
        self,
        *,
        tenant_id: UUID,
        outbox_id: UUID,
        actor_user_id: UUID,
        now: datetime | None = None,
    ) -> OutboxRecord:
        if not self._settings.dingtalk_delivery_enabled:
            raise DingTalkIntentError("DINGTALK_DELIVERY_DISABLED")
        current = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(tables.integration_outbox)
                    .where(
                        tables.integration_outbox.c.tenant_id == tenant_id,
                        tables.integration_outbox.c.id == outbox_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise DingTalkIntentError("DINGTALK_OUTBOX_NOT_FOUND")
            if row["status"] not in {"failed", "manual"}:
                raise DingTalkIntentError("DINGTALK_REPLAY_NOT_ALLOWED")
            if row["attempt_count"] >= row["max_attempts"]:
                raise DingTalkIntentError("DINGTALK_REPLAY_LIMIT_REACHED")
            updated = (
                connection.execute(
                    update(tables.integration_outbox)
                    .where(tables.integration_outbox.c.id == outbox_id)
                    .values(
                        status="pending",
                        next_attempt_at=current,
                        completed_at=None,
                        last_error_code=None,
                        last_error_message=None,
                        updated_at=current,
                    )
                    .returning(tables.integration_outbox)
                )
                .mappings()
                .one()
            )
            self._update_domain_queued(
                connection,
                outbox_id=outbox_id,
                operation=row["operation"],
                now=current,
            )
            self._write_outbox_audit(
                connection,
                tenant_id=tenant_id,
                project_id=row["project_id"],
                actor_user_id=actor_user_id,
                outbox_id=outbox_id,
                action="dingtalk.outbox.replay",
                before_status=row["status"],
                after_status="pending",
                context={"human_confirmed": True},
            )
        return _outbox_record(updated)

    @staticmethod
    def _update_domain_delivery(
        connection: Connection,
        *,
        outbox_id: UUID,
        operation: str,
        remote_reference: str | None,
        succeeded: bool,
        now: datetime,
    ) -> None:
        if operation == "gate_approval_create":
            connection.execute(
                update(tables.dingtalk_approval_instances)
                .where(tables.dingtalk_approval_instances.c.outbox_id == outbox_id)
                .values(
                    status="pending" if succeeded else "sync_failed",
                    remote_instance_id=remote_reference if succeeded else None,
                    updated_at=now,
                )
            )
        elif operation == "interactive_card_create":
            connection.execute(
                update(tables.dingtalk_interactive_cards)
                .where(tables.dingtalk_interactive_cards.c.outbox_id == outbox_id)
                .values(
                    status="sent" if succeeded else "failed",
                    remote_instance_id=remote_reference if succeeded else None,
                    updated_at=now,
                )
            )

    @staticmethod
    def _update_domain_queued(
        connection: Connection,
        *,
        outbox_id: UUID,
        operation: str,
        now: datetime,
    ) -> None:
        if operation == "gate_approval_create":
            connection.execute(
                update(tables.dingtalk_approval_instances)
                .where(tables.dingtalk_approval_instances.c.outbox_id == outbox_id)
                .values(status="queued", updated_at=now)
            )
        elif operation == "interactive_card_create":
            connection.execute(
                update(tables.dingtalk_interactive_cards)
                .where(tables.dingtalk_interactive_cards.c.outbox_id == outbox_id)
                .values(status="queued", updated_at=now)
            )

    @staticmethod
    def _write_outbox_audit(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID | None,
        actor_user_id: UUID | None,
        outbox_id: UUID,
        action: str,
        before_status: str,
        after_status: str,
        context: dict[str, object],
    ) -> None:
        connection.execute(
            tables.audit_log.insert().values(
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                event_id=f"dingtalk-outbox:{outbox_id}:{action}:{uuid4()}",
                action=action,
                entity="integration_outbox",
                entity_id=outbox_id,
                before_snapshot={"status": before_status},
                after_snapshot={"status": after_status},
                context=context,
            )
        )

    def enqueue_gate_approval(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        gate_id: UUID,
        actor_user_id: UUID,
        approver_user_id: UUID,
        idempotency_key: str,
    ) -> ApprovalIntent:
        with self._engine.begin() as connection:
            existing = self._existing_outbox(
                connection,
                tenant_id=tenant_id,
                operation="gate_approval_create",
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                existing_payload = dict(existing["payload"])
                approval = connection.execute(
                    select(tables.dingtalk_approval_instances.c.id).where(
                        tables.dingtalk_approval_instances.c.id
                        == UUID(existing_payload["approval_id"]),
                        tables.dingtalk_approval_instances.c.project_id == project_id,
                        tables.dingtalk_approval_instances.c.gate_id == gate_id,
                        tables.dingtalk_approval_instances.c.approver_user_id == approver_user_id,
                    )
                ).scalar_one_or_none()
                if approval is None:
                    raise DingTalkIntentError("DINGTALK_IDEMPOTENCY_CONFLICT")
                return ApprovalIntent(id=approval, outbox=_outbox_record(existing))
            approval_id = uuid4()
            request_id = f"pdos-gate-{approval_id}"
            self._assert_gate_and_users(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                gate_id=gate_id,
                originator_user_id=actor_user_id,
                approver_user_id=approver_user_id,
            )
            outbox = self._insert_outbox(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                operation="gate_approval_create",
                idempotency_key=idempotency_key,
                payload={"approval_id": str(approval_id)},
            )
            connection.execute(
                tables.dingtalk_approval_instances.insert().values(
                    id=approval_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    gate_id=gate_id,
                    outbox_id=outbox.id,
                    requested_by_user_id=actor_user_id,
                    originator_user_id=actor_user_id,
                    approver_user_id=approver_user_id,
                    request_id=request_id,
                    status="manual" if outbox.status == "manual" else "queued",
                )
            )
        return ApprovalIntent(id=approval_id, outbox=outbox)

    def enqueue_interactive_card(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        recipient_user_id: UUID,
        action_key: Literal["acknowledge", "open"],
        title: str,
        body: str,
        idempotency_key: str,
    ) -> CardIntent:
        action_path = f"/projects/{project_id}/gates" if action_key == "open" else None
        with self._engine.begin() as connection:
            existing = self._existing_outbox(
                connection,
                tenant_id=tenant_id,
                operation="interactive_card_create",
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                existing_payload = dict(existing["payload"])
                card = (
                    connection.execute(
                        select(
                            tables.dingtalk_interactive_cards.c.id,
                            tables.dingtalk_interactive_cards.c.out_track_id,
                        ).where(
                            tables.dingtalk_interactive_cards.c.id
                            == UUID(existing_payload["card_id"]),
                            tables.dingtalk_interactive_cards.c.project_id == project_id,
                            tables.dingtalk_interactive_cards.c.recipient_user_id
                            == recipient_user_id,
                            tables.dingtalk_interactive_cards.c.action_key == action_key,
                            tables.dingtalk_interactive_cards.c.action_path == action_path,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if (
                    card is None
                    or existing_payload.get("title") != title
                    or existing_payload.get("body") != body
                ):
                    raise DingTalkIntentError("DINGTALK_IDEMPOTENCY_CONFLICT")
                return CardIntent(
                    id=card["id"],
                    out_track_id=card["out_track_id"],
                    outbox=_outbox_record(existing),
                )
            card_id = uuid4()
            out_track_id = f"pdos-card-{card_id}"
            binding = connection.execute(
                select(tables.dingtalk_tenant_bindings.c.card_template_id).where(
                    tables.dingtalk_tenant_bindings.c.tenant_id == tenant_id,
                    tables.dingtalk_tenant_bindings.c.status == "active",
                )
            ).scalar_one_or_none()
            if binding is None:
                raise DingTalkIntentError("DINGTALK_CARD_NOT_CONFIGURED")
            self._assert_project_member_binding(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=recipient_user_id,
            )
            outbox = self._insert_outbox(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                operation="interactive_card_create",
                idempotency_key=idempotency_key,
                payload={
                    "card_id": str(card_id),
                    "title": title,
                    "body": body,
                },
            )
            connection.execute(
                tables.dingtalk_interactive_cards.insert().values(
                    id=card_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    outbox_id=outbox.id,
                    recipient_user_id=recipient_user_id,
                    out_track_id=out_track_id,
                    card_template_id=binding,
                    action_key=action_key,
                    action_path=action_path,
                    status="manual" if outbox.status == "manual" else "queued",
                )
            )
        return CardIntent(id=card_id, out_track_id=out_track_id, outbox=outbox)

    @staticmethod
    def _existing_outbox(
        connection: Connection,
        *,
        tenant_id: UUID,
        operation: str,
        idempotency_key: str,
    ) -> RowMapping | None:
        return (
            connection.execute(
                select(tables.integration_outbox).where(
                    tables.integration_outbox.c.tenant_id == tenant_id,
                    tables.integration_outbox.c.provider == "dingtalk",
                    tables.integration_outbox.c.operation == operation,
                    tables.integration_outbox.c.idempotency_key == idempotency_key,
                )
            )
            .mappings()
            .one_or_none()
        )

    def _insert_outbox(
        self,
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID | None,
        operation: str,
        idempotency_key: str,
        payload: dict[str, str],
    ) -> OutboxRecord:
        existing = (
            connection.execute(
                select(tables.integration_outbox).where(
                    tables.integration_outbox.c.tenant_id == tenant_id,
                    tables.integration_outbox.c.provider == "dingtalk",
                    tables.integration_outbox.c.operation == operation,
                    tables.integration_outbox.c.idempotency_key == idempotency_key,
                )
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            if existing["project_id"] != project_id or dict(existing["payload"]) != payload:
                raise DingTalkIntentError("DINGTALK_IDEMPOTENCY_CONFLICT")
            return _outbox_record(existing)
        status = "pending" if self._settings.dingtalk_delivery_enabled else "manual"
        row = (
            connection.execute(
                tables.integration_outbox.insert()
                .values(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    project_id=project_id,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    payload=payload,
                    status=status,
                    next_attempt_at=datetime.now(UTC) if status == "pending" else None,
                    last_error_code=(None if status == "pending" else "DINGTALK_DELIVERY_DISABLED"),
                )
                .returning(tables.integration_outbox)
            )
            .mappings()
            .one()
        )
        self._write_outbox_audit(
            connection,
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=actor_user_id,
            outbox_id=row["id"],
            action="dingtalk.outbox.enqueue",
            before_status="absent",
            after_status=status,
            context={"operation": operation},
        )
        return _outbox_record(row)

    def _validated_public_base_url(self) -> str:
        base_url = self._settings.public_base_url.rstrip("/")
        parsed = urlparse(base_url)
        local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
        if (
            (parsed.scheme != "https" and not local_http)
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise DingTalkIntentError("DINGTALK_PUBLIC_BASE_URL_INVALID")
        return base_url

    def _group_text_with_project_link(self, *, project_id: UUID, text: str) -> str:
        base_url = self._validated_public_base_url()
        return f"{text}\n\n[Open PDOS]({base_url}/projects/{project_id})"

    @staticmethod
    def _assert_project_member_binding(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        user_id: UUID,
    ) -> None:
        row = connection.execute(
            select(tables.users.c.id)
            .join(
                tables.project_members,
                (tables.project_members.c.tenant_id == tables.users.c.tenant_id)
                & (tables.project_members.c.user_id == tables.users.c.id),
            )
            .join(
                tables.dingtalk_user_bindings,
                (tables.dingtalk_user_bindings.c.tenant_id == tables.users.c.tenant_id)
                & (tables.dingtalk_user_bindings.c.user_id == tables.users.c.id),
            )
            .where(
                tables.users.c.tenant_id == tenant_id,
                tables.users.c.id == user_id,
                tables.users.c.is_active.is_(True),
                tables.project_members.c.project_id == project_id,
                tables.dingtalk_user_bindings.c.status == "active",
            )
        ).scalar_one_or_none()
        if row is None:
            raise DingTalkIntentError("DINGTALK_PROJECT_MEMBER_NOT_LINKED")

    @classmethod
    def _assert_gate_and_users(
        cls,
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        gate_id: UUID,
        originator_user_id: UUID,
        approver_user_id: UUID,
    ) -> None:
        gate = connection.execute(
            select(tables.gates.c.id).where(
                tables.gates.c.tenant_id == tenant_id,
                tables.gates.c.project_id == project_id,
                tables.gates.c.id == gate_id,
            )
        ).scalar_one_or_none()
        if gate is None:
            raise DingTalkIntentError("DINGTALK_GATE_NOT_FOUND")
        cls._assert_project_member_binding(
            connection,
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=originator_user_id,
        )
        cls._assert_project_member_binding(
            connection,
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=approver_user_id,
        )


class DingTalkOutboxProcessor:
    def __init__(
        self,
        *,
        engine: Engine,
        client: DingTalkDeliveryClient,
        settings: Settings,
        worker_id: str,
    ) -> None:
        self._engine = engine
        self._client = client
        self._settings = settings
        self._worker_id = worker_id

    def process_one(self, *, now: datetime | None = None) -> OutboxRecord | None:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        self._quarantine_expired_leases(now=current)
        row = self._claim(now=current)
        if row is None:
            return None
        outbox_id = row["id"]
        try:
            result = self._deliver(row)
        except DingTalkDeliveryError as error:
            return self._fail(outbox_id=outbox_id, error=error, now=current)
        return self._succeed(
            outbox_id=outbox_id,
            remote_reference=result,
            operation=row["operation"],
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            now=current,
        )

    def sync_one_approval(self, *, now: datetime | None = None) -> UUID | None:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.connect() as connection:
            approval = (
                connection.execute(
                    select(tables.dingtalk_approval_instances)
                    .where(
                        tables.dingtalk_approval_instances.c.sync_requested_at.is_not(None),
                        tables.dingtalk_approval_instances.c.remote_instance_id.is_not(None),
                    )
                    .order_by(tables.dingtalk_approval_instances.c.sync_requested_at)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if approval is None:
                return None
            approval_id = UUID(str(approval["id"]))
            binding = (
                connection.execute(
                    select(tables.dingtalk_tenant_bindings).where(
                        tables.dingtalk_tenant_bindings.c.tenant_id == approval["tenant_id"],
                        tables.dingtalk_tenant_bindings.c.status == "active",
                    )
                )
                .mappings()
                .one_or_none()
            )
        client_id = self._settings.dingtalk_client_id
        client_secret = self._settings.dingtalk_client_secret
        if (
            binding is None
            or not client_id
            or client_secret is None
            or binding["client_id"] != client_id
        ):
            self._mark_approval_sync_failed(approval_id, current)
            return approval_id
        try:
            token = self._client.app_token(
                client_id=client_id,
                client_secret=client_secret.get_secret_value(),
            )
            snapshot = self._client.get_approval(
                token=token,
                process_instance_id=approval["remote_instance_id"],
            )
        except DingTalkDeliveryError:
            self._mark_approval_sync_failed(approval_id, current)
            return approval_id
        with self._engine.begin() as connection:
            before = approval["status"]
            connection.execute(
                update(tables.dingtalk_approval_instances)
                .where(tables.dingtalk_approval_instances.c.id == approval["id"])
                .values(
                    status=snapshot.status,
                    remote_result=snapshot.result,
                    sync_requested_at=None,
                    completed_at=(
                        current
                        if snapshot.status in {"approved", "rejected", "terminated"}
                        else None
                    ),
                    updated_at=current,
                )
            )
            EventAuditWriter(
                connection,
                tenant_id=approval["tenant_id"],
                project_id=approval["project_id"],
                actor_user_id=None,
            ).record(
                EventDraft(
                    event_id=f"dingtalk-approval:{approval['id']}:sync:{uuid4()}",
                    event_type="DINGTALK_APPROVAL_UPDATED",
                    source="dingtalk_connector_service",
                    entity_id=approval["id"],
                    payload={"approval_id": str(approval["id"]), "status": snapshot.status},
                    occurred_at=current,
                ),
                AuditDraft(
                    action="dingtalk.approval.sync",
                    before_snapshot={"status": before},
                    after_snapshot={"status": snapshot.status},
                    context={"system_of_record": "external_evidence_only"},
                ),
            )
        return approval_id

    def _mark_approval_sync_failed(self, approval_id: UUID, now: datetime) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                update(tables.dingtalk_approval_instances)
                .where(tables.dingtalk_approval_instances.c.id == approval_id)
                .values(status="sync_failed", sync_requested_at=None, updated_at=now)
            )

    def _claim(self, *, now: datetime) -> RowMapping | None:
        if not self._settings.dingtalk_delivery_enabled:
            return None
        with self._engine.begin() as connection:
            rows = (
                connection.execute(
                    select(tables.integration_outbox)
                    .where(
                        tables.integration_outbox.c.provider == "dingtalk",
                        tables.integration_outbox.c.status.in_(["pending", "retry_wait"]),
                        tables.integration_outbox.c.attempt_count
                        < tables.integration_outbox.c.max_attempts,
                        or_(
                            tables.integration_outbox.c.next_attempt_at.is_(None),
                            tables.integration_outbox.c.next_attempt_at <= now,
                        ),
                    )
                    .order_by(
                        tables.integration_outbox.c.created_at, tables.integration_outbox.c.id
                    )
                    .with_for_update(skip_locked=True)
                    .limit(50)
                )
                .mappings()
                .all()
            )
            for row in rows:
                if row["operation"] in ("reminder_dm", "meeting_invite_dm"):
                    from app.domain.reminder_preferences import reserve_delivery

                    try:
                        recipient = UUID(str(row["payload"].get("recipient_user_id")))
                    except (ValueError, TypeError):
                        connection.execute(
                            update(tables.integration_outbox)
                            .where(tables.integration_outbox.c.id == row["id"])
                            .values(
                                status="manual",
                                last_error_code="REMINDER_RECIPIENT_INVALID",
                                last_error_message="Reminder recipient requires correction",
                                updated_at=now,
                            )
                        )
                        continue
                    reason = reserve_delivery(
                        connection, row["tenant_id"], recipient, row["id"], self._settings, now
                    )
                    if reason:
                        connection.execute(
                            update(tables.integration_outbox)
                            .where(tables.integration_outbox.c.id == row["id"])
                            .values(
                                next_attempt_at=now + timedelta(minutes=5),
                                last_error_code=reason,
                                last_error_message=reason,
                            )
                        )
                        continue
                connection.execute(
                    update(tables.integration_outbox)
                    .where(tables.integration_outbox.c.id == row["id"])
                    .values(
                        status="sending",
                        attempt_count=tables.integration_outbox.c.attempt_count + 1,
                        lease_owner=self._worker_id,
                        lease_expires_at=now + timedelta(minutes=2),
                        updated_at=now,
                    )
                )
                claimed = dict(row)
                claimed["attempt_count"] += 1
                return claimed  # type: ignore[return-value]
        return None

    def _quarantine_expired_leases(self, *, now: datetime) -> None:
        if not self._settings.dingtalk_delivery_enabled:
            return
        with self._engine.begin() as connection:
            expired = list(
                connection.execute(
                    select(
                        tables.integration_outbox.c.id,
                        tables.integration_outbox.c.operation,
                    )
                    .where(
                        tables.integration_outbox.c.provider == "dingtalk",
                        tables.integration_outbox.c.status == "sending",
                        tables.integration_outbox.c.lease_expires_at < now,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(100)
                ).mappings()
            )
            for row in expired:
                connection.execute(
                    update(tables.integration_outbox)
                    .where(tables.integration_outbox.c.id == row["id"])
                    .values(
                        status="uncertain",
                        next_attempt_at=None,
                        lease_owner=None,
                        lease_expires_at=None,
                        last_error_code="DINGTALK_LEASE_EXPIRED_OUTCOME_UNKNOWN",
                        last_error_message="DINGTALK_LEASE_EXPIRED_OUTCOME_UNKNOWN",
                        updated_at=now,
                    )
                )
                self._mark_domain_uncertain(
                    connection,
                    outbox_id=row["id"],
                    operation=row["operation"],
                    now=now,
                )

    @staticmethod
    def _mark_domain_uncertain(
        connection: Connection,
        *,
        outbox_id: UUID,
        operation: str,
        now: datetime,
    ) -> None:
        if operation == "gate_approval_create":
            connection.execute(
                update(tables.dingtalk_approval_instances)
                .where(tables.dingtalk_approval_instances.c.outbox_id == outbox_id)
                .values(status="uncertain", updated_at=now)
            )
        elif operation == "interactive_card_create":
            connection.execute(
                update(tables.dingtalk_interactive_cards)
                .where(tables.dingtalk_interactive_cards.c.outbox_id == outbox_id)
                .values(status="uncertain", updated_at=now)
            )

    def _deliver(self, row: RowMapping) -> str:
        client_id = self._settings.dingtalk_client_id
        client_secret = self._settings.dingtalk_client_secret
        if not client_id or client_secret is None:
            raise DingTalkDeliveryError("DINGTALK_TOKEN_UNAVAILABLE", retryable=True)
        with self._engine.connect() as connection:
            binding = (
                connection.execute(
                    select(tables.dingtalk_tenant_bindings).where(
                        tables.dingtalk_tenant_bindings.c.tenant_id == row["tenant_id"],
                        tables.dingtalk_tenant_bindings.c.status == "active",
                    )
                )
                .mappings()
                .one_or_none()
            )
            if binding is None or binding["client_id"] != client_id:
                raise DingTalkDeliveryError("DINGTALK_CONFIGURATION_MISMATCH")
            token = self._client.app_token(
                client_id=client_id,
                client_secret=client_secret.get_secret_value(),
            )
            payload = dict(row["payload"])
            operation = row["operation"]
            if operation == "group_markdown":
                channel = (
                    connection.execute(
                        select(tables.dingtalk_project_channels).where(
                            tables.dingtalk_project_channels.c.tenant_id == row["tenant_id"],
                            tables.dingtalk_project_channels.c.project_id == row["project_id"],
                            tables.dingtalk_project_channels.c.id == UUID(payload["channel_id"]),
                            tables.dingtalk_project_channels.c.status == "active",
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if channel is None or not binding["robot_code"]:
                    raise DingTalkDeliveryError("DINGTALK_GROUP_NOT_CONFIGURED")
                return self._client.send_group_markdown(
                    token=token,
                    robot_code=binding["robot_code"],
                    open_conversation_id=channel["open_conversation_id"],
                    title=payload["title"],
                    text=payload["text"],
                ).remote_reference
            if operation in ("reminder_dm", "meeting_invite_dm"):
                if operation == "meeting_invite_dm":
                    from app.domain.meeting_notifications import validate_delivery

                    validate_delivery(connection, row, self._settings)
                if not binding["robot_code"]:
                    raise DingTalkDeliveryError("DINGTALK_GROUP_NOT_CONFIGURED")
                return self._client.send_oto_markdown(
                    token=token,
                    robot_code=binding["robot_code"],
                    staff_id=payload["staff_id"],
                    title=payload["title"],
                    text=payload["text"],
                ).remote_reference
            if operation == "gate_approval_create":
                return self._deliver_approval(connection, binding, token, payload).remote_reference
            if operation == "interactive_card_create":
                return self._deliver_card(connection, binding, token, payload).remote_reference
            raise DingTalkDeliveryError("DINGTALK_OPERATION_UNSUPPORTED")

    def _deliver_approval(
        self,
        connection: Connection,
        binding: RowMapping,
        token: str,
        payload: dict[str, str],
    ) -> DeliveryResult:
        approval = (
            connection.execute(
                select(
                    tables.dingtalk_approval_instances,
                    tables.projects.c.code.label("project_code"),
                    tables.projects.c.name.label("project_name"),
                    tables.gates.c.code.label("gate_code"),
                    tables.gates.c.name.label("gate_name"),
                    tables.gates.c.status.label("gate_status"),
                    tables.dingtalk_user_bindings.c.staff_id.label("originator_staff_id"),
                )
                .join(
                    tables.projects,
                    (tables.projects.c.tenant_id == tables.dingtalk_approval_instances.c.tenant_id)
                    & (tables.projects.c.id == tables.dingtalk_approval_instances.c.project_id),
                )
                .join(
                    tables.gates,
                    (tables.gates.c.tenant_id == tables.dingtalk_approval_instances.c.tenant_id)
                    & (tables.gates.c.id == tables.dingtalk_approval_instances.c.gate_id),
                )
                .join(
                    tables.dingtalk_user_bindings,
                    (
                        tables.dingtalk_user_bindings.c.tenant_id
                        == tables.dingtalk_approval_instances.c.tenant_id
                    )
                    & (
                        tables.dingtalk_user_bindings.c.user_id
                        == tables.dingtalk_approval_instances.c.originator_user_id
                    ),
                )
                .where(tables.dingtalk_approval_instances.c.id == UUID(payload["approval_id"]))
            )
            .mappings()
            .one()
        )
        approver_staff_id = connection.execute(
            select(tables.dingtalk_user_bindings.c.staff_id).where(
                tables.dingtalk_user_bindings.c.tenant_id == approval["tenant_id"],
                tables.dingtalk_user_bindings.c.user_id == approval["approver_user_id"],
                tables.dingtalk_user_bindings.c.status == "active",
            )
        ).scalar_one()
        if not binding["approval_process_code"]:
            raise DingTalkDeliveryError("DINGTALK_APPROVAL_NOT_CONFIGURED")
        agent_id = int(binding["agent_id"]) if binding["agent_id"] else None
        return self._client.create_gate_approval(
            token=token,
            process_code=binding["approval_process_code"],
            originator_staff_id=approval["originator_staff_id"],
            approver_staff_id=approver_staff_id,
            agent_id=agent_id,
            request_id=approval["request_id"],
            form_values=[
                {
                    "name": "Project",
                    "value": f"{approval['project_code']} · {approval['project_name']}",
                },
                {"name": "Gate", "value": f"{approval['gate_code']} · {approval['gate_name']}"},
                {"name": "PDOS status", "value": approval["gate_status"]},
            ],
        )

    def _deliver_card(
        self,
        connection: Connection,
        binding: RowMapping,
        token: str,
        payload: dict[str, str],
    ) -> DeliveryResult:
        card = (
            connection.execute(
                select(
                    tables.dingtalk_interactive_cards,
                    tables.dingtalk_user_bindings.c.staff_id,
                )
                .join(
                    tables.dingtalk_user_bindings,
                    (
                        tables.dingtalk_user_bindings.c.tenant_id
                        == tables.dingtalk_interactive_cards.c.tenant_id
                    )
                    & (
                        tables.dingtalk_user_bindings.c.user_id
                        == tables.dingtalk_interactive_cards.c.recipient_user_id
                    ),
                )
                .where(tables.dingtalk_interactive_cards.c.id == UUID(payload["card_id"]))
            )
            .mappings()
            .one()
        )
        callback_route = binding["card_callback_route_key"]
        if not callback_route:
            raise DingTalkDeliveryError("DINGTALK_CARD_NOT_CONFIGURED")
        params = {
            "title": payload["title"],
            "body": payload["body"],
            "status": "pending",
            "action": card["action_key"],
            "actionPath": card["action_path"] or "",
        }
        return self._client.create_interactive_card(
            token=token,
            staff_id=card["staff_id"],
            template_id=card["card_template_id"],
            out_track_id=card["out_track_id"],
            callback_route_key=callback_route,
            card_params=params,
        )

    def _succeed(
        self,
        *,
        outbox_id: UUID,
        remote_reference: str,
        operation: str,
        tenant_id: UUID,
        project_id: UUID | None,
        now: datetime,
    ) -> OutboxRecord:
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    update(tables.integration_outbox)
                    .where(tables.integration_outbox.c.id == outbox_id)
                    .values(
                        status="succeeded",
                        remote_reference=remote_reference,
                        completed_at=now,
                        lease_owner=None,
                        lease_expires_at=None,
                        last_error_code=None,
                        last_error_message=None,
                        updated_at=now,
                    )
                    .returning(tables.integration_outbox)
                )
                .mappings()
                .one()
            )
            if operation == "gate_approval_create":
                connection.execute(
                    update(tables.dingtalk_approval_instances)
                    .where(tables.dingtalk_approval_instances.c.outbox_id == outbox_id)
                    .values(status="pending", remote_instance_id=remote_reference, updated_at=now)
                )
            elif operation == "interactive_card_create":
                connection.execute(
                    update(tables.dingtalk_interactive_cards)
                    .where(tables.dingtalk_interactive_cards.c.outbox_id == outbox_id)
                    .values(status="sent", remote_instance_id=remote_reference, updated_at=now)
                )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=None,
            ).record(
                EventDraft(
                    event_id=f"dingtalk-outbox:{outbox_id}:delivered",
                    event_type="DINGTALK_NOTIFICATION_DELIVERED",
                    source="dingtalk_connector_service",
                    entity_id=outbox_id,
                    payload={"outbox_id": str(outbox_id), "operation": operation},
                    occurred_at=now,
                ),
                AuditDraft(
                    action="dingtalk.outbox.delivered",
                    after_snapshot={"status": "succeeded", "operation": operation},
                ),
            )
        return _outbox_record(row)

    def _fail(
        self,
        *,
        outbox_id: UUID,
        error: DingTalkDeliveryError,
        now: datetime,
    ) -> OutboxRecord:
        with self._engine.begin() as connection:
            current = (
                connection.execute(
                    select(tables.integration_outbox).where(
                        tables.integration_outbox.c.id == outbox_id
                    )
                )
                .mappings()
                .one()
            )
            if error.uncertain:
                status = "uncertain"
                next_attempt_at = None
            elif error.retryable and current["attempt_count"] < current["max_attempts"]:
                status = "retry_wait"
                next_attempt_at = now + timedelta(seconds=min(300, 2 ** current["attempt_count"]))
            else:
                status = "failed"
                next_attempt_at = None
            row = (
                connection.execute(
                    update(tables.integration_outbox)
                    .where(tables.integration_outbox.c.id == outbox_id)
                    .values(
                        status=status,
                        next_attempt_at=next_attempt_at,
                        lease_owner=None,
                        lease_expires_at=None,
                        last_error_code=error.code,
                        last_error_message=error.code,
                        updated_at=now,
                    )
                    .returning(tables.integration_outbox)
                )
                .mappings()
                .one()
            )
            domain_status = (
                "uncertain"
                if status == "uncertain"
                else "manual"
                if status == "retry_wait"
                else "sync_failed"
            )
            if current["operation"] == "gate_approval_create":
                connection.execute(
                    update(tables.dingtalk_approval_instances)
                    .where(tables.dingtalk_approval_instances.c.outbox_id == outbox_id)
                    .values(status=domain_status, updated_at=now)
                )
            elif current["operation"] == "interactive_card_create":
                card_status = (
                    "uncertain"
                    if status == "uncertain"
                    else "manual"
                    if status == "retry_wait"
                    else "failed"
                )
                connection.execute(
                    update(tables.dingtalk_interactive_cards)
                    .where(tables.dingtalk_interactive_cards.c.outbox_id == outbox_id)
                    .values(status=card_status, updated_at=now)
                )
        return _outbox_record(row)
