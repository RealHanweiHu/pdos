"""Project-scoped fixed observations from original Issue run receipts."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import Engine
from sqlalchemy.exc import DBAPIError

from app.api.ai_issue_applications import _invoke
from app.api.auth import current_context
from app.auth.repository import AuthContext
from app.db.engine import get_engine
from app.domain.ai_issue_observations import CaptureRequest, IssueObservations, ObservationError

router = APIRouter(prefix="/api/projects/{project_id}/ai-issue-observations", tags=["work-items"])
Context = Annotated[AuthContext, Depends(current_context)]
Database = Annotated[Engine, Depends(get_engine)]


def _call(response: Response, callback: Any) -> Any:
    try:
        return _invoke(response, callback)
    except ObservationError as error:
        raise HTTPException(409, detail={"code": error.code, "message": error.message}) from error
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) in {"40001", "23505"}:
            raise HTTPException(
                409,
                detail={
                    "code": "OBSERVATION_RETRY",
                    "message": "观察记录正被更新，请沿原请求重新核对",
                },
            ) from error
        raise


@router.get("")
def history(
    project_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    before_id: UUID | None = None,
) -> Any:
    return _call(
        response, lambda: IssueObservations(engine).history(context, project_id, before_id)
    )


@router.get("/{observation_id}")
def get(
    project_id: UUID, observation_id: UUID, response: Response, context: Context, engine: Database
) -> Any:
    return _call(
        response, lambda: IssueObservations(engine).get(context, project_id, observation_id)
    )


@router.post("")
def capture(
    project_id: UUID, body: CaptureRequest, response: Response, context: Context, engine: Database
) -> Any:
    return _call(response, lambda: IssueObservations(engine).capture(context, project_id, body))
