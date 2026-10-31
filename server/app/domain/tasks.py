"""Project-scoped Task dependency and lifecycle use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, delete, select
from sqlalchemy.engine import RowMapping

from app.db.schema import tables
from app.domain.project_write_lock import lock_project_write_scope
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


class TaskTerminalError(ValueError):
    """Raised when a terminal Task is edited."""


@dataclass(frozen=True)
class TaskRecord:
    id: UUID
    project_id: UUID
    stage_id: UUID | None
    parent_task_id: UUID | None
    assignee_user_id: UUID | None
    title: str
    description: str | None
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


@dataclass(frozen=True)
class TaskUpdate:
    changes: dict[str, object]
    dependency_task_ids: tuple[UUID, ...] | None = None


@dataclass(frozen=True)
class ProjectMemberRecord:
    user_id: UUID
    display_name: str
    role: str
    is_active: bool
    assignable: bool


TASK_TRANSITIONS = {
    "todo": frozenset({"in_progress", "blocked", "skipped"}),
    "in_progress": frozenset({"blocked", "done"}),
    "blocked": frozenset({"todo", "in_progress", "skipped"}),
    "done": frozenset(),
    "skipped": frozenset(),
    "pending_approval": frozenset(),
}
TERMINAL_TASK_STATUSES = frozenset({"done", "skipped"})
# Roles that may own project work; mirrored by the members listing's `assignable` flag.
ASSIGNABLE_MEMBER_ROLES = frozenset({"owner", "admin", "project_manager", "engineer", "quality"})


def _task_statement() -> Any:
    return select(
        tables.tasks.c.id,
        tables.tasks.c.project_id,
        tables.tasks.c.stage_id,
        tables.tasks.c.parent_task_id,
        tables.tasks.c.assignee_user_id,
        tables.tasks.c.title,
        tables.tasks.c.description,
        tables.tasks.c.status,
        tables.tasks.c.blocked_reason,
        tables.tasks.c.priority,
        tables.tasks.c.start_date,
        tables.tasks.c.due_date,
        tables.tasks.c.completed_at,
        tables.tasks.c.created_at,
        tables.tasks.c.updated_at,
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
        )
    ).all()
    return tuple(sorted(((row[0], row[1]) for row in rows), key=lambda item: str(item[0])))


def _record_from_row(
    connection: Connection,
    *,
    tenant_id: UUID,
    row: RowMapping,
) -> TaskRecord:
    dependency_statuses = _dependency_statuses(
        connection,
        tenant_id=tenant_id,
        project_id=row["project_id"],
        task_id=row["id"],
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
        status=status,
        blocked_reason=row["blocked_reason"],
        priority=row["priority"],
        start_date=row["start_date"],
        due_date=row["due_date"],
        completed_at=row["completed_at"],
        dependency_task_ids=dependency_ids,
        unresolved_dependency_ids=unresolved,
        readiness=readiness,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
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
                tables.users.c.role.in_(ASSIGNABLE_MEMBER_ROLES),
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
        if task_id in dependency_task_ids:
            raise TaskDependencyCycleError
        rows = connection.execute(
            select(
                tables.task_dependencies.c.task_id,
                tables.task_dependencies.c.depends_on_task_id,
            ).where(
                tables.task_dependencies.c.tenant_id == tenant_id,
                tables.task_dependencies.c.project_id == project_id,
            )
        ).all()
        edges: dict[UUID, set[UUID]] = {}
        for child_id, predecessor_id in rows:
            edges.setdefault(child_id, set()).add(predecessor_id)
        edges[task_id] = set(dependency_task_ids)

        def reaches(start: UUID, target: UUID) -> bool:
            pending = [start]
            visited: set[UUID] = set()
            while pending:
                current = pending.pop()
                if current == target:
                    return True
                if current in visited:
                    continue
                visited.add(current)
                pending.extend(edges.get(current, ()))
            return False

        if any(reaches(dependency_id, task_id) for dependency_id in dependency_task_ids):
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
        connection.execute(
            delete(tables.task_dependencies).where(
                tables.task_dependencies.c.tenant_id == tenant_id,
                tables.task_dependencies.c.project_id == project_id,
                tables.task_dependencies.c.task_id == task_id,
            )
        )
        if dependency_task_ids:
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
                    for dependency_id in dependency_task_ids
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

    def list_members(self, *, tenant_id: UUID, project_id: UUID) -> list[ProjectMemberRecord]:
        """Project members with the identity fields needed to show and pick assignees."""
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(
                    tables.users.c.id,
                    tables.users.c.display_name,
                    tables.users.c.role,
                    tables.users.c.is_active,
                )
                .join(
                    tables.project_members,
                    (tables.project_members.c.tenant_id == tables.users.c.tenant_id)
                    & (tables.project_members.c.user_id == tables.users.c.id),
                )
                .where(
                    tables.project_members.c.tenant_id == tenant_id,
                    tables.project_members.c.project_id == project_id,
                )
                .order_by(tables.users.c.display_name, tables.users.c.id)
            ).mappings()
            return [
                ProjectMemberRecord(
                    user_id=row["id"],
                    display_name=row["display_name"],
                    role=row["role"],
                    is_active=row["is_active"],
                    assignable=row["role"] in ASSIGNABLE_MEMBER_ROLES,
                )
                for row in rows
            ]

    def list(self, *, tenant_id: UUID, project_id: UUID) -> list[TaskRecord]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                _task_statement()
                .where(
                    tables.tasks.c.tenant_id == tenant_id,
                    tables.tasks.c.project_id == project_id,
                )
                .order_by(tables.tasks.c.updated_at.desc(), tables.tasks.c.id.desc())
            ).mappings()
            return [_record_from_row(connection, tenant_id=tenant_id, row=row) for row in rows]

    def create(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        draft: TaskDraft,
    ) -> TaskRecord:
        _validate_dates(draft.start_date, draft.due_date)
        task_id = uuid4()
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
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
                AuditDraft(action="task.create", after_snapshot=_task_snapshot(task)),
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
    ) -> TaskRecord:
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
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
    ) -> TaskRecord:
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise TaskNotFoundError
            before = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, task_id=task_id
            )
            if to_status not in TASK_TRANSITIONS[before.status]:
                raise TaskInvalidTransitionError
            if to_status == "in_progress" and before.unresolved_dependency_ids:
                raise TaskDependenciesIncompleteError
            values: dict[str, object] = {
                "status": to_status,
                "blocked_reason": blocked_reason if to_status == "blocked" else None,
                "completed_at": occurred_at if to_status == "done" else None,
                "updated_at": occurred_at,
            }
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
            EventAuditWriter(
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
            return after
