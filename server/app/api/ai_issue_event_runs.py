"""Source-bound event-Issue suggestions; no Issue creation or withdrawal commands."""

from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import Engine

from app.ai.application_gateway import configured_application_gateway
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.issue_event_proposal import KEY, IssueEventProposalError
from app.ai.issue_event_runs import IssueEventRuns, Request, prepare
from app.ai.rollout_guard import CapabilityUnavailableError, require_live_key
from app.api.auth import current_context, no_store
from app.auth.repository import AuthContext
from app.db.engine import get_engine

router = APIRouter(prefix="/api/projects/{project_id}/ai-issue-event-runs", tags=["work-items"])
Context = Annotated[AuthContext, Depends(current_context)]
Database = Annotated[Engine, Depends(get_engine)]
EventId = Annotated[int, Query(gt=0, le=9007199254740991)]
OptionalEventId = Annotated[int | None, Query(gt=0, le=9007199254740991)]


def _failure(error: Exception) -> HTTPException:
    if isinstance(error, IssueEventProposalError):
        status, code, message = 409, error.code, error.message
    elif isinstance(error, CapabilityUnavailableError):
        status, code, message = 409, error.code, "当前异常建议能力尚未开放实际运行；原记录保留"
    elif isinstance(error, PermissionError):
        status, code, message = (
            403,
            "OBJECT_PERMISSION_DENIED",
            "当前没有项目异常建议的读取或运行权限",
        )
    elif isinstance(error, LookupError):
        status, code, message = (
            404,
            "ISSUE_EVENT_SOURCE_NOT_FOUND",
            "原事件或运行不存在，或不在当前项目范围内",
        )
    elif isinstance(error, BudgetLedgerError):
        status = 403 if error.code == "APPLICATION_AUTHORIZATION_DENIED" else 409
        code, message = error.code, "当前异常建议的预算或运行授权尚未就绪；原记录保留"
    else:
        raise error
    return HTTPException(
        status,
        detail={"code": code, "message": message},
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def _invoke(response: Response, callback: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    no_store(response)
    try:
        return callback()
    except (
        IssueEventProposalError,
        PermissionError,
        LookupError,
        BudgetLedgerError,
        CapabilityUnavailableError,
    ) as error:
        raise _failure(error) from error


@router.get("/preparation")
def preparation(
    project_id: UUID, event_row_id: EventId, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    return _invoke(response, lambda: prepare(engine, context, project_id, event_row_id))


@router.get("")
def history(
    project_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    event_row_id: OptionalEventId = None,
    before_id: UUID | None = None,
    run_id: UUID | None = None,
    attention: bool = False,
) -> dict[str, Any]:
    return _invoke(
        response,
        lambda: IssueEventRuns.list_results(
            engine,
            context=context,
            project_id=project_id,
            event_row_id=event_row_id,
            before_id=before_id,
            run_id=run_id,
            attention=attention,
        ),
    )


@router.post("")
def create(
    project_id: UUID, body: Request, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    def execute() -> dict[str, Any]:
        require_live_key(KEY)
        with configured_application_gateway(engine) as gateway:
            return IssueEventRuns(engine, gateway=gateway).create(
                context=context, project_id=project_id, request=body
            )

    return _invoke(response, execute)
