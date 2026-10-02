"""Administrator boundary for the DC-11 tenant write policy."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine

from app.ai.write_policy import OperationSetting, TenantWriteMode, WriteOperation
from app.api.auth import current_context, no_store
from app.api.model_governance import require_action
from app.auth.errors import ObjectPermissionDeniedError
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.engine import get_engine
from app.domain.ai_write_observations import AiWriteObservationService
from app.domain.ai_write_policy import AiWritePolicyService, PolicyUpdate, WritePolicyError

router = APIRouter(prefix="/api/ai/governance/write-policy", tags=["ai-governance"])


class OperationResponse(WriteOperation):
    rollout: str | None
    blockers: list[str]


class PolicyResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    revision: int
    mode: TenantWriteMode
    contract_version: str
    operation_settings: dict[str, OperationSetting]
    principal_id: UUID | None
    principal_name: str
    created_at: datetime | None
    operations: list[OperationResponse]
    notice: str


class PolicyReceipt(BaseModel):
    revision: int
    replayed: bool


class PolicyUpdateResponse(BaseModel):
    policy: PolicyResponse
    receipt: PolicyReceipt


class PolicyHistoryItem(BaseModel):
    revision: int
    mode: TenantWriteMode
    contract_version: str
    operation_settings: dict[str, OperationSetting]
    actor_user_id: UUID
    actor_name: str
    reason: str
    created_at: datetime


class PolicyHistoryResponse(BaseModel):
    items: list[PolicyHistoryItem]
    next_before_revision: int | None


class TrialObservation(BaseModel):
    draft_kind: str
    policy_revision: int
    provider: str
    model: str
    model_version: str | None
    prompt_version: str
    context_version: str
    generated: int
    confirmed: int
    edited: int
    withdrawn: int
    handled: int
    pending: int
    retained_original: int
    withdrawn_after_confirmation: int
    published: int


class TrialObservationResponse(BaseModel):
    as_of: datetime
    window_start: datetime
    items: list[TrialObservation]
    next_offset: int | None
    qualification_granted: bool
    scope_notice: str


@router.get("/observations", response_model=TrialObservationResponse)
def trial_observations(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    as_of: datetime | None = None,
    offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
) -> Any:
    require_action(context, Action.MODEL_GOVERNANCE_VIEW)
    no_store(response)
    if (offset and as_of is None) or (
        as_of is not None and (as_of.tzinfo is None or as_of > datetime.now(UTC))
    ):
        raise HTTPException(422, detail="续读须保留原统计时点，且时点须包含时区且不晚于当前时间")
    return AiWriteObservationService(engine).get(
        tenant_id=context.tenant.id, as_of=as_of, offset=offset
    )


@router.get("", response_model=PolicyResponse)
def get_policy(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> Any:
    require_action(context, Action.MODEL_GOVERNANCE_VIEW)
    no_store(response)
    return AiWritePolicyService(engine).get(tenant_id=context.tenant.id)


@router.get("/history", response_model=PolicyHistoryResponse)
def get_history(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_revision: Annotated[int | None, Query(ge=1)] = None,
) -> Any:
    require_action(context, Action.MODEL_GOVERNANCE_VIEW)
    no_store(response)
    return AiWritePolicyService(engine).history(
        tenant_id=context.tenant.id, before_revision=before_revision
    )


@router.post("", response_model=PolicyUpdateResponse)
def update_policy(
    body: PolicyUpdate,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> Any:
    require_action(context, Action.MODEL_GOVERNANCE_MANAGE)
    no_store(response)
    try:
        return AiWritePolicyService(engine).update(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            changes=body,
        )
    except ObjectPermissionDeniedError as error:
        raise HTTPException(
            403, detail={"code": "OBJECT_PERMISSION_DENIED", "message": "当前账号无权调整设置"}
        ) from error
    except WritePolicyError as error:
        raise HTTPException(409, detail={"code": error.code, "message": error.message}) from error
