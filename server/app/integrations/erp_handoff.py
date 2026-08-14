"""Durable, tenant-bound ERP EBOM handoff intents and manual fallback."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, select, update
from sqlalchemy.engine import RowMapping

from app.db.schema import tables
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class ErpHandoffError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ErpOutboxRecord:
    id: UUID
    status: str
    delivery_mode: str
    attempt_count: int
    payload_digest: str
    remote_reference: str | None
    last_error_code: str | None


@dataclass(frozen=True)
class ErpDelivery:
    handoff: dict[str, Any]
    outbox: ErpOutboxRecord
    delivery_package: dict[str, Any]


def _outbox_record(row: RowMapping) -> ErpOutboxRecord:
    return ErpOutboxRecord(
        id=row["id"],
        status=row["status"],
        delivery_mode=row["delivery_mode"],
        attempt_count=row["attempt_count"],
        payload_digest=row["payload_digest"],
        remote_reference=row["remote_reference"],
        last_error_code=row["last_error_code"],
    )


def _package(handoff: RowMapping) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "handoff_id": str(handoff["id"]),
        "tenant_id": str(handoff["tenant_id"]),
        "project_id": str(handoff["project_id"]),
        "ecn_id": str(handoff["ecn_id"]),
        "source_system": handoff["source_system"],
        "target_system": handoff["target_system"],
        "source_bom": dict(handoff["source_bom_snapshot"]),
        "effectivity": dict(handoff["effectivity_snapshot"]),
    }


def _digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


class ErpHandoffService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def queue(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        handoff_id: UUID,
        idempotency_key: str,
        mode: Literal["manual", "api"],
    ) -> ErpDelivery:
        if mode != "manual":
            raise ErpHandoffError("ERP_API_NOT_CONFIGURED")
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            handoff = self._handoff(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                handoff_id=handoff_id,
                lock=True,
            )
            payload = _package(handoff)
            payload_digest = _digest(payload)
            existing = self._outbox(connection, tenant_id=tenant_id, handoff_id=handoff_id)
            if existing is not None:
                if (
                    existing["idempotency_key"] != idempotency_key
                    or existing["delivery_mode"] != mode
                    or dict(existing["payload"]) != payload
                    or existing["payload_digest"] != payload_digest
                ):
                    raise ErpHandoffError("ERP_HANDOFF_ALREADY_QUEUED")
                return ErpDelivery(dict(handoff), _outbox_record(existing), payload)
            if handoff["status"] != "ready":
                raise ErpHandoffError("ERP_HANDOFF_NOT_READY")
            outbox = (
                connection.execute(
                    tables.integration_outbox.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        project_id=project_id,
                        erp_handoff_id=handoff_id,
                        provider="erp",
                        operation="ebom_handoff",
                        delivery_mode=mode,
                        idempotency_key=idempotency_key,
                        payload=payload,
                        payload_digest=payload_digest,
                        status="manual",
                        last_error_code="ERP_MANUAL_DELIVERY_REQUIRED",
                        created_at=now,
                        updated_at=now,
                    )
                    .returning(tables.integration_outbox)
                )
                .mappings()
                .one()
            )
            updated_handoff = self._update_handoff(
                connection,
                handoff=handoff,
                values={"status": "queued", "last_error": None, "updated_at": now},
            )
            self._record(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                handoff_id=handoff_id,
                action="queued",
                before_status="ready",
                after_status="queued",
                context={"delivery_mode": mode, "payload_digest": payload_digest},
            )
            return ErpDelivery(dict(updated_handoff), _outbox_record(outbox), payload)

    def get(self, *, tenant_id: UUID, project_id: UUID, handoff_id: UUID) -> ErpDelivery:
        with self._engine.connect() as connection:
            handoff = self._handoff(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                handoff_id=handoff_id,
            )
            outbox = self._outbox(connection, tenant_id=tenant_id, handoff_id=handoff_id)
            if outbox is None:
                raise ErpHandoffError("ERP_OUTBOX_NOT_FOUND")
            return ErpDelivery(dict(handoff), _outbox_record(outbox), dict(outbox["payload"]))

    def export_manual(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        handoff_id: UUID,
    ) -> ErpDelivery:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            handoff, outbox = self._locked_delivery(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                handoff_id=handoff_id,
            )
            if (
                handoff["status"] != "queued"
                or outbox["delivery_mode"] != "manual"
                or outbox["status"] != "manual"
            ):
                raise ErpHandoffError("ERP_EXPORT_NOT_ALLOWED")
            updated_outbox = (
                connection.execute(
                    update(tables.integration_outbox)
                    .where(tables.integration_outbox.c.id == outbox["id"])
                    .values(
                        status="succeeded",
                        attempt_count=tables.integration_outbox.c.attempt_count + 1,
                        completed_at=now,
                        last_error_code=None,
                        last_error_message=None,
                        updated_at=now,
                    )
                    .returning(tables.integration_outbox)
                )
                .mappings()
                .one()
            )
            updated_handoff = self._update_handoff(
                connection,
                handoff=handoff,
                values={"status": "sent", "last_error": None, "updated_at": now},
            )
            self._record(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                handoff_id=handoff_id,
                action="exported",
                before_status="queued",
                after_status="sent",
                context={"delivery_mode": "manual", "payload_digest": outbox["payload_digest"]},
            )
            return ErpDelivery(
                dict(updated_handoff), _outbox_record(updated_outbox), dict(outbox["payload"])
            )

    def reconcile(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        handoff_id: UUID,
        outcome: Literal["confirmed_delivered", "confirmed_not_delivered"],
        external_reference: str | None,
    ) -> ErpDelivery:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            handoff, outbox = self._locked_delivery(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                handoff_id=handoff_id,
            )
            if handoff["status"] != "sent" or outbox["status"] not in {"succeeded", "uncertain"}:
                raise ErpHandoffError("ERP_RECONCILIATION_NOT_ALLOWED")
            if outcome == "confirmed_delivered":
                if external_reference is None or not external_reference.strip():
                    raise ErpHandoffError("ERP_EXTERNAL_REFERENCE_REQUIRED")
                normalized_reference = external_reference.strip()
                handoff_status, outbox_status, error_code = "confirmed", "succeeded", None
            else:
                if external_reference is not None:
                    raise ErpHandoffError("ERP_EXTERNAL_REFERENCE_NOT_ALLOWED")
                normalized_reference = None
                handoff_status, outbox_status, error_code = (
                    "failed",
                    "failed",
                    "ERP_RECONCILED_NOT_DELIVERED",
                )
            updated_outbox = (
                connection.execute(
                    update(tables.integration_outbox)
                    .where(tables.integration_outbox.c.id == outbox["id"])
                    .values(
                        status=outbox_status,
                        remote_reference=normalized_reference,
                        last_error_code=error_code,
                        last_error_message=error_code,
                        updated_at=now,
                    )
                    .returning(tables.integration_outbox)
                )
                .mappings()
                .one()
            )
            updated_handoff = self._update_handoff(
                connection,
                handoff=handoff,
                values={
                    "status": handoff_status,
                    "external_reference": normalized_reference,
                    "last_error": error_code,
                    "updated_at": now,
                },
            )
            self._record(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                handoff_id=handoff_id,
                action="reconciled",
                before_status="sent",
                after_status=handoff_status,
                context={"outcome": outcome},
            )
            return ErpDelivery(
                dict(updated_handoff), _outbox_record(updated_outbox), dict(outbox["payload"])
            )

    def replay(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        handoff_id: UUID,
    ) -> ErpDelivery:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            handoff, outbox = self._locked_delivery(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                handoff_id=handoff_id,
            )
            if handoff["status"] != "failed" or outbox["status"] != "failed":
                raise ErpHandoffError("ERP_REPLAY_NOT_ALLOWED")
            if outbox["attempt_count"] >= outbox["max_attempts"]:
                raise ErpHandoffError("ERP_REPLAY_LIMIT_REACHED")
            status = "manual" if outbox["delivery_mode"] == "manual" else "pending"
            updated_outbox = (
                connection.execute(
                    update(tables.integration_outbox)
                    .where(tables.integration_outbox.c.id == outbox["id"])
                    .values(
                        status=status,
                        next_attempt_at=now if status == "pending" else None,
                        remote_reference=None,
                        completed_at=None,
                        last_error_code=(
                            "ERP_MANUAL_DELIVERY_REQUIRED" if status == "manual" else None
                        ),
                        last_error_message=None,
                        updated_at=now,
                    )
                    .returning(tables.integration_outbox)
                )
                .mappings()
                .one()
            )
            updated_handoff = self._update_handoff(
                connection,
                handoff=handoff,
                values={
                    "status": "queued",
                    "external_reference": None,
                    "last_error": None,
                    "updated_at": now,
                },
            )
            self._record(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                handoff_id=handoff_id,
                action="replayed",
                before_status="failed",
                after_status="queued",
                context={"delivery_mode": outbox["delivery_mode"]},
            )
            return ErpDelivery(
                dict(updated_handoff), _outbox_record(updated_outbox), dict(outbox["payload"])
            )

    @staticmethod
    def _handoff(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        handoff_id: UUID,
        lock: bool = False,
    ) -> RowMapping:
        statement = select(tables.erp_handoffs).where(
            tables.erp_handoffs.c.tenant_id == tenant_id,
            tables.erp_handoffs.c.project_id == project_id,
            tables.erp_handoffs.c.id == handoff_id,
        )
        if lock:
            statement = statement.with_for_update()
        row = connection.execute(statement).mappings().one_or_none()
        if row is None:
            raise ErpHandoffError("ERP_HANDOFF_NOT_FOUND")
        return row

    @staticmethod
    def _outbox(
        connection: Connection, *, tenant_id: UUID, handoff_id: UUID, lock: bool = False
    ) -> RowMapping | None:
        statement = select(tables.integration_outbox).where(
            tables.integration_outbox.c.tenant_id == tenant_id,
            tables.integration_outbox.c.provider == "erp",
            tables.integration_outbox.c.erp_handoff_id == handoff_id,
        )
        if lock:
            statement = statement.with_for_update()
        return connection.execute(statement).mappings().one_or_none()

    def _locked_delivery(
        self,
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        handoff_id: UUID,
    ) -> tuple[RowMapping, RowMapping]:
        handoff = self._handoff(
            connection,
            tenant_id=tenant_id,
            project_id=project_id,
            handoff_id=handoff_id,
            lock=True,
        )
        outbox = self._outbox(connection, tenant_id=tenant_id, handoff_id=handoff_id, lock=True)
        if outbox is None:
            raise ErpHandoffError("ERP_OUTBOX_NOT_FOUND")
        return handoff, outbox

    @staticmethod
    def _update_handoff(
        connection: Connection, *, handoff: RowMapping, values: dict[str, Any]
    ) -> RowMapping:
        return (
            connection.execute(
                update(tables.erp_handoffs)
                .where(
                    tables.erp_handoffs.c.tenant_id == handoff["tenant_id"],
                    tables.erp_handoffs.c.id == handoff["id"],
                )
                .values(**values)
                .returning(tables.erp_handoffs)
            )
            .mappings()
            .one()
        )

    @staticmethod
    def _record(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        handoff_id: UUID,
        action: str,
        before_status: str,
        after_status: str,
        context: dict[str, Any],
    ) -> None:
        EventAuditWriter(
            connection,
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=actor_user_id,
        ).record(
            EventDraft(
                event_id=f"erp-handoff:{handoff_id}:{action}:{uuid4()}",
                event_type="CHANGE_RECORD_CHANGED",
                source="change_service",
                entity_id=handoff_id,
                payload={"record_type": "erp_handoff", "action": action},
            ),
            AuditDraft(
                action=f"change.erp_handoff.{action}",
                before_snapshot={"status": before_status},
                after_snapshot={"status": after_status},
                context=context,
            ),
        )
