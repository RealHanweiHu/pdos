"""Tenant- and project-bound change governance HTTP boundary."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError

from app.api.auth import current_context, no_store
from app.api.work_items import authorize_project
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.engine import get_engine
from app.domain.change_governance import (
    ChangeFourEyesError,
    ChangeGovernanceService,
    ChangeHandoffNotReadyError,
    ChangeNotFoundError,
    ChangeScopeError,
    ChangeTransitionError,
)

router = APIRouter(prefix="/api/projects/{project_id}/changes", tags=["change-governance"])


class EcrCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=512)
    reason: str = Field(min_length=1, max_length=20_000)


class ImpactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    impact_analysis: dict[str, Any]
    affected_bom_ids: list[UUID] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_boms(self) -> ImpactRequest:
        if len(set(self.affected_bom_ids)) != len(self.affected_bom_ids):
            raise ValueError("affected_bom_ids must be unique")
        return self


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["approved", "rejected"]
    note: str | None = Field(default=None, max_length=20_000)


class EcnCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=512)
    implementation_plan: dict[str, Any] = Field(default_factory=dict)


class EffectivityDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["approved", "rejected"]
    effectivity: dict[str, Any]
    released_bom_id: UUID | None = None
    target_system: str = Field(default="erp", min_length=1, max_length=64)


def _access(engine: Engine, context: AuthContext, project_id: UUID, action: Action) -> None:
    authorize_project(engine=engine, context=context, project_id=project_id, action=action)


def _error(error: Exception) -> HTTPException:
    if isinstance(error, ChangeNotFoundError):
        return HTTPException(
            status_code=404,
            detail={"code": "CHANGE_NOT_FOUND", "message": "Change record was not found"},
        )
    if isinstance(error, ChangeFourEyesError):
        return HTTPException(
            status_code=409,
            detail={
                "code": "CHANGE_FOUR_EYES_REQUIRED",
                "message": "Requester cannot approve their own ECR",
            },
        )
    if isinstance(error, ChangeHandoffNotReadyError):
        return HTTPException(
            status_code=409,
            detail={
                "code": "HANDOFF_PVT_GATE_REQUIRED",
                "message": "PVT Gate must be approved before handoff is ready",
            },
        )
    if isinstance(error, (ChangeScopeError, ChangeTransitionError, IntegrityError)):
        return HTTPException(
            status_code=409,
            detail={
                "code": "CHANGE_CONFLICT",
                "message": "Change scope, lifecycle, or identity conflict",
            },
        )
    return HTTPException(
        status_code=500,
        detail={"code": "CHANGE_INTERNAL_ERROR", "message": "Change operation failed"},
    )


@router.get("", dependencies=[Depends(no_store)])
def snapshot(
    project_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, list[dict[str, Any]]]:
    _access(engine, context, project_id, Action.CHANGE_VIEW)
    try:
        return ChangeGovernanceService(engine).snapshot(
            tenant_id=context.tenant.id, project_id=project_id
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/ecrs", status_code=status.HTTP_201_CREATED)
def create_ecr(
    project_id: UUID,
    body: EcrCreateRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.CHANGE_EDIT)
    try:
        return ChangeGovernanceService(engine).create_ecr(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            code=body.code.strip(),
            title=body.title.strip(),
            reason=body.reason.strip(),
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/ecrs/{ecr_id}/start-impact")
def start_impact(
    project_id: UUID,
    ecr_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.CHANGE_EDIT)
    try:
        return ChangeGovernanceService(engine).start_impact(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            ecr_id=ecr_id,
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/ecrs/{ecr_id}/submit-impact")
def submit_impact(
    project_id: UUID,
    ecr_id: UUID,
    body: ImpactRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.CHANGE_EDIT)
    try:
        return ChangeGovernanceService(engine).submit_impact(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            ecr_id=ecr_id,
            impact_analysis=body.impact_analysis,
            affected_bom_ids=body.affected_bom_ids,
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/ecrs/{ecr_id}/decide")
def decide_ecr(
    project_id: UUID,
    ecr_id: UUID,
    body: DecisionRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.CHANGE_APPROVE)
    try:
        return ChangeGovernanceService(engine).decide_ecr(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            ecr_id=ecr_id,
            outcome=body.outcome,
            note=body.note.strip() if body.note else None,
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/ecrs/{ecr_id}/ecns", status_code=status.HTTP_201_CREATED)
def create_ecn(
    project_id: UUID,
    ecr_id: UUID,
    body: EcnCreateRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.CHANGE_EDIT)
    try:
        return ChangeGovernanceService(engine).create_ecn(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            ecr_id=ecr_id,
            code=body.code.strip(),
            title=body.title.strip(),
            implementation_plan=body.implementation_plan,
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/ecns/{ecn_id}/submit-effectivity")
def submit_effectivity(
    project_id: UUID,
    ecn_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.CHANGE_EDIT)
    try:
        return ChangeGovernanceService(engine).submit_effectivity(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            ecn_id=ecn_id,
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/ecns/{ecn_id}/decide-effectivity")
def decide_effectivity(
    project_id: UUID,
    ecn_id: UUID,
    body: EffectivityDecisionRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.CHANGE_APPROVE)
    try:
        return ChangeGovernanceService(engine).decide_effectivity(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            ecn_id=ecn_id,
            outcome=body.outcome,
            effectivity=body.effectivity,
            released_bom_id=body.released_bom_id,
            target_system=body.target_system.strip(),
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/handoffs/{handoff_id}/ready")
def ready_handoff(
    project_id: UUID,
    handoff_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.HANDOFF_PREPARE)
    try:
        return ChangeGovernanceService(engine).mark_handoff_ready(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            handoff_id=handoff_id,
        )
    except Exception as error:
        raise _error(error) from error
