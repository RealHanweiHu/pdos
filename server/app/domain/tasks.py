"""Project-scoped Task dependency and lifecycle use cases."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, delete, select
from sqlalchemy.engine import RowMapping

from app.db.schema import tables
from app.domain.process_template_fields import TemplateFieldConflictError
from app.domain.process_template_task_fields import project_fields, validate_values
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.task_dependency_graph import (
    active_dependencies,
    dependency_graph_has_cycle,
    projected_dependencies,
)
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class TaskNotFoundError(LookupError):
    """Raised when a Task is absent from the tenant-bound Project."""


class TaskScopeError(ValueError):
    """Raised when a related Stage, member, parent, or dependency is out of scope."""


class TaskDateOrderError(ValueError):
    """Raised when a due date precedes a start date."""


class TaskDependencyCycleError(ValueError):
    """Raised when a dependency edit would create a directed cycle."""


class TaskDependenciesIncompleteError(ValueError):
    """Raised when a waiting Task is started before its predecessors finish."""


class TaskInvalidTransitionError(ValueError):
    """Raised when a Task status edge is outside the frozen graph."""


class TaskVersionConflictError(ValueError):
    """Raised when a reviewed Task changed before a requested transition."""


class TaskTerminalError(ValueError):
    """Raised when a terminal Task is edited."""


class TaskEvidenceRequiredError(ValueError):
    """Raised when an action task completes without completion evidence."""


ACTION_SOURCE_TABLES = {
    "meeting_action": "meetings",
    "issue_action": "issues",
    "risk_action": "risks",
    "gate_action": "gates",
    "change_action": "engineering_change_requests",
}


@dataclass(frozen=True)
class TaskRecord:
    id: UUID
    project_id: UUID
    stage_id: UUID | None
    parent_task_id: UUID | None
    assignee_user_id: UUID | None
    title: str
    description: str | None
    kind: str
    source_entity: str | None
    source_entity_id: UUID | None
    expected_output: str | None
    completion_evidence_ref: str | None
    status: str
    blocked_reason: str | None
    priority: str
    start_date: date | None
    due_date: date | None
    completed_at: datetime | None
    dependency_task_ids: tuple[UUID, ...]
    unresolved_dependency_ids: tuple[UUID, ...]
    readiness: str
    created_at: datetime
    updated_at: datetime
    baseline_dependency_task_ids: tuple[UUID, ...] = ()
    template_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskDraft:
    stage_id: UUID | None
    parent_task_id: UUID | None
    assignee_user_id: UUID | None
    title: str
    description: str | None
    priority: str
    start_date: date | None
    due_date: date | None
    dependency_task_ids: tuple[UUID, ...]
    kind: str = "task"
    source_entity_id: UUID | None = None
    expected_output: str | None = None


@dataclass(frozen=True)
class TaskUpdate:
    changes: dict[str, object]
    dependency_task_ids: tuple[UUID, ...] | None = None
    expected_updated_at: datetime | None = None


TASK_TRANSITIONS = {
    "todo": frozenset({"in_progress", "blocked", "skipped"}),
    "in_progress": frozenset({"blocked", "done"}),
    "blocked": frozenset({"todo", "in_progress", "skipped"}),
    "done": frozenset(),
    "skipped": frozenset(),
    "pending_approval": frozenset(),
}
TERMINAL_TASK_STATUSES = frozenset({"done", "skipped"})


def _task_statement() -> Any:
    return select(
        tables.tasks.c.id,
        tables.tasks.c.project_id,
        tables.tasks.c.stage_id,
        tables.tasks.c.parent_task_id,
        tables.tasks.c.assignee_user_id,
        tables.tasks.c.title,
        tables.tasks.c.description,
        tables.tasks.c.kind,
        tables.tasks.c.source_entity,
        tables.tasks.c.source_entity_id,
        tables.tasks.c.expected_output,
        tables.tasks.c.completion_evidence_ref,
        tables.tasks.c.status,
        tables.tasks.c.blocked_reason,
        tables.tasks.c.priority,
        tables.tasks.c.start_date,
        tables.tasks.c.due_date,
        tables.tasks.c.completed_at,
        tables.tasks.c.created_at,
        tables.tasks.c.updated_at,
        tables.tasks.c.template_fields,
    )


def _dependency_statuses(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    task_id: UUID,
) -> tuple[tuple[UUID, str], ...]:
    rows = connection.execute(
        select(tables.task_dependencies.c.depends_on_task_id, tables.tasks.c.status)
        .join(
            tables.tasks,
            (tables.tasks.c.tenant_id == tables.task_dependencies.c.tenant_id)
            & (tables.tasks.c.project_id == tables.task_dependencies.c.project_id)
            & (tables.tasks.c.id == tables.task_dependencies.c.depends_on_task_id),
        )
        .where(
            tables.task_dependencies.c.tenant_id == tenant_id,
            tables.task_dependencies.c.project_id == project_id,
            tables.task_dependencies.c.task_id == task_id,
            active_dependencies(tenant_id, project_id),
        )
        .distinct()
    ).all()
    return tuple(sorted(((row[0], row[1]) for row in rows), key=lambda item: str(item[0])))


def _record_from_row(
    connection: Connection,
    *,
    tenant_id: UUID,
    row: RowMapping,
    dependency_statuses: tuple[tuple[UUID, str], ...] | None = None,
    baseline_dependency_ids: tuple[UUID, ...] | None = None,
) -> TaskRecord:
    if dependency_statuses is None:
        dependency_statuses = _dependency_statuses(
            connection,
            tenant_id=tenant_id,
            project_id=row["project_id"],
            task_id=row["id"],
        )
    if baseline_dependency_ids is None:
        baseline_dependency_ids = tuple(
            sorted(
                projected_dependencies(
                    connection,
                    tenant_id=tenant_id,
                    project_id=row["project_id"],
                    task_id=row["id"],
                ),
                key=str,
            )
        )
    dependency_ids = tuple(item[0] for item in dependency_statuses)
    unresolved = tuple(
        dependency_id
        for dependency_id, status in dependency_statuses
        if status not in TERMINAL_TASK_STATUSES
    )
    status = row["status"]
    if status == "blocked":
        readiness = "blocked"
    elif status in TERMINAL_TASK_STATUSES:
        readiness = "complete"
    elif status == "pending_approval":
        readiness = "waiting_approval"
    elif unresolved:
        readiness = "waiting"
    else:
        readiness = "ready"
    return TaskRecord(
        id=row["id"],
        project_id=row["project_id"],
        stage_id=row["stage_id"],
        parent_task_id=row["parent_task_id"],
        assignee_user_id=row["assignee_user_id"],
        title=row["title"],
        description=row["description"],
        kind=row["kind"],
        source_entity=row["source_entity"],
        source_entity_id=row["source_entity_id"],
        expected_output=row["expected_output"],
        completion_evidence_ref=row["completion_evidence_ref"],
        status=status,
        blocked_reason=row["blocked_reason"],
        priority=row["priority"],
        start_date=row["start_date"],
        due_date=row["due_date"],
        completed_at=row["completed_at"],
        dependency_task_ids=dependency_ids,
        baseline_dependency_task_ids=baseline_dependency_ids,
        unresolved_dependency_ids=unresolved,
        readiness=readiness,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        template_fields=dict(row["template_fields"]),
    )


def _task_snapshot(record: TaskRecord) -> dict[str, object]:
    return {
        "project_id": str(record.project_id),
        "stage_id": str(record.stage_id) if record.stage_id is not None else None,
        "parent_task_id": (
            str(record.parent_task_id) if record.parent_task_id is not None else None
        ),
        "assignee_user_id": (
            str(record.assignee_user_id) if record.assignee_user_id is not None else None
        ),
        "title": record.title,
        "description": record.description,
        "completion_evidence_ref": record.completion_evidence_ref,
        "status": record.status,
        "blocked_reason": record.blocked_reason,
        "priority": record.priority,
        "start_date": record.start_date.isoformat() if record.start_date is not None else None,
        "due_date": record.due_date.isoformat() if record.due_date is not None else None,
        "completed_at": (
            record.completed_at.isoformat() if record.completed_at is not None else None
        ),
        "dependency_task_ids": [str(value) for value in record.dependency_task_ids],
        "readiness": record.readiness,
        **({"template_fields": record.template_fields} if record.template_fields else {}),
    }


def _validate_dates(start_date: date | None, due_date: date | None) -> None:
    if start_date is not None and due_date is not None and due_date < start_date:
        raise TaskDateOrderError


class TaskService:
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
            raise TaskNotFoundError
        return workflow_id

    @staticmethod
    def _get_record(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        task_id: UUID,
    ) -> TaskRecord:
        row = (
            connection.execute(
                _task_statement().where(
                    tables.tasks.c.tenant_id == tenant_id,
                    tables.tasks.c.project_id == project_id,
                    tables.tasks.c.id == task_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise TaskNotFoundError
        return _record_from_row(connection, tenant_id=tenant_id, row=row)

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
            raise TaskScopeError

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
                tables.users.c.is_active.is_(True),
                tables.users.c.role.in_(
                    {"owner", "admin", "project_manager", "engineer", "quality"}
                ),
            )
        ).scalar_one_or_none()
        if found is None:
            raise TaskScopeError

    @staticmethod
    def _validate_task_ids(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        task_ids: tuple[UUID, ...],
    ) -> None:
        if not task_ids:
            return
        if len(set(task_ids)) != len(task_ids):
            raise TaskScopeError
        found = set(
            connection.execute(
                select(tables.tasks.c.id).where(
                    tables.tasks.c.tenant_id == tenant_id,
                    tables.tasks.c.project_id == project_id,
                    tables.tasks.c.id.in_(task_ids),
                )
            ).scalars()
        )
        if found != set(task_ids):
            raise TaskScopeError

    @staticmethod
    def _validate_dependency_graph(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        task_id: UUID,
        dependency_task_ids: tuple[UUID, ...],
    ) -> None:
        if dependency_graph_has_cycle(
            connection,
            tenant_id=tenant_id,
            project_id=project_id,
            replacement_task_id=task_id,
            replacement_dependencies=dependency_task_ids,
        ):
            raise TaskDependencyCycleError

    @staticmethod
    def _replace_dependencies(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        task_id: UUID,
        dependency_task_ids: tuple[UUID, ...],
        occurred_at: datetime,
    ) -> None:
        projected = projected_dependencies(
            connection,
            tenant_id=tenant_id,
            project_id=project_id,
            task_id=task_id,
        )
        existing_manual = set(
            connection.execute(
                select(tables.task_dependencies.c.depends_on_task_id).where(
                    tables.task_dependencies.c.tenant_id == tenant_id,
                    tables.task_dependencies.c.project_id == project_id,
                    tables.task_dependencies.c.task_id == task_id,
                    tables.task_dependencies.c.baseline_id.is_(None),
                )
            ).scalars()
        )
        # Existing clients submit the full visible dependency list. Do not turn
        # projected edges into new manual constraints merely by saving a Task.
        manual_ids = tuple(
            dependency_id
            for dependency_id in dependency_task_ids
            if dependency_id not in projected or dependency_id in existing_manual
        )
        connection.execute(
            delete(tables.task_dependencies).where(
                tables.task_dependencies.c.tenant_id == tenant_id,
                tables.task_dependencies.c.project_id == project_id,
                tables.task_dependencies.c.task_id == task_id,
                tables.task_dependencies.c.baseline_id.is_(None),
            )
        )
        if manual_ids:
            connection.execute(
                tables.task_dependencies.insert(),
                [
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "task_id": task_id,
                        "depends_on_task_id": dependency_id,
                        "created_at": occurred_at,
                    }
                    for dependency_id in manual_ids
                ],
            )

    def get(self, *, tenant_id: UUID, project_id: UUID, task_id: UUID) -> TaskRecord:
        with self._engine.connect() as connection:
            return self._get_record(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                task_id=task_id,
            )

    def list(self, *, tenant_id: UUID, project_id: UUID) -> list[TaskRecord]:
        # The task rows and their predecessors must describe the same snapshot.
        with self._engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            rows = (
                connection.execute(
                    _task_statement()
                    .where(
                        tables.tasks.c.tenant_id == tenant_id,
                        tables.tasks.c.project_id == project_id,
                    )
                    .order_by(tables.tasks.c.updated_at.desc(), tables.tasks.c.id.desc())
                )
                .mappings()
                .all()
            )
            if not rows:
                return []
            dependencies: dict[UUID, set[tuple[UUID, str]]] = {}
            projected: dict[UUID, set[UUID]] = {}
            dependency_rows = connection.execute(
                select(
                    tables.task_dependencies.c.task_id,
                    tables.task_dependencies.c.depends_on_task_id,
                    tables.tasks.c.status,
                    tables.task_dependencies.c.baseline_id,
                )
                .join(
                    tables.tasks,
                    (tables.tasks.c.tenant_id == tables.task_dependencies.c.tenant_id)
                    & (tables.tasks.c.project_id == tables.task_dependencies.c.project_id)
                    & (tables.tasks.c.id == tables.task_dependencies.c.depends_on_task_id),
                )
                .where(
                    tables.task_dependencies.c.tenant_id == tenant_id,
                    tables.task_dependencies.c.project_id == project_id,
                    active_dependencies(tenant_id, project_id),
                )
            )
            for dependency in dependency_rows:
                dependencies.setdefault(dependency.task_id, set()).add(
                    (dependency.depends_on_task_id, dependency.status)
                )
                if dependency.baseline_id is not None:
                    projected.setdefault(dependency.task_id, set()).add(
                        dependency.depends_on_task_id
                    )
            return [
                _record_from_row(
                    connection,
                    tenant_id=tenant_id,
                    row=row,
                    baseline_dependency_ids=tuple(sorted(projected.get(row["id"], ()), key=str)),
                    dependency_statuses=tuple(
                        sorted(dependencies.get(row["id"], []), key=lambda item: str(item[0]))
                    ),
                )
                for row in rows
            ]

    def create(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        draft: TaskDraft,
        connection: Connection | None = None,
        audit_context: dict[str, Any] | None = None,
    ) -> TaskRecord:
        _validate_dates(draft.start_date, draft.due_date)
        task_id = uuid4()
        occurred_at = datetime.now(UTC)
        with self._engine.begin() if connection is None else nullcontext(connection) as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise TaskNotFoundError
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
                user_id=draft.assignee_user_id,
            )
            references = tuple(
                value
                for value in (draft.parent_task_id, *draft.dependency_task_ids)
                if value is not None
            )
            self._validate_task_ids(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                task_ids=references,
            )
            if draft.kind != "task":
                source_table_name = ACTION_SOURCE_TABLES.get(draft.kind)
                if source_table_name is None or draft.source_entity_id is None:
                    raise TaskScopeError
                source_table = getattr(tables, source_table_name)
                source_query = select(source_table.c.id).where(
                    source_table.c.tenant_id == tenant_id,
                    source_table.c.project_id == project_id,
                    source_table.c.id == draft.source_entity_id,
                )
                if draft.kind == "risk_action":
                    source_query = source_query.where(source_table.c.draft_state == "confirmed")
                source_found = connection.execute(source_query).scalar_one_or_none()
                if source_found is None:
                    raise TaskScopeError
            if draft.kind == "meeting_action":
                meeting = (
                    connection.execute(
                        select(tables.meetings).where(
                            tables.meetings.c.tenant_id == tenant_id,
                            tables.meetings.c.project_id == project_id,
                            tables.meetings.c.id == draft.source_entity_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if (
                    meeting is None
                    or meeting["status"] not in {"in_progress", "completed"}
                    or meeting["deleted_at"]
                    or meeting["archived_at"]
                    or draft.assignee_user_id is None
                    or draft.due_date is None
                    or not (draft.expected_output or "").strip()
                ):
                    raise TaskScopeError
            connection.execute(
                tables.tasks.insert(),
                {
                    "id": task_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "workflow_id": workflow_id if draft.stage_id is not None else None,
                    "stage_id": draft.stage_id,
                    "parent_task_id": draft.parent_task_id,
                    "assignee_user_id": draft.assignee_user_id,
                    "title": draft.title,
                    "description": draft.description,
                    "kind": draft.kind,
                    "source_entity": (
                        ACTION_SOURCE_TABLES.get(draft.kind) if draft.kind != "task" else None
                    ),
                    "source_entity_id": draft.source_entity_id if draft.kind != "task" else None,
                    "expected_output": draft.expected_output,
                    "status": "todo",
                    "priority": draft.priority,
                    "start_date": draft.start_date,
                    "due_date": draft.due_date,
                    "created_at": occurred_at,
                    "updated_at": occurred_at,
                },
            )
            self._replace_dependencies(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                task_id=task_id,
                dependency_task_ids=draft.dependency_task_ids,
                occurred_at=occurred_at,
            )
            task = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, task_id=task_id
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"task:{task_id}:created",
                    event_type="TASK_CREATED",
                    source="task_service",
                    entity_id=task_id,
                    payload={
                        "task_id": str(task_id),
                        "status": task.status,
                        "priority": task.priority,
                    },
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="task.create",
                    after_snapshot=_task_snapshot(task),
                    context=audit_context or {},
                ),
            )
            return task

    def update(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        task_id: UUID,
        patch: TaskUpdate,
        connection: Connection | None = None,
    ) -> TaskRecord:
        occurred_at = datetime.now(UTC)
        with self._engine.begin() if connection is None else nullcontext(connection) as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise TaskNotFoundError
            current = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, task_id=task_id
            )
            if current.status in TERMINAL_TASK_STATUSES:
                raise TaskTerminalError
            workflow_id = self._project_workflow(
                connection, tenant_id=tenant_id, project_id=project_id
            )
            changes = dict(patch.changes)
            fields, field_source = project_fields(connection, tenant_id, project_id)
            if "template_fields" in changes:
                if (
                    patch.expected_updated_at is None
                    or patch.expected_updated_at != current.updated_at
                ):
                    raise TemplateFieldConflictError("任务已被修改，请重新读取后核对补充字段")
                changes["template_fields"] = validate_values(
                    fields, changes["template_fields"], current.status
                )
            if "stage_id" in changes:
                stage_id = changes["stage_id"]
                if stage_id is not None and not isinstance(stage_id, UUID):
                    raise TaskScopeError
                self._validate_stage(
                    connection,
                    tenant_id=tenant_id,
                    workflow_id=workflow_id,
                    stage_id=stage_id,
                )
                changes["workflow_id"] = workflow_id if stage_id is not None else None
            if "assignee_user_id" in changes:
                assignee_id = changes["assignee_user_id"]
                if assignee_id is not None and not isinstance(assignee_id, UUID):
                    raise TaskScopeError
                self._validate_member(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    user_id=assignee_id,
                )
            if "parent_task_id" in changes:
                parent_id = changes["parent_task_id"]
                if parent_id == task_id or (
                    parent_id is not None and not isinstance(parent_id, UUID)
                ):
                    raise TaskScopeError
                self._validate_task_ids(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    task_ids=(parent_id,) if isinstance(parent_id, UUID) else (),
                )
            start_date = changes.get("start_date", current.start_date)
            due_date = changes.get("due_date", current.due_date)
            _validate_dates(
                start_date if isinstance(start_date, date) else None,
                due_date if isinstance(due_date, date) else None,
            )
            if patch.dependency_task_ids is not None:
                self._validate_task_ids(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    task_ids=patch.dependency_task_ids,
                )
                self._validate_dependency_graph(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    task_id=task_id,
                    dependency_task_ids=patch.dependency_task_ids,
                )
            if changes:
                connection.execute(
                    tables.tasks.update()
                    .where(
                        tables.tasks.c.tenant_id == tenant_id,
                        tables.tasks.c.project_id == project_id,
                        tables.tasks.c.id == task_id,
                    )
                    .values(**changes, updated_at=occurred_at)
                )
            if patch.dependency_task_ids is not None:
                self._replace_dependencies(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    task_id=task_id,
                    dependency_task_ids=patch.dependency_task_ids,
                    occurred_at=occurred_at,
                )
                if not changes:
                    connection.execute(
                        tables.tasks.update()
                        .where(
                            tables.tasks.c.tenant_id == tenant_id,
                            tables.tasks.c.project_id == project_id,
                            tables.tasks.c.id == task_id,
                        )
                        .values(updated_at=occurred_at)
                    )
            after = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, task_id=task_id
            )
            changed_fields = set(patch.changes)
            if patch.dependency_task_ids is not None:
                changed_fields.add("dependency_task_ids")
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"task:{task_id}:updated:{uuid4()}",
                    event_type="TASK_UPDATED",
                    source="task_service",
                    entity_id=task_id,
                    payload={"changed_fields": sorted(changed_fields), "status": after.status},
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="task.update",
                    before_snapshot=_task_snapshot(current),
                    after_snapshot=_task_snapshot(after),
                    context={"template_field_source": field_source}
                    if "template_fields" in changes
                    else {},
                ),
            )
            return after

    def transition(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        task_id: UUID,
        to_status: str,
        blocked_reason: str | None,
        completion_evidence_ref: str | None = None,
        expected_updated_at: datetime | None = None,
    ) -> TaskRecord:
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise TaskNotFoundError
            before = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, task_id=task_id
            )
            if expected_updated_at is not None and before.updated_at != expected_updated_at:
                raise TaskVersionConflictError
            if to_status not in TASK_TRANSITIONS[before.status]:
                raise TaskInvalidTransitionError
            fields, _ = project_fields(connection, tenant_id, project_id)
            validate_values(fields, before.template_fields, to_status)
            from app.domain.schedule_execution import guard_task_transition, record_task_actual

            guard_task_transition(
                connection, tenant_id, project_id, task_id, to_status, occurred_at
            )
            if to_status == "done":
                from app.domain.task_takeover import guard_completion

                guard_completion(connection, tenant_id, project_id, task_id)
            if to_status == "in_progress" and before.unresolved_dependency_ids:
                raise TaskDependenciesIncompleteError
            quality_investigation = (
                connection.execute(
                    select(tables.quality_work_package_items.c.id).where(
                        tables.quality_work_package_items.c.tenant_id == tenant_id,
                        tables.quality_work_package_items.c.project_id == project_id,
                        tables.quality_work_package_items.c.task_id == task_id,
                    )
                ).first()
                if to_status == "done"
                else None
            )
            if (
                to_status == "done"
                and (before.kind != "task" or quality_investigation is not None)
                and not (completion_evidence_ref or before.completion_evidence_ref or "").strip()
            ):
                raise TaskEvidenceRequiredError
            values: dict[str, object] = {
                "status": to_status,
                "blocked_reason": blocked_reason if to_status == "blocked" else None,
                "completed_at": occurred_at if to_status == "done" else None,
                "updated_at": occurred_at,
            }
            if to_status == "done" and completion_evidence_ref is not None:
                values["completion_evidence_ref"] = completion_evidence_ref
            connection.execute(
                tables.tasks.update()
                .where(
                    tables.tasks.c.tenant_id == tenant_id,
                    tables.tasks.c.project_id == project_id,
                    tables.tasks.c.id == task_id,
                )
                .values(**values)
            )
            after = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, task_id=task_id
            )
            written = EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"task:{task_id}:status:{to_status}:{uuid4()}",
                    event_type="TASK_STATUS_CHANGED",
                    source="task_service",
                    entity_id=task_id,
                    payload={"from_status": before.status, "to_status": after.status},
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="task.transition",
                    before_snapshot=_task_snapshot(before),
                    after_snapshot=_task_snapshot(after),
                ),
            )
            record_task_actual(
                connection,
                tenant_id,
                project_id,
                task_id,
                to_status,
                actor_user_id,
                occurred_at,
                written,
            )
            if to_status == "done" and before.kind in {"issue_action", "risk_action"}:
                self._touch_action_source(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    actor_user_id=actor_user_id,
                    record=after,
                    occurred_at=occurred_at,
                )
            return after

    @staticmethod
    def _touch_action_source(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        record: TaskRecord,
        occurred_at: datetime,
    ) -> None:
        source_entity_id = record.source_entity_id
        if source_entity_id is None:
            # The action_source_consistent CHECK makes this unreachable for the
            # action kinds this runs for; failing loudly beats emitting an event
            # that names no entity.
            raise ValueError("an action task must carry its source entity")
        source_table = getattr(tables, ACTION_SOURCE_TABLES[record.kind])
        row = (
            connection.execute(
                select(source_table).where(
                    source_table.c.tenant_id == tenant_id,
                    source_table.c.id == source_entity_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return
        connection.execute(
            source_table.update()
            .where(
                source_table.c.tenant_id == tenant_id,
                source_table.c.id == source_entity_id,
            )
            .values(updated_at=occurred_at)
        )
        if record.kind == "issue_action":
            event = EventDraft(
                event_id=f"issue:{source_entity_id}:updated:{uuid4()}",
                event_type="ISSUE_UPDATED",
                source="issue_service",
                entity_id=source_entity_id,
                payload={
                    "changed_fields": ["action_completed"],
                    "status": row["status"],
                    "severity": row["severity"],
                },
                occurred_at=occurred_at,
            )
        else:
            event = EventDraft(
                event_id=f"risk:{source_entity_id}:updated:{uuid4()}",
                event_type="RISK_UPDATED",
                source="risk_service",
                entity_id=source_entity_id,
                payload={
                    "changed_fields": ["action_completed"],
                    "status": row["status"],
                    "score": row["likelihood"] * row["impact"],
                },
                occurred_at=occurred_at,
            )
        EventAuditWriter(
            connection,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            project_id=project_id,
        ).record(
            event,
            AuditDraft(
                action=f"{record.kind}.completed",
                after_snapshot={
                    "task_id": str(record.id),
                    "source_entity_id": str(source_entity_id),
                    "completion_evidence_ref": record.completion_evidence_ref,
                },
            ),
        )
