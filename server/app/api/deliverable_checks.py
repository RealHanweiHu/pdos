"""Project-bound deliverable check library HTTP boundary."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.api.work_items import authorize_project
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.engine import get_engine
from app.domain.deliverable_checks import (
    DeliverableAssetError,
    DeliverableCheckService,
    DeliverableNotFoundError,
    DeliverableTransitionError,
)

router = APIRouter(
    prefix="/api/projects/{project_id}/deliverable-checks",
    tags=["deliverable-checks"],
)


class ResolveCheckItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["completed", "not_applicable"]
    evidence_reference: str | None = Field(default=None, max_length=2048)
    note: str | None = Field(default=None, max_length=20_000)


def _access(engine: Engine, context: AuthContext, project_id: UUID, action: Action) -> None:
    authorize_project(engine=engine, context=context, project_id=project_id, action=action)


def _clean(value: str | None) -> str | None:
    normalized = value.strip() if value else ""
    return normalized or None


def _error(error: Exception) -> HTTPException:
    if isinstance(error, DeliverableNotFoundError):
        return HTTPException(
            status_code=404,
            detail={"code": "DELIVERABLE_CHECK_NOT_FOUND", "message": "Check item was not found"},
        )
    if isinstance(error, (DeliverableAssetError, DeliverableTransitionError)):
        return HTTPException(
            status_code=409,
            detail={
                "code": "DELIVERABLE_CHECK_CONFLICT",
                "message": "Check library or completion contract conflict",
            },
        )
    return HTTPException(
        status_code=500,
        detail={"code": "DELIVERABLE_CHECK_INTERNAL_ERROR", "message": "Operation failed"},
    )


@router.post("/prepare")
def prepare_project(
    project_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.GATE_MANAGE)
    try:
        return DeliverableCheckService(engine).prepare_project(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
        )
    except Exception as error:
        raise _error(error) from error


@router.get("", dependencies=[Depends(no_store)])
def list_items(
    project_id: UUID,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, list[dict[str, Any]]]:
    _access(engine, context, project_id, Action.GATE_VIEW)
    try:
        return {
            "items": DeliverableCheckService(engine).list_items(
                tenant_id=context.tenant.id,
                project_id=project_id,
            )
        }
    except Exception as error:
        raise _error(error) from error


@router.post("/items/{item_id}/resolve")
def resolve_item(
    project_id: UUID,
    item_id: UUID,
    body: ResolveCheckItemRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.WORK_ITEM_EDIT)
    try:
        return DeliverableCheckService(engine).resolve_item(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            item_id=item_id,
            status=body.status,
            evidence_reference=_clean(body.evidence_reference),
            note=_clean(body.note),
        )
    except Exception as error:
        raise _error(error) from error
