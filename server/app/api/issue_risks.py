"""Project-scoped Issue and Risk HTTP boundaries."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Self
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.api.work_items import authorize_project
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.engine import get_engine
from app.domain.issues import (
    IssueDraft,
    IssueInvalidTransitionError,
    IssueNotFoundError,
    IssueRecord,
    IssueScopeError,
    IssueService,
    IssueTerminalError,
    IssueUpdate,
)
from app.domain.risks import (
    RiskDraft,
    RiskInvalidTransitionError,
    RiskNotFoundError,
    RiskRecord,
    RiskScopeError,
    RiskService,
    RiskTerminalError,
    RiskUpdate,
)

router = APIRouter(prefix="/api/projects/{project_id}", tags=["work-items"])


class IssueResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

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


class IssueListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[IssueResponse]


class IssueCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_id: UUID | None = None
    owner_user_id: UUID | None = None
    title: str = Field(min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=20_000)
    severity: str = Field(default="medium", pattern=r"^(low|medium|high|critical)$")
    root_cause: str | None = Field(default=None, max_length=20_000)
    resolution: str | None = Field(default=None, max_length=20_000)
    target_date: date | None = None

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("description", "root_cause", "resolution", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


class IssueUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_id: UUID | None = None
    owner_user_id: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=20_000)
    severity: str | None = Field(default=None, pattern=r"^(low|medium|high|critical)$")
    root_cause: str | None = Field(default=None, max_length=20_000)
    resolution: str | None = Field(default=None, max_length=20_000)
    target_date: date | None = None

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("description", "root_cause", "resolution", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be supplied")
        for field_name in {"title", "severity"}:
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class IssueTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_status: str = Field(pattern=r"^(analysis|action|verification|closed)$")


class RiskResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    owner_user_id: UUID | None
    title: str
    description: str | None
    status: str
    likelihood: int
    impact: int
    score: int
    mitigation_plan: str | None
    contingency_plan: str | None
    target_date: date | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RiskListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[RiskResponse]


class RiskCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_user_id: UUID | None = None
    title: str = Field(min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=20_000)
    likelihood: int = Field(default=1, ge=1, le=5)
    impact: int = Field(default=1, ge=1, le=5)
    mitigation_plan: str | None = Field(default=None, max_length=20_000)
    contingency_plan: str | None = Field(default=None, max_length=20_000)
    target_date: date | None = None

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator(
        "description",
        "mitigation_plan",
        "contingency_plan",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


class RiskUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_user_id: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=20_000)
    likelihood: int | None = Field(default=None, ge=1, le=5)
    impact: int | None = Field(default=None, ge=1, le=5)
    mitigation_plan: str | None = Field(default=None, max_length=20_000)
    contingency_plan: str | None = Field(default=None, max_length=20_000)
    target_date: date | None = None

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator(
        "description",
        "mitigation_plan",
        "contingency_plan",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be supplied")
        for field_name in {"title", "likelihood", "impact"}:
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class RiskTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_status: str = Field(pattern=r"^(mitigating|watching|closed)$")


def issue_response(record: IssueRecord) -> IssueResponse:
    return IssueResponse.model_validate(record, from_attributes=True)


def risk_response(record: RiskRecord) -> RiskResponse:
    return RiskResponse.model_validate(record, from_attributes=True)


def issue_error(error: Exception) -> HTTPException:
    if isinstance(error, IssueNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ISSUE_NOT_FOUND", "message": "Issue was not found"},
        )
    if isinstance(error, IssueScopeError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "ISSUE_RELATED_OBJECT_NOT_FOUND",
                "message": "Related object was not found",
            },
        )
    if isinstance(error, IssueInvalidTransitionError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ISSUE_INVALID_TRANSITION",
                "message": "Issue transition is not allowed",
            },
        )
    if isinstance(error, IssueTerminalError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "ISSUE_TERMINAL", "message": "Closed Issue cannot be edited"},
        )
    raise error


def risk_error(error: Exception) -> HTTPException:
    if isinstance(error, RiskNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RISK_NOT_FOUND", "message": "Risk was not found"},
        )
    if isinstance(error, RiskScopeError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RISK_RELATED_OBJECT_NOT_FOUND",
                "message": "Related object was not found",
            },
        )
    if isinstance(error, RiskInvalidTransitionError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "RISK_INVALID_TRANSITION", "message": "Risk transition is not allowed"},
        )
    if isinstance(error, RiskTerminalError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "RISK_TERMINAL", "message": "Closed Risk cannot be edited"},
        )
    raise error


def require_access(
    *, engine: Engine, context: AuthContext, project_id: UUID, action: Action
) -> None:
    authorize_project(
        engine=engine,
        context=context,
        project_id=project_id,
        action=action,
    )


@router.get("/issues", response_model=IssueListResponse)
def list_issues(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> IssueListResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_VIEW
    )
    return IssueListResponse(
        items=[
            issue_response(item)
            for item in IssueService(engine).list(
                tenant_id=context.tenant.id, project_id=project_id
            )
        ]
    )


@router.post("/issues", response_model=IssueResponse, status_code=status.HTTP_201_CREATED)
def create_issue(
    project_id: UUID,
    body: IssueCreateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> IssueResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    try:
        record = IssueService(engine).create(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            draft=IssueDraft(
                stage_id=body.stage_id,
                owner_user_id=body.owner_user_id,
                title=body.title,
                description=body.description,
                severity=body.severity,
                root_cause=body.root_cause,
                resolution=body.resolution,
                target_date=body.target_date,
            ),
        )
    except Exception as error:
        raise issue_error(error) from error
    return issue_response(record)


@router.get("/issues/{issue_id}", response_model=IssueResponse)
def get_issue(
    project_id: UUID,
    issue_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> IssueResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_VIEW
    )
    try:
        return issue_response(
            IssueService(engine).get(
                tenant_id=context.tenant.id,
                project_id=project_id,
                issue_id=issue_id,
            )
        )
    except Exception as error:
        raise issue_error(error) from error


@router.patch("/issues/{issue_id}", response_model=IssueResponse)
def update_issue(
    project_id: UUID,
    issue_id: UUID,
    body: IssueUpdateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> IssueResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    try:
        return issue_response(
            IssueService(engine).update(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                issue_id=issue_id,
                patch=IssueUpdate(changes=body.model_dump(exclude_unset=True)),
            )
        )
    except Exception as error:
        raise issue_error(error) from error


@router.post("/issues/{issue_id}/transitions", response_model=IssueResponse)
def transition_issue(
    project_id: UUID,
    issue_id: UUID,
    body: IssueTransitionRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> IssueResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    try:
        return issue_response(
            IssueService(engine).transition(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                issue_id=issue_id,
                to_status=body.to_status,
            )
        )
    except Exception as error:
        raise issue_error(error) from error


@router.get("/risks", response_model=RiskListResponse)
def list_risks(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RiskListResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_VIEW
    )
    return RiskListResponse(
        items=[
            risk_response(item)
            for item in RiskService(engine).list(tenant_id=context.tenant.id, project_id=project_id)
        ]
    )


@router.post("/risks", response_model=RiskResponse, status_code=status.HTTP_201_CREATED)
def create_risk(
    project_id: UUID,
    body: RiskCreateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RiskResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    try:
        record = RiskService(engine).create(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            draft=RiskDraft(
                owner_user_id=body.owner_user_id,
                title=body.title,
                description=body.description,
                likelihood=body.likelihood,
                impact=body.impact,
                mitigation_plan=body.mitigation_plan,
                contingency_plan=body.contingency_plan,
                target_date=body.target_date,
            ),
        )
    except Exception as error:
        raise risk_error(error) from error
    return risk_response(record)


@router.get("/risks/{risk_id}", response_model=RiskResponse)
def get_risk(
    project_id: UUID,
    risk_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RiskResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_VIEW
    )
    try:
        return risk_response(
            RiskService(engine).get(
                tenant_id=context.tenant.id,
                project_id=project_id,
                risk_id=risk_id,
            )
        )
    except Exception as error:
        raise risk_error(error) from error


@router.patch("/risks/{risk_id}", response_model=RiskResponse)
def update_risk(
    project_id: UUID,
    risk_id: UUID,
    body: RiskUpdateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RiskResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    try:
        return risk_response(
            RiskService(engine).update(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                risk_id=risk_id,
                patch=RiskUpdate(changes=body.model_dump(exclude_unset=True)),
            )
        )
    except Exception as error:
        raise risk_error(error) from error


@router.post("/risks/{risk_id}/transitions", response_model=RiskResponse)
def transition_risk(
    project_id: UUID,
    risk_id: UUID,
    body: RiskTransitionRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RiskResponse:
    no_store(response)
    require_access(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    try:
        return risk_response(
            RiskService(engine).transition(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                risk_id=risk_id,
                to_status=body.to_status,
            )
        )
    except Exception as error:
        raise risk_error(error) from error
