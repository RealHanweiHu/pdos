"""Session-scoped dashboard aggregates without per-project request fan-out."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.db.engine import get_engine
from app.domain.dashboard import DashboardRiskService

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class DashboardRiskProjectResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    code: str
    name: str


class DashboardRiskResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    title: str
    status: str
    likelihood: int
    impact: int
    score: int
    updated_at: datetime
    project: DashboardRiskProjectResponse


class DashboardProjectRiskSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    open_risk_count: int
    max_score: int


class DashboardRisksResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[DashboardRiskResponse]
    total: int
    projects: list[DashboardProjectRiskSummaryResponse]


@router.get("/risks", response_model=DashboardRisksResponse)
def get_dashboard_risks(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> DashboardRisksResponse:
    no_store(response)
    if not is_allowed(context.user.role, Action.WORK_ITEM_VIEW):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "DASHBOARD_RISKS_FORBIDDEN",
                "message": "This role cannot view dashboard risks",
            },
        )
    snapshot = DashboardRiskService(engine).load(
        tenant_id=context.tenant.id,
        user_id=context.user.id,
        role=Role(context.user.role),
    )
    return DashboardRisksResponse.model_validate(snapshot, from_attributes=True)
