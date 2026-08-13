"""Project-scoped Complaint creation and read use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, func, select
from sqlalchemy.engine import RowMapping

from app.db.schema import tables
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class ComplaintNotFoundError(LookupError):
    """Raised when a Complaint is absent from the tenant-bound Project."""


class ComplaintScopeError(ValueError):
    """Raised when a related object is outside the tenant-bound Project."""


class ComplaintTimeError(ValueError):
    """Raised when occurrence time is after the server report time."""


class ComplaintInvalidTransitionError(ValueError):
    """Raised when a Complaint transition is outside the frozen lifecycle."""


class ComplaintNcrGateError(ValueError):
    """Raised when Complaint resolution has no fully closed NCR set."""


class ComplaintResolutionError(ValueError):
    """Raised when Complaint resolution lacks the required conclusion."""


@dataclass(frozen=True)
class ComplaintRecord:
    id: UUID
    project_id: UUID
    customer_id: UUID | None
    reported_by_user_id: UUID
    owner_user_id: UUID
    closed_by_user_id: UUID | None
    code: str
    title: str
    description: str
    source: str
    severity: str
    status: str
    occurred_at: datetime
    reported_at: datetime
    customer_reference: str | None
    affected_scope: str | None
    document_refs: list[str]
    resolution_summary: str | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ComplaintDraft:
    customer_id: UUID | None
    owner_user_id: UUID
    title: str
    description: str
    source: str
    severity: str
    occurred_at: datetime
    customer_reference: str | None
    affected_scope: str | None
    document_refs: list[UUID]


def _complaint_statement() -> Any:
    return select(
        tables.complaints.c.id,
        tables.complaints.c.project_id,
        tables.complaints.c.customer_id,
        tables.complaints.c.reported_by_user_id,
        tables.complaints.c.owner_user_id,
        tables.complaints.c.closed_by_user_id,
        tables.complaints.c.code,
        tables.complaints.c.title,
        tables.complaints.c.description,
        tables.complaints.c.source,
        tables.complaints.c.severity,
        tables.complaints.c.status,
        tables.complaints.c.occurred_at,
        tables.complaints.c.reported_at,
        tables.complaints.c.customer_reference,
        tables.complaints.c.affected_scope,
        tables.complaints.c.document_refs,
        tables.complaints.c.resolution_summary,
        tables.complaints.c.closed_at,
        tables.complaints.c.created_at,
        tables.complaints.c.updated_at,
    )


def _record(row: RowMapping) -> ComplaintRecord:
    return ComplaintRecord(**{field: row[field] for field in ComplaintRecord.__dataclass_fields__})


def _snapshot(record: ComplaintRecord) -> dict[str, object]:
    return {
        "project_id": str(record.project_id),
        "customer_id": str(record.customer_id) if record.customer_id else None,
        "reported_by_user_id": str(record.reported_by_user_id),
        "owner_user_id": str(record.owner_user_id),
        "code": record.code,
        "title": record.title,
        "description": record.description,
        "source": record.source,
        "severity": record.severity,
        "status": record.status,
        "occurred_at": record.occurred_at.isoformat(),
        "reported_at": record.reported_at.isoformat(),
        "customer_reference": record.customer_reference,
        "affected_scope": record.affected_scope,
        "document_refs": record.document_refs,
        "resolution_summary": record.resolution_summary,
        "closed_by_user_id": (str(record.closed_by_user_id) if record.closed_by_user_id else None),
        "closed_at": record.closed_at.isoformat() if record.closed_at else None,
    }


class ComplaintService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _get(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        complaint_id: UUID,
    ) -> ComplaintRecord:
        row = (
            connection.execute(
                _complaint_statement().where(
                    tables.complaints.c.tenant_id == tenant_id,
                    tables.complaints.c.project_id == project_id,
                    tables.complaints.c.id == complaint_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ComplaintNotFoundError
        return _record(row)

    @staticmethod
    def _validate_member(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        user_id: UUID,
    ) -> None:
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
                tables.users.c.role.in_(
                    {"owner", "admin", "project_manager", "engineer", "quality"}
                ),
            )
        ).scalar_one_or_none()
        if found is None:
            raise ComplaintScopeError

    @staticmethod
    def _validate_customer(
        connection: Connection,
        *,
        tenant_id: UUID,
        customer_id: UUID | None,
    ) -> None:
        if customer_id is None:
            return
        found = connection.execute(
            select(tables.customers.c.id).where(
                tables.customers.c.tenant_id == tenant_id,
                tables.customers.c.id == customer_id,
            )
        ).scalar_one_or_none()
        if found is None:
            raise ComplaintScopeError

    @staticmethod
    def _validate_documents(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        document_ids: list[UUID],
    ) -> None:
        if len(set(document_ids)) != len(document_ids):
            raise ComplaintScopeError
        if not document_ids:
            return
        found = connection.execute(
            select(func.count())
            .select_from(tables.documents)
            .where(
                tables.documents.c.tenant_id == tenant_id,
                tables.documents.c.project_id == project_id,
                tables.documents.c.id.in_(document_ids),
            )
        ).scalar_one()
        if found != len(document_ids):
            raise ComplaintScopeError

    def create(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        draft: ComplaintDraft,
    ) -> ComplaintRecord:
        complaint_id = uuid4()
        reported_at = datetime.now(UTC)
        occurred_at = draft.occurred_at.astimezone(UTC)
        if occurred_at > reported_at:
            raise ComplaintTimeError
        with self._engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise ComplaintNotFoundError
            self._validate_member(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=actor_user_id,
            )
            self._validate_member(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=draft.owner_user_id,
            )
            self._validate_customer(
                connection,
                tenant_id=tenant_id,
                customer_id=draft.customer_id,
            )
            self._validate_documents(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                document_ids=draft.document_refs,
            )
            connection.execute(
                tables.complaints.insert(),
                {
                    "id": complaint_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "customer_id": draft.customer_id,
                    "reported_by_user_id": actor_user_id,
                    "owner_user_id": draft.owner_user_id,
                    "code": f"CMP-{complaint_id.hex.upper()}",
                    "title": draft.title,
                    "description": draft.description,
                    "source": draft.source,
                    "severity": draft.severity,
                    "status": "open",
                    "occurred_at": occurred_at,
                    "reported_at": reported_at,
                    "customer_reference": draft.customer_reference,
                    "affected_scope": draft.affected_scope,
                    "document_refs": [str(document_id) for document_id in draft.document_refs],
                    "created_at": reported_at,
                    "updated_at": reported_at,
                },
            )
            record = self._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                complaint_id=complaint_id,
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"complaint:{complaint_id}:created",
                    event_type="COMPLAINT_CREATED",
                    source="quality_service",
                    entity_id=complaint_id,
                    payload={"complaint_id": str(complaint_id), "severity": record.severity},
                    occurred_at=reported_at,
                ),
                AuditDraft(action="quality.complaint.create", after_snapshot=_snapshot(record)),
            )
            return record

    def get(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        complaint_id: UUID,
    ) -> ComplaintRecord:
        with self._engine.connect() as connection:
            return self._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                complaint_id=complaint_id,
            )

    def list(self, *, tenant_id: UUID, project_id: UUID) -> list[ComplaintRecord]:
        with self._engine.connect() as connection:
            return [
                _record(row)
                for row in connection.execute(
                    _complaint_statement()
                    .where(
                        tables.complaints.c.tenant_id == tenant_id,
                        tables.complaints.c.project_id == project_id,
                    )
                    .order_by(tables.complaints.c.updated_at.desc(), tables.complaints.c.id.desc())
                ).mappings()
            ]

    def transition(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        complaint_id: UUID,
        to_status: str,
        resolution_summary: str | None,
    ) -> ComplaintRecord:
        occurred_at = datetime.now(UTC)
        transitions = {
            "triaged": "investigating",
            "investigating": "resolved",
            "resolved": "closed",
        }
        with self._engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise ComplaintNotFoundError
            before = self._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                complaint_id=complaint_id,
            )
            if transitions.get(before.status) != to_status:
                raise ComplaintInvalidTransitionError
            self._validate_member(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=actor_user_id,
            )
            values: dict[str, object] = {"status": to_status, "updated_at": occurred_at}
            if to_status == "resolved":
                ncr_count, open_count = connection.execute(
                    select(
                        func.count(),
                        func.count().filter(tables.nonconformance_reports.c.status != "closed"),
                    ).where(
                        tables.nonconformance_reports.c.tenant_id == tenant_id,
                        tables.nonconformance_reports.c.project_id == project_id,
                        tables.nonconformance_reports.c.complaint_id == complaint_id,
                    )
                ).one()
                if ncr_count < 1 or open_count:
                    raise ComplaintNcrGateError
                if resolution_summary is None:
                    raise ComplaintResolutionError
                values["resolution_summary"] = resolution_summary
            elif to_status == "closed":
                if resolution_summary is not None:
                    raise ComplaintResolutionError
                values.update(closed_by_user_id=actor_user_id, closed_at=occurred_at)
            elif resolution_summary is not None:
                raise ComplaintResolutionError
            connection.execute(
                tables.complaints.update()
                .where(
                    tables.complaints.c.tenant_id == tenant_id,
                    tables.complaints.c.project_id == project_id,
                    tables.complaints.c.id == complaint_id,
                )
                .values(**values)
            )
            after = self._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                complaint_id=complaint_id,
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"complaint:{complaint_id}:status:{to_status}:{uuid4()}",
                    event_type="COMPLAINT_STATUS_CHANGED",
                    source="quality_service",
                    entity_id=complaint_id,
                    payload={"from_status": before.status, "to_status": after.status},
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="quality.complaint.transition",
                    before_snapshot=_snapshot(before),
                    after_snapshot=_snapshot(after),
                ),
            )
            return after
