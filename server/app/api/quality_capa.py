"""NCR, Root Cause, and CAPA Action HTTP boundaries."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.api.quality_complaints import NcrResponse, complaint_error, ncr_response
from app.api.work_items import authorize_project
from app.auth.repository import AuthContext
from app.auth.roles import Action, Role
from app.db.engine import get_engine
from app.domain.capa_actions import (
    CapaActionDraft,
    CapaActionNotFoundError,
    CapaActionOwnershipError,
    CapaActionRecord,
    CapaActionService,
    CapaActionTransitionError,
)
from app.domain.effectiveness import (
    EffectivenessFourEyesError,
    EffectivenessObservationPendingError,
    EffectivenessReviewDraft,
    EffectivenessReviewRecord,
    EffectivenessService,
)
from app.domain.nonconformance import (
    NcrActionGateError,
    NcrContainmentGateError,
    NcrEffectivenessGateError,
    NcrInvalidTransitionError,
    NcrObservationPlanError,
    NcrPreventiveDispositionError,
    NcrRepeatActionGateError,
    NcrRootCauseGateError,
    NonconformanceService,
)
from app.domain.quality_evidence import QualityEvidenceError
from app.domain.root_causes import (
    RootCauseDraft,
    RootCauseFourEyesError,
    RootCauseNotFoundError,
    RootCauseRecord,
    RootCauseService,
    RootCauseTerminalError,
)

router = APIRouter(prefix="/api/projects/{project_id}/quality", tags=["quality"])


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["document", "event"]
    reference: str = Field(min_length=1, max_length=256)

    @field_validator("reference", mode="before")
    @classmethod
    def normalize_reference(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class NcrTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_status: str = Field(pattern=r"^(containment|root_cause|action|verification|closed)$")
    containment_action: str | None = Field(default=None, max_length=20_000)
    effectiveness_criteria: str | None = Field(default=None, max_length=20_000)
    observation_due_at: datetime | None = None

    @field_validator("containment_action", "effectiveness_criteria", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("observation_due_at")
    @classmethod
    def observation_requires_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("observation_due_at must include a timezone")
        return value


class RootCauseResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    ncr_id: UUID
    analyst_user_id: UUID
    approved_by_user_id: UUID | None
    version: int
    method: str
    analysis: str
    root_cause: str
    evidence_refs: list[dict[str, object]]
    status: str
    approved_at: datetime | None
    superseded_at: datetime | None
    created_at: datetime


class RootCauseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: str = Field(pattern=r"^(5why|fishbone|8d|other)$")
    analysis: str = Field(min_length=1, max_length=20_000)
    root_cause: str = Field(min_length=1, max_length=20_000)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list, max_length=100)

    @field_validator("analysis", "root_cause", mode="before")
    @classmethod
    def normalize_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class CapaActionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    ncr_id: UUID
    owner_user_id: UUID
    created_by_user_id: UUID
    action_type: str
    description: str
    due_date: date
    status: str
    completion_summary: str | None
    evidence_refs: list[dict[str, object]]
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CapaActionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_user_id: UUID
    action_type: str = Field(pattern=r"^(corrective|preventive)$")
    description: str = Field(min_length=1, max_length=20_000)
    due_date: date

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("due_date")
    @classmethod
    def due_date_not_past(cls, value: date) -> date:
        if value < date.today():
            raise ValueError("due_date cannot be in the past")
        return value


class CapaActionTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_status: str = Field(pattern=r"^(in_progress|completed)$")
    completion_summary: str | None = Field(default=None, max_length=20_000)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list, max_length=100)

    @field_validator("completion_summary", mode="before")
    @classmethod
    def normalize_completion(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


class EffectivenessReviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    ncr_id: UUID
    reviewer_user_id: UUID
    review_number: int
    criteria: str
    observation_due_at: datetime
    actual_result: str
    result: str
    evidence_refs: list[dict[str, object]]
    reviewed_at: datetime
    created_at: datetime


class EffectivenessReviewCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actual_result: str = Field(min_length=1, max_length=20_000)
    result: str = Field(pattern=r"^(effective|ineffective)$")
    evidence_refs: list[EvidenceReference] = Field(min_length=1, max_length=100)

    @field_validator("actual_result", mode="before")
    @classmethod
    def normalize_actual_result(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class EffectivenessReviewResultResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    review: EffectivenessReviewResponse
    ncr: NcrResponse


class PreventiveNotApplicableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=20_000)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class NcrDetailResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    ncr: NcrResponse
    root_causes: list[RootCauseResponse]
    actions: list[CapaActionResponse]
    effectiveness_reviews: list[EffectivenessReviewResponse]


def root_cause_response(record: RootCauseRecord) -> RootCauseResponse:
    return RootCauseResponse.model_validate(record, from_attributes=True)


def capa_action_response(record: CapaActionRecord) -> CapaActionResponse:
    return CapaActionResponse.model_validate(record, from_attributes=True)


def effectiveness_response(record: EffectivenessReviewRecord) -> EffectivenessReviewResponse:
    return EffectivenessReviewResponse.model_validate(record, from_attributes=True)


def evidence_payload(refs: list[EvidenceReference]) -> list[dict[str, object]]:
    return [ref.model_dump() for ref in refs]


def require_quality_role(context: AuthContext) -> None:
    if context.user.role != Role.QUALITY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "CAPA_QUALITY_ROLE_REQUIRED",
                "message": "This action requires the Quality role",
            },
        )


def capa_error(error: Exception) -> HTTPException:
    if isinstance(error, NcrContainmentGateError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "NCR_CONTAINMENT_NOT_READY", "message": "Containment is incomplete"},
        )
    if isinstance(error, NcrRootCauseGateError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "NCR_ROOT_CAUSE_NOT_APPROVED", "message": "Root cause is not approved"},
        )
    if isinstance(error, NcrActionGateError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "CAPA_ACTION_GATE_NOT_READY", "message": "CAPA actions are incomplete"},
        )
    if isinstance(error, NcrObservationPlanError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CAPA_OBSERVATION_PLAN_INVALID",
                "message": "Effectiveness criteria or observation timing is invalid",
            },
        )
    if isinstance(error, NcrRepeatActionGateError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CAPA_NEW_ACTION_REQUIRED",
                "message": "A failed review requires a new follow-up action",
            },
        )
    if isinstance(error, NcrEffectivenessGateError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CAPA_EFFECTIVENESS_NOT_PROVEN",
                "message": "Latest effectiveness review is not effective",
            },
        )
    if isinstance(error, NcrPreventiveDispositionError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CAPA_PREVENTIVE_DISPOSITION_INVALID",
                "message": "Preventive disposition cannot be approved",
            },
        )
    if isinstance(error, NcrInvalidTransitionError):
        return complaint_error(error)
    if isinstance(error, RootCauseNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ROOT_CAUSE_NOT_FOUND", "message": "Root cause was not found"},
        )
    if isinstance(error, RootCauseFourEyesError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ROOT_CAUSE_FOUR_EYES_REQUIRED",
                "message": "Self-approval is forbidden",
            },
        )
    if isinstance(error, RootCauseTerminalError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "ROOT_CAUSE_IMMUTABLE", "message": "Root cause is immutable"},
        )
    if isinstance(error, CapaActionNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CAPA_ACTION_NOT_FOUND", "message": "CAPA action was not found"},
        )
    if isinstance(error, CapaActionOwnershipError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "CAPA_ACTION_OWNER_REQUIRED", "message": "Assigned owner required"},
        )
    if isinstance(error, CapaActionTransitionError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CAPA_ACTION_INVALID_TRANSITION",
                "message": "Action transition invalid",
            },
        )
    if isinstance(error, QualityEvidenceError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "QUALITY_EVIDENCE_NOT_FOUND", "message": "Evidence was not found"},
        )
    if isinstance(error, EffectivenessFourEyesError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "EFFECTIVENESS_FOUR_EYES_REQUIRED",
                "message": "Reviewer cannot own an action under review",
            },
        )
    if isinstance(error, EffectivenessObservationPendingError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "EFFECTIVENESS_OBSERVATION_PENDING",
                "message": "Observation period has not completed",
            },
        )
    return complaint_error(error)


@router.get("/ncrs/{ncr_id}", response_model=NcrResponse)
def get_ncr(
    project_id: UUID,
    ncr_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> NcrResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.QUALITY_VIEW
    )
    try:
        return ncr_response(
            NonconformanceService(engine).get(
                tenant_id=context.tenant.id,
                project_id=project_id,
                ncr_id=ncr_id,
            )
        )
    except Exception as error:
        raise capa_error(error) from error


@router.get("/ncrs/{ncr_id}/detail", response_model=NcrDetailResponse)
def get_ncr_detail(
    project_id: UUID,
    ncr_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> NcrDetailResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.QUALITY_VIEW
    )
    try:
        ncr = NonconformanceService(engine).get(
            tenant_id=context.tenant.id,
            project_id=project_id,
            ncr_id=ncr_id,
        )
        root_causes = RootCauseService(engine).list(
            tenant_id=context.tenant.id,
            project_id=project_id,
            ncr_id=ncr_id,
        )
        actions = CapaActionService(engine).list(
            tenant_id=context.tenant.id,
            project_id=project_id,
            ncr_id=ncr_id,
        )
        reviews = EffectivenessService(engine).list(
            tenant_id=context.tenant.id,
            project_id=project_id,
            ncr_id=ncr_id,
        )
    except Exception as error:
        raise capa_error(error) from error
    return NcrDetailResponse(
        ncr=ncr_response(ncr),
        root_causes=[root_cause_response(record) for record in root_causes],
        actions=[capa_action_response(record) for record in actions],
        effectiveness_reviews=[effectiveness_response(record) for record in reviews],
    )


@router.post("/ncrs/{ncr_id}/transitions", response_model=NcrResponse)
def transition_ncr(
    project_id: UUID,
    ncr_id: UUID,
    body: NcrTransitionRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> NcrResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.CAPA_MANAGE
    )
    if body.to_status == "closed":
        require_quality_role(context)
    try:
        record = NonconformanceService(engine).transition(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            ncr_id=ncr_id,
            to_status=body.to_status,
            containment_action=body.containment_action,
            effectiveness_criteria=body.effectiveness_criteria,
            observation_due_at=body.observation_due_at,
        )
    except Exception as error:
        raise capa_error(error) from error
    return ncr_response(record)


@router.post(
    "/ncrs/{ncr_id}/root-causes",
    response_model=RootCauseResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_root_cause(
    project_id: UUID,
    ncr_id: UUID,
    body: RootCauseCreateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RootCauseResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.CAPA_EXECUTE
    )
    try:
        record = RootCauseService(engine).create(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            ncr_id=ncr_id,
            draft=RootCauseDraft(
                method=body.method,
                analysis=body.analysis,
                root_cause=body.root_cause,
                evidence_refs=evidence_payload(body.evidence_refs),
            ),
        )
    except Exception as error:
        raise capa_error(error) from error
    return root_cause_response(record)


@router.post(
    "/ncrs/{ncr_id}/root-causes/{root_cause_id}/approve",
    response_model=RootCauseResponse,
)
def approve_root_cause(
    project_id: UUID,
    ncr_id: UUID,
    root_cause_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RootCauseResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.CAPA_VERIFY
    )
    require_quality_role(context)
    try:
        return root_cause_response(
            RootCauseService(engine).approve(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                ncr_id=ncr_id,
                root_cause_id=root_cause_id,
            )
        )
    except Exception as error:
        raise capa_error(error) from error


@router.post(
    "/ncrs/{ncr_id}/actions",
    response_model=CapaActionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_capa_action(
    project_id: UUID,
    ncr_id: UUID,
    body: CapaActionCreateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> CapaActionResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.CAPA_EXECUTE
    )
    if body.owner_user_id != context.user.id and context.user.role not in {
        Role.OWNER,
        Role.ADMIN,
        Role.QUALITY,
    }:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "CAPA_ASSIGNMENT_DENIED", "message": "Cannot assign another owner"},
        )
    try:
        record = CapaActionService(engine).create(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            ncr_id=ncr_id,
            draft=CapaActionDraft(
                owner_user_id=body.owner_user_id,
                action_type=body.action_type,
                description=body.description,
                due_date=body.due_date,
            ),
        )
    except Exception as error:
        raise capa_error(error) from error
    return capa_action_response(record)


@router.post(
    "/ncrs/{ncr_id}/actions/{action_id}/transitions",
    response_model=CapaActionResponse,
)
def transition_capa_action(
    project_id: UUID,
    ncr_id: UUID,
    action_id: UUID,
    body: CapaActionTransitionRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> CapaActionResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.CAPA_EXECUTE
    )
    try:
        record = CapaActionService(engine).transition(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            ncr_id=ncr_id,
            action_id=action_id,
            to_status=body.to_status,
            completion_summary=body.completion_summary,
            evidence_refs=evidence_payload(body.evidence_refs),
        )
    except Exception as error:
        raise capa_error(error) from error
    return capa_action_response(record)


@router.post(
    "/ncrs/{ncr_id}/effectiveness-reviews",
    response_model=EffectivenessReviewResultResponse,
    status_code=status.HTTP_201_CREATED,
)
def review_effectiveness(
    project_id: UUID,
    ncr_id: UUID,
    body: EffectivenessReviewCreateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> EffectivenessReviewResultResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.CAPA_VERIFY
    )
    require_quality_role(context)
    try:
        result = EffectivenessService(engine).review(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            ncr_id=ncr_id,
            draft=EffectivenessReviewDraft(
                actual_result=body.actual_result,
                result=body.result,
                evidence_refs=evidence_payload(body.evidence_refs),
            ),
        )
    except Exception as error:
        raise capa_error(error) from error
    return EffectivenessReviewResultResponse(
        review=effectiveness_response(result.review),
        ncr=ncr_response(result.ncr),
    )


@router.post("/ncrs/{ncr_id}/preventive-not-applicable", response_model=NcrResponse)
def approve_preventive_not_applicable(
    project_id: UUID,
    ncr_id: UUID,
    body: PreventiveNotApplicableRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> NcrResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.CAPA_VERIFY
    )
    require_quality_role(context)
    try:
        return ncr_response(
            NonconformanceService(engine).approve_preventive_not_applicable(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                ncr_id=ncr_id,
                reason=body.reason,
            )
        )
    except Exception as error:
        raise capa_error(error) from error
