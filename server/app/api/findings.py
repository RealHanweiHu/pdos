"""Tenant-bound AI Finding inbox, human review, and independent apply endpoints."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.api.work_items import authorize_project
from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.db.engine import get_engine
from app.domain.findings import (
    FindingApplyNotSupportedError,
    FindingApplyPermissionError,
    FindingGroundTruthConflictError,
    FindingInvalidTransitionError,
    FindingNotFoundError,
    FindingPayloadInvalidError,
    FindingRecord,
    FindingReview,
    FindingService,
    KnowledgeDraftPayload,
    RiskSuggestionPayload,
)

router = APIRouter(prefix="/api/ai/findings", tags=["ai-findings"])


class RiskSuggestionPayloadResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    description: str | None
    likelihood: int
    impact: int
    mitigation_plan: str | None
    contingency_plan: str | None
    target_date: date | None


class FindingEvidenceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_row_id: int
    label: str
    href: str


class FindingResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    run_id: UUID
    model_invocation_id: UUID
    agent_key: str
    finding_type: str
    origin_key: str
    status: str
    title: str
    summary: str
    proposed_payload: dict[str, object]
    accepted_payload: dict[str, object] | None
    evidence_event_ids: list[int]
    evidence: list[FindingEvidenceResponse]
    confidence_basis_points: int
    preflight_version: str
    reviewed_by_user_id: UUID | None
    reviewed_at: datetime | None
    review_comment: str | None
    applied_by_user_id: UUID | None
    applied_at: datetime | None
    applied_entity_type: str | None
    applied_entity_id: UUID | None
    created_at: datetime
    updated_at: datetime


class FindingListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[FindingResponse]


class FindingReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accepted", "rejected"]
    edited_payload: RiskSuggestionPayload | KnowledgeDraftPayload | None = None
    comment: str | None = Field(default=None, max_length=20_000)

    @field_validator("comment", mode="before")
    @classmethod
    def normalize_comment(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @model_validator(mode="after")
    def reject_payload_only_on_accept(self) -> FindingReviewRequest:
        if self.decision == "rejected" and self.edited_payload is not None:
            raise ValueError("edited_payload is only valid for accepted findings")
        if self.decision == "rejected" and self.comment is None:
            raise ValueError("comment is required for rejected findings")
        return self


class FindingApplyResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    finding: FindingResponse
    risk_id: UUID
    idempotent_replay: bool


def response_from_record(record: FindingRecord) -> FindingResponse:
    return FindingResponse(
        id=record.id,
        project_id=record.project_id,
        run_id=record.run_id,
        model_invocation_id=record.model_invocation_id,
        agent_key=record.agent_key,
        finding_type=record.finding_type,
        origin_key=record.origin_key,
        status=record.status,
        title=record.title,
        summary=record.summary,
        proposed_payload=record.proposed_payload,
        accepted_payload=record.accepted_payload,
        evidence_event_ids=list(record.evidence_event_ids),
        evidence=[
            FindingEvidenceResponse(
                event_row_id=event_row_id,
                label=f"事件 #{event_row_id}",
                href=(
                    f"/projects?project={record.project_id}&tab=timeline&event_id={event_row_id}"
                ),
            )
            for event_row_id in record.evidence_event_ids
        ],
        confidence_basis_points=record.confidence_basis_points,
        preflight_version=record.preflight_version,
        reviewed_by_user_id=record.reviewed_by_user_id,
        reviewed_at=record.reviewed_at,
        review_comment=record.review_comment,
        applied_by_user_id=record.applied_by_user_id,
        applied_at=record.applied_at,
        applied_entity_type=record.applied_entity_type,
        applied_entity_id=record.applied_entity_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def finding_error(error: Exception) -> HTTPException:
    if isinstance(error, FindingNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "FINDING_NOT_FOUND", "message": "Finding was not found"},
        )
    if isinstance(error, FindingApplyPermissionError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FINDING_ACCESS_DENIED", "message": "Finding access denied"},
        )
    if isinstance(error, FindingInvalidTransitionError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "FINDING_INVALID_TRANSITION",
                "message": "Finding transition is not allowed",
            },
        )
    if isinstance(error, FindingApplyNotSupportedError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "FINDING_APPLY_NOT_SUPPORTED",
                "message": "This Finding type cannot be applied to a business record",
            },
        )
    if isinstance(error, FindingGroundTruthConflictError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "FINDING_GROUND_TRUTH_CONFLICT",
                "message": "Finding references no longer match database truth",
            },
        )
    if isinstance(error, FindingPayloadInvalidError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "FINDING_PAYLOAD_INVALID", "message": "Finding payload is invalid"},
        )
    raise error


@router.get("", response_model=FindingListResponse)
def list_findings(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    project_id: Annotated[UUID | None, Query()] = None,
    finding_status: Annotated[
        Literal["pending_review", "accepted", "rejected", "applied"] | None,
        Query(alias="status"),
    ] = None,
) -> FindingListResponse:
    no_store(response)
    if not is_allowed(context.user.role, Action.FINDING_VIEW):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FINDING_ACCESS_DENIED", "message": "Finding access denied"},
        )
    if project_id is not None:
        authorize_project(
            engine=engine,
            context=context,
            project_id=project_id,
            action=Action.FINDING_VIEW,
        )
    records = FindingService(engine).list(
        tenant_id=context.tenant.id,
        project_id=project_id,
        status=finding_status,
        member_user_id=(None if context.user.role in {"owner", "admin"} else context.user.id),
    )
    return FindingListResponse(items=[response_from_record(record) for record in records])


@router.get("/{finding_id}", response_model=FindingResponse)
def get_finding(
    finding_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> FindingResponse:
    no_store(response)
    try:
        record = FindingService(engine).get(
            tenant_id=context.tenant.id,
            finding_id=finding_id,
        )
    except Exception as error:
        raise finding_error(error) from error
    authorize_project(
        engine=engine,
        context=context,
        project_id=record.project_id,
        action=Action.FINDING_VIEW,
    )
    return response_from_record(record)


@router.post("/{finding_id}/review", response_model=FindingResponse)
def review_finding(
    finding_id: UUID,
    body: FindingReviewRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> FindingResponse:
    no_store(response)
    try:
        record = FindingService(engine).review(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            finding_id=finding_id,
            review=FindingReview(
                decision=body.decision,
                edited_payload=body.edited_payload,
                comment=body.comment,
            ),
        )
    except Exception as error:
        raise finding_error(error) from error
    return response_from_record(record)


@router.post("/{finding_id}/apply", response_model=FindingApplyResponse)
def apply_finding(
    finding_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> FindingApplyResponse:
    no_store(response)
    try:
        result = FindingService(engine).apply(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            finding_id=finding_id,
        )
    except Exception as error:
        raise finding_error(error) from error
    return FindingApplyResponse(
        finding=response_from_record(result.finding),
        risk_id=result.risk_id,
        idempotent_replay=result.idempotent_replay,
    )
