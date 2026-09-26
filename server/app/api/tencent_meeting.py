"""Tencent enterprise account mapping; these endpoints never call the provider."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.auth.errors import ObjectPermissionDeniedError
from app.auth.repository import AuthContext
from app.db.engine import get_engine
from app.domain import tencent_meeting_bindings as service
from app.domain.meetings import MeetingStateError
from app.settings import get_settings

router = APIRouter(prefix="/api/integrations/tencent-meeting", tags=["tencent-meeting"])


def mapped(error: Exception) -> HTTPException:
    if isinstance(error, ObjectPermissionDeniedError):
        return HTTPException(403, detail={"message": "无权管理此账号映射"})
    if isinstance(error, MeetingStateError):
        return HTTPException(409, detail={"message": str(error)})
    return HTTPException(500, detail={"message": "账号映射办理失败，请核对原请求后重试"})


@router.get("/bindings")
def get_bindings(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    user_id: UUID | None = None,
    q: str = Query(default="", max_length=100),
    before_version: int | None = Query(default=None, ge=1),
) -> dict[str, object]:
    no_store(response)
    try:
        return service.read(engine, context, get_settings(), user_id, q, before_version)
    except Exception as error:
        raise mapped(error) from error


@router.post("/bindings")
def save_binding(
    payload: service.Command,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, object]:
    no_store(response)
    try:
        return service.save(engine, context, get_settings(), payload)
    except Exception as error:
        raise mapped(error) from error
