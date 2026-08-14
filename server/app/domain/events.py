"""Tenant-bound, read-only event stream queries for internal debugging."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4, uuid5

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
    requirement_id: UUID | None = None


class CrmCustomerNotFoundError(LookupError):
    """Raised when a CRM customer code is not an active tenant customer."""


class CrmRequirementConflictError(ValueError):
    """Raised when a CRM external identity or Requirement code is already bound."""


EXTERNAL_EVENT_TYPES = frozenset(
    {
        "TEST_FAILED",
        "SUPPLIER_DELAY_REPORTED",
        "COMPLAINT_CREATED",
        "CRM_REQUIREMENT_RECEIVED",
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
        crm_payload = (
            self._crm_payload(payload) if event_type == "CRM_REQUIREMENT_RECEIVED" else None
        )
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
                    return self._replay(connection, existing, expected=expected)
                if event_type == "SUPPLIER_DELAY_REPORTED":
                    self._validate_supplier_delay(
                        connection,
                        tenant_id=tenant_id,
                        payload=payload,
                    )
                written = EventAuditWriter(
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
                requirement_id = None
                if crm_payload is not None:
                    requirement_id = self._create_crm_requirement(
                        connection,
                        tenant_id=tenant_id,
                        actor_user_id=actor_user_id,
                        project_id=project_id,
                        source_event_row_id=written.event_row_id,
                        event_id=event_id,
                        payload=crm_payload,
                        occurred_at=occurred_at,
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
                return EventIngestResult(
                    record=_record(created_row),
                    created=True,
                    requirement_id=requirement_id,
                )
        except IntegrityError as error:
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
                if event_type == "CRM_REQUIREMENT_RECEIVED":
                    raise CrmRequirementConflictError from error
                raise
            with self._engine.connect() as connection:
                return self._replay(connection, concurrent_row, expected=expected)

    @staticmethod
    def _replay(connection: Any, row: RowMapping, *, expected: dict[str, Any]) -> EventIngestResult:
        comparable = {key: row[key] for key in expected}
        comparable["payload"] = dict(comparable["payload"])
        if comparable != expected:
            raise EventIdempotencyConflictError(str(expected["event_id"]))
        requirement_id = connection.execute(
            select(tables.crm_requirement_intakes.c.requirement_id).where(
                tables.crm_requirement_intakes.c.tenant_id == row["tenant_id"],
                tables.crm_requirement_intakes.c.source_event_row_id == row["id"],
            )
        ).scalar_one_or_none()
        return EventIngestResult(record=_record(row), created=False, requirement_id=requirement_id)

    @staticmethod
    def _crm_payload(payload: dict[str, Any]) -> dict[str, Any]:
        criteria = payload.get("acceptance_criteria")
        required_text = {
            "external_requirement_id": 128,
            "code": 64,
            "title": 512,
        }
        for key, limit in required_text.items():
            value = payload.get(key)
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
                raise InvalidEventPayloadError("CRM_REQUIREMENT_RECEIVED")
        description = payload.get("description")
        customer_code = payload.get("customer_code")
        priority = payload.get("priority")
        if (
            not isinstance(description, str)
            or len(description) > 20_000
            or not isinstance(customer_code, str)
            or len(customer_code.strip()) > 64
            or priority not in {"low", "medium", "high", "critical"}
            or not isinstance(criteria, list)
            or len(criteria) > 100
            or any(
                not isinstance(value, str) or not value.strip() or len(value.strip()) > 512
                for value in criteria
            )
        ):
            raise InvalidEventPayloadError("CRM_REQUIREMENT_RECEIVED")
        return {
            "external_requirement_id": payload["external_requirement_id"].strip(),
            "code": payload["code"].strip(),
            "title": payload["title"].strip(),
            "description": description.strip() or None,
            "priority": priority,
            "acceptance_criteria": [value.strip() for value in criteria],
            "customer_code": customer_code.strip(),
        }

    @staticmethod
    def _validate_supplier_delay(
        connection: Any,
        *,
        tenant_id: UUID,
        payload: dict[str, Any],
    ) -> None:
        try:
            supplier_id = UUID(str(payload["supplier_id"]))
            expected_date = date.fromisoformat(str(payload["expected_date"]))
            reported_date = date.fromisoformat(str(payload["reported_date"]))
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidEventPayloadError("SUPPLIER_DELAY_REPORTED") from error
        if (
            str(payload["supplier_id"]) != str(supplier_id)
            or str(payload["expected_date"]) != expected_date.isoformat()
            or str(payload["reported_date"]) != reported_date.isoformat()
            or reported_date <= expected_date
        ):
            raise InvalidEventPayloadError("SUPPLIER_DELAY_REPORTED")
        supplier_exists = connection.execute(
            select(tables.suppliers.c.id).where(
                tables.suppliers.c.tenant_id == tenant_id,
                tables.suppliers.c.id == supplier_id,
                tables.suppliers.c.status == "active",
            )
        ).scalar_one_or_none()
        if supplier_exists is None:
            raise InvalidEventPayloadError("SUPPLIER_DELAY_REPORTED")

    @staticmethod
    def _create_crm_requirement(
        connection: Any,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        source_event_row_id: int,
        event_id: str,
        payload: dict[str, Any],
        occurred_at: datetime,
    ) -> UUID:
        customer_id = None
        if payload["customer_code"]:
            customer_id = connection.execute(
                select(tables.customers.c.id).where(
                    tables.customers.c.tenant_id == tenant_id,
                    tables.customers.c.code == payload["customer_code"],
                    tables.customers.c.status == "active",
                )
            ).scalar_one_or_none()
            if customer_id is None:
                raise CrmCustomerNotFoundError
        requirement_id = uuid5(tenant_id, f"crm-requirement:{event_id}")
        connection.execute(
            tables.requirements.insert(),
            {
                "id": requirement_id,
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "created_by_user_id": actor_user_id,
                "code": payload["code"],
                "title": payload["title"],
                "description": payload["description"],
                "source": "crm",
                "status": "draft",
                "priority": payload["priority"],
                "acceptance_criteria": payload["acceptance_criteria"],
                "created_at": occurred_at,
                "updated_at": occurred_at,
            },
        )
        connection.execute(
            tables.crm_requirement_intakes.insert(),
            {
                "id": uuid4(),
                "tenant_id": tenant_id,
                "project_id": project_id,
                "requirement_id": requirement_id,
                "source_event_row_id": source_event_row_id,
                "external_requirement_id": payload["external_requirement_id"],
                "created_at": occurred_at,
                "updated_at": occurred_at,
            },
        )
        EventAuditWriter(
            connection,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            project_id=project_id,
        ).record(
            EventDraft(
                event_id=f"requirement:{requirement_id}:created",
                event_type="REQUIREMENT_CREATED",
                source="requirement_service",
                entity_id=requirement_id,
                payload={
                    "requirement_code": payload["code"],
                    "status": "draft",
                    "priority": payload["priority"],
                },
                occurred_at=occurred_at,
            ),
            AuditDraft(
                action="requirement.create_from_crm",
                after_snapshot={
                    "code": payload["code"],
                    "title": payload["title"],
                    "source": "crm",
                    "status": "draft",
                    "priority": payload["priority"],
                    "customer_id": str(customer_id) if customer_id else None,
                },
                context={"source_event_row_id": source_event_row_id},
            ),
        )
        return requirement_id


__all__ = [
    "EventIdempotencyConflictError",
    "EventPage",
    "EventProjectNotFoundError",
    "EventQueryService",
    "EventRecord",
    "CrmCustomerNotFoundError",
    "CrmRequirementConflictError",
    "ExternalEventService",
    "ExternalEventTypeDeniedError",
    "InvalidEventPayloadError",
    "SensitiveAuditDataError",
]
