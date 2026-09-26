"""Tenant-bound Gate rounds, signoffs, decisions, and historical exemptions."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.api.work_items import authorize_project
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.engine import get_engine
from app.domain.gate_assignments import GateAssignmentError, GateAssignmentRequest
from app.domain.gates import (
    GateAdditionRecord,
    GateBasisChangedError,
    GateCondition,
    GateConditionsRequiredError,
    GateConflictError,
    GateGrandfatherNotAllowedError,
    GateGrandfatherPermissionError,
    GateGrandfatherRecord,
    GateInvalidStateError,
    GateNotCurrentError,
    GateNotFoundError,
    GateNotReadyError,
    GateRecord,
    GateRequirementPromotionError,
    GateRoundNotOpenError,
    GateRouteBlockedError,
    GateService,
    GateSigningDeniedError,
)

router = APIRouter(prefix="/api/projects/{project_id}/gates", tags=["gates"])


class GateStageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    code: str
    name: str
    sequence: int


class GateSignoffResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    slot: str
    requirement: str
    status: str
    signed_by_user_id: UUID | None
    signer_role: str | None
    signed_at: datetime | None
    note: str | None


class GateRoundResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    round_number: int
    status: str
    policy_version: str
    requirements: dict[str, str]
    risk_snapshot: dict[str, object]
    readiness_snapshot: dict[str, object] | None
    opened_by_user_id: UUID
    opened_at: datetime
    superseded_at: datetime | None
    supersede_reason: str | None
    completed_at: datetime | None
    signoffs: list[GateSignoffResponse]
    routing_snapshot: dict[str, object] = Field(default_factory=dict)
    routing_blockers: dict[str, list[str]] = Field(default_factory=dict)


class GateReadinessResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    ready: bool
    blocker_keys: list[str]
    blockers: list[dict[str, str]]
    evaluated_at: datetime
    material_digest: str | None = None


class GateAdditionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    slot: str
    requirement: str
    reason: str
    added_by_user_id: UUID
    created_at: datetime


class GateGrandfatherResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    requirement_key: str
    policy_version: str
    reason: str
    approved_by_user_id: UUID
    created_at: datetime


class GateResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    stage: GateStageResponse
    code: str
    name: str
    status: str
    review_due_at: datetime | None
    signing_basis: str
    decided_at: datetime | None
    decided_by_user_id: UUID | None
    is_current: bool
    round: GateRoundResponse | None
    readiness: GateReadinessResponse
    additions: list[GateAdditionResponse]
    grandfather_exemptions: list[GateGrandfatherResponse]
    named_signer_policy: dict[str, Any] = Field(default_factory=dict)


class GateListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[GateResponse]


class GateSignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["approved", "conditional", "rejected"]
    expected_basis: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    note: str | None = Field(default=None, max_length=20_000)

    @field_validator("note", mode="before")
    @classmethod
    def normalize_note(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


class GateRequirementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot: Literal["product", "engineering", "quality"]
    requirement: Literal["conditional", "required"]
    reason: str = Field(min_length=1, max_length=20_000)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class GateConditionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=512)
    owner_user_id: UUID
    due_date: date
    closure_evidence: str = Field(min_length=1, max_length=2_000)

    @field_validator("title", "closure_evidence", mode="before")
    @classmethod
    def normalize(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class GateDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["approved", "conditional", "hold", "rejected"]
    rationale: str = Field(min_length=1, max_length=20_000)
    conditions: list[GateConditionRequest] = Field(default_factory=list, max_length=20)

    @field_validator("rationale", mode="before")
    @classmethod
    def normalize_rationale(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class GateGrandfatherRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_key: str = Field(min_length=1, max_length=128)
    policy_version: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=20_000)

    @field_validator("requirement_key", "policy_version", "reason", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


def gate_response(record: GateRecord) -> GateResponse:
    return GateResponse.model_validate(record, from_attributes=True)


def addition_response(record: GateAdditionRecord) -> GateAdditionResponse:
    return GateAdditionResponse.model_validate(record, from_attributes=True)


def grandfather_response(record: GateGrandfatherRecord) -> GateGrandfatherResponse:
    return GateGrandfatherResponse.model_validate(record, from_attributes=True)


def gate_error(error: Exception) -> HTTPException:
    if isinstance(error, GateAssignmentError):
        return HTTPException(
            409, detail={"code": "GATE_ASSIGNMENT_CONFLICT", "message": str(error)}
        )
    from app.domain.schedule_execution import ScheduleExecutionBlocked

    if isinstance(error, ScheduleExecutionBlocked):
        return HTTPException(
            status_code=409,
            detail={
                "code": "SCHEDULE_EXECUTION_BLOCKED",
                "message": str(error),
                "blockers": error.blockers,
            },
        )
    if isinstance(error, GateConditionsRequiredError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "GATE_CONDITIONS_REQUIRED",
                "message": (
                    "A conditional pass must name its conditions, and only a "
                    "conditional pass may carry them"
                ),
            },
        )
    if isinstance(error, GateNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "GATE_NOT_FOUND", "message": "Gate was not found"},
        )
    if isinstance(error, GateBasisChangedError):
        return HTTPException(
            status_code=409,
            detail={
                "code": "GATE_BASIS_CHANGED",
                "message": "签核轮次、意见或前置状态已变化，请刷新后核对",
            },
        )
    if isinstance(error, GateRouteBlockedError):
        return HTTPException(
            status_code=409,
            detail={
                "code": "GATE_ROUTE_BLOCKED",
                "message": "前置签核尚未完成，请先办理前置专业签核",
                "slots": error.slots,
            },
        )
    if isinstance(error, GateSigningDeniedError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "GATE_SIGNING_DENIED",
                "message": "Role cannot sign this professional Gate slot",
            },
        )
    if isinstance(error, GateGrandfatherPermissionError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "GATE_GRANDFATHER_PERMISSION_DENIED",
                "message": "Only Owner or Admin can approve a historical exemption",
            },
        )
    if isinstance(error, GateNotReadyError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "GATE_NOT_READY",
                "message": "Gate readiness blockers remain",
                "blocker_keys": list(error.blockers),
            },
        )
    if isinstance(error, GateRequirementPromotionError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "GATE_REQUIREMENT_NOT_PROMOTED",
                "message": "Gate requirements can only be promoted",
            },
        )
    if isinstance(error, GateGrandfatherNotAllowedError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "GATE_GRANDFATHER_NOT_ALLOWED",
                "message": "Only an already-passed historical Gate can be grandfathered",
            },
        )
    if isinstance(error, GateNotCurrentError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "GATE_NOT_CURRENT", "message": "Gate is not the current Stage Gate"},
        )
    if isinstance(error, GateRoundNotOpenError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "GATE_ROUND_NOT_OPEN", "message": "Gate round is not open"},
        )
    if isinstance(error, (GateInvalidStateError, GateConflictError)):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "GATE_CONFLICT", "message": "Gate operation conflicts with state"},
        )
    raise error


@router.get("", response_model=GateListResponse)
def list_gates(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> GateListResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.GATE_VIEW
    )
    return GateListResponse(
        items=[
            gate_response(record)
            for record in GateService(engine).list(
                tenant_id=context.tenant.id,
                project_id=project_id,
            )
        ]
    )


@router.post(
    "/{gate_id}/rounds",
    response_model=GateResponse,
    status_code=status.HTTP_201_CREATED,
)
def open_round(
    project_id: UUID,
    gate_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    body: GateAssignmentRequest | None = None,
) -> GateResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.GATE_MANAGE
    )
    try:
        return gate_response(
            GateService(engine).open_round(
                tenant_id=context.tenant.id,
                project_id=project_id,
                gate_id=gate_id,
                actor_user_id=context.user.id,
                assignment=body,
            )
        )
    except Exception as error:
        raise gate_error(error) from error


@router.put(
    "/{gate_id}/rounds/{round_id}/signoffs/{slot}",
    response_model=GateResponse,
)
def sign_round(
    project_id: UUID,
    gate_id: UUID,
    round_id: UUID,
    slot: Literal["product", "engineering", "quality"],
    body: GateSignRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> GateResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.GATE_SIGN
    )
    try:
        return gate_response(
            GateService(engine).sign(
                tenant_id=context.tenant.id,
                project_id=project_id,
                gate_id=gate_id,
                round_id=round_id,
                actor_user_id=context.user.id,
                actor_role=context.user.role,
                slot=slot,
                status=body.status,
                note=body.note,
                expected_basis=body.expected_basis,
            )
        )
    except Exception as error:
        raise gate_error(error) from error


@router.post(
    "/{gate_id}/requirements",
    response_model=GateAdditionResponse,
    status_code=status.HTTP_201_CREATED,
)
def promote_requirement(
    project_id: UUID,
    gate_id: UUID,
    body: GateRequirementRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> GateAdditionResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.GATE_MANAGE
    )
    try:
        return addition_response(
            GateService(engine).promote(
                tenant_id=context.tenant.id,
                project_id=project_id,
                gate_id=gate_id,
                actor_user_id=context.user.id,
                slot=body.slot,
                requested=body.requirement,
                reason=body.reason,
            )
        )
    except Exception as error:
        raise gate_error(error) from error


@router.post("/{gate_id}/decisions", response_model=GateResponse)
def decide_gate(
    project_id: UUID,
    gate_id: UUID,
    body: GateDecisionRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> GateResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.GATE_MANAGE
    )
    try:
        return gate_response(
            GateService(engine).decide(
                tenant_id=context.tenant.id,
                project_id=project_id,
                gate_id=gate_id,
                actor_user_id=context.user.id,
                status=body.status,
                rationale=body.rationale,
                conditions=tuple(
                    GateCondition(
                        title=item.title,
                        owner_user_id=item.owner_user_id,
                        due_date=item.due_date,
                        closure_evidence=item.closure_evidence,
                    )
                    for item in body.conditions
                ),
            )
        )
    except Exception as error:
        raise gate_error(error) from error


@router.post(
    "/{gate_id}/grandfather-exemptions",
    response_model=GateGrandfatherResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_grandfather_exemption(
    project_id: UUID,
    gate_id: UUID,
    body: GateGrandfatherRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> GateGrandfatherResponse:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.GATE_MANAGE
    )
    try:
        return grandfather_response(
            GateService(engine).create_grandfather_exemption(
                tenant_id=context.tenant.id,
                project_id=project_id,
                gate_id=gate_id,
                actor_user_id=context.user.id,
                actor_role=context.user.role,
                requirement_key=body.requirement_key,
                policy_version=body.policy_version,
                reason=body.reason,
            )
        )
    except Exception as error:
        raise gate_error(error) from error


@router.get("/{gate_id}/assignment-options")
def assignment_options(
    project_id: UUID,
    gate_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.gate_assignments import options

    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.GATE_MANAGE
    )
    try:
        with engine.connect() as connection:
            return options(connection, context.tenant.id, project_id, gate_id)
    except Exception as error:
        raise gate_error(error) from error


@router.get("/{gate_id}/rounds")
def round_history(
    project_id: UUID,
    gate_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before: Annotated[int | None, Query(ge=1)] = None,
    round_id: UUID | None = None,
) -> dict[str, Any]:
    from app.domain.gate_assignments import history

    if before is not None and round_id is not None:
        raise HTTPException(
            422,
            detail={"code": "INVALID_GATE_HISTORY", "message": "指定原轮次与历史翻页不能同时使用"},
        )
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.GATE_VIEW
    )
    try:
        with engine.connect() as connection:
            return history(connection, context.tenant.id, project_id, gate_id, before, round_id)
    except Exception as error:
        raise gate_error(error) from error


@router.get("/{gate_id}/conditions")
def condition_history(
    project_id: UUID,
    gate_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    from app.domain.gate_conditions import history

    no_store(response)
    for action in (Action.GATE_VIEW, Action.WORK_ITEM_VIEW):
        authorize_project(engine=engine, context=context, project_id=project_id, action=action)
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
            return history(c, context.tenant.id, project_id, gate_id, before)
    except Exception as error:
        raise gate_error(error) from error
