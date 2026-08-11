"""Tenant-bound, read-only event stream queries for internal debugging."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.engine import RowMapping

from app.db.schema import tables
from app.events.catalog import definition_for


class EventProjectNotFoundError(LookupError):
    """Raised when a Project filter is absent from the authenticated tenant."""


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
