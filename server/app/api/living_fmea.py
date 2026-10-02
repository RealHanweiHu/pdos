"""Original project quality actions for human FMEA lifecycle."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.auth.repository import AuthContext
from app.db.engine import get_engine
from app.domain import living_fmea as service
from app.domain.fmea_design_rules import Draft as DesignRuleDraft
from app.domain.product_workspace import ProductWorkError

router = APIRouter(prefix="/api/projects/{project_id}/quality/fmea", tags=["quality"])
Context = Annotated[AuthContext, Depends(current_context)]
Database = Annotated[Engine, Depends(get_engine)]
Offset = Annotated[int, Query(ge=0, le=100000)]


def error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(
            403, detail={"code": "FMEA_ACCESS_DENIED", "message": "当前没有此项目或操作权限"}
        )
    if isinstance(exc, ProductWorkError):
        return HTTPException(409, detail={"code": "FMEA_STATE_CONFLICT", "message": str(exc)})
    raise exc


@router.get("")
def list_fmea(
    project_id: UUID, response: Response, context: Context, engine: Database, offset: Offset = 0
) -> dict[str, Any]:
    no_store(response)
    try:
        return service.listing(engine, context, project_id, offset)
    except Exception as exc:
        raise error(exc) from exc


@router.get("/sources")
def sources(
    project_id: UUID,
    kind: service.Kind,
    response: Response,
    context: Context,
    engine: Database,
    offset: Offset = 0,
) -> dict[str, Any]:
    no_store(response)
    try:
        return service.sources(engine, context, project_id, kind, offset)
    except Exception as exc:
        raise error(exc) from exc


@router.get("/coverage")
def coverage(
    project_id: UUID, response: Response, context: Context, engine: Database, offset: Offset = 0
) -> dict[str, Any]:
    no_store(response)
    try:
        return service.coverage(engine, context, project_id, offset)
    except Exception as exc:
        raise error(exc) from exc


@router.post("/versions")
def save(
    project_id: UUID, body: service.Draft, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return service.save(engine, context, project_id, body)
    except Exception as exc:
        raise error(exc) from exc


@router.get("/{entry_id}")
def detail(
    project_id: UUID,
    entry_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    before_version: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return service.detail(engine, context, project_id, entry_id, before_version)
    except Exception as exc:
        raise error(exc) from exc


@router.post("/{entry_id}/publish")
def publish(
    project_id: UUID,
    entry_id: UUID,
    body: service.Publication,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return service.publish(engine, context, project_id, entry_id, body)
    except Exception as exc:
        raise error(exc) from exc


@router.get("/{entry_id}/design-rules")
def design_rules(
    project_id: UUID, entry_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    from app.domain.fmea_design_rules import read

    no_store(response)
    try:
        return read(engine, context, project_id, entry_id)
    except Exception as exc:
        raise error(exc) from exc


@router.post("/{entry_id}/design-rules")
def create_design_rule(
    project_id: UUID,
    entry_id: UUID,
    body: DesignRuleDraft,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    from app.domain.fmea_design_rules import create

    no_store(response)
    try:
        return create(engine, context, project_id, entry_id, body)
    except Exception as exc:
        raise error(exc) from exc
