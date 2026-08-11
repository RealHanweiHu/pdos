"""Project-scoped Issue lifecycle use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, select
from sqlalchemy.engine import RowMapping

from app.db.schema import tables
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class IssueNotFoundError(LookupError):
    """Raised when an Issue is absent from the tenant-bound Project."""


class IssueScopeError(ValueError):
    """Raised when a related Stage or owner is outside the Project."""


class IssueInvalidTransitionError(ValueError):
    """Raised when an Issue status edge is outside the frozen graph."""


class IssueTerminalError(ValueError):
    """Raised when a closed Issue is edited."""


@dataclass(frozen=True)
class IssueRecord:
    id: UUID
    project_id: UUID
    stage_id: UUID | None
    owner_user_id: UUID | None
    reported_by_user_id: UUID
    title: str
    description: str | None
    status: str
    severity: str
    root_cause: str | None
    resolution: str | None
    target_date: date | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class IssueDraft:
    stage_id: UUID | None
    owner_user_id: UUID | None
    title: str
    description: str | None
    severity: str
    root_cause: str | None
    resolution: str | None
    target_date: date | None


@dataclass(frozen=True)
class IssueUpdate:
    changes: dict[str, object]


ISSUE_TRANSITIONS = {
    "open": frozenset({"analysis"}),
    "analysis": frozenset({"action"}),
    "action": frozenset({"verification"}),
    "verification": frozenset({"closed"}),
    "closed": frozenset(),
}


def _issue_statement() -> Any:
    return select(
        tables.issues.c.id,
        tables.issues.c.project_id,
        tables.issues.c.stage_id,
        tables.issues.c.owner_user_id,
        tables.issues.c.reported_by_user_id,
        tables.issues.c.title,
        tables.issues.c.description,
        tables.issues.c.status,
        tables.issues.c.severity,
        tables.issues.c.root_cause,
        tables.issues.c.resolution,
        tables.issues.c.target_date,
        tables.issues.c.closed_at,
        tables.issues.c.created_at,
        tables.issues.c.updated_at,
    )


def _record_from_row(row: RowMapping) -> IssueRecord:
    reporter_id = row["reported_by_user_id"]
    if not isinstance(reporter_id, UUID):
        raise IssueNotFoundError
    return IssueRecord(
        id=row["id"],
        project_id=row["project_id"],
        stage_id=row["stage_id"],
        owner_user_id=row["owner_user_id"],
        reported_by_user_id=reporter_id,
        title=row["title"],
        description=row["description"],
        status=row["status"],
        severity=row["severity"],
        root_cause=row["root_cause"],
        resolution=row["resolution"],
        target_date=row["target_date"],
        closed_at=row["closed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _issue_snapshot(record: IssueRecord) -> dict[str, object]:
    return {
        "project_id": str(record.project_id),
        "stage_id": str(record.stage_id) if record.stage_id is not None else None,
        "owner_user_id": (str(record.owner_user_id) if record.owner_user_id is not None else None),
        "reported_by_user_id": str(record.reported_by_user_id),
        "title": record.title,
        "description": record.description,
        "status": record.status,
        "severity": record.severity,
        "root_cause": record.root_cause,
        "resolution": record.resolution,
        "target_date": record.target_date.isoformat() if record.target_date is not None else None,
        "closed_at": record.closed_at.isoformat() if record.closed_at is not None else None,
    }


class IssueService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _project_workflow(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
    ) -> UUID:
        workflow_id = connection.execute(
            select(tables.projects.c.workflow_id).where(
                tables.projects.c.tenant_id == tenant_id,
                tables.projects.c.id == project_id,
            )
        ).scalar_one_or_none()
        if not isinstance(workflow_id, UUID):
            raise IssueNotFoundError
        return workflow_id

    @staticmethod
    def _get_record(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        issue_id: UUID,
    ) -> IssueRecord:
        row = (
            connection.execute(
                _issue_statement().where(
                    tables.issues.c.tenant_id == tenant_id,
                    tables.issues.c.project_id == project_id,
                    tables.issues.c.id == issue_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise IssueNotFoundError
        return _record_from_row(row)

    @staticmethod
    def _validate_stage(
        connection: Connection,
        *,
        tenant_id: UUID,
        workflow_id: UUID,
        stage_id: UUID | None,
    ) -> None:
        if stage_id is None:
            return
        found = connection.execute(
            select(tables.stages.c.id).where(
                tables.stages.c.tenant_id == tenant_id,
                tables.stages.c.workflow_id == workflow_id,
                tables.stages.c.id == stage_id,
            )
        ).scalar_one_or_none()
        if found is None:
            raise IssueScopeError

    @staticmethod
    def _validate_member(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        user_id: UUID | None,
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
                tables.users.c.role.in_(
                    {"owner", "admin", "project_manager", "engineer", "quality"}
                ),
            )
        ).scalar_one_or_none()
        if found is None:
            raise IssueScopeError

    def get(self, *, tenant_id: UUID, project_id: UUID, issue_id: UUID) -> IssueRecord:
        with self._engine.connect() as connection:
            return self._get_record(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                issue_id=issue_id,
            )

    def list(self, *, tenant_id: UUID, project_id: UUID) -> list[IssueRecord]:
        with self._engine.connect() as connection:
            return [
                _record_from_row(row)
                for row in connection.execute(
                    _issue_statement()
                    .where(
                        tables.issues.c.tenant_id == tenant_id,
                        tables.issues.c.project_id == project_id,
                    )
                    .order_by(tables.issues.c.updated_at.desc(), tables.issues.c.id.desc())
                ).mappings()
            ]

    def create(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        draft: IssueDraft,
    ) -> IssueRecord:
        issue_id = uuid4()
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            workflow_id = self._project_workflow(
                connection, tenant_id=tenant_id, project_id=project_id
            )
            self._validate_stage(
                connection,
                tenant_id=tenant_id,
                workflow_id=workflow_id,
                stage_id=draft.stage_id,
            )
            self._validate_member(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=draft.owner_user_id,
            )
            connection.execute(
                tables.issues.insert(),
                {
                    "id": issue_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "workflow_id": workflow_id if draft.stage_id is not None else None,
                    "stage_id": draft.stage_id,
                    "owner_user_id": draft.owner_user_id,
                    "reported_by_user_id": actor_user_id,
                    "title": draft.title,
                    "description": draft.description,
                    "status": "open",
                    "severity": draft.severity,
                    "root_cause": draft.root_cause,
                    "resolution": draft.resolution,
                    "target_date": draft.target_date,
                    "created_at": occurred_at,
                    "updated_at": occurred_at,
                },
            )
            issue = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, issue_id=issue_id
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"issue:{issue_id}:created",
                    event_type="ISSUE_CREATED",
                    source="issue_service",
                    entity_id=issue_id,
                    payload={"issue_id": str(issue_id), "severity": issue.severity},
                    occurred_at=occurred_at,
                ),
                AuditDraft(action="issue.create", after_snapshot=_issue_snapshot(issue)),
            )
            return issue

    def update(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        issue_id: UUID,
        patch: IssueUpdate,
    ) -> IssueRecord:
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            before = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, issue_id=issue_id
            )
            if before.status == "closed":
                raise IssueTerminalError
            workflow_id = self._project_workflow(
                connection, tenant_id=tenant_id, project_id=project_id
            )
            changes = dict(patch.changes)
            if "stage_id" in changes:
                stage_id = changes["stage_id"]
                if stage_id is not None and not isinstance(stage_id, UUID):
                    raise IssueScopeError
                self._validate_stage(
                    connection,
                    tenant_id=tenant_id,
                    workflow_id=workflow_id,
                    stage_id=stage_id,
                )
                changes["workflow_id"] = workflow_id if stage_id is not None else None
            if "owner_user_id" in changes:
                owner_id = changes["owner_user_id"]
                if owner_id is not None and not isinstance(owner_id, UUID):
                    raise IssueScopeError
                self._validate_member(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    user_id=owner_id,
                )
            connection.execute(
                tables.issues.update()
                .where(
                    tables.issues.c.tenant_id == tenant_id,
                    tables.issues.c.project_id == project_id,
                    tables.issues.c.id == issue_id,
                )
                .values(**changes, updated_at=occurred_at)
            )
            after = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, issue_id=issue_id
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"issue:{issue_id}:updated:{uuid4()}",
                    event_type="ISSUE_UPDATED",
                    source="issue_service",
                    entity_id=issue_id,
                    payload={
                        "changed_fields": sorted(patch.changes),
                        "status": after.status,
                        "severity": after.severity,
                    },
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="issue.update",
                    before_snapshot=_issue_snapshot(before),
                    after_snapshot=_issue_snapshot(after),
                ),
            )
            return after

    def transition(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        issue_id: UUID,
        to_status: str,
    ) -> IssueRecord:
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            before = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, issue_id=issue_id
            )
            if to_status not in ISSUE_TRANSITIONS[before.status]:
                raise IssueInvalidTransitionError
            connection.execute(
                tables.issues.update()
                .where(
                    tables.issues.c.tenant_id == tenant_id,
                    tables.issues.c.project_id == project_id,
                    tables.issues.c.id == issue_id,
                )
                .values(
                    status=to_status,
                    closed_at=occurred_at if to_status == "closed" else None,
                    updated_at=occurred_at,
                )
            )
            after = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, issue_id=issue_id
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"issue:{issue_id}:status:{to_status}:{uuid4()}",
                    event_type="ISSUE_STATUS_CHANGED",
                    source="issue_service",
                    entity_id=issue_id,
                    payload={"from_status": before.status, "to_status": after.status},
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="issue.transition",
                    before_snapshot=_issue_snapshot(before),
                    after_snapshot=_issue_snapshot(after),
                ),
            )
            return after
