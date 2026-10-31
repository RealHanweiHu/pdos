"""Cross-project read models scoped to the Projects the caller may see."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.api.issue_risks import RiskListResponse, risk_response
from app.api.work_items import TaskListResponse, task_response
from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.db.engine import get_engine
from app.domain.risks import RiskService
from app.domain.tasks import TaskService

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


def _member_scope(context: AuthContext) -> UUID | None:
    """Owners and admins see every tenant Project; everyone else only their memberships."""
    if not is_allowed(context.user.role, Action.WORK_ITEM_VIEW):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "PERMISSION_DENIED", "message": "Work items are not visible"},
        )
    return None if context.user.role in {Role.OWNER, Role.ADMIN} else context.user.id


@router.get("/risks", response_model=RiskListResponse)
def portfolio_risks(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RiskListResponse:
    member_user_id = _member_scope(context)
    no_store(response)
    return RiskListResponse(
        items=[
            risk_response(record)
            for record in RiskService(engine).list_open_for_portfolio(
                tenant_id=context.tenant.id,
                member_user_id=member_user_id,
            )
        ]
    )


@router.get("/my-tasks", response_model=TaskListResponse)
def my_tasks(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> TaskListResponse:
    member_user_id = _member_scope(context)
    no_store(response)
    return TaskListResponse(
        items=[
            task_response(record)
            for record in TaskService(engine).list_assigned(
                tenant_id=context.tenant.id,
                assignee_user_id=context.user.id,
                member_user_id=member_user_id,
            )
        ]
    )
