"""Named confirmation and project AI scope; no implicit automatic execution."""

from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import Engine

from app.ai.issue_event_proposal import IssueEventProposalError
from app.ai.rollout_guard import CapabilityUnavailableError
from app.api.auth import current_context, no_store
from app.auth.repository import AuthContext
from app.db.engine import get_engine
from app.domain.ai_issue_applications import (
    ApplyRequest,
    IssueApplicationError,
    IssueApplicationService,
)
from app.domain.ai_issue_proposal_reviews import IssueProposalReviews, ReviewRequest
from app.domain.ai_issue_sample_reviews import IssueSampleReviews, SampleReviewRequest
from app.domain.ai_issue_withdrawals import (
    IssueWithdrawalService,
    SingleWithdrawalRequest,
    WithdrawalRequest,
)
from app.domain.ai_issue_write_access import ScopeService
from app.domain.ai_meeting_drafts import ScopeChange
from app.domain.ai_write_policy import WritePolicyError

router = APIRouter(prefix="/api/projects/{project_id}/ai-issue-applications", tags=["work-items"])
Context = Annotated[AuthContext, Depends(current_context)]
Database = Annotated[Engine, Depends(get_engine)]


def _invoke(response: Response, callback: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    no_store(response)
    try:
        return callback()
    except (IssueApplicationError, WritePolicyError, IssueEventProposalError) as error:
        status, code, message = 409, error.code, error.message
    except CapabilityUnavailableError as error:
        status, code, message = 409, error.code, "当前事件建单能力尚未开放确认应用"
    except PermissionError:
        status, code, message = (
            403,
            "OBJECT_PERMISSION_DENIED",
            "当前没有此项目建议的办理或授权管理权限",
        )
    except LookupError:
        status, code, message = (
            404,
            "ISSUE_APPLICATION_NOT_FOUND",
            "原运行或项目不存在，或不在当前范围内",
        )
    raise HTTPException(
        status,
        detail={"code": code, "message": message},
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


# Static scope paths must precede /{run_id} so "scope" is never parsed as a UUID.
@router.get("/scope")
def read_scope(
    project_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    return _invoke(response, lambda: ScopeService(engine).get(context, project_id))


@router.post("/scope")
def change_scope(
    project_id: UUID, body: ScopeChange, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    return _invoke(response, lambda: ScopeService(engine).change(context, project_id, body))


@router.get("/{run_id}")
def detail(
    project_id: UUID, run_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    return _invoke(
        response, lambda: IssueApplicationService(engine).get(context, project_id, run_id)
    )


@router.post("/{run_id}")
def apply(
    project_id: UUID,
    run_id: UUID,
    body: ApplyRequest,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    return _invoke(
        response, lambda: IssueApplicationService(engine).apply(context, project_id, run_id, body)
    )


@router.get("/{run_id}/review")
def review_history(
    project_id: UUID,
    run_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    before_version: Annotated[int | None, Query(gt=0)] = None,
) -> dict[str, Any]:
    return _invoke(
        response,
        lambda: IssueProposalReviews(engine).get(context, project_id, run_id, before_version),
    )


@router.post("/{run_id}/review")
def review(
    project_id: UUID,
    run_id: UUID,
    body: ReviewRequest,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    return _invoke(
        response, lambda: IssueProposalReviews(engine).change(context, project_id, run_id, body)
    )


@router.post("/{run_id}/withdraw")
def withdraw(
    project_id: UUID,
    run_id: UUID,
    body: SingleWithdrawalRequest,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    return _invoke(
        response, lambda: IssueWithdrawalService(engine).withdraw(context, project_id, run_id, body)
    )


@router.post("/{run_id}/withdraw-run")
def withdraw_run(
    project_id: UUID,
    run_id: UUID,
    body: WithdrawalRequest,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    return _invoke(
        response, lambda: IssueWithdrawalService(engine).withdraw(context, project_id, run_id, body)
    )


@router.get("/{run_id}/sample-review")
def sample_review_history(
    project_id: UUID,
    run_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    before_id: UUID | None = None,
) -> dict[str, Any]:
    return _invoke(
        response, lambda: IssueSampleReviews(engine).get(context, project_id, run_id, before_id)
    )


@router.post("/{run_id}/sample-review")
def sample_review(
    project_id: UUID,
    run_id: UUID,
    body: SampleReviewRequest,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    return _invoke(
        response, lambda: IssueSampleReviews(engine).change(context, project_id, run_id, body)
    )
