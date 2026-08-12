"""Project creation, lifecycle, and workflow-stage use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError

from app.auth.roles import Role
from app.db.schema import tables
from app.domain.workflow_templates import NPD_WORKFLOW_TEMPLATE, WorkflowTemplate
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class DevelopmentCaseNotFoundForProjectError(LookupError):
    """Raised when the source Case is absent from the active tenant."""


class ProjectAlreadyExistsError(ValueError):
    """Raised when a Case already owns a Project."""


class ProjectCaseNotApprovedError(ValueError):
    """Raised when Project creation is attempted before Case approval."""


class ProjectCodeConflictError(ValueError):
    """Raised when a Project code already exists in the tenant."""


class ProjectDateOrderError(ValueError):
    """Raised when target date precedes start date."""


class ProjectInvalidTransitionError(ValueError):
    """Raised when a Project status edge is not frozen."""


class ProjectNotActiveError(ValueError):
    """Raised when a Stage transition is attempted outside Active status."""


class ProjectNotFoundError(LookupError):
    """Raised when a Project is absent from the active tenant."""


class ProjectStageInvalidTransitionError(ValueError):
    """Raised when a Stage transition is not the adjacent Workflow Stage."""


class ProjectGateNotApprovedError(ValueError):
    """Raised when Stage advancement attempts to bypass its hard Gate."""


class ProjectTerminalError(ValueError):
    """Raised when content mutation is attempted on an archived Project."""


@dataclass(frozen=True)
class StageRecord:
    id: UUID
    code: str
    name: str
    description: str | None
    sequence: int


@dataclass(frozen=True)
class WorkflowRecord:
    id: UUID
    code: str
    name: str
    description: str | None
    version: int
    is_active: bool
    stages: tuple[StageRecord, ...]


@dataclass(frozen=True)
class ProjectRecord:
    id: UUID
    development_case_id: UUID
    customer_id: UUID | None
    workflow: WorkflowRecord
    current_stage: StageRecord
    owner_user_id: UUID
    code: str
    name: str
    description: str | None
    status: str
    start_date: date | None
    target_date: date | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ProjectDraft:
    development_case_id: UUID
    code: str
    name: str
    description: str | None
    start_date: date | None
    target_date: date | None


@dataclass(frozen=True)
class ProjectUpdate:
    changes: dict[str, object]


PROJECT_TRANSITIONS = {
    "draft": frozenset({"proposed"}),
    "proposed": frozenset({"approved"}),
    "approved": frozenset({"active"}),
    "active": frozenset({"on_hold", "completed"}),
    "on_hold": frozenset({"active"}),
    "completed": frozenset({"archived"}),
    "archived": frozenset(),
}


def _project_statement() -> Any:
    return select(
        tables.projects.c.id,
        tables.projects.c.development_case_id,
        tables.projects.c.customer_id,
        tables.projects.c.workflow_id,
        tables.projects.c.current_stage_id,
        tables.projects.c.owner_user_id,
        tables.projects.c.code,
        tables.projects.c.name,
        tables.projects.c.description,
        tables.projects.c.status,
        tables.projects.c.start_date,
        tables.projects.c.target_date,
        tables.projects.c.created_at,
        tables.projects.c.updated_at,
        tables.workflows.c.code.label("workflow_code"),
        tables.workflows.c.name.label("workflow_name"),
        tables.workflows.c.description.label("workflow_description"),
        tables.workflows.c.version.label("workflow_version"),
        tables.workflows.c.is_active.label("workflow_is_active"),
    ).join(
        tables.workflows,
        (tables.workflows.c.tenant_id == tables.projects.c.tenant_id)
        & (tables.workflows.c.id == tables.projects.c.workflow_id),
    )


def _stage_from_row(row: RowMapping) -> StageRecord:
    return StageRecord(
        id=row["id"],
        code=row["code"],
        name=row["name"],
        description=row["description"],
        sequence=row["sequence"],
    )


def _stages_for_workflow(
    connection: Connection,
    *,
    tenant_id: UUID,
    workflow_id: UUID,
) -> tuple[StageRecord, ...]:
    rows = connection.execute(
        select(
            tables.stages.c.id,
            tables.stages.c.code,
            tables.stages.c.name,
            tables.stages.c.description,
            tables.stages.c.sequence,
        )
        .where(
            tables.stages.c.tenant_id == tenant_id,
            tables.stages.c.workflow_id == workflow_id,
        )
        .order_by(tables.stages.c.sequence, tables.stages.c.id)
    ).mappings()
    return tuple(_stage_from_row(row) for row in rows)


def _record_from_row(
    connection: Connection,
    *,
    tenant_id: UUID,
    row: RowMapping,
) -> ProjectRecord:
    stages = _stages_for_workflow(
        connection,
        tenant_id=tenant_id,
        workflow_id=row["workflow_id"],
    )
    current_stage = next(
        (stage for stage in stages if stage.id == row["current_stage_id"]),
        None,
    )
    if current_stage is None or row["development_case_id"] is None or row["owner_user_id"] is None:
        raise ProjectNotFoundError
    return ProjectRecord(
        id=row["id"],
        development_case_id=row["development_case_id"],
        customer_id=row["customer_id"],
        workflow=WorkflowRecord(
            id=row["workflow_id"],
            code=row["workflow_code"],
            name=row["workflow_name"],
            description=row["workflow_description"],
            version=row["workflow_version"],
            is_active=row["workflow_is_active"],
            stages=stages,
        ),
        current_stage=current_stage,
        owner_user_id=row["owner_user_id"],
        code=row["code"],
        name=row["name"],
        description=row["description"],
        status=row["status"],
        start_date=row["start_date"],
        target_date=row["target_date"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _project_snapshot(record: ProjectRecord) -> dict[str, object]:
    return {
        "development_case_id": str(record.development_case_id),
        "customer_id": str(record.customer_id) if record.customer_id is not None else None,
        "workflow_id": str(record.workflow.id),
        "workflow_code": record.workflow.code,
        "workflow_version": record.workflow.version,
        "stage_ids": [str(stage.id) for stage in record.workflow.stages],
        "current_stage_id": str(record.current_stage.id),
        "owner_user_id": str(record.owner_user_id),
        "code": record.code,
        "name": record.name,
        "description": record.description,
        "status": record.status,
        "start_date": record.start_date.isoformat() if record.start_date is not None else None,
        "target_date": record.target_date.isoformat() if record.target_date is not None else None,
    }


def _case_snapshot(row: RowMapping, *, status: str | None = None) -> dict[str, object]:
    return {
        "requirement_id": str(row["requirement_id"]),
        "code": row["code"],
        "title": row["title"],
        "summary": row["summary"],
        "status": status or row["status"],
        "business_case": dict(row["business_case"]),
        "created_by_user_id": (
            str(row["created_by_user_id"]) if row["created_by_user_id"] is not None else None
        ),
    }


def _validate_dates(start_date: date | None, target_date: date | None) -> None:
    if start_date is not None and target_date is not None and target_date < start_date:
        raise ProjectDateOrderError


class ProjectService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _get_record(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
    ) -> ProjectRecord:
        row = (
            connection.execute(
                _project_statement().where(
                    tables.projects.c.tenant_id == tenant_id,
                    tables.projects.c.id == project_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ProjectNotFoundError
        return _record_from_row(connection, tenant_id=tenant_id, row=row)

    def get(self, *, tenant_id: UUID, project_id: UUID) -> ProjectRecord:
        with self._engine.connect() as connection:
            return self._get_record(connection, tenant_id=tenant_id, project_id=project_id)

    def list(
        self,
        *,
        tenant_id: UUID,
        member_user_id: UUID | None,
    ) -> list[ProjectRecord]:
        statement = _project_statement().where(tables.projects.c.tenant_id == tenant_id)
        if member_user_id is not None:
            statement = statement.join(
                tables.project_members,
                (tables.project_members.c.tenant_id == tables.projects.c.tenant_id)
                & (tables.project_members.c.project_id == tables.projects.c.id),
            ).where(tables.project_members.c.user_id == member_user_id)
        statement = statement.order_by(
            tables.projects.c.updated_at.desc(),
            tables.projects.c.id.desc(),
        )
        with self._engine.connect() as connection:
            return [
                _record_from_row(connection, tenant_id=tenant_id, row=row)
                for row in connection.execute(statement).mappings()
            ]

    def create(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        actor_role: Role,
        draft: ProjectDraft,
        template: WorkflowTemplate = NPD_WORKFLOW_TEMPLATE,
    ) -> ProjectRecord:
        _validate_dates(draft.start_date, draft.target_date)
        project_id = uuid4()
        workflow_id = uuid4()
        stage_ids = tuple(uuid4() for _ in template.stages)
        occurred_at = datetime.now(UTC)
        try:
            with self._engine.begin() as connection:
                case = (
                    connection.execute(
                        select(tables.development_cases)
                        .where(
                            tables.development_cases.c.tenant_id == tenant_id,
                            tables.development_cases.c.id == draft.development_case_id,
                        )
                        .with_for_update()
                    )
                    .mappings()
                    .one_or_none()
                )
                if case is None:
                    raise DevelopmentCaseNotFoundForProjectError
                existing_project = connection.execute(
                    select(tables.projects.c.id).where(
                        tables.projects.c.tenant_id == tenant_id,
                        tables.projects.c.development_case_id == draft.development_case_id,
                    )
                ).scalar_one_or_none()
                if existing_project is not None:
                    raise ProjectAlreadyExistsError
                if case["status"] != "approved":
                    raise ProjectCaseNotApprovedError

                customer_id = connection.execute(
                    select(tables.requirements.c.customer_id).where(
                        tables.requirements.c.tenant_id == tenant_id,
                        tables.requirements.c.id == case["requirement_id"],
                    )
                ).scalar_one()
                connection.execute(
                    tables.workflows.insert(),
                    {
                        "id": workflow_id,
                        "tenant_id": tenant_id,
                        "code": f"{template.code}-{project_id}",
                        "name": f"{template.name} · {draft.code}",
                        "description": template.description,
                        "version": template.version,
                        "is_active": True,
                        "created_at": occurred_at,
                        "updated_at": occurred_at,
                    },
                )
                connection.execute(
                    tables.stages.insert(),
                    [
                        {
                            "id": stage_id,
                            "tenant_id": tenant_id,
                            "workflow_id": workflow_id,
                            "code": stage.code,
                            "name": stage.name,
                            "description": stage.description,
                            "sequence": stage.sequence,
                            "created_at": occurred_at,
                            "updated_at": occurred_at,
                        }
                        for stage_id, stage in zip(stage_ids, template.stages, strict=True)
                    ],
                )
                connection.execute(
                    tables.projects.insert(),
                    {
                        "id": project_id,
                        "tenant_id": tenant_id,
                        "development_case_id": draft.development_case_id,
                        "customer_id": customer_id,
                        "workflow_id": workflow_id,
                        "current_stage_id": stage_ids[0],
                        "owner_user_id": actor_user_id,
                        "code": draft.code,
                        "name": draft.name,
                        "description": draft.description,
                        "status": "draft",
                        "start_date": draft.start_date,
                        "target_date": draft.target_date,
                        "created_at": occurred_at,
                        "updated_at": occurred_at,
                    },
                )
                connection.execute(
                    tables.project_members.insert(),
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "user_id": actor_user_id,
                        "added_by_user_id": actor_user_id,
                        "created_at": occurred_at,
                    },
                )
                connection.execute(
                    tables.gates.insert(),
                    [
                        {
                            "id": uuid4(),
                            "tenant_id": tenant_id,
                            "project_id": project_id,
                            "stage_id": stage_id,
                            "code": stage.code,
                            "name": f"{stage.name} Gate",
                            "status": "preparing",
                            "created_at": occurred_at,
                            "updated_at": occurred_at,
                        }
                        for stage_id, stage in zip(stage_ids, template.stages, strict=True)
                    ],
                )
                connection.execute(
                    tables.development_cases.update()
                    .where(
                        tables.development_cases.c.tenant_id == tenant_id,
                        tables.development_cases.c.id == draft.development_case_id,
                    )
                    .values(status="converted", updated_at=occurred_at)
                )
                project = self._get_record(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                )
                writer = EventAuditWriter(
                    connection,
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    project_id=project_id,
                )
                writer.record(
                    EventDraft(
                        event_id=f"project:{project_id}:created",
                        event_type="PROJECT_CREATED",
                        source="project_service",
                        entity_id=project_id,
                        payload={"project_code": project.code, "project_name": project.name},
                        occurred_at=occurred_at,
                    ),
                    AuditDraft(
                        action="project.create",
                        after_snapshot=_project_snapshot(project),
                        context={"creator_role": actor_role.value},
                    ),
                )
                writer.record(
                    EventDraft(
                        event_id=(
                            f"development-case:{draft.development_case_id}:status:converted:"
                            f"{project_id}"
                        ),
                        event_type="DEVELOPMENT_CASE_STATUS_CHANGED",
                        source="development_case_service",
                        entity_id=draft.development_case_id,
                        payload={"from_status": "approved", "to_status": "converted"},
                        occurred_at=occurred_at,
                    ),
                    AuditDraft(
                        action="development_case.transition",
                        before_snapshot=_case_snapshot(case),
                        after_snapshot=_case_snapshot(case, status="converted"),
                        context={"project_id": str(project_id)},
                    ),
                )
                return project
        except IntegrityError as error:
            constraint = str(error.orig)
            if "uq_projects_tenant_development_case" in constraint:
                raise ProjectAlreadyExistsError from error
            if "uq_projects_tenant_code" in constraint:
                raise ProjectCodeConflictError from error
            raise

    def update(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        patch: ProjectUpdate,
    ) -> ProjectRecord:
        occurred_at = datetime.now(UTC)
        try:
            with self._engine.begin() as connection:
                locked = (
                    connection.execute(
                        select(
                            tables.projects.c.status,
                            tables.projects.c.start_date,
                            tables.projects.c.target_date,
                        )
                        .where(
                            tables.projects.c.tenant_id == tenant_id,
                            tables.projects.c.id == project_id,
                        )
                        .with_for_update()
                    )
                    .mappings()
                    .one_or_none()
                )
                if locked is None:
                    raise ProjectNotFoundError
                if locked["status"] == "archived":
                    raise ProjectTerminalError
                start_date = patch.changes.get("start_date", locked["start_date"])
                target_date = patch.changes.get("target_date", locked["target_date"])
                _validate_dates(
                    start_date if isinstance(start_date, date) else None,
                    target_date if isinstance(target_date, date) else None,
                )
                before = self._get_record(connection, tenant_id=tenant_id, project_id=project_id)
                connection.execute(
                    tables.projects.update()
                    .where(
                        tables.projects.c.tenant_id == tenant_id,
                        tables.projects.c.id == project_id,
                    )
                    .values(**patch.changes, updated_at=occurred_at)
                )
                after = self._get_record(connection, tenant_id=tenant_id, project_id=project_id)
                EventAuditWriter(
                    connection,
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    project_id=project_id,
                ).record(
                    EventDraft(
                        event_id=f"project:{project_id}:updated:{uuid4()}",
                        event_type="PROJECT_UPDATED",
                        source="project_service",
                        entity_id=project_id,
                        payload={"changed_fields": sorted(patch.changes), "status": after.status},
                        occurred_at=occurred_at,
                    ),
                    AuditDraft(
                        action="project.update",
                        before_snapshot=_project_snapshot(before),
                        after_snapshot=_project_snapshot(after),
                    ),
                )
                return after
        except IntegrityError as error:
            if "uq_projects_tenant_code" in str(error.orig):
                raise ProjectCodeConflictError from error
            raise

    def transition_status(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        to_status: str,
    ) -> ProjectRecord:
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            current_status = connection.execute(
                select(tables.projects.c.status)
                .where(
                    tables.projects.c.tenant_id == tenant_id,
                    tables.projects.c.id == project_id,
                )
                .with_for_update()
            ).scalar_one_or_none()
            if current_status is None:
                raise ProjectNotFoundError
            if to_status not in PROJECT_TRANSITIONS[current_status]:
                raise ProjectInvalidTransitionError
            before = self._get_record(connection, tenant_id=tenant_id, project_id=project_id)
            connection.execute(
                tables.projects.update()
                .where(
                    tables.projects.c.tenant_id == tenant_id,
                    tables.projects.c.id == project_id,
                )
                .values(status=to_status, updated_at=occurred_at)
            )
            after = self._get_record(connection, tenant_id=tenant_id, project_id=project_id)
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"project:{project_id}:status:{to_status}:{uuid4()}",
                    event_type="PROJECT_STATUS_CHANGED",
                    source="project_service",
                    entity_id=project_id,
                    payload={"from_status": before.status, "to_status": after.status},
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="project.transition",
                    before_snapshot=_project_snapshot(before),
                    after_snapshot=_project_snapshot(after),
                ),
            )
            return after

    def transition_stage(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        to_stage_id: UUID,
    ) -> ProjectRecord:
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            locked = (
                connection.execute(
                    select(
                        tables.projects.c.status,
                        tables.projects.c.workflow_id,
                        tables.projects.c.current_stage_id,
                    )
                    .where(
                        tables.projects.c.tenant_id == tenant_id,
                        tables.projects.c.id == project_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if locked is None:
                raise ProjectNotFoundError
            if locked["status"] != "active":
                raise ProjectNotActiveError
            current_gate_status = connection.execute(
                select(tables.gates.c.status).where(
                    tables.gates.c.tenant_id == tenant_id,
                    tables.gates.c.project_id == project_id,
                    tables.gates.c.stage_id == locked["current_stage_id"],
                )
            ).scalar_one_or_none()
            if current_gate_status != "approved":
                raise ProjectGateNotApprovedError
            current_sequence = connection.execute(
                select(tables.stages.c.sequence).where(
                    tables.stages.c.tenant_id == tenant_id,
                    tables.stages.c.workflow_id == locked["workflow_id"],
                    tables.stages.c.id == locked["current_stage_id"],
                )
            ).scalar_one()
            target_sequence = connection.execute(
                select(tables.stages.c.sequence).where(
                    tables.stages.c.tenant_id == tenant_id,
                    tables.stages.c.workflow_id == locked["workflow_id"],
                    tables.stages.c.id == to_stage_id,
                )
            ).scalar_one_or_none()
            if target_sequence != current_sequence + 1:
                raise ProjectStageInvalidTransitionError
            before = self._get_record(connection, tenant_id=tenant_id, project_id=project_id)
            connection.execute(
                tables.projects.update()
                .where(
                    tables.projects.c.tenant_id == tenant_id,
                    tables.projects.c.id == project_id,
                )
                .values(current_stage_id=to_stage_id, updated_at=occurred_at)
            )
            after = self._get_record(connection, tenant_id=tenant_id, project_id=project_id)
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"project:{project_id}:stage:{to_stage_id}:{uuid4()}",
                    event_type="PROJECT_STAGE_CHANGED",
                    source="project_service",
                    entity_id=project_id,
                    payload={
                        "from_stage_id": str(before.current_stage.id),
                        "to_stage_id": str(after.current_stage.id),
                    },
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="project.stage.transition",
                    before_snapshot=_project_snapshot(before),
                    after_snapshot=_project_snapshot(after),
                ),
            )
            return after
