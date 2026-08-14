"""Same-transaction event and audit writer with allowlisted payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection

from app.db.schema import tables
from app.events.catalog import EventDefinition, definition_for

SENSITIVE_KEY_PARTS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "password",
        "secret",
        "token",
    }
)
NON_SENSITIVE_METRIC_KEYS = frozenset(
    {
        "daily_token_budget",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "used_tokens_today",
        "remaining_tokens_today",
    }
)


class EventSourceMismatchError(ValueError):
    """Raised when a producer does not match the registered server-side source."""


class InvalidEventPayloadError(ValueError):
    """Raised when an event payload does not match its frozen schema."""


class SensitiveAuditDataError(ValueError):
    """Raised before secret-bearing data can enter events or audit storage."""


@dataclass(frozen=True)
class EventDraft:
    event_id: str
    event_type: str
    source: str
    entity_id: UUID
    payload: dict[str, Any]
    occurred_at: datetime | None = None


@dataclass(frozen=True)
class AuditDraft:
    action: str
    before_snapshot: dict[str, Any] | None = None
    after_snapshot: dict[str, Any] | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WrittenEventAudit:
    event_row_id: int
    audit_row_id: int


def _contains_sensitive_key(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized_key = str(key).lower()
            if normalized_key not in NON_SENSITIVE_METRIC_KEYS and any(
                part in normalized_key for part in SENSITIVE_KEY_PARTS
            ):
                return True
            if _contains_sensitive_key(nested):
                return True
        return False
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def _validate_payload(definition: EventDefinition, payload: dict[str, Any]) -> None:
    schema = definition.payload_schema
    required = set(schema["required"])
    properties: dict[str, dict[str, str]] = schema["properties"]
    if set(payload) != required or set(payload) - set(properties):
        raise InvalidEventPayloadError(definition.event_type)

    validators = {
        "string": lambda value: isinstance(value, str),
        "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
        "boolean": lambda value: isinstance(value, bool),
        "object": lambda value: isinstance(value, Mapping),
        "array": lambda value: isinstance(value, list),
    }
    for name, value in payload.items():
        property_type = properties[name]["type"]
        validator = validators.get(property_type)
        if validator is None or not validator(value):
            raise InvalidEventPayloadError(definition.event_type)


class EventAuditWriter:
    def __init__(
        self,
        connection: Connection,
        *,
        tenant_id: UUID,
        actor_user_id: UUID | None,
        project_id: UUID | None = None,
    ) -> None:
        self._connection = connection
        self._tenant_id = tenant_id
        self._actor_user_id = actor_user_id
        self._project_id = project_id

    def record(self, event: EventDraft, audit: AuditDraft) -> WrittenEventAudit:
        definition = definition_for(event.event_type)
        if event.source != definition.producer:
            raise EventSourceMismatchError(event.event_type)
        _validate_payload(definition, event.payload)
        if audit.before_snapshot is None and audit.after_snapshot is None:
            raise InvalidEventPayloadError("audit snapshot required")
        if any(
            _contains_sensitive_key(value)
            for value in (
                event.payload,
                audit.before_snapshot,
                audit.after_snapshot,
                audit.context,
            )
            if value is not None
        ):
            raise SensitiveAuditDataError

        occurred_at = (event.occurred_at or datetime.now(UTC)).astimezone(UTC)
        event_row_id = self._connection.execute(
            tables.events.insert()
            .values(
                tenant_id=self._tenant_id,
                project_id=self._project_id,
                event_id=event.event_id,
                event_type=definition.event_type,
                schema_version=definition.version,
                source=definition.producer,
                entity=definition.entity,
                entity_id=event.entity_id,
                payload=event.payload,
                timestamp=occurred_at,
            )
            .returning(tables.events.c.id)
        ).scalar_one()
        audit_values: dict[str, Any] = {
            "tenant_id": self._tenant_id,
            "project_id": self._project_id,
            "actor_user_id": self._actor_user_id,
            "event_id": event.event_id,
            "action": audit.action,
            "entity": definition.entity,
            "entity_id": event.entity_id,
            "context": audit.context,
            "timestamp": occurred_at,
        }
        if audit.before_snapshot is not None:
            audit_values["before_snapshot"] = audit.before_snapshot
        if audit.after_snapshot is not None:
            audit_values["after_snapshot"] = audit.after_snapshot
        audit_row_id = self._connection.execute(
            tables.audit_log.insert().values(**audit_values).returning(tables.audit_log.c.id)
        ).scalar_one()
        return WrittenEventAudit(event_row_id=event_row_id, audit_row_id=audit_row_id)
