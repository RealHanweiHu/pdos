"""Tenant-bound AI Finding inbox, human review, and independent apply endpoints."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Engine, select, tuple_

from app.ai.rollout_guard import CapabilityUnavailableError
from app.api.auth import current_context, no_store
from app.api.work_items import authorize_project
from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.db.engine import get_engine
from app.db.schema import tables
from app.domain import finding_batches
from app.domain.change_work_package_proposals import ChangeWorkPackagePayload
from app.domain.cost_reduction_findings import CostReductionPayload
from app.domain.findings import (
    FINDING_ARCHIVE_TTL_DAYS,
    FINDING_REVIEW_UNDO_SECONDS,
    FindingAiDraftOwnedError,
    FindingApplyNotSupportedError,
    FindingApplyPermissionError,
    FindingGroundTruthConflictError,
    FindingInvalidTransitionError,
    FindingNotFoundError,
    FindingPayloadInvalidError,
    FindingRecord,
    FindingReview,
    FindingService,
    FindingUndoUnavailableError,
    KnowledgeDraftPayload,
    RiskSuggestionPayload,
)
from app.domain.knowledge_push import KnowledgeAccessError, KnowledgeVersionError
from app.domain.meeting_action_proposals import MeetingActionPayload, MeetingActionProposalError
from app.domain.meeting_business_proposals import (
    MeetingBusinessProposalError,
    MeetingChangePayload,
    MeetingIssuePayload,
    MeetingRiskPayload,
)
from app.domain.meeting_decision_proposals import (
    MeetingDecisionPayload,
    MeetingDecisionProposalError,
)
from app.domain.meeting_minutes_proposals import MeetingMinutesPayload, MeetingMinutesProposalError
from app.domain.meetings import MeetingNotFoundError, MeetingStateError
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError
from app.domain.quality_work_packages import QualityWorkPackagePayload
from app.domain.supplier_recovery_findings import SupplierRecoveryPayload
from app.domain.test_plan_changes import TestPlanChangeError, TestPlanChangePayload
from app.settings import Settings, get_settings

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
    superseded_by: str | None = None
    ai_draft_id: UUID | None = None
    review_undo_until: datetime | None = None


class FindingListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[FindingResponse]


class FindingReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accepted", "rejected"]
    edited_payload: (
        RiskSuggestionPayload
        | KnowledgeDraftPayload
        | TestPlanChangePayload
        | MeetingActionPayload
        | MeetingDecisionPayload
        | MeetingIssuePayload
        | MeetingRiskPayload
        | MeetingChangePayload
        | MeetingMinutesPayload
        | ChangeWorkPackagePayload
        | QualityWorkPackagePayload
        | CostReductionPayload
        | SupplierRecoveryPayload
        | None
    ) = None
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
    applied_entity_type: str
    applied_entity_id: UUID
    risk_id: UUID | None
    memory_id: UUID | None
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
                    f"/projects?project={record.project_id}&tab=overview&event_id={event_row_id}"
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
        superseded_by=record.superseded_by,
        ai_draft_id=record.ai_draft_id,
        review_undo_until=(
            record.reviewed_at + timedelta(seconds=FINDING_REVIEW_UNDO_SECONDS)
            if record.status in {"accepted", "rejected"}
            and record.reviewed_at
            and not record.superseded_by
            else None
        ),
    )


def finding_error(error: Exception) -> HTTPException:
    if isinstance(error, FindingUndoUnavailableError):
        return HTTPException(
            409,
            detail={
                "code": "FINDING_UNDO_UNAVAILABLE",
                "message": (
                    "只能在本人裁决后的5秒内撤销；"
                    "窗口已结束、版本变化或已应用时须到原业务记录纠错。"
                ),
            },
        )
    if isinstance(error, ProductWorkAccessError):
        return HTTPException(
            403, detail={"code": "FINDING_SOURCE_ACCESS_DENIED", "message": str(error)}
        )
    if isinstance(error, ProductWorkError):
        return HTTPException(
            status_code=409, detail={"code": "CHANGE_WORK_PACKAGE_CONFLICT", "message": str(error)}
        )
    if isinstance(error, KnowledgeAccessError):
        return HTTPException(
            status_code=403,
            detail={"code": "MINUTES_APPLY_DENIED", "message": "当前没有相应会议事项办理权限"},
        )
    if isinstance(
        error,
        (
            MeetingMinutesProposalError,
            MeetingActionProposalError,
            MeetingDecisionProposalError,
            MeetingBusinessProposalError,
            KnowledgeVersionError,
            MeetingStateError,
            MeetingNotFoundError,
        ),
    ):
        return HTTPException(
            status_code=409, detail={"code": "MEETING_MINUTES_CONFLICT", "message": str(error)}
        )
    if isinstance(error, CapabilityUnavailableError):
        return HTTPException(
            status_code=409,
            detail={"code": error.code, "message": "该能力当前不可用于员工候选或应用"},
        )
    if isinstance(error, TestPlanChangeError):
        return HTTPException(
            status_code=409, detail={"code": "TEST_PLAN_CHANGE_CONFLICT", "message": str(error)}
        )
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
    if isinstance(error, FindingAiDraftOwnedError):
        return HTTPException(
            status_code=409,
            detail={
                "code": "FINDING_AI_DRAFT_OWNED",
                "message": "本候选已进入AI会议草稿，请打开会议进行一次确认、修订或撤回",
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


class FindingBatchResponse(BaseModel):
    receipt: dict[str, Any]
    items: list[FindingResponse]
    replayed: bool


def batch_response(result: finding_batches.BatchResult) -> FindingBatchResponse:
    return FindingBatchResponse(
        receipt=result.receipt,
        items=[response_from_record(record) for record in result.items],
        replayed=result.replayed,
    )


@router.post("/batch", response_model=FindingBatchResponse, dependencies=[Depends(no_store)])
def execute_finding_batch(
    body: finding_batches.BatchRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> FindingBatchResponse:
    try:
        return batch_response(
            finding_batches.execute(engine, context.tenant.id, context.user.id, body)
        )
    except Exception as error:
        raise finding_error(error) from error


@router.get(
    "/batch/{request_id}", response_model=FindingBatchResponse, dependencies=[Depends(no_store)]
)
def read_finding_batch(
    request_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> FindingBatchResponse:
    try:
        return batch_response(
            finding_batches.read(engine, context.tenant.id, context.user.id, request_id)
        )
    except Exception as error:
        raise finding_error(error) from error


@router.get("", response_model=FindingListResponse)
def list_findings(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    project_id: Annotated[UUID | None, Query()] = None,
    finding_status: Annotated[
        Literal["pending_review", "accepted", "rejected", "applied", "archived"] | None,
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
        actor_user_id=context.user.id,
        status=finding_status,
        member_user_id=(None if context.user.role in {"owner", "admin"} else context.user.id),
    )
    return FindingListResponse(items=[response_from_record(record) for record in records])


@router.get("/archive-policy")
def archive_policy(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    no_store(response)
    if not is_allowed(context.user.role, Action.FINDING_VIEW):
        raise HTTPException(403, detail={"code": "FINDING_ACCESS_DENIED"})
    return {
        "automatic_enabled": settings.finding_auto_archive_enabled,
        "ttl_days": FINDING_ARCHIVE_TTL_DAYS,
        "batch_size": 200,
        "policy": "finding-inactivity-v1",
        "restore_renews_period": True,
    }


@router.get("/{finding_id}/lifecycle")
def finding_lifecycle(
    finding_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_at: AwareDatetime | None = None,
    before_id: UUID | None = None,
) -> dict[str, object]:
    no_store(response)
    if (before_at is None) != (before_id is None):
        raise HTTPException(422, detail={"code": "LIFECYCLE_CURSOR_REQUIRED"})
    try:
        record = FindingService(engine).get(
            tenant_id=context.tenant.id, finding_id=finding_id, actor_user_id=context.user.id
        )
    except Exception as error:
        raise finding_error(error) from error
    authorize_project(
        engine=engine, context=context, project_id=record.project_id, action=Action.FINDING_VIEW
    )
    actions = tables.finding_actions
    query = (
        select(actions, tables.users.c.display_name.label("actor_name"))
        .outerjoin(
            tables.users,
            (tables.users.c.tenant_id == actions.c.tenant_id)
            & (tables.users.c.id == actions.c.actor_user_id),
        )
        .where(actions.c.tenant_id == context.tenant.id, actions.c.finding_id == finding_id)
    )
    if before_at is not None:
        query = query.where(tuple_(actions.c.created_at, actions.c.id) < (before_at, before_id))
    with engine.connect() as c:
        values = list(
            c.execute(
                query.order_by(actions.c.created_at.desc(), actions.c.id.desc()).limit(31)
            ).mappings()
        )
    page = values[:30]
    return {
        "items": [dict(row) for row in page],
        "next": {"before_at": page[-1]["created_at"], "before_id": page[-1]["id"]}
        if len(values) > 30
        else None,
    }


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
            actor_user_id=context.user.id,
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
        applied_entity_type=result.applied_entity_type,
        applied_entity_id=result.applied_entity_id,
        risk_id=result.risk_id,
        memory_id=result.memory_id,
        idempotent_replay=result.idempotent_replay,
    )


class FindingArchiveStaleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ttl_days: int = Field(default=FINDING_ARCHIVE_TTL_DAYS, ge=1, le=365)


class FindingArchiveStaleResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    archived: list[FindingResponse]


@router.post("/archive-stale", response_model=FindingArchiveStaleResponse)
def archive_stale_findings(
    body: FindingArchiveStaleRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> FindingArchiveStaleResponse:
    no_store(response)
    if not is_allowed(context.user.role, Action.FINDING_REVIEW):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FINDING_ACCESS_DENIED", "message": "Finding access denied"},
        )
    records = FindingService(engine).archive_stale(
        tenant_id=context.tenant.id,
        actor_user_id=context.user.id,
        member_user_id=(None if context.user.role in {"owner", "admin"} else context.user.id),
        ttl_days=body.ttl_days,
    )
    return FindingArchiveStaleResponse(
        archived=[response_from_record(record) for record in records]
    )


@router.post("/{finding_id}/restore", response_model=FindingResponse)
def restore_finding(
    finding_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> FindingResponse:
    no_store(response)
    try:
        record = FindingService(engine).restore(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            finding_id=finding_id,
        )
    except Exception as error:
        raise finding_error(error) from error
    return response_from_record(record)
