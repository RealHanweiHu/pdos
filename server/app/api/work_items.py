"""Project-scoped Task, Issue, and Risk HTTP boundaries."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Self
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.auth.errors import ObjectPermissionDeniedError
from app.auth.project_access import ProjectAccessService, SqlProjectAccessRepository
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.engine import get_engine
from app.domain.tasks import (
    ProjectMemberRecord,
    TaskDateOrderError,
    TaskDependenciesIncompleteError,
    TaskDependencyCycleError,
    TaskDraft,
    TaskInvalidTransitionError,
    TaskNotFoundError,
    TaskRecord,
    TaskScopeError,
    TaskService,
    TaskTerminalError,
    TaskUpdate,
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
    status: str
    blocked_reason: str | None
    priority: str
    start_date: date | None
    due_date: date | None
    completed_at: datetime | None
    dependency_task_ids: list[UUID]
    unresolved_dependency_ids: list[UUID]
    readiness: str
    created_at: datetime
    updated_at: datetime


class TaskListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[TaskResponse]


class ProjectMemberResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: UUID
    display_name: str
    role: str
    is_active: bool
    assignable: bool


class ProjectMemberListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[ProjectMemberResponse]


class TaskCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_id: UUID | None = None
    parent_task_id: UUID | None = None
    assignee_user_id: UUID | None = None
    title: str = Field(min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=20_000)
    priority: str = Field(default="medium", pattern=r"^(low|medium|high|critical)$")
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

    to_status: str = Field(pattern=r"^(todo|in_progress|blocked|done|skipped)$")
    blocked_reason: str | None = Field(default=None, max_length=20_000)

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
        status=record.status,
        blocked_reason=record.blocked_reason,
        priority=record.priority,
        start_date=record.start_date,
        due_date=record.due_date,
        completed_at=record.completed_at,
        dependency_task_ids=list(record.dependency_task_ids),
        unresolved_dependency_ids=list(record.unresolved_dependency_ids),
        readiness=record.readiness,
        created_at=record.created_at,
        updated_at=record.updated_at,
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


def member_response(record: ProjectMemberRecord) -> ProjectMemberResponse:
    return ProjectMemberResponse(
        user_id=record.user_id,
        display_name=record.display_name,
        role=record.role,
        is_active=record.is_active,
        assignable=record.assignable,
    )


@router.get("/members", response_model=ProjectMemberListResponse)
def list_project_members(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ProjectMemberListResponse:
    no_store(response)
    authorize_project(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.WORK_ITEM_VIEW,
    )
    return ProjectMemberListResponse(
        items=[
            member_response(record)
            for record in TaskService(engine).list_members(
                tenant_id=context.tenant.id,
                project_id=project_id,
            )
        ]
    )


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
            )
        )
    except Exception as error:
        raise task_error(error) from error
