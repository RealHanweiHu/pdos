"""Personal cross-project work aggregation HTTP boundary (My Work, vNext V1-A2)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.db.engine import get_engine
from app.domain.my_work import MyWorkQueueChanged, MyWorkService, WorkCollection
from app.domain.my_work_filters import WorkFocus

router = APIRouter(prefix="/api/me", tags=["my-work"])


class MyWorkProjectResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    code: str
    name: str


class MyWorkTaskResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project: MyWorkProjectResponse
    title: str
    status: str
    priority: str
    due_date: date | None


class MyWorkIssueResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project: MyWorkProjectResponse
    title: str
    status: str
    severity: str
    target_date: date | None


class MyWorkRiskResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project: MyWorkProjectResponse
    title: str
    status: str
    likelihood: int
    impact: int
    target_date: date | None


class MyWorkCapaActionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project: MyWorkProjectResponse
    ncr_id: UUID
    action_type: str
    description: str
    status: str
    due_date: date


class MyWorkGateSignoffResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project: MyWorkProjectResponse
    gate_id: UUID
    gate_code: str
    gate_name: str
    slot: str
    requirement: str
    round_number: int
    review_due_at: datetime | None


class MyWorkFindingResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project: MyWorkProjectResponse
    finding_type: str
    status: str = "pending_review"
    title: str
    created_at: datetime


class MyWorkCrossScheduleResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: UUID
    project: MyWorkProjectResponse
    title: str
    operation: str
    created_at: datetime


class MyWorkIdDesignResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: UUID
    project: MyWorkProjectResponse
    kind: str
    revision_id: UUID
    freeze_id: UUID | None
    title: str
    created_at: datetime


class MyWorkChangeExecutionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: UUID
    project: MyWorkProjectResponse
    binding_id: UUID
    ecr_id: UUID
    task_id: UUID
    ecr_code: str
    title: str
    action: str
    revision_number: int
    created_at: datetime


class MyWorkRiskFollowupResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: UUID
    project: MyWorkProjectResponse
    risk_id: UUID
    task_id: UUID
    title: str
    mode: str
    created_at: datetime


class MyWorkTaskTakeoverResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: UUID
    project: MyWorkProjectResponse
    task_id: UUID
    title: str
    mode: Literal["review", "revise"]
    revision: int
    due_date: date | None
    priority: str
    status: str
    created_at: datetime


class MyWorkCostFreezeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: UUID
    project: MyWorkProjectResponse
    title: str
    created_at: datetime


class MyWorkCountsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    tasks: int
    issues: int
    risks: int
    capa_actions: int
    gate_signoffs: int
    findings: int
    cross_schedule_approvals: int = 0
    id_design_actions: int = 0
    change_execution_confirmations: int = 0
    risk_followup_actions: int = 0
    task_takeover_actions: int = 0
    cost_freeze_approvals: int = 0


class MyWorkPageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    offset: int
    next_offset: int | None
    revision: str


class MyWorkResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    tasks: list[MyWorkTaskResponse]
    issues: list[MyWorkIssueResponse]
    risks: list[MyWorkRiskResponse]
    capa_actions: list[MyWorkCapaActionResponse]
    gate_signoffs: list[MyWorkGateSignoffResponse]
    findings: list[MyWorkFindingResponse]
    counts: MyWorkCountsResponse
    pages: dict[WorkCollection, MyWorkPageResponse] = {}
    cross_schedule_approvals: list[MyWorkCrossScheduleResponse] = []
    id_design_actions: list[MyWorkIdDesignResponse] = []
    change_execution_confirmations: list[MyWorkChangeExecutionResponse] = []
    risk_followup_actions: list[MyWorkRiskFollowupResponse] = []
    task_takeover_actions: list[MyWorkTaskTakeoverResponse] = []
    cost_freeze_approvals: list[MyWorkCostFreezeResponse] = []


@router.get("/work", response_model=MyWorkResponse)
def get_my_work(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    collection: WorkCollection | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    expected_revision: Annotated[str | None, Query(pattern="^[a-f0-9]{32}$")] = None,
    project_id: UUID | None = None,
    search: Annotated[str, Query(max_length=200)] = "",
    focus: WorkFocus = "all",
    as_of_date: date | None = None,
) -> MyWorkResponse:
    no_store(response)
    if not is_allowed(context.user.role, Action.MY_WORK_VIEW):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "MY_WORK_FORBIDDEN",
                "message": "This role cannot view the personal work queue",
            },
        )
    if (offset or expected_revision is not None) and collection is None:
        raise HTTPException(
            422, detail={"code": "WORK_COLLECTION_REQUIRED", "message": "翻页须指定工作类型"}
        )
    if offset and expected_revision is None:
        raise HTTPException(
            422, detail={"code": "WORK_REVISION_REQUIRED", "message": "翻页须带入原队列版本"}
        )
    try:
        snapshot = MyWorkService(engine).load(
            tenant_id=context.tenant.id,
            user_id=context.user.id,
            role=Role(context.user.role),
            limit=limit,
            collection=collection,
            offset=offset,
            expected_revision=expected_revision,
            project_id=project_id,
            search=search,
            focus=focus,
            as_of_date=as_of_date,
        )
    except MyWorkQueueChanged as error:
        raise HTTPException(
            409,
            detail={
                "code": "MY_WORK_QUEUE_CHANGED",
                "message": "待办内容或顺序已变化，请刷新本类工作后继续加载。",
            },
        ) from error
    return MyWorkResponse.model_validate(snapshot, from_attributes=True)


@router.get("/risk-followup-reviews")
def risk_followup_reviews(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    from app.api.issue_risks import risk_followup_error
    from app.domain.risk_followup_results import pending_reviews

    no_store(response)
    try:
        return pending_reviews(engine, context, offset)
    except Exception as error:
        raise risk_followup_error(error) from error
