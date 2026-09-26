"""Product template selection, explicit difference proposals and adoption."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.api.work_items import authorize_project
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.engine import get_engine
from app.domain.project_templates import (
    ProjectTemplateError,
    ProjectTemplateSelection,
    ProjectTemplateService,
)

router = APIRouter(prefix="/api/projects/{project_id}/product-template", tags=["projects"])
Context = Annotated[AuthContext, Depends(current_context)]
Database = Annotated[Engine, Depends(get_engine)]


class TemplateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool


@router.get("")
def get_templates(
    project_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_VIEW
    )
    return ProjectTemplateService(engine).get(tenant_id=context.tenant.id, project_id=project_id)


@router.post("/proposals", status_code=201)
def propose_template(
    project_id: UUID,
    body: ProjectTemplateSelection,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.PROJECT_EDIT
    )
    try:
        return ProjectTemplateService(engine).propose(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            selection=body,
        )
    except ProjectTemplateError as error:
        raise HTTPException(
            409, detail={"code": "PROJECT_TEMPLATE_INVALID", "message": str(error)}
        ) from error


@router.post("/versions/{version_id}/decision")
def decide_template(
    project_id: UUID,
    version_id: UUID,
    body: TemplateDecision,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.PROJECT_EDIT
    )
    try:
        return ProjectTemplateService(engine).decide(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            version_id=version_id,
            confirm=body.confirm,
        )
    except ProjectTemplateError as error:
        raise HTTPException(
            409, detail={"code": "PROJECT_TEMPLATE_INVALID", "message": str(error)}
        ) from error
