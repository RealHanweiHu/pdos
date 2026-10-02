"""Requirement pool use cases with tenant-bound persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import Select

from app.db.schema import tables
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class CustomerNotFoundError(LookupError):
    """Raised when a Customer is absent from the active tenant scope."""


class CustomerCodeConflictError(ValueError):
    """Raised when a Customer code already exists in the tenant."""


class RequirementCodeConflictError(ValueError):
    """Raised when a Requirement code already exists in the tenant."""


class RequirementNotFoundError(LookupError):
    """Raised when a Requirement is absent from the active tenant scope."""


class CrmRequirementReviewRequiredError(ValueError):
    """Raised when a CRM draft tries to bypass the explicit review action."""


class CrmRequirementIntakeNotFoundError(LookupError):
    """Raised when a Requirement has no tenant-bound CRM intake."""


class CrmRequirementAlreadyReviewedError(ValueError):
    """Raised when a CRM intake review is repeated or its draft already moved."""


@dataclass(frozen=True)
class CustomerRecord:
    id: UUID
    code: str
    name: str
    status: str


@dataclass(frozen=True)
class CustomerCreate:
    code: str
    name: str


@dataclass(frozen=True)
class RequirementRecord:
    id: UUID
    code: str
    title: str
    description: str | None
    source: str | None
    status: str
    priority: str
    acceptance_criteria: list[str]
    customer: CustomerRecord | None
    created_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class RequirementCreate:
    code: str
    title: str
    description: str | None
    source: str | None
    priority: str
    acceptance_criteria: list[str]
    customer_id: UUID | None


@dataclass(frozen=True)
class RequirementUpdate:
    changes: dict[str, object]


def _requirement_statement() -> Select[Any]:
    return select(
        tables.requirements.c.id,
        tables.requirements.c.code,
        tables.requirements.c.title,
        tables.requirements.c.description,
        tables.requirements.c.source,
        tables.requirements.c.status,
        tables.requirements.c.priority,
        tables.requirements.c.acceptance_criteria,
        tables.requirements.c.created_by_user_id,
        tables.requirements.c.created_at,
        tables.requirements.c.updated_at,
        tables.customers.c.id.label("customer_record_id"),
        tables.customers.c.code.label("customer_code"),
        tables.customers.c.name.label("customer_name"),
        tables.customers.c.status.label("customer_status"),
    ).select_from(
        tables.requirements.outerjoin(
            tables.customers,
            (tables.customers.c.tenant_id == tables.requirements.c.tenant_id)
            & (tables.customers.c.id == tables.requirements.c.customer_id),
        )
    )


def _record_from_row(row: RowMapping) -> RequirementRecord:
    customer = None
    if row["customer_record_id"] is not None:
        customer = CustomerRecord(
            id=row["customer_record_id"],
            code=row["customer_code"],
            name=row["customer_name"],
            status=row["customer_status"],
        )
    return RequirementRecord(
        id=row["id"],
        code=row["code"],
        title=row["title"],
        description=row["description"],
        source=row["source"],
        status=row["status"],
        priority=row["priority"],
        acceptance_criteria=list(row["acceptance_criteria"]),
        customer=customer,
        created_by_user_id=row["created_by_user_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _snapshot(record: RequirementRecord) -> dict[str, object]:
    return {
        "code": record.code,
        "title": record.title,
        "description": record.description,
        "source": record.source,
        "status": record.status,
        "priority": record.priority,
        "acceptance_criteria": record.acceptance_criteria,
        "customer_id": str(record.customer.id) if record.customer is not None else None,
        "created_by_user_id": (
            str(record.created_by_user_id) if record.created_by_user_id is not None else None
        ),
    }


class CustomerService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        draft: CustomerCreate,
    ) -> CustomerRecord:
        customer_id = uuid4()
        occurred_at = datetime.now(UTC)
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    tables.customers.insert(),
                    {
                        "id": customer_id,
                        "tenant_id": tenant_id,
                        "code": draft.code,
                        "name": draft.name,
                        "created_at": occurred_at,
                        "updated_at": occurred_at,
                    },
                )
                record = CustomerRecord(
                    id=customer_id,
                    code=draft.code,
                    name=draft.name,
                    status="active",
                )
                snapshot = {
                    "code": record.code,
                    "name": record.name,
                    "status": record.status,
                }
                EventAuditWriter(
                    connection,
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                ).record(
                    EventDraft(
                        event_id=f"customer:{customer_id}:created",
                        event_type="CUSTOMER_CREATED",
                        source="customer_service",
                        entity_id=customer_id,
                        payload={"customer_code": record.code, "status": record.status},
                        occurred_at=occurred_at,
                    ),
                    AuditDraft(action="customer.create", after_snapshot=snapshot),
                )
                return record
        except IntegrityError as error:
            if "uq_customers_tenant_code" in str(error.orig):
                raise CustomerCodeConflictError from error
            raise


class RequirementService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _active_customer_exists(
        connection: Connection,
        *,
        tenant_id: UUID,
        customer_id: UUID,
    ) -> bool:
        statement = select(tables.customers.c.id).where(
            tables.customers.c.tenant_id == tenant_id,
            tables.customers.c.id == customer_id,
            tables.customers.c.status == "active",
        )
        return connection.execute(statement).scalar_one_or_none() is not None

    @staticmethod
    def _get_record(
        connection: Connection,
        *,
        tenant_id: UUID,
        requirement_id: UUID,
    ) -> RequirementRecord:
        statement = _requirement_statement().where(
            tables.requirements.c.tenant_id == tenant_id,
            tables.requirements.c.id == requirement_id,
        )
        row = connection.execute(statement).mappings().one_or_none()
        if row is None:
            raise RequirementNotFoundError
        return _record_from_row(row)

    def get(self, *, tenant_id: UUID, requirement_id: UUID) -> RequirementRecord:
        with self._engine.connect() as connection:
            return self._get_record(
                connection,
                tenant_id=tenant_id,
                requirement_id=requirement_id,
            )

    def list(self, *, tenant_id: UUID) -> list[RequirementRecord]:
        statement = (
            _requirement_statement()
            .where(tables.requirements.c.tenant_id == tenant_id)
            .order_by(
                tables.requirements.c.updated_at.desc(),
                tables.requirements.c.id.desc(),
            )
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement).mappings()
            return [_record_from_row(row) for row in rows]

    def create(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        draft: RequirementCreate,
    ) -> RequirementRecord:
        try:
            with self._engine.begin() as connection:
                return self.create_connection(
                    connection, tenant_id=tenant_id, actor_user_id=actor_user_id, draft=draft
                )
        except IntegrityError as error:
            if "uq_requirements_tenant_code" in str(error.orig):
                raise RequirementCodeConflictError from error
            raise

    def create_connection(
        self,
        connection: Connection,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        draft: RequirementCreate,
    ) -> RequirementRecord:
        """Shared transaction boundary for reviewed draft intake batches."""
        requirement_id = uuid4()
        occurred_at = datetime.now(UTC)
        if draft.customer_id is not None and not self._active_customer_exists(
            connection,
            tenant_id=tenant_id,
            customer_id=draft.customer_id,
        ):
            raise CustomerNotFoundError
        connection.execute(
            tables.requirements.insert(),
            {
                "id": requirement_id,
                "tenant_id": tenant_id,
                "customer_id": draft.customer_id,
                "created_by_user_id": actor_user_id,
                "code": draft.code,
                "title": draft.title,
                "description": draft.description,
                "source": draft.source,
                "status": "draft",
                "priority": draft.priority,
                "acceptance_criteria": draft.acceptance_criteria,
                "created_at": occurred_at,
                "updated_at": occurred_at,
            },
        )
        record = self._get_record(
            connection,
            tenant_id=tenant_id,
            requirement_id=requirement_id,
        )
        EventAuditWriter(
            connection,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
        ).record(
            EventDraft(
                event_id=f"requirement:{requirement_id}:created",
                event_type="REQUIREMENT_CREATED",
                source="requirement_service",
                entity_id=requirement_id,
                payload={
                    "requirement_code": record.code,
                    "status": record.status,
                    "priority": record.priority,
                },
                occurred_at=occurred_at,
            ),
            AuditDraft(
                action="requirement.create",
                after_snapshot=_snapshot(record),
            ),
        )
        return record

    def update(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        requirement_id: UUID,
        patch: RequirementUpdate,
    ) -> RequirementRecord:
        if "source" in patch.changes:
            raise ValueError("requirement source is immutable")
        occurred_at = datetime.now(UTC)
        try:
            with self._engine.begin() as connection:
                locked_id = connection.execute(
                    select(tables.requirements.c.id)
                    .where(
                        tables.requirements.c.tenant_id == tenant_id,
                        tables.requirements.c.id == requirement_id,
                    )
                    .with_for_update()
                ).scalar_one_or_none()
                if locked_id is None:
                    raise RequirementNotFoundError
                before = self._get_record(
                    connection,
                    tenant_id=tenant_id,
                    requirement_id=requirement_id,
                )
                if "status" in patch.changes and before.source == "crm":
                    pending_intake = connection.execute(
                        select(tables.crm_requirement_intakes.c.id).where(
                            tables.crm_requirement_intakes.c.tenant_id == tenant_id,
                            tables.crm_requirement_intakes.c.requirement_id == requirement_id,
                            tables.crm_requirement_intakes.c.status == "pending_review",
                        )
                    ).scalar_one_or_none()
                    if pending_intake is not None and patch.changes["status"] != "draft":
                        raise CrmRequirementReviewRequiredError
                if "customer_id" in patch.changes:
                    customer_id = patch.changes["customer_id"]
                    if customer_id is not None and (
                        not isinstance(customer_id, UUID)
                        or not self._active_customer_exists(
                            connection,
                            tenant_id=tenant_id,
                            customer_id=customer_id,
                        )
                    ):
                        raise CustomerNotFoundError
                connection.execute(
                    tables.requirements.update()
                    .where(
                        tables.requirements.c.tenant_id == tenant_id,
                        tables.requirements.c.id == requirement_id,
                    )
                    .values(**patch.changes, updated_at=occurred_at)
                )
                after = self._get_record(
                    connection,
                    tenant_id=tenant_id,
                    requirement_id=requirement_id,
                )
                EventAuditWriter(
                    connection,
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                ).record(
                    EventDraft(
                        event_id=f"requirement:{requirement_id}:updated:{uuid4()}",
                        event_type="REQUIREMENT_UPDATED",
                        source="requirement_service",
                        entity_id=requirement_id,
                        payload={
                            "changed_fields": sorted(patch.changes),
                            "status": after.status,
                            "priority": after.priority,
                        },
                        occurred_at=occurred_at,
                    ),
                    AuditDraft(
                        action="requirement.update",
                        before_snapshot=_snapshot(before),
                        after_snapshot=_snapshot(after),
                    ),
                )
                return after
        except IntegrityError as error:
            if "uq_requirements_tenant_code" in str(error.orig):
                raise RequirementCodeConflictError from error
            raise

    def review_crm_intake(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        requirement_id: UUID,
        decision: str,
        rationale: str,
    ) -> RequirementRecord:
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            intake = (
                connection.execute(
                    select(tables.crm_requirement_intakes)
                    .where(
                        tables.crm_requirement_intakes.c.tenant_id == tenant_id,
                        tables.crm_requirement_intakes.c.requirement_id == requirement_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if intake is None:
                raise CrmRequirementIntakeNotFoundError
            before = self._get_record(
                connection,
                tenant_id=tenant_id,
                requirement_id=requirement_id,
            )
            if intake["status"] != "pending_review" or before.status != "draft":
                raise CrmRequirementAlreadyReviewedError
            intake_status = "established" if decision == "establish" else "rejected"
            requirement_status = "proposed" if decision == "establish" else "rejected"
            connection.execute(
                tables.crm_requirement_intakes.update()
                .where(
                    tables.crm_requirement_intakes.c.tenant_id == tenant_id,
                    tables.crm_requirement_intakes.c.id == intake["id"],
                )
                .values(
                    status=intake_status,
                    reviewed_by_user_id=actor_user_id,
                    reviewed_at=occurred_at,
                    review_rationale=rationale,
                    updated_at=occurred_at,
                )
            )
            connection.execute(
                tables.requirements.update()
                .where(
                    tables.requirements.c.tenant_id == tenant_id,
                    tables.requirements.c.id == requirement_id,
                )
                .values(status=requirement_status, updated_at=occurred_at)
            )
            after = self._get_record(
                connection,
                tenant_id=tenant_id,
                requirement_id=requirement_id,
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=intake["project_id"],
            ).record(
                EventDraft(
                    event_id=f"requirement:{requirement_id}:crm-review:{intake['id']}",
                    event_type="REQUIREMENT_UPDATED",
                    source="requirement_service",
                    entity_id=requirement_id,
                    payload={
                        "changed_fields": ["status"],
                        "status": requirement_status,
                        "priority": after.priority,
                    },
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="requirement.crm_intake_review",
                    before_snapshot=_snapshot(before),
                    after_snapshot=_snapshot(after),
                    context={"decision": decision, "rationale": rationale},
                ),
            )
            return after
