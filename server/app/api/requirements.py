"""Tenant-bound Requirement pool HTTP boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Engine, select

from app.api.auth import current_context, no_store
from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.db.engine import get_engine
from app.db.schema import tables
from app.domain.requirements import (
    CrmRequirementAlreadyReviewedError,
    CrmRequirementIntakeNotFoundError,
    CrmRequirementReviewRequiredError,
    CustomerCodeConflictError,
    CustomerCreate,
    CustomerNotFoundError,
    CustomerRecord,
    CustomerService,
    RequirementCodeConflictError,
    RequirementCreate,
    RequirementNotFoundError,
    RequirementRecord,
    RequirementService,
    RequirementUpdate,
)

router = APIRouter(tags=["requirements"])


class CustomerSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    code: str
    name: str
    status: str


class CustomerListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[CustomerSummaryResponse]


class CustomerCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=256)

    @field_validator("code", "name", mode="before")
    @classmethod
    def normalize_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class RequirementCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=20_000)
    source: str | None = Field(default="manual", max_length=64)
    priority: str = Field(default="medium", pattern=r"^(low|medium|high|critical)$")
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=100)
    customer_id: UUID | None = None

    @field_validator("code", "title", mode="before")
    @classmethod
    def normalize_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("description", "source", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("acceptance_criteria")
    @classmethod
    def validate_acceptance_criteria(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value or len(value) > 512 for value in normalized):
            raise ValueError("acceptance criteria must contain nonblank bounded text")
        return normalized


class RequirementResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    code: str
    title: str
    description: str | None
    source: str | None
    status: str
    priority: str
    acceptance_criteria: list[str]
    customer: CustomerSummaryResponse | None
    created_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime


class RequirementUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, min_length=1, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=20_000)
    # source is intake provenance and immutable after creation: rewriting it would
    # let a PATCH strip the "crm" marker that gates the mandatory human review.
    status: str | None = Field(
        default=None,
        pattern=r"^(draft|proposed|approved|rejected)$",
    )
    priority: str | None = Field(
        default=None,
        pattern=r"^(low|medium|high|critical)$",
    )
    acceptance_criteria: list[str] | None = Field(default=None, max_length=100)
    customer_id: UUID | None = None

    @field_validator("code", "title", mode="before")
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

    @field_validator("acceptance_criteria")
    @classmethod
    def validate_acceptance_criteria(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        normalized = [value.strip() for value in values]
        if any(not value or len(value) > 512 for value in normalized):
            raise ValueError("acceptance criteria must contain nonblank bounded text")
        return normalized

    @model_validator(mode="after")
    def require_nonempty_valid_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be supplied")
        for field_name in {"code", "title", "status", "priority", "acceptance_criteria"}:
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class RequirementListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[RequirementResponse]


class CrmIntakeReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: Literal["REVIEW_CONFIRMED"]
    decision: Literal["establish", "reject"]
    rationale: str = Field(min_length=1, max_length=20_000)

    @field_validator("rationale", mode="before")
    @classmethod
    def normalize_rationale(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


def customer_response(customer: CustomerRecord | None) -> CustomerSummaryResponse | None:
    if customer is None:
        return None
    return CustomerSummaryResponse(
        id=customer.id,
        code=customer.code,
        name=customer.name,
        status=customer.status,
    )


def requirement_response(record: RequirementRecord) -> RequirementResponse:
    return RequirementResponse(
        id=record.id,
        code=record.code,
        title=record.title,
        description=record.description,
        source=record.source,
        status=record.status,
        priority=record.priority,
        acceptance_criteria=record.acceptance_criteria,
        customer=customer_response(record.customer),
        created_by_user_id=record.created_by_user_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def require_requirement_action(context: AuthContext, action: Action) -> None:
    if not is_allowed(context.user.role, action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "OBJECT_PERMISSION_DENIED",
                "message": "The requested requirement action is not permitted",
            },
        )


@router.get("/api/customers", response_model=CustomerListResponse)
def list_customers(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> CustomerListResponse:
    require_requirement_action(context, Action.REQUIREMENT_VIEW)
    statement = (
        select(
            tables.customers.c.id,
            tables.customers.c.code,
            tables.customers.c.name,
            tables.customers.c.status,
        )
        .where(tables.customers.c.tenant_id == context.tenant.id)
        .order_by(tables.customers.c.code, tables.customers.c.id)
    )
    with engine.connect() as connection:
        customers = [
            CustomerSummaryResponse.model_validate(row)
            for row in connection.execute(statement).mappings()
        ]
    no_store(response)
    return CustomerListResponse(items=customers)


@router.post(
    "/api/customers",
    response_model=CustomerSummaryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_customer(
    payload: CustomerCreateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> CustomerSummaryResponse:
    require_requirement_action(context, Action.REQUIREMENT_CREATE)
    try:
        record = CustomerService(engine).create(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            draft=CustomerCreate(code=payload.code, name=payload.name),
        )
    except CustomerCodeConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CUSTOMER_CODE_CONFLICT",
                "message": "Customer code already exists",
            },
        ) from error
    no_store(response)
    customer = customer_response(record)
    assert customer is not None
    return customer


@router.post(
    "/api/requirements",
    response_model=RequirementResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_requirement(
    payload: RequirementCreateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RequirementResponse:
    require_requirement_action(context, Action.REQUIREMENT_CREATE)
    try:
        record = RequirementService(engine).create(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            draft=RequirementCreate(**payload.model_dump()),
        )
    except CustomerNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CUSTOMER_NOT_FOUND", "message": "Customer was not found"},
        ) from error
    except RequirementCodeConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "REQUIREMENT_CODE_CONFLICT",
                "message": "Requirement code already exists",
            },
        ) from error
    no_store(response)
    return requirement_response(record)


@router.post(
    "/api/requirements/{requirement_id}/review-crm-intake",
    response_model=RequirementResponse,
)
def review_crm_intake(
    requirement_id: UUID,
    payload: CrmIntakeReviewRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RequirementResponse:
    require_requirement_action(context, Action.REQUIREMENT_EDIT)
    try:
        record = RequirementService(engine).review_crm_intake(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            requirement_id=requirement_id,
            decision=payload.decision,
            rationale=payload.rationale,
        )
    except CrmRequirementIntakeNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CRM_INTAKE_NOT_FOUND", "message": "CRM intake was not found"},
        ) from error
    except CrmRequirementAlreadyReviewedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CRM_REQUIREMENT_ALREADY_REVIEWED",
                "message": "CRM intake was already reviewed",
            },
        ) from error
    no_store(response)
    return requirement_response(record)


@router.get("/api/requirements", response_model=RequirementListResponse)
def list_requirements(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RequirementListResponse:
    require_requirement_action(context, Action.REQUIREMENT_VIEW)
    records = RequirementService(engine).list(tenant_id=context.tenant.id)
    no_store(response)
    return RequirementListResponse(items=[requirement_response(record) for record in records])


@router.get("/api/requirements/{requirement_id}", response_model=RequirementResponse)
def get_requirement(
    requirement_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RequirementResponse:
    require_requirement_action(context, Action.REQUIREMENT_VIEW)
    try:
        record = RequirementService(engine).get(
            tenant_id=context.tenant.id,
            requirement_id=requirement_id,
        )
    except RequirementNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "REQUIREMENT_NOT_FOUND", "message": "Requirement was not found"},
        ) from error
    no_store(response)
    return requirement_response(record)


@router.patch("/api/requirements/{requirement_id}", response_model=RequirementResponse)
def update_requirement(
    requirement_id: UUID,
    payload: RequirementUpdateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RequirementResponse:
    require_requirement_action(context, Action.REQUIREMENT_EDIT)
    try:
        record = RequirementService(engine).update(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            requirement_id=requirement_id,
            patch=RequirementUpdate(changes=payload.model_dump(exclude_unset=True)),
        )
    except RequirementNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "REQUIREMENT_NOT_FOUND", "message": "Requirement was not found"},
        ) from error
    except CustomerNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CUSTOMER_NOT_FOUND", "message": "Customer was not found"},
        ) from error
    except RequirementCodeConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "REQUIREMENT_CODE_CONFLICT",
                "message": "Requirement code already exists",
            },
        ) from error
    except CrmRequirementReviewRequiredError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CRM_REQUIREMENT_REVIEW_REQUIRED",
                "message": "CRM drafts require the explicit review action",
            },
        ) from error
    no_store(response)
    return requirement_response(record)
