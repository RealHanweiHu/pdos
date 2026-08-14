"""Project-scoped Complaint HTTP boundary."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.api.work_items import authorize_project
from app.auth.repository import AuthContext
from app.auth.roles import Action, Role
from app.db.engine import get_engine
from app.domain.complaints import (
    ComplaintDraft,
    ComplaintInvalidTransitionError,
    ComplaintNcrGateError,
    ComplaintNotFoundError,
    ComplaintRecord,
    ComplaintResolutionError,
    ComplaintScopeError,
    ComplaintService,
    ComplaintTimeError,
)
from app.domain.nonconformance import (
    NcrDraft,
    NcrInvalidTransitionError,
    NcrNotFoundError,
    NcrRecord,
    NonconformanceService,
)

router = APIRouter(prefix="/api/projects/{project_id}/quality", tags=["quality"])


class ComplaintResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    customer_id: UUID | None
    reported_by_user_id: UUID
    owner_user_id: UUID
    closed_by_user_id: UUID | None
    code: str
    title: str
    description: str
    source: str
    severity: str
    status: str
    occurred_at: datetime
    reported_at: datetime
    customer_reference: str | None
    affected_scope: str | None
    document_refs: list[UUID]
    resolution_summary: str | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ComplaintListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[ComplaintResponse]


class ComplaintCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: UUID | None = None
    owner_user_id: UUID
    title: str = Field(min_length=1, max_length=512)
    description: str = Field(min_length=1, max_length=20_000)
    source: str = Field(pattern=r"^(customer|field|rma|internal)$")
    severity: str = Field(pattern=r"^(critical|high|medium|low)$")
    occurred_at: datetime
    customer_reference: str | None = Field(default=None, max_length=128)
    affected_scope: str | None = Field(default=None, max_length=20_000)
    document_refs: list[UUID] = Field(default_factory=list, max_length=100)

    @field_validator("title", "description", mode="before")
    @classmethod
    def normalize_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("customer_reference", "affected_scope", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("occurred_at")
    @classmethod
    def require_timezone_and_past(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        if value.astimezone(UTC) > datetime.now(UTC):
            raise ValueError("occurred_at cannot be in the future")
        return value


class NcrResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    complaint_id: UUID
    owner_user_id: UUID
    created_by_user_id: UUID
    preventive_disposition_approved_by_user_id: UUID | None
    closed_by_user_id: UUID | None
    code: str
    nonconformity: str
    requirement_reference: str
    severity: str
    status: str
    target_date: date
    containment_action: str | None
    containment_completed_at: datetime | None
    affected_quantity: int | None
    affected_scope: str | None
    preventive_not_applicable_reason: str | None
    preventive_disposition_approved_at: datetime | None
    effectiveness_criteria: str | None
    observation_due_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class NcrCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_user_id: UUID
    nonconformity: str = Field(min_length=1, max_length=20_000)
    requirement_reference: str = Field(min_length=1, max_length=20_000)
    severity: str = Field(pattern=r"^(critical|high|medium|low)$")
    target_date: date
    affected_quantity: int | None = Field(default=None, ge=0)
    affected_scope: str | None = Field(default=None, max_length=20_000)

    @field_validator("nonconformity", "requirement_reference", mode="before")
    @classmethod
    def normalize_ncr_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("affected_scope", mode="before")
    @classmethod
    def normalize_ncr_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("target_date")
    @classmethod
    def target_date_not_past(cls, value: date) -> date:
        if value < date.today():
            raise ValueError("target_date cannot be in the past")
        return value


class NcrListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[NcrResponse]


class ComplaintTriageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    complaint: ComplaintResponse
    ncr: NcrResponse


class ComplaintTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_status: str = Field(pattern=r"^(investigating|resolved|closed)$")
    resolution_summary: str | None = Field(default=None, max_length=20_000)

    @field_validator("resolution_summary", mode="before")
    @classmethod
    def normalize_resolution(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


def complaint_response(record: ComplaintRecord) -> ComplaintResponse:
    return ComplaintResponse.model_validate(record, from_attributes=True)


def ncr_response(record: NcrRecord) -> NcrResponse:
    return NcrResponse.model_validate(record, from_attributes=True)


def complaint_error(error: Exception) -> HTTPException:
    if isinstance(error, ComplaintNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "COMPLAINT_NOT_FOUND", "message": "Complaint was not found"},
        )
    if isinstance(error, ComplaintScopeError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "QUALITY_RELATED_OBJECT_NOT_FOUND",
                "message": "Related object was not found",
            },
        )
    if isinstance(error, ComplaintTimeError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "COMPLAINT_TIME_INVALID",
                "message": "Occurrence time cannot be after report time",
            },
        )
    if isinstance(error, ComplaintInvalidTransitionError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "QUALITY_INVALID_TRANSITION",
                "message": "Quality record transition is not allowed",
            },
        )
    if isinstance(error, ComplaintNcrGateError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "COMPLAINT_NCR_GATE_NOT_READY",
                "message": "All NCRs must be closed before resolution",
            },
        )
    if isinstance(error, ComplaintResolutionError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "COMPLAINT_RESOLUTION_INVALID",
                "message": "Complaint resolution is invalid",
            },
        )
    if isinstance(error, NcrNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NCR_NOT_FOUND", "message": "NCR was not found"},
        )
    if isinstance(error, NcrInvalidTransitionError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "QUALITY_INVALID_TRANSITION",
                "message": "Quality record transition is not allowed",
            },
        )
    raise error


@router.get("/complaints", response_model=ComplaintListResponse)
def list_complaints(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ComplaintListResponse:
    no_store(response)
    authorize_project(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.QUALITY_VIEW,
    )
    return ComplaintListResponse(
        items=[
            complaint_response(record)
            for record in ComplaintService(engine).list(
                tenant_id=context.tenant.id,
                project_id=project_id,
            )
        ]
    )


@router.post(
    "/complaints",
    response_model=ComplaintResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_complaint(
    project_id: UUID,
    body: ComplaintCreateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ComplaintResponse:
    no_store(response)
    authorize_project(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.COMPLAINT_CREATE,
    )
    try:
        record = ComplaintService(engine).create(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            draft=ComplaintDraft(
                customer_id=body.customer_id,
                owner_user_id=body.owner_user_id,
                title=body.title,
                description=body.description,
                source=body.source,
                severity=body.severity,
                occurred_at=body.occurred_at,
                customer_reference=body.customer_reference,
                affected_scope=body.affected_scope,
                document_refs=body.document_refs,
            ),
        )
    except Exception as error:
        raise complaint_error(error) from error
    return complaint_response(record)


@router.get("/complaints/{complaint_id}", response_model=ComplaintResponse)
def get_complaint(
    project_id: UUID,
    complaint_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ComplaintResponse:
    no_store(response)
    authorize_project(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.QUALITY_VIEW,
    )
    try:
        return complaint_response(
            ComplaintService(engine).get(
                tenant_id=context.tenant.id,
                project_id=project_id,
                complaint_id=complaint_id,
            )
        )
    except Exception as error:
        raise complaint_error(error) from error


@router.post(
    "/complaints/{complaint_id}/triage",
    response_model=ComplaintTriageResponse,
    status_code=status.HTTP_201_CREATED,
)
def triage_complaint(
    project_id: UUID,
    complaint_id: UUID,
    body: NcrCreateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ComplaintTriageResponse:
    no_store(response)
    authorize_project(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.CAPA_MANAGE,
    )
    try:
        result = NonconformanceService(engine).triage(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            complaint_id=complaint_id,
            draft=NcrDraft(
                owner_user_id=body.owner_user_id,
                nonconformity=body.nonconformity,
                requirement_reference=body.requirement_reference,
                severity=body.severity,
                target_date=body.target_date,
                affected_quantity=body.affected_quantity,
                affected_scope=body.affected_scope,
            ),
        )
    except Exception as error:
        raise complaint_error(error) from error
    return ComplaintTriageResponse(
        complaint=complaint_response(result.complaint),
        ncr=ncr_response(result.ncr),
    )


@router.post("/complaints/{complaint_id}/transitions", response_model=ComplaintResponse)
def transition_complaint(
    project_id: UUID,
    complaint_id: UUID,
    body: ComplaintTransitionRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ComplaintResponse:
    no_store(response)
    authorize_project(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.CAPA_MANAGE,
    )
    if body.to_status == "closed" and context.user.role != Role.QUALITY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "CAPA_QUALITY_ROLE_REQUIRED",
                "message": "This action requires the Quality role",
            },
        )
    try:
        return complaint_response(
            ComplaintService(engine).transition(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                complaint_id=complaint_id,
                to_status=body.to_status,
                resolution_summary=body.resolution_summary,
            )
        )
    except Exception as error:
        raise complaint_error(error) from error


@router.get("/complaints/{complaint_id}/ncrs", response_model=NcrListResponse)
def list_complaint_ncrs(
    project_id: UUID,
    complaint_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> NcrListResponse:
    no_store(response)
    authorize_project(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.QUALITY_VIEW,
    )
    try:
        return NcrListResponse(
            items=[
                ncr_response(record)
                for record in NonconformanceService(engine).list_for_complaint(
                    tenant_id=context.tenant.id,
                    project_id=project_id,
                    complaint_id=complaint_id,
                )
            ]
        )
    except Exception as error:
        raise complaint_error(error) from error
