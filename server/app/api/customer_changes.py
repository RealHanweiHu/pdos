"""Customer change request HTTP boundary (vNext V1-B8, G18).

Kept on its own router and prefix so the customer track never shares a URL
space with the engineering ECR track.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.api.work_items import authorize_project
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.engine import get_engine
from app.domain.customer_changes import (
    CustomerChangeFourEyesError,
    CustomerChangeNotFoundError,
    CustomerChangeRecord,
    CustomerChangeScopeError,
    CustomerChangeService,
    CustomerChangeTransitionError,
)

router = APIRouter(prefix="/api/projects/{project_id}/customer-changes", tags=["customer-changes"])


def customer_change_error(error: Exception) -> HTTPException:
    if isinstance(error, CustomerChangeNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "CUSTOMER_CHANGE_NOT_FOUND",
                "message": "Customer change request was not found",
            },
        )
    if isinstance(error, CustomerChangeScopeError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "CUSTOMER_CHANGE_RELATED_OBJECT_NOT_FOUND",
                "message": "Related object was not found",
            },
        )
    if isinstance(error, CustomerChangeFourEyesError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "CUSTOMER_CHANGE_FOUR_EYES",
                "message": "The quote drafter cannot approve their own reply",
            },
        )
    if isinstance(error, CustomerChangeTransitionError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CUSTOMER_CHANGE_INVALID_TRANSITION",
                "message": "Customer change step is not allowed from this state",
            },
        )
    raise error


class CustomerChangeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    customer_id: UUID
    requirement_id: UUID
    engineering_change_request_id: UUID | None
    code: str
    title: str
    description: str | None
    status: str
    impact_analysis: dict[str, Any] | None
    quote_note: str | None
    lead_time_days: int | None
    customer_decision_note: str | None
    received_by_user_id: UUID
    analyzed_by_user_id: UUID | None
    reply_drafted_by_user_id: UUID | None
    reply_approved_by_user_id: UUID | None
    decision_recorded_by_user_id: UUID | None
    received_at: datetime
    analyzed_at: datetime | None
    reply_drafted_at: datetime | None
    reply_approved_at: datetime | None
    decided_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CustomerChangeListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[CustomerChangeResponse]


class CustomerChangeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: UUID
    requirement_id: UUID
    code: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=20_000)

    @field_validator("code", "title", mode="before")
    @classmethod
    def normalize(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ReplyDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote_note: str = Field(min_length=1, max_length=20_000)
    lead_time_days: int = Field(ge=0, le=3650)


class CustomerDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool
    note: str | None = Field(default=None, max_length=20_000)


class LinkEcrRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engineering_change_request_id: UUID


def change_response(record: CustomerChangeRecord) -> CustomerChangeResponse:
    return CustomerChangeResponse(**record.__dict__)


def _authorize(engine: Engine, context: AuthContext, project_id: UUID, action: Action) -> None:
    authorize_project(engine=engine, context=context, project_id=project_id, action=action)


@router.get("", response_model=CustomerChangeListResponse)
def list_customer_changes(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> CustomerChangeListResponse:
    no_store(response)
    _authorize(engine, context, project_id, Action.CHANGE_VIEW)
    return CustomerChangeListResponse(
        items=[
            change_response(record)
            for record in CustomerChangeService(engine).list(
                tenant_id=context.tenant.id, project_id=project_id
            )
        ]
    )


@router.post("", response_model=CustomerChangeResponse, status_code=status.HTTP_201_CREATED)
def create_customer_change(
    project_id: UUID,
    body: CustomerChangeCreateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> CustomerChangeResponse:
    no_store(response)
    _authorize(engine, context, project_id, Action.CHANGE_EDIT)
    try:
        return change_response(
            CustomerChangeService(engine).create(
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                customer_id=body.customer_id,
                requirement_id=body.requirement_id,
                code=body.code,
                title=body.title,
                description=body.description,
            )
        )
    except Exception as error:
        raise customer_change_error(error) from error


@router.post("/{change_id}/analyze", response_model=CustomerChangeResponse)
def analyze_customer_change(
    project_id: UUID,
    change_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> CustomerChangeResponse:
    no_store(response)
    _authorize(engine, context, project_id, Action.CHANGE_EDIT)
    try:
        return change_response(
            CustomerChangeService(engine).analyze(
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                change_id=change_id,
            )
        )
    except Exception as error:
        raise customer_change_error(error) from error


@router.post("/{change_id}/reply", response_model=CustomerChangeResponse)
def draft_customer_reply(
    project_id: UUID,
    change_id: UUID,
    body: ReplyDraftRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> CustomerChangeResponse:
    no_store(response)
    _authorize(engine, context, project_id, Action.CHANGE_EDIT)
    try:
        return change_response(
            CustomerChangeService(engine).draft_reply(
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                change_id=change_id,
                quote_note=body.quote_note,
                lead_time_days=body.lead_time_days,
            )
        )
    except Exception as error:
        raise customer_change_error(error) from error


@router.post("/{change_id}/reply/approve", response_model=CustomerChangeResponse)
def approve_customer_reply(
    project_id: UUID,
    change_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> CustomerChangeResponse:
    """Hard gate: approving a price and a date for outward use (CHANGE_APPROVE)."""
    no_store(response)
    _authorize(engine, context, project_id, Action.CHANGE_APPROVE)
    try:
        return change_response(
            CustomerChangeService(engine).approve_reply(
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                change_id=change_id,
            )
        )
    except Exception as error:
        raise customer_change_error(error) from error


@router.post("/{change_id}/customer-decision", response_model=CustomerChangeResponse)
def record_customer_decision(
    project_id: UUID,
    change_id: UUID,
    body: CustomerDecisionRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> CustomerChangeResponse:
    no_store(response)
    _authorize(engine, context, project_id, Action.CHANGE_EDIT)
    try:
        return change_response(
            CustomerChangeService(engine).record_customer_decision(
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                change_id=change_id,
                accepted=body.accepted,
                note=body.note,
            )
        )
    except Exception as error:
        raise customer_change_error(error) from error


@router.post("/{change_id}/engineering-change", response_model=CustomerChangeResponse)
def link_engineering_change(
    project_id: UUID,
    change_id: UUID,
    body: LinkEcrRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> CustomerChangeResponse:
    no_store(response)
    _authorize(engine, context, project_id, Action.CHANGE_EDIT)
    try:
        return change_response(
            CustomerChangeService(engine).link_engineering_change(
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                change_id=change_id,
                engineering_change_request_id=body.engineering_change_request_id,
            )
        )
    except Exception as error:
        raise customer_change_error(error) from error
