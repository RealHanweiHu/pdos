"""Authenticated project boundaries for Xiaopai continuous delegation."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.api.conversations import error_response
from app.auth.repository import AuthContext
from app.db.engine import get_engine
from app.domain.xiaopai import DelegationCreate, DelegationState, FollowupReply, XiaopaiService

router = APIRouter(prefix="/api/projects/{project_id}/xiaopai", tags=["xiaopai"])
Context = Annotated[AuthContext, Depends(current_context)]
Database = Annotated[Engine, Depends(get_engine)]


@router.get("")
def get_workspace(
    project_id: UUID, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return XiaopaiService(engine).view(context, project_id)
    except Exception as error:
        raise error_response(error) from error


@router.post("/delegations")
def create_delegation(
    project_id: UUID, body: DelegationCreate, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return XiaopaiService(engine).create(context, project_id, body)
    except Exception as error:
        raise error_response(error) from error


@router.post("/delegations/{delegation_id}/state")
def update_delegation(
    project_id: UUID,
    delegation_id: UUID,
    body: DelegationState,
    context: Context,
    engine: Database,
    response: Response,
) -> dict[str, Any]:
    no_store(response)
    try:
        return XiaopaiService(engine).state(context, project_id, delegation_id, body)
    except Exception as error:
        raise error_response(error) from error


@router.post("/followups/{followup_id}/reply")
def reply_followup(
    project_id: UUID,
    followup_id: UUID,
    body: FollowupReply,
    context: Context,
    engine: Database,
    response: Response,
) -> dict[str, Any]:
    no_store(response)
    try:
        return XiaopaiService(engine).reply(context, project_id, followup_id, body)
    except Exception as error:
        raise error_response(error) from error
