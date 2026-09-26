"""Project completion readiness, internal handoff, and Issue verification policy."""

from typing import Annotated, Any, Self
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.api.work_items import authorize_project
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.engine import get_engine
from app.domain.project_completion import CompletionError, ProjectCompletionService

router = APIRouter(prefix="/api/projects/{project_id}/completion", tags=["projects"])


class HandoffCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID | None = None
    expected_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def paired(self) -> Self:
        if (self.request_id is None) != (self.expected_digest is None):
            raise ValueError("请求编号与原版本摘要须同时提供")
        return self


class HandoffPrepare(HandoffCommand):
    receiver_change_reason: str | None = Field(default=None, min_length=1, max_length=2048)
    document_id: UUID
    receiver_user_id: UUID
    note: str = Field(min_length=1, max_length=10_000)


class HandoffResponse(HandoffCommand):
    accept: bool
    note: str = Field(min_length=1, max_length=10_000)


class IssuePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    low: bool
    medium: bool


Context = Annotated[AuthContext, Depends(current_context)]
Database = Annotated[Engine, Depends(get_engine)]


@router.get("")
def get_completion(
    project_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.HANDOFF_VIEW
    )
    return ProjectCompletionService(engine).get(tenant_id=context.tenant.id, project_id=project_id)


@router.get("/handoff/{item_key}/history")
def handoff_history(
    project_id: UUID,
    item_key: str,
    response: Response,
    context: Context,
    engine: Database,
    before_id: Annotated[int | None, Query(gt=0)] = None,
) -> dict[str, Any]:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.HANDOFF_VIEW
    )
    try:
        return ProjectCompletionService(engine).handoff_history(
            tenant_id=context.tenant.id,
            project_id=project_id,
            item_key=item_key,
            before_id=before_id,
        )
    except CompletionError as error:
        raise HTTPException(
            409, detail={"code": "PROJECT_HANDOFF_INVALID", "message": str(error)}
        ) from error


@router.put("/handoff/{item_key}")
def prepare_handoff(
    project_id: UUID,
    item_key: str,
    body: HandoffPrepare,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.PROJECT_EDIT
    )
    try:
        return ProjectCompletionService(engine).prepare(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            item_key=item_key,
            **body.model_dump(),
        )
    except CompletionError as error:
        raise HTTPException(
            409, detail={"code": "PROJECT_HANDOFF_INVALID", "message": str(error)}
        ) from error


@router.post("/handoff/{item_key}/response")
def respond_handoff(
    project_id: UUID,
    item_key: str,
    body: HandoffResponse,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    try:
        return ProjectCompletionService(engine).respond(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            item_key=item_key,
            **body.model_dump(),
        )
    except CompletionError as error:
        raise HTTPException(
            409, detail={"code": "PROJECT_HANDOFF_INVALID", "message": str(error)}
        ) from error


@router.put("/issue-policy", status_code=204)
def set_issue_policy(
    project_id: UUID, body: IssuePolicy, response: Response, context: Context, engine: Database
) -> None:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.PROJECT_EDIT
    )
    try:
        ProjectCompletionService(engine).set_policy(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            **body.model_dump(),
        )
    except CompletionError as error:
        raise HTTPException(
            409, detail={"code": "PROJECT_POLICY_INVALID", "message": str(error)}
        ) from error
