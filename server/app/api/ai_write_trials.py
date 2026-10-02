"""Named trial registration and fixed collections; no client-supplied qualification."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.api.model_governance import require_action
from app.auth.errors import ObjectPermissionDeniedError
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.ai_write_trial_protocol import CollectTrial, RegisterTrial
from app.db.engine import get_engine
from app.domain.ai_write_policy import WritePolicyError
from app.domain.ai_write_trial_current import current_trial_check
from app.domain.ai_write_trial_preparation import prepare_trial_registration
from app.domain.ai_write_trial_protocols import AiWriteTrialProtocolService

router = APIRouter(prefix="/api/ai/governance/write-policy/trials", tags=["ai-governance"])
Context = Annotated[AuthContext, Depends(current_context)]
Database = Annotated[Engine, Depends(get_engine)]


def _invoke(response: Response, callback: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    no_store(response)
    try:
        return callback()
    except ObjectPermissionDeniedError as error:
        raise HTTPException(
            403,
            detail={"code": "OBJECT_PERMISSION_DENIED", "message": "当前账号无权访问此试运行范围"},
        ) from error
    except WritePolicyError as error:
        status = 404 if error.code in {"TRIAL_NOT_FOUND", "TRIAL_RECEIPT_NOT_FOUND"} else 409
        raise HTTPException(
            status, detail={"code": error.code, "message": error.message}
        ) from error


@router.post("")
def register(body: RegisterTrial, response: Response, context: Context, engine: Database) -> Any:
    require_action(context, Action.MODEL_GOVERNANCE_MANAGE)
    return _invoke(
        response,
        lambda: AiWriteTrialProtocolService(engine).register(
            tenant_id=context.tenant.id,
            actor_id=context.user.id,
            body=body,
        ),
    )


@router.get("")
def history(
    response: Response, context: Context, engine: Database, before_id: UUID | None = None
) -> Any:
    require_action(context, Action.MODEL_GOVERNANCE_VIEW)
    return _invoke(
        response,
        lambda: AiWriteTrialProtocolService(engine).list(
            tenant_id=context.tenant.id,
            actor_id=context.user.id,
            before_id=before_id,
        ),
    )


@router.get("/preparation")
def preparation(response: Response, context: Context, engine: Database) -> Any:
    require_action(context, Action.MODEL_GOVERNANCE_MANAGE)
    with engine.connect() as connection:
        return _invoke(
            response,
            lambda: prepare_trial_registration(
                connection, tenant_id=context.tenant.id, actor_id=context.user.id
            ),
        )


@router.get("/{protocol_id}")
def get(protocol_id: UUID, response: Response, context: Context, engine: Database) -> Any:
    require_action(context, Action.MODEL_GOVERNANCE_VIEW)
    return _invoke(
        response,
        lambda: AiWriteTrialProtocolService(engine).get(
            tenant_id=context.tenant.id,
            actor_id=context.user.id,
            protocol_id=protocol_id,
        ),
    )


@router.post("/{protocol_id}/receipts")
def collect(
    protocol_id: UUID, body: CollectTrial, response: Response, context: Context, engine: Database
) -> Any:
    require_action(context, Action.MODEL_GOVERNANCE_MANAGE)
    return _invoke(
        response,
        lambda: AiWriteTrialProtocolService(engine).collect(
            tenant_id=context.tenant.id,
            actor_id=context.user.id,
            protocol_id=protocol_id,
            body=body,
        ),
    )


@router.get("/{protocol_id}/receipts")
def receipts(
    protocol_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    before_id: UUID | None = None,
) -> Any:
    require_action(context, Action.MODEL_GOVERNANCE_VIEW)
    return _invoke(
        response,
        lambda: AiWriteTrialProtocolService(engine).receipts(
            tenant_id=context.tenant.id,
            actor_id=context.user.id,
            protocol_id=protocol_id,
            before_id=before_id,
        ),
    )


@router.get("/{protocol_id}/current-check")
def current_check(
    protocol_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    project_id: UUID | None = None,
) -> Any:
    require_action(context, Action.MODEL_GOVERNANCE_VIEW)
    return _invoke(
        response,
        lambda: current_trial_check(
            engine,
            tenant_id=context.tenant.id,
            actor_id=context.user.id,
            protocol_id=protocol_id,
            project_id=project_id,
        ),
    )
