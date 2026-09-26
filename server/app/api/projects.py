"""Tenant- and membership-bound Project HTTP boundary."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Self
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Engine, select

from app.api.auth import current_context, no_store
from app.auth.errors import ObjectPermissionDeniedError
from app.auth.project_access import (
    ProjectAccess,
    ProjectAccessService,
    SqlProjectAccessRepository,
)
from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.db.engine import get_engine
from app.db.schema import tables
from app.domain.case_requirements import CaseRequirementReadinessError
from app.domain.case_reviews import CaseReviewNotReadyError
from app.domain.process_template_gates import requirements as template_gate_requirements
from app.domain.process_template_reminders import policy as template_reminder_policy
from app.domain.project_completion import ProjectCompletionNotReadyError
from app.domain.project_execution import ProjectExecutionNotReadyError
from app.domain.project_templates import ProjectCreationTemplate, ProjectTemplateError, catalog
from app.domain.projects import (
    DevelopmentCaseNotFoundForProjectError,
    ProjectAlreadyExistsError,
    ProjectCaseNotApprovedError,
    ProjectCodeConflictError,
    ProjectDateOrderError,
    ProjectDraft,
    ProjectGateNotApprovedError,
    ProjectInvalidTransitionError,
    ProjectNotActiveError,
    ProjectNotFoundError,
    ProjectRecord,
    ProjectService,
    ProjectStageInvalidTransitionError,
    ProjectTerminalError,
    ProjectUpdate,
    StageRecord,
    WorkflowRecord,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])


class StageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    code: str
    name: str
    description: str | None
    sequence: int


class WorkflowResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    code: str
    name: str
    description: str | None
    version: int
    is_active: bool
    stages: list[StageResponse]


class ProjectResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    development_case_id: UUID | None
    customer_id: UUID | None
    workflow: WorkflowResponse
    current_stage: StageResponse
    owner_user_id: UUID
    code: str
    name: str
    description: str | None
    status: str
    start_date: date | None
    target_date: date | None
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[ProjectResponse]


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    development_case_id: UUID
    product_template: ProjectCreationTemplate | None = None
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=20_000)
    start_date: date | None = None
    target_date: date | None = None

    @field_validator("code", "name", mode="before")
    @classmethod
    def normalize_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("description", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @model_validator(mode="after")
    def validate_date_order(self) -> Self:
        if (
            self.start_date is not None
            and self.target_date is not None
            and self.target_date < self.start_date
        ):
            raise ValueError("target_date cannot precede start_date")
        return self


class ProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=20_000)
    start_date: date | None = None
    target_date: date | None = None

    @field_validator("code", "name", mode="before")
    @classmethod
    def normalize_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("description", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @model_validator(mode="after")
    def require_nonempty_valid_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be supplied")
        for field_name in {"code", "name"}:
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class ProjectTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_status: str = Field(pattern=r"^(proposed|approved|active|on_hold|completed|archived)$")


class ProjectStageTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_stage_id: UUID


class ProjectAccessResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    role: Role
    allowed_actions: list[Action]


class ProjectActivityResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    event_type: str
    entity: str
    entity_id: UUID
    timestamp: datetime


class ProjectActivityListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[ProjectActivityResponse]


def stage_response(record: StageRecord) -> StageResponse:
    return StageResponse(
        id=record.id,
        code=record.code,
        name=record.name,
        description=record.description,
        sequence=record.sequence,
    )


def workflow_response(record: WorkflowRecord) -> WorkflowResponse:
    return WorkflowResponse(
        id=record.id,
        code=record.code,
        name=record.name,
        description=record.description,
        version=record.version,
        is_active=record.is_active,
        stages=[stage_response(stage) for stage in record.stages],
    )


def project_response(record: ProjectRecord) -> ProjectResponse:
    return ProjectResponse(
        id=record.id,
        development_case_id=record.development_case_id,
        customer_id=record.customer_id,
        workflow=workflow_response(record.workflow),
        current_stage=stage_response(record.current_stage),
        owner_user_id=record.owner_user_id,
        code=record.code,
        name=record.name,
        description=record.description,
        status=record.status,
        start_date=record.start_date,
        target_date=record.target_date,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def permission_denied() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "OBJECT_PERMISSION_DENIED",
            "message": "The requested project action is not permitted",
        },
    )


def require_project_action(
    *,
    project_id: UUID,
    context: AuthContext,
    engine: Engine,
    action: Action,
) -> ProjectAccess:
    try:
        return ProjectAccessService(SqlProjectAccessRepository(engine)).authorize(
            context=context,
            project_id=project_id,
            action=action,
        )
    except ObjectPermissionDeniedError as error:
        raise permission_denied() from error


def require_project_view(
    project_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ProjectAccess:
    return require_project_action(
        project_id=project_id,
        context=context,
        engine=engine,
        action=Action.PROJECT_VIEW,
    )


@router.get("/creation-templates")
def creation_templates(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    if not is_allowed(context.user.role, Action.PROJECT_CREATE):
        raise permission_denied()
    no_store(response)
    with engine.connect() as connection:
        return {
            "items": [
                item
                | {
                    "gate_requirements": template_gate_requirements(item),
                    "reminder_policy": template_reminder_policy(item).model_dump(mode="json"),
                }
                for item in catalog(connection=connection, tenant_id=context.tenant.id)
            ]
        }


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ProjectResponse:
    if not is_allowed(context.user.role, Action.PROJECT_CREATE):
        raise permission_denied()
    try:
        record = ProjectService(engine).create(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            actor_role=context.user.role,
            draft=ProjectDraft(**payload.model_dump(exclude={"product_template"})),
            product_template=payload.product_template,
        )
    except ProjectTemplateError as error:
        raise HTTPException(
            409, detail={"code": "PROJECT_TEMPLATE_INVALID", "message": str(error)}
        ) from error
    except DevelopmentCaseNotFoundForProjectError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "DEVELOPMENT_CASE_NOT_FOUND",
                "message": "Development Case was not found",
            },
        ) from error
    except (CaseRequirementReadinessError, CaseReviewNotReadyError) as error:
        raise HTTPException(
            status_code=409, detail={"code": "CASE_REQUIREMENTS_NOT_READY", "message": str(error)}
        ) from error
    except ProjectCaseNotApprovedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "CASE_NOT_APPROVED", "message": "Case must be approved"},
        ) from error
    except ProjectAlreadyExistsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "PROJECT_ALREADY_EXISTS", "message": "Case already has a Project"},
        ) from error
    except ProjectCodeConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "PROJECT_CODE_CONFLICT", "message": "Project code already exists"},
        ) from error
    no_store(response)
    return project_response(record)


@router.get("", response_model=ProjectListResponse)
def list_projects(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ProjectListResponse:
    if not is_allowed(context.user.role, Action.PROJECT_VIEW):
        raise permission_denied()
    member_user_id = None if context.user.role in {Role.OWNER, Role.ADMIN} else context.user.id
    records = ProjectService(engine).list(
        tenant_id=context.tenant.id,
        member_user_id=member_user_id,
    )
    no_store(response)
    return ProjectListResponse(items=[project_response(record) for record in records])


@router.get("/{project_id}/access", response_model=ProjectAccessResponse)
def project_access(
    response: Response,
    access: Annotated[ProjectAccess, Depends(require_project_view)],
) -> ProjectAccessResponse:
    no_store(response)
    return ProjectAccessResponse(
        project_id=access.project_id,
        role=access.role,
        allowed_actions=sorted(access.allowed_actions, key=lambda action: action.value),
    )


@router.get("/{project_id}/activity", response_model=ProjectActivityListResponse)
def project_activity(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ProjectActivityListResponse:
    require_project_action(
        project_id=project_id,
        context=context,
        engine=engine,
        action=Action.PROJECT_VIEW,
    )
    with engine.connect() as connection:
        rows = list(
            connection.execute(
                select(
                    tables.events.c.id,
                    tables.events.c.event_type,
                    tables.events.c.entity,
                    tables.events.c.entity_id,
                    tables.events.c.timestamp,
                )
                .where(
                    tables.events.c.tenant_id == context.tenant.id,
                    tables.events.c.project_id == project_id,
                )
                .order_by(tables.events.c.id.desc())
                .limit(100)
            ).mappings()
        )
    no_store(response)
    return ProjectActivityListResponse(items=[ProjectActivityResponse(**row) for row in rows])


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ProjectResponse:
    require_project_action(
        project_id=project_id,
        context=context,
        engine=engine,
        action=Action.PROJECT_VIEW,
    )
    try:
        record = ProjectService(engine).get(
            tenant_id=context.tenant.id,
            project_id=project_id,
        )
    except ProjectNotFoundError as error:
        raise permission_denied() from error
    no_store(response)
    return project_response(record)


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: UUID,
    payload: ProjectUpdateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ProjectResponse:
    require_project_action(
        project_id=project_id,
        context=context,
        engine=engine,
        action=Action.PROJECT_EDIT,
    )
    try:
        record = ProjectService(engine).update(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            patch=ProjectUpdate(changes=payload.model_dump(exclude_unset=True)),
        )
    except ProjectNotFoundError as error:
        raise permission_denied() from error
    except ProjectTerminalError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "PROJECT_TERMINAL", "message": "Archived Project cannot be edited"},
        ) from error
    except ProjectDateOrderError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "PROJECT_DATE_ORDER", "message": "Target date precedes start date"},
        ) from error
    except ProjectCodeConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "PROJECT_CODE_CONFLICT", "message": "Project code already exists"},
        ) from error
    no_store(response)
    return project_response(record)


@router.post("/{project_id}/transitions", response_model=ProjectResponse)
def transition_project(
    project_id: UUID,
    payload: ProjectTransitionRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ProjectResponse:
    require_project_action(
        project_id=project_id,
        context=context,
        engine=engine,
        action=Action.PROJECT_EDIT,
    )
    try:
        record = ProjectService(engine).transition_status(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            to_status=payload.to_status,
        )
    except ProjectNotFoundError as error:
        raise permission_denied() from error
    except ProjectCompletionNotReadyError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PROJECT_COMPLETION_NOT_READY",
                "message": str(error),
                "blockers": error.blockers,
            },
        ) from error
    except ProjectExecutionNotReadyError as error:
        raise HTTPException(
            status_code=409, detail={"code": "PROJECT_EXECUTION_NOT_READY", "message": str(error)}
        ) from error
    except ProjectInvalidTransitionError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "PROJECT_INVALID_TRANSITION",
                "message": "Project transition is invalid",
            },
        ) from error
    no_store(response)
    return project_response(record)


@router.post("/{project_id}/stage-transitions", response_model=ProjectResponse)
def transition_project_stage(
    project_id: UUID,
    payload: ProjectStageTransitionRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ProjectResponse:
    require_project_action(
        project_id=project_id,
        context=context,
        engine=engine,
        action=Action.PROJECT_EDIT,
    )
    try:
        record = ProjectService(engine).transition_stage(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            to_stage_id=payload.to_stage_id,
        )
    except ProjectNotFoundError as error:
        raise permission_denied() from error
    except ProjectNotActiveError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "PROJECT_NOT_ACTIVE", "message": "Project must be active"},
        ) from error
    except ProjectGateNotApprovedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "PROJECT_GATE_NOT_APPROVED",
                "message": "Current Stage Gate must be approved before advancement",
            },
        ) from error
    except ProjectStageInvalidTransitionError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "PROJECT_STAGE_INVALID_TRANSITION",
                "message": "Stage transition must target the adjacent Workflow Stage",
            },
        ) from error
    no_store(response)
    return project_response(record)
