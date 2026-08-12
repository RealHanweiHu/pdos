"""Tenant-bound, read-only event stream queries for internal debugging."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError

from app.db.schema import tables
from app.events.catalog import definition_for
from app.events.writer import (
    AuditDraft,
    EventAuditWriter,
    EventDraft,
    InvalidEventPayloadError,
    SensitiveAuditDataError,
)


class EventProjectNotFoundError(LookupError):
    """Raised when a Project filter is absent from the authenticated tenant."""


class ExternalEventTypeDeniedError(ValueError):
    """Raised when the public ingestion port is asked to impersonate an internal service."""


class EventIdempotencyConflictError(ValueError):
    """Raised when an idempotency key is reused with a different immutable request."""


@dataclass(frozen=True)
class EventRecord:
    id: int
    project_id: UUID | None
    event_id: str
    event_type: str
    schema_version: int
    source: str
    entity: str
    entity_id: UUID
    payload: dict[str, Any]
    timestamp: datetime
    consumers: tuple[str, ...]


@dataclass(frozen=True)
class EventPage:
    items: tuple[EventRecord, ...]
    next_after_id: int | None
    has_more: bool


@dataclass(frozen=True)
class EventIngestResult:
    record: EventRecord
    created: bool


EXTERNAL_EVENT_TYPES = frozenset(
    {
        "TEST_FAILED",
        "SUPPLIER_DELAY_REPORTED",
        "COMPLAINT_CREATED",
    }
)


def _record(row: RowMapping) -> EventRecord:
    definition = definition_for(row["event_type"])
    return EventRecord(
        id=row["id"],
        project_id=row["project_id"],
        event_id=row["event_id"],
        event_type=row["event_type"],
        schema_version=row["schema_version"],
        source=row["source"],
        entity=row["entity"],
        entity_id=row["entity_id"],
        payload=dict(row["payload"]),
        timestamp=row["timestamp"],
        consumers=definition.consumers,
    )


class EventQueryService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list(
        self,
        *,
        tenant_id: UUID,
        after_id: int | None,
        limit: int,
        event_type: str | None,
        project_id: UUID | None,
    ) -> EventPage:
        with self._engine.connect() as connection:
            if project_id is not None:
                project_exists = connection.execute(
                    select(tables.projects.c.id).where(
                        tables.projects.c.tenant_id == tenant_id,
                        tables.projects.c.id == project_id,
                    )
                ).scalar_one_or_none()
                if project_exists is None:
                    raise EventProjectNotFoundError

            statement = select(tables.events).where(tables.events.c.tenant_id == tenant_id)
            if after_id is not None:
                statement = statement.where(tables.events.c.id > after_id)
            if event_type is not None:
                statement = statement.where(tables.events.c.event_type == event_type)
            if project_id is not None:
                statement = statement.where(tables.events.c.project_id == project_id)
            rows = list(
                connection.execute(
                    statement.order_by(tables.events.c.id).limit(limit + 1)
                ).mappings()
            )

        has_more = len(rows) > limit
        records = tuple(_record(row) for row in rows[:limit])
        return EventPage(
            items=records,
            next_after_id=records[-1].id if records else after_id,
            has_more=has_more,
        )


class ExternalEventService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def ingest(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        event_id: str,
        event_type: str,
        entity_id: UUID,
        payload: dict[str, Any],
        occurred_at: datetime,
    ) -> EventIngestResult:
        if event_type not in EXTERNAL_EVENT_TYPES:
            raise ExternalEventTypeDeniedError(event_type)
        definition = definition_for(event_type)
        expected = {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "event_id": event_id,
            "event_type": event_type,
            "schema_version": definition.version,
            "source": definition.producer,
            "entity": definition.entity,
            "entity_id": entity_id,
            "payload": payload,
            "timestamp": occurred_at,
        }
        try:
            with self._engine.begin() as connection:
                existing = (
                    connection.execute(
                        select(tables.events).where(
                            tables.events.c.source == definition.producer,
                            tables.events.c.event_id == event_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    return self._replay(existing, expected=expected)
                EventAuditWriter(
                    connection,
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    project_id=project_id,
                ).record(
                    EventDraft(
                        event_id=event_id,
                        event_type=event_type,
                        source=definition.producer,
                        entity_id=entity_id,
                        payload=payload,
                        occurred_at=occurred_at,
                    ),
                    AuditDraft(
                        action="external_event.ingest",
                        after_snapshot={
                            "event_id": event_id,
                            "event_type": event_type,
                            "entity_id": str(entity_id),
                            "payload": payload,
                            "occurred_at": occurred_at.isoformat(),
                        },
                        context={"ingress": "authenticated_api"},
                    ),
                )
                created_row = (
                    connection.execute(
                        select(tables.events).where(
                            tables.events.c.source == definition.producer,
                            tables.events.c.event_id == event_id,
                        )
                    )
                    .mappings()
                    .one()
                )
                return EventIngestResult(record=_record(created_row), created=True)
        except IntegrityError:
            with self._engine.connect() as connection:
                concurrent_row = (
                    connection.execute(
                        select(tables.events).where(
                            tables.events.c.source == definition.producer,
                            tables.events.c.event_id == event_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
            if concurrent_row is None:
                raise
            return self._replay(concurrent_row, expected=expected)

    @staticmethod
    def _replay(row: RowMapping, *, expected: dict[str, Any]) -> EventIngestResult:
        comparable = {key: row[key] for key in expected}
        comparable["payload"] = dict(comparable["payload"])
        if comparable != expected:
            raise EventIdempotencyConflictError(str(expected["event_id"]))
        return EventIngestResult(record=_record(row), created=False)


__all__ = [
    "EventIdempotencyConflictError",
    "EventPage",
    "EventProjectNotFoundError",
    "EventQueryService",
    "EventRecord",
    "ExternalEventService",
    "ExternalEventTypeDeniedError",
    "InvalidEventPayloadError",
    "SensitiveAuditDataError",
]
