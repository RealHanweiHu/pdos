"""Project resource allocation and cost register HTTP boundary."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.api.work_items import authorize_project
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.engine import get_engine
from app.domain.resources_costs import (
    CostRecord,
    RegisterDateOrderError,
    RegisterInvalidTransitionError,
    RegisterLockedError,
    RegisterNotFoundError,
    RegisterScopeError,
    ResourceCostService,
    ResourceRecord,
)

router = APIRouter(prefix="/api/projects/{project_id}", tags=["resources-costs"])

# Costs carry commercial figures, so only roles that may edit the Project (owner, admin,
# project manager) can read or change them. Resources are visible to every internal member.
COST_ACTION = Action.PROJECT_EDIT
RESOURCE_VIEW_ACTION = Action.WORK_ITEM_VIEW
RESOURCE_EDIT_ACTION = Action.PROJECT_EDIT

CostType = Literal["material", "labor", "tooling", "logistics", "other"]
ResourceType = Literal["person", "equipment", "facility", "capability"]
Amount = Annotated[Decimal, Field(ge=0, le=Decimal("999999999999"), decimal_places=2)]
Allocation = Annotated[Decimal, Field(gt=0, le=100, decimal_places=2)]


def _optional_text(value: object) -> object:
    if isinstance(value, str):
        return value.strip() or None
    return value


class CostResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

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


class CostListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[CostResponse]


class CostCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cost_type: CostType
    amount: Amount
    currency: str = Field(default="CNY", pattern=r"^[A-Z]{3}$")
    incurred_on: date | None = None
    description: str | None = Field(default=None, max_length=2_000)

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: object) -> object:
        return _optional_text(value)


class CostUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cost_type: CostType | None = None
    amount: Amount | None = None
    incurred_on: date | None = None
    description: str | None = Field(default=None, max_length=2_000)

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: object) -> object:
        return _optional_text(value)

    @model_validator(mode="after")
    def require_fields(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be supplied")
        for name in ("cost_type", "amount"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class CostTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_status: Literal["approved", "actual"]


class ResourceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

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
    assignee_active_allocation_percent: Decimal | None
    created_at: datetime
    updated_at: datetime


class ResourceListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[ResourceResponse]


class ResourceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=256)
    resource_type: ResourceType
    assigned_user_id: UUID | None = None
    allocation_percent: Allocation = Decimal(100)
    start_date: date | None = None
    end_date: date | None = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ResourceUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=256)
    assigned_user_id: UUID | None = None
    allocation_percent: Allocation | None = None
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def require_fields(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be supplied")
        for name in ("name", "allocation_percent"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class ResourceTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_status: Literal["active", "released"]


def cost_response(record: CostRecord) -> CostResponse:
    return CostResponse.model_validate(record, from_attributes=True)


def resource_response(record: ResourceRecord) -> ResourceResponse:
    return ResourceResponse.model_validate(record, from_attributes=True)


def register_error(error: Exception) -> HTTPException:
    if isinstance(error, RegisterNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "REGISTER_RECORD_NOT_FOUND", "message": "Record was not found"},
        )
    if isinstance(error, RegisterScopeError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "REGISTER_ASSIGNEE_NOT_MEMBER",
                "message": "Assignee must be an internal project member",
            },
        )
    if isinstance(error, RegisterLockedError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "REGISTER_RECORD_LOCKED", "message": "Record can no longer be edited"},
        )
    if isinstance(error, RegisterInvalidTransitionError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "REGISTER_INVALID_TRANSITION", "message": "Transition is invalid"},
        )
    if isinstance(error, RegisterDateOrderError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "REGISTER_DATE_ORDER", "message": "End date precedes start date"},
        )
    raise error


Context = Annotated[AuthContext, Depends(current_context)]
EngineDep = Annotated[Engine, Depends(get_engine)]


@router.get("/costs", response_model=CostListResponse)
def list_costs(
    project_id: UUID, response: Response, context: Context, engine: EngineDep
) -> CostListResponse:
    no_store(response)
    authorize_project(engine=engine, context=context, project_id=project_id, action=COST_ACTION)
    return CostListResponse(
        items=[
            cost_response(record)
            for record in ResourceCostService(engine).list_costs(
                tenant_id=context.tenant.id, project_id=project_id
            )
        ]
    )


@router.post("/costs", response_model=CostResponse, status_code=status.HTTP_201_CREATED)
def create_cost(
    project_id: UUID,
    body: CostCreateRequest,
    response: Response,
    context: Context,
    engine: EngineDep,
) -> CostResponse:
    no_store(response)
    authorize_project(engine=engine, context=context, project_id=project_id, action=COST_ACTION)
    try:
        return cost_response(
            ResourceCostService(engine).create_cost(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                **body.model_dump(),
            )
        )
    except Exception as error:
        raise register_error(error) from error


@router.patch("/costs/{cost_id}", response_model=CostResponse)
def update_cost(
    project_id: UUID,
    cost_id: UUID,
    body: CostUpdateRequest,
    response: Response,
    context: Context,
    engine: EngineDep,
) -> CostResponse:
    no_store(response)
    authorize_project(engine=engine, context=context, project_id=project_id, action=COST_ACTION)
    try:
        return cost_response(
            ResourceCostService(engine).update_cost(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                cost_id=cost_id,
                changes=body.model_dump(exclude_unset=True),
            )
        )
    except Exception as error:
        raise register_error(error) from error


@router.post("/costs/{cost_id}/transitions", response_model=CostResponse)
def transition_cost(
    project_id: UUID,
    cost_id: UUID,
    body: CostTransitionRequest,
    response: Response,
    context: Context,
    engine: EngineDep,
) -> CostResponse:
    no_store(response)
    authorize_project(engine=engine, context=context, project_id=project_id, action=COST_ACTION)
    try:
        return cost_response(
            ResourceCostService(engine).transition_cost(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                cost_id=cost_id,
                to_status=body.to_status,
            )
        )
    except Exception as error:
        raise register_error(error) from error


@router.get("/resources", response_model=ResourceListResponse)
def list_resources(
    project_id: UUID, response: Response, context: Context, engine: EngineDep
) -> ResourceListResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=RESOURCE_VIEW_ACTION
    )
    return ResourceListResponse(
        items=[
            resource_response(record)
            for record in ResourceCostService(engine).list_resources(
                tenant_id=context.tenant.id, project_id=project_id
            )
        ]
    )


@router.post("/resources", response_model=ResourceResponse, status_code=status.HTTP_201_CREATED)
def create_resource(
    project_id: UUID,
    body: ResourceCreateRequest,
    response: Response,
    context: Context,
    engine: EngineDep,
) -> ResourceResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=RESOURCE_EDIT_ACTION
    )
    try:
        return resource_response(
            ResourceCostService(engine).create_resource(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                **body.model_dump(),
            )
        )
    except Exception as error:
        raise register_error(error) from error


@router.patch("/resources/{resource_id}", response_model=ResourceResponse)
def update_resource(
    project_id: UUID,
    resource_id: UUID,
    body: ResourceUpdateRequest,
    response: Response,
    context: Context,
    engine: EngineDep,
) -> ResourceResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=RESOURCE_EDIT_ACTION
    )
    try:
        return resource_response(
            ResourceCostService(engine).update_resource(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                resource_id=resource_id,
                changes=body.model_dump(exclude_unset=True),
            )
        )
    except Exception as error:
        raise register_error(error) from error


@router.post("/resources/{resource_id}/transitions", response_model=ResourceResponse)
def transition_resource(
    project_id: UUID,
    resource_id: UUID,
    body: ResourceTransitionRequest,
    response: Response,
    context: Context,
    engine: EngineDep,
) -> ResourceResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=RESOURCE_EDIT_ACTION
    )
    try:
        return resource_response(
            ResourceCostService(engine).transition_resource(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                resource_id=resource_id,
                to_status=body.to_status,
            )
        )
    except Exception as error:
        raise register_error(error) from error
