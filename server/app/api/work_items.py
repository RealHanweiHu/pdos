"""Project-scoped Task, Issue, and Risk HTTP boundaries."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Self
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.auth.errors import ObjectPermissionDeniedError
from app.auth.project_access import ProjectAccessService, SqlProjectAccessRepository
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.engine import get_engine
from app.domain.process_template_fields import TemplateFieldConflictError, TemplateFieldError
from app.domain.process_template_task_fields import project_fields
from app.domain.task_takeover import PacketRequest
from app.domain.task_takeover_residuals import Kind as ResidualKind
from app.domain.tasks import (
    TaskDateOrderError,
    TaskDependenciesIncompleteError,
    TaskDependencyCycleError,
    TaskDraft,
    TaskEvidenceRequiredError,
    TaskInvalidTransitionError,
    TaskNotFoundError,
    TaskRecord,
    TaskScopeError,
    TaskService,
    TaskTerminalError,
    TaskUpdate,
    TaskVersionConflictError,
)

router = APIRouter(prefix="/api/projects/{project_id}", tags=["work-items"])


class TaskResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

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
    dependency_task_ids: list[UUID]
    baseline_dependency_task_ids: list[UUID]
    unresolved_dependency_ids: list[UUID]
    readiness: str
    created_at: datetime
    updated_at: datetime
    template_fields: dict[str, Any] = Field(default_factory=dict)


class TaskListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[TaskResponse]


class TaskCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_id: UUID | None = None
    parent_task_id: UUID | None = None
    assignee_user_id: UUID | None = None
    title: str = Field(min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=20_000)
    priority: str = Field(default="medium", pattern=r"^(low|medium|high|critical)$")
    kind: str = Field(
        default="task",
        pattern=r"^(task|meeting_action|issue_action|gate_action|change_action|risk_action)$",
    )
    source_entity_id: UUID | None = None
    expected_output: str | None = Field(default=None, max_length=20_000)
    start_date: date | None = None
    due_date: date | None = None
    dependency_task_ids: list[UUID] = Field(default_factory=list, max_length=100)

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @model_validator(mode="after")
    def validate_dates_and_dependencies(self) -> Self:
        if (
            self.start_date is not None
            and self.due_date is not None
            and self.due_date < self.start_date
        ):
            raise ValueError("due_date cannot precede start_date")
        if len(set(self.dependency_task_ids)) != len(self.dependency_task_ids):
            raise ValueError("dependency_task_ids must be unique")
        return self


class TaskUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_id: UUID | None = None
    parent_task_id: UUID | None = None
    assignee_user_id: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=20_000)
    priority: str | None = Field(default=None, pattern=r"^(low|medium|high|critical)$")
    start_date: date | None = None
    due_date: date | None = None
    dependency_task_ids: list[UUID] | None = Field(default=None, max_length=100)

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be supplied")
        for field_name in {"title", "priority"}:
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        if self.dependency_task_ids is not None and len(set(self.dependency_task_ids)) != len(
            self.dependency_task_ids
        ):
            raise ValueError("dependency_task_ids must be unique")
        return self


class TaskTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_updated_at: AwareDatetime | None = None

    to_status: str = Field(pattern=r"^(todo|in_progress|blocked|done|skipped)$")
    blocked_reason: str | None = Field(default=None, max_length=20_000)
    completion_evidence_ref: str | None = Field(default=None, max_length=2_000)

    @field_validator("blocked_reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @model_validator(mode="after")
    def require_reason_only_for_blocked(self) -> Self:
        if self.to_status == "blocked" and self.blocked_reason is None:
            raise ValueError("blocked_reason is required")
        if self.to_status != "blocked" and self.blocked_reason is not None:
            raise ValueError("blocked_reason is only valid for blocked")
        return self


def task_response(record: TaskRecord) -> TaskResponse:
    return TaskResponse(
        id=record.id,
        project_id=record.project_id,
        stage_id=record.stage_id,
        parent_task_id=record.parent_task_id,
        assignee_user_id=record.assignee_user_id,
        title=record.title,
        description=record.description,
        kind=record.kind,
        source_entity=record.source_entity,
        source_entity_id=record.source_entity_id,
        expected_output=record.expected_output,
        completion_evidence_ref=record.completion_evidence_ref,
        status=record.status,
        blocked_reason=record.blocked_reason,
        priority=record.priority,
        start_date=record.start_date,
        due_date=record.due_date,
        completed_at=record.completed_at,
        dependency_task_ids=list(record.dependency_task_ids),
        baseline_dependency_task_ids=list(record.baseline_dependency_task_ids),
        unresolved_dependency_ids=list(record.unresolved_dependency_ids),
        readiness=record.readiness,
        created_at=record.created_at,
        updated_at=record.updated_at,
        template_fields=record.template_fields,
    )


def authorize_project(
    *,
    engine: Engine,
    context: AuthContext,
    project_id: UUID,
    action: Action,
) -> None:
    try:
        ProjectAccessService(SqlProjectAccessRepository(engine)).authorize(
            context=context,
            project_id=project_id,
            action=action,
        )
    except ObjectPermissionDeniedError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "PROJECT_ACCESS_DENIED", "message": "Project access denied"},
        ) from error


def task_error(error: Exception) -> HTTPException:
    if isinstance(error, (TemplateFieldError, TemplateFieldConflictError)):
        return HTTPException(
            409 if isinstance(error, TemplateFieldConflictError) else 422,
            detail={"code": "TASK_TEMPLATE_FIELDS", "message": str(error)},
        )
    from app.domain.schedule_execution import ScheduleExecutionBlocked
    from app.domain.task_takeover import TaskTakeoverIncompleteError

    if isinstance(error, TaskTakeoverIncompleteError):
        return HTTPException(409, detail={"code": "TASK_TAKEOVER_REQUIRED", "message": str(error)})

    if isinstance(error, ScheduleExecutionBlocked):
        return HTTPException(
            status_code=409,
            detail={
                "code": "SCHEDULE_EXECUTION_BLOCKED",
                "message": str(error),
                "blockers": error.blockers,
            },
        )
    if isinstance(error, TaskNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TASK_NOT_FOUND", "message": "Task was not found"},
        )
    if isinstance(error, TaskScopeError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "TASK_RELATED_OBJECT_NOT_FOUND",
                "message": "Related object was not found",
            },
        )
    if isinstance(error, TaskEvidenceRequiredError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "TASK_EVIDENCE_REQUIRED",
                "message": "Action tasks need completion evidence to be marked done",
            },
        )
    if isinstance(error, TaskDependencyCycleError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "TASK_DEPENDENCY_CYCLE", "message": "Task dependency cycle detected"},
        )
    if isinstance(error, TaskDependenciesIncompleteError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "TASK_DEPENDENCIES_INCOMPLETE",
                "message": "Task is waiting for predecessors",
            },
        )
    if isinstance(error, TaskInvalidTransitionError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "TASK_INVALID_TRANSITION", "message": "Task transition is not allowed"},
        )
    if isinstance(error, TaskVersionConflictError):
        return HTTPException(
            status_code=409,
            detail={
                "code": "TASK_VERSION_CHANGED",
                "message": "任务内容或办理状态已变化，请刷新工作卡后核对再办理",
            },
        )
    if isinstance(error, TaskTerminalError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "TASK_TERMINAL", "message": "Terminal Task cannot be edited"},
        )
    if isinstance(error, TaskDateOrderError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "TASK_DATE_ORDER", "message": "Due date precedes start date"},
        )
    raise error


@router.get("/tasks", response_model=TaskListResponse)
def list_tasks(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> TaskListResponse:
    no_store(response)
    authorize_project(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.WORK_ITEM_VIEW,
    )
    return TaskListResponse(
        items=[
            task_response(record)
            for record in TaskService(engine).list(
                tenant_id=context.tenant.id,
                project_id=project_id,
            )
        ]
    )


@router.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    project_id: UUID,
    body: TaskCreateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> TaskResponse:
    no_store(response)
    authorize_project(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.WORK_ITEM_EDIT,
    )
    try:
        record = TaskService(engine).create(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            draft=TaskDraft(
                kind=body.kind,
                source_entity_id=body.source_entity_id,
                expected_output=body.expected_output,
                stage_id=body.stage_id,
                parent_task_id=body.parent_task_id,
                assignee_user_id=body.assignee_user_id,
                title=body.title,
                description=body.description,
                priority=body.priority,
                start_date=body.start_date,
                due_date=body.due_date,
                dependency_task_ids=tuple(body.dependency_task_ids),
            ),
        )
    except Exception as error:
        raise task_error(error) from error
    return task_response(record)


@router.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(
    project_id: UUID,
    task_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> TaskResponse:
    no_store(response)
    authorize_project(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.WORK_ITEM_VIEW,
    )
    try:
        return task_response(
            TaskService(engine).get(
                tenant_id=context.tenant.id,
                project_id=project_id,
                task_id=task_id,
            )
        )
    except Exception as error:
        raise task_error(error) from error


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
def update_task(
    project_id: UUID,
    task_id: UUID,
    body: TaskUpdateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> TaskResponse:
    no_store(response)
    authorize_project(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.WORK_ITEM_EDIT,
    )
    serialized = body.model_dump(exclude_unset=True)
    dependency_ids = serialized.pop("dependency_task_ids", None)
    try:
        return task_response(
            TaskService(engine).update(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                task_id=task_id,
                patch=TaskUpdate(
                    changes=serialized,
                    dependency_task_ids=(
                        tuple(dependency_ids) if dependency_ids is not None else None
                    ),
                ),
            )
        )
    except Exception as error:
        raise task_error(error) from error


class TaskTemplateFieldsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict[str, Any] = Field(max_length=30)
    expected_updated_at: AwareDatetime


@router.get("/tasks/{task_id}/template-fields")
def get_task_template_fields(
    project_id: UUID,
    task_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_VIEW
    )
    try:
        record = TaskService(engine).get(
            tenant_id=context.tenant.id, project_id=project_id, task_id=task_id
        )
        with engine.connect() as connection:
            fields, source = project_fields(connection, context.tenant.id, project_id)
        return {
            "task": task_response(record).model_dump(mode="json"),
            "fields": [item.model_dump(mode="json") for item in fields],
            "source": source,
        }
    except Exception as error:
        raise task_error(error) from error


@router.patch("/tasks/{task_id}/template-fields", response_model=TaskResponse)
def save_task_template_fields(
    project_id: UUID,
    task_id: UUID,
    body: TaskTemplateFieldsRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> TaskResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    try:
        return task_response(
            TaskService(engine).update(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                task_id=task_id,
                patch=TaskUpdate(
                    changes={"template_fields": body.values},
                    expected_updated_at=body.expected_updated_at,
                ),
            )
        )
    except Exception as error:
        raise task_error(error) from error


@router.post("/tasks/{task_id}/transitions", response_model=TaskResponse)
def transition_task(
    project_id: UUID,
    task_id: UUID,
    body: TaskTransitionRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> TaskResponse:
    no_store(response)
    authorize_project(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.WORK_ITEM_EDIT,
    )
    try:
        return task_response(
            TaskService(engine).transition(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                task_id=task_id,
                to_status=body.to_status,
                blocked_reason=body.blocked_reason,
                completion_evidence_ref=body.completion_evidence_ref,
                expected_updated_at=body.expected_updated_at,
            )
        )
    except Exception as error:
        raise task_error(error) from error


@router.get("/tasks/{task_id}/preparation")
def task_preparation(
    project_id: UUID,
    task_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError
    from app.domain.task_preparation import TaskPreparationService

    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_VIEW
    )
    try:
        result = TaskPreparationService(engine).get(context, project_id, task_id)
        try:
            authorize_project(
                engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
            )
            result["can_edit"] = True
        except HTTPException as permission_error:
            if permission_error.status_code != 403:
                raise
            result["can_edit"] = False
        return result
    except ProductWorkAccessError as error:
        raise HTTPException(
            status_code=403, detail={"code": "PROJECT_ACCESS_DENIED", "message": str(error)}
        ) from error
    except ProductWorkError as error:
        raise HTTPException(
            status_code=409, detail={"code": "TASK_PREPARATION_UNAVAILABLE", "message": str(error)}
        ) from error
    except TaskNotFoundError as error:
        raise task_error(error) from error


def takeover_error(error: Exception) -> HTTPException:
    from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError

    if isinstance(error, ProductWorkAccessError):
        return HTTPException(403, detail={"code": "TAKEOVER_ACCESS_DENIED", "message": str(error)})
    if isinstance(error, ProductWorkError):
        return HTTPException(409, detail={"code": "TAKEOVER_CHANGED", "message": str(error)})
    return task_error(error)


@router.get("/tasks/{task_id}/takeover")
def task_takeover_read(
    project_id: UUID,
    task_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    request_id: UUID | None = None,
) -> dict[str, Any]:
    from app.domain.task_takeover import read

    no_store(response)
    try:
        return read(engine, context, project_id, task_id, request_id)
    except Exception as error:
        raise takeover_error(error) from error


@router.post("/tasks/{task_id}/takeover")
def task_takeover_save(
    project_id: UUID,
    task_id: UUID,
    body: PacketRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.task_takeover import save

    no_store(response)
    try:
        return save(engine, context, project_id, task_id, body)
    except Exception as error:
        raise takeover_error(error) from error


@router.get("/tasks/{task_id}/takeover/residuals")
def takeover_residuals(
    project_id: UUID,
    task_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    kind: ResidualKind,
    search: Annotated[str, Query(max_length=200)] = "",
    after_id: UUID | None = None,
) -> dict[str, Any]:
    from app.domain.task_takeover_residuals import options

    no_store(response)
    try:
        return options(engine, context, project_id, task_id, kind, search, after_id)
    except Exception as error:
        raise takeover_error(error) from error


@router.get("/tasks/{task_id}/takeover/history")
def takeover_history(
    project_id: UUID,
    task_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_revision: Annotated[int, Query(gt=0)],
) -> dict[str, Any]:
    from app.domain.task_takeover import history

    no_store(response)
    try:
        return history(engine, context, project_id, task_id, before_revision)
    except Exception as error:
        raise takeover_error(error) from error
