"""Project-bound Issue/NCR linking and quality escalation HTTP actions."""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.api.quality_capa import capa_error
from app.auth.repository import AuthContext
from app.db.engine import get_engine
from app.domain import quality_issue_links as service
from app.domain.product_workspace import ProductWorkError

router = APIRouter(prefix="/api/projects/{project_id}/quality/issue-links", tags=["quality"])
Context = Annotated[AuthContext, Depends(current_context)]
Database = Annotated[Engine, Depends(get_engine)]
Offset = Annotated[int, Query(ge=0, le=100000)]


def error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(
            403,
            detail={"code": "QUALITY_ISSUE_ACCESS_DENIED", "message": "当前没有此项目或操作权限"},
        )
    if isinstance(exc, ProductWorkError):
        return HTTPException(409, detail={"code": "QUALITY_ISSUE_CONFLICT", "message": str(exc)})
    return capa_error(exc)


@router.get("")
def listing(
    project_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    issue_id: UUID | None = None,
    ncr_id: UUID | None = None,
    offset: Offset = 0,
) -> dict[str, Any]:
    no_store(response)
    try:
        return service.listing(engine, context, project_id, issue_id, ncr_id, offset)
    except Exception as exc:
        raise error(exc) from exc


@router.get("/options")
def options(
    project_id: UUID,
    kind: Literal["issue", "ncr", "document"],
    response: Response,
    context: Context,
    engine: Database,
    offset: Offset = 0,
) -> dict[str, Any]:
    no_store(response)
    try:
        return service.options(engine, context, project_id, kind, offset)
    except Exception as exc:
        raise error(exc) from exc


@router.post("")
def link(
    project_id: UUID, body: service.Link, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return service.link(engine, context, project_id, body)
    except Exception as exc:
        raise error(exc) from exc


@router.post("/escalate")
def escalate(
    project_id: UUID, body: service.Escalate, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return service.escalate(engine, context, project_id, body)
    except Exception as exc:
        raise error(exc) from exc


@router.post("/{link_id}/retract")
def retract(
    project_id: UUID,
    link_id: UUID,
    body: service.Retract,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return service.retract(engine, context, project_id, link_id, body)
    except Exception as exc:
        raise error(exc) from exc
