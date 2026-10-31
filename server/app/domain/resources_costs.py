"""Project resource allocation and cost register over the cehub_cost / resource tables."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, Table, func, select
from sqlalchemy.engine import RowMapping

from app.db.schema import tables
from app.domain.tasks import ASSIGNABLE_MEMBER_ROLES
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class RegisterNotFoundError(LookupError):
    """Raised when the Project or record is absent from the tenant."""


class RegisterScopeError(ValueError):
    """Raised when an assigned user is not an internal member of the Project."""


class RegisterLockedError(ValueError):
    """Raised when a record is edited past its editable status, or the Project is archived."""


class RegisterInvalidTransitionError(ValueError):
    """Raised when a status edge is outside the register's graph."""


class RegisterDateOrderError(ValueError):
    """Raised when an end date precedes its start date."""


CENTS = Decimal("0.01")

COST_TRANSITIONS: dict[str, frozenset[str]] = {
    "estimate": frozenset({"approved"}),
    "approved": frozenset({"actual"}),
    "actual": frozenset(),
}
RESOURCE_TRANSITIONS: dict[str, frozenset[str]] = {
    "planned": frozenset({"active", "released"}),
    "active": frozenset({"released"}),
    "released": frozenset(),
}


@dataclass(frozen=True)
class CostRecord:
    id: UUID
    project_id: UUID
    code: str
    cost_type: str
    amount: Decimal
    currency: str
    status: str
    incurred_on: date | None
    description: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ResourceRecord:
    id: UUID
    project_id: UUID
    code: str
    name: str
    resource_type: str
    assigned_user_id: UUID | None
    allocation_percent: Decimal
    start_date: date | None
    end_date: date | None
    status: str
    # Sum of the assignee's active allocations across every tenant Project (load check).
    assignee_active_allocation_percent: Decimal | None
    created_at: datetime
    updated_at: datetime


def _cost_from_row(row: RowMapping) -> CostRecord:
    details = row["details"] or {}
    return CostRecord(
        id=row["id"],
        project_id=row["project_id"],
        code=row["code"],
        cost_type=row["cost_type"],
        amount=Decimal(row["amount"]).quantize(CENTS),
        currency=row["currency"],
        status=row["status"],
        incurred_on=row["incurred_on"],
        description=details.get("description"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _cost_snapshot(record: CostRecord) -> dict[str, object]:
    return {
        "code": record.code,
        "cost_type": record.cost_type,
        "amount": str(record.amount),
        "currency": record.currency,
        "status": record.status,
        "incurred_on": record.incurred_on.isoformat() if record.incurred_on else None,
        "description": record.description,
    }


def _resource_snapshot(record: ResourceRecord) -> dict[str, object]:
    return {
        "code": record.code,
        "name": record.name,
        "resource_type": record.resource_type,
        "assigned_user_id": str(record.assigned_user_id) if record.assigned_user_id else None,
        "allocation_percent": str(record.allocation_percent),
        "start_date": record.start_date.isoformat() if record.start_date else None,
        "end_date": record.end_date.isoformat() if record.end_date else None,
        "status": record.status,
    }


class ResourceCostService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # ── shared helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _lock_project(connection: Connection, *, tenant_id: UUID, project_id: UUID) -> None:
        status = connection.execute(
            select(tables.projects.c.status)
            .where(tables.projects.c.tenant_id == tenant_id, tables.projects.c.id == project_id)
            .with_for_update()
        ).scalar_one_or_none()
        if status is None:
            raise RegisterNotFoundError
        if status == "archived":
            raise RegisterLockedError

    @staticmethod
    def _next_code(
        connection: Connection, *, table: Table, prefix: str, tenant_id: UUID, project_id: UUID
    ) -> str:
        count = connection.execute(
            select(func.count())
            .select_from(table)
            .where(table.c.tenant_id == tenant_id, table.c.project_id == project_id)
        ).scalar_one()
        return f"{prefix}-{int(count) + 1:03d}"

    @staticmethod
    def _writer(
        connection: Connection, *, tenant_id: UUID, actor_user_id: UUID, project_id: UUID
    ) -> EventAuditWriter:
        return EventAuditWriter(
            connection, tenant_id=tenant_id, actor_user_id=actor_user_id, project_id=project_id
        )

    # ── costs ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _get_cost(
        connection: Connection, *, tenant_id: UUID, project_id: UUID, cost_id: UUID
    ) -> CostRecord:
        row = (
            connection.execute(
                select(tables.costs).where(
                    tables.costs.c.tenant_id == tenant_id,
                    tables.costs.c.project_id == project_id,
                    tables.costs.c.id == cost_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise RegisterNotFoundError
        return _cost_from_row(row)

    def list_costs(self, *, tenant_id: UUID, project_id: UUID) -> list[CostRecord]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(tables.costs)
                .where(
                    tables.costs.c.tenant_id == tenant_id, tables.costs.c.project_id == project_id
                )
                .order_by(tables.costs.c.created_at.desc(), tables.costs.c.id.desc())
            ).mappings()
            return [_cost_from_row(row) for row in rows]

    def create_cost(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        cost_type: str,
        amount: Decimal,
        currency: str,
        incurred_on: date | None,
        description: str | None,
    ) -> CostRecord:
        occurred_at = datetime.now(UTC)
        cost_id = uuid4()
        with self._engine.begin() as connection:
            self._lock_project(connection, tenant_id=tenant_id, project_id=project_id)
            code = self._next_code(
                connection,
                table=tables.costs,
                prefix="COST",
                tenant_id=tenant_id,
                project_id=project_id,
            )
            connection.execute(
                tables.costs.insert(),
                {
                    "id": cost_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "code": code,
                    "cost_type": cost_type,
                    "amount": amount,
                    "currency": currency,
                    "status": "estimate",
                    "incurred_on": incurred_on,
                    "details": {"description": description} if description else {},
                    "created_at": occurred_at,
                    "updated_at": occurred_at,
                },
            )
            record = self._get_cost(
                connection, tenant_id=tenant_id, project_id=project_id, cost_id=cost_id
            )
            self._record_cost(
                connection, tenant_id, actor_user_id, record, "created", None, occurred_at
            )
            return record

    def update_cost(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        cost_id: UUID,
        changes: dict[str, Any],
    ) -> CostRecord:
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            self._lock_project(connection, tenant_id=tenant_id, project_id=project_id)
            before = self._get_cost(
                connection, tenant_id=tenant_id, project_id=project_id, cost_id=cost_id
            )
            if before.status != "estimate":
                raise RegisterLockedError
            values = {key: value for key, value in changes.items() if key != "description"}
            if "description" in changes:
                values["details"] = (
                    {"description": changes["description"]} if changes["description"] else {}
                )
            connection.execute(
                tables.costs.update()
                .where(tables.costs.c.tenant_id == tenant_id, tables.costs.c.id == cost_id)
                .values(**values, updated_at=occurred_at)
            )
            after = self._get_cost(
                connection, tenant_id=tenant_id, project_id=project_id, cost_id=cost_id
            )
            self._record_cost(
                connection, tenant_id, actor_user_id, after, "updated", before, occurred_at
            )
            return after

    def transition_cost(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        cost_id: UUID,
        to_status: str,
    ) -> CostRecord:
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            self._lock_project(connection, tenant_id=tenant_id, project_id=project_id)
            before = self._get_cost(
                connection, tenant_id=tenant_id, project_id=project_id, cost_id=cost_id
            )
            if to_status not in COST_TRANSITIONS[before.status]:
                raise RegisterInvalidTransitionError
            connection.execute(
                tables.costs.update()
                .where(tables.costs.c.tenant_id == tenant_id, tables.costs.c.id == cost_id)
                .values(status=to_status, updated_at=occurred_at)
            )
            after = self._get_cost(
                connection, tenant_id=tenant_id, project_id=project_id, cost_id=cost_id
            )
            self._record_cost(
                connection, tenant_id, actor_user_id, after, "status_changed", before, occurred_at
            )
            return after

    def _record_cost(
        self,
        connection: Connection,
        tenant_id: UUID,
        actor_user_id: UUID,
        record: CostRecord,
        action: str,
        before: CostRecord | None,
        occurred_at: datetime,
    ) -> None:
        self._writer(
            connection,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            project_id=record.project_id,
        ).record(
            EventDraft(
                event_id=f"cost:{record.id}:{action}:{uuid4()}",
                event_type="COST_RECORD_CHANGED",
                source="resource_cost_service",
                entity_id=record.id,
                payload={"code": record.code, "action": action, "status": record.status},
                occurred_at=occurred_at,
            ),
            AuditDraft(
                action={"created": "cost.create", "updated": "cost.update"}.get(
                    action, "cost.transition"
                ),
                before_snapshot=_cost_snapshot(before) if before is not None else None,
                after_snapshot=_cost_snapshot(record),
            ),
        )

    # ── resources ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _resource_rows(
        connection: Connection, *, tenant_id: UUID, project_id: UUID, resource_id: UUID | None
    ) -> list[ResourceRecord]:
        statement = select(tables.resources).where(
            tables.resources.c.tenant_id == tenant_id,
            tables.resources.c.project_id == project_id,
        )
        if resource_id is not None:
            statement = statement.where(tables.resources.c.id == resource_id)
        rows = list(
            connection.execute(
                statement.order_by(tables.resources.c.created_at.desc(), tables.resources.c.id)
            ).mappings()
        )
        assignees = {row["assigned_user_id"] for row in rows if row["assigned_user_id"]}
        loads: dict[UUID, Decimal] = {}
        if assignees:
            loads = {
                user_id: Decimal(total).quantize(CENTS)
                for user_id, total in connection.execute(
                    select(
                        tables.resources.c.assigned_user_id,
                        func.sum(tables.resources.c.allocation_percent),
                    )
                    .where(
                        tables.resources.c.tenant_id == tenant_id,
                        tables.resources.c.status == "active",
                        tables.resources.c.assigned_user_id.in_(assignees),
                    )
                    .group_by(tables.resources.c.assigned_user_id)
                ).all()
            }
        return [
            ResourceRecord(
                id=row["id"],
                project_id=row["project_id"],
                code=row["code"],
                name=row["name"],
                resource_type=row["resource_type"],
                assigned_user_id=row["assigned_user_id"],
                allocation_percent=row["allocation_percent"],
                start_date=row["start_date"],
                end_date=row["end_date"],
                status=row["status"],
                assignee_active_allocation_percent=(
                    loads.get(row["assigned_user_id"], Decimal(0).quantize(CENTS))
                    if row["assigned_user_id"]
                    else None
                ),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def _get_resource(
        self, connection: Connection, *, tenant_id: UUID, project_id: UUID, resource_id: UUID
    ) -> ResourceRecord:
        found = self._resource_rows(
            connection, tenant_id=tenant_id, project_id=project_id, resource_id=resource_id
        )
        if not found:
            raise RegisterNotFoundError
        return found[0]

    @staticmethod
    def _validate_assignee(
        connection: Connection, *, tenant_id: UUID, project_id: UUID, user_id: UUID | None
    ) -> None:
        if user_id is None:
            return
        found = connection.execute(
            select(tables.project_members.c.id)
            .join(
                tables.users,
                (tables.users.c.tenant_id == tables.project_members.c.tenant_id)
                & (tables.users.c.id == tables.project_members.c.user_id),
            )
            .where(
                tables.project_members.c.tenant_id == tenant_id,
                tables.project_members.c.project_id == project_id,
                tables.project_members.c.user_id == user_id,
                tables.users.c.role.in_(ASSIGNABLE_MEMBER_ROLES),
            )
        ).scalar_one_or_none()
        if found is None:
            raise RegisterScopeError

    @staticmethod
    def _validate_dates(start_date: date | None, end_date: date | None) -> None:
        if start_date is not None and end_date is not None and end_date < start_date:
            raise RegisterDateOrderError

    def list_resources(self, *, tenant_id: UUID, project_id: UUID) -> list[ResourceRecord]:
        with self._engine.connect() as connection:
            return self._resource_rows(
                connection, tenant_id=tenant_id, project_id=project_id, resource_id=None
            )

    def create_resource(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        name: str,
        resource_type: str,
        assigned_user_id: UUID | None,
        allocation_percent: Decimal,
        start_date: date | None,
        end_date: date | None,
    ) -> ResourceRecord:
        self._validate_dates(start_date, end_date)
        occurred_at = datetime.now(UTC)
        resource_id = uuid4()
        with self._engine.begin() as connection:
            self._lock_project(connection, tenant_id=tenant_id, project_id=project_id)
            self._validate_assignee(
                connection, tenant_id=tenant_id, project_id=project_id, user_id=assigned_user_id
            )
            code = self._next_code(
                connection,
                table=tables.resources,
                prefix="RES",
                tenant_id=tenant_id,
                project_id=project_id,
            )
            connection.execute(
                tables.resources.insert(),
                {
                    "id": resource_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "assigned_user_id": assigned_user_id,
                    "code": code,
                    "name": name,
                    "resource_type": resource_type,
                    "allocation_percent": allocation_percent,
                    "start_date": start_date,
                    "end_date": end_date,
                    "status": "planned",
                    "created_at": occurred_at,
                    "updated_at": occurred_at,
                },
            )
            record = self._get_resource(
                connection, tenant_id=tenant_id, project_id=project_id, resource_id=resource_id
            )
            self._record_resource(
                connection, tenant_id, actor_user_id, record, "created", None, occurred_at
            )
            return record

    def update_resource(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        resource_id: UUID,
        changes: dict[str, Any],
    ) -> ResourceRecord:
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            self._lock_project(connection, tenant_id=tenant_id, project_id=project_id)
            before = self._get_resource(
                connection, tenant_id=tenant_id, project_id=project_id, resource_id=resource_id
            )
            if before.status == "released":
                raise RegisterLockedError
            if "assigned_user_id" in changes:
                self._validate_assignee(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    user_id=changes["assigned_user_id"],
                )
            self._validate_dates(
                changes.get("start_date", before.start_date),
                changes.get("end_date", before.end_date),
            )
            connection.execute(
                tables.resources.update()
                .where(
                    tables.resources.c.tenant_id == tenant_id,
                    tables.resources.c.id == resource_id,
                )
                .values(**changes, updated_at=occurred_at)
            )
            after = self._get_resource(
                connection, tenant_id=tenant_id, project_id=project_id, resource_id=resource_id
            )
            self._record_resource(
                connection, tenant_id, actor_user_id, after, "updated", before, occurred_at
            )
            return after

    def transition_resource(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        resource_id: UUID,
        to_status: str,
    ) -> ResourceRecord:
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            self._lock_project(connection, tenant_id=tenant_id, project_id=project_id)
            before = self._get_resource(
                connection, tenant_id=tenant_id, project_id=project_id, resource_id=resource_id
            )
            if to_status not in RESOURCE_TRANSITIONS[before.status]:
                raise RegisterInvalidTransitionError
            connection.execute(
                tables.resources.update()
                .where(
                    tables.resources.c.tenant_id == tenant_id,
                    tables.resources.c.id == resource_id,
                )
                .values(status=to_status, updated_at=occurred_at)
            )
            after = self._get_resource(
                connection, tenant_id=tenant_id, project_id=project_id, resource_id=resource_id
            )
            self._record_resource(
                connection, tenant_id, actor_user_id, after, "status_changed", before, occurred_at
            )
            return after

    def _record_resource(
        self,
        connection: Connection,
        tenant_id: UUID,
        actor_user_id: UUID,
        record: ResourceRecord,
        action: str,
        before: ResourceRecord | None,
        occurred_at: datetime,
    ) -> None:
        self._writer(
            connection,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            project_id=record.project_id,
        ).record(
            EventDraft(
                event_id=f"resource:{record.id}:{action}:{uuid4()}",
                event_type="RESOURCE_RECORD_CHANGED",
                source="resource_cost_service",
                entity_id=record.id,
                payload={"code": record.code, "action": action, "status": record.status},
                occurred_at=occurred_at,
            ),
            AuditDraft(
                action={"created": "resource.create", "updated": "resource.update"}.get(
                    action, "resource.transition"
                ),
                before_snapshot=_resource_snapshot(before) if before is not None else None,
                after_snapshot=_resource_snapshot(record),
            ),
        )
