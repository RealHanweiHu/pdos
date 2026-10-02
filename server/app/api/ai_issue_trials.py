"""Project-scoped Issue preregistration; no automatic qualification."""

from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import Engine

from app.api.ai_issue_applications import _invoke
from app.api.auth import current_context
from app.auth.repository import AuthContext
from app.contracts.ai_issue_trial_protocol import RegisterIssueTrial
from app.db.engine import get_engine
from app.domain.ai_issue_observations import ObservationError
from app.domain.ai_issue_trial_collections import CollectIssueTrial, IssueTrialCollections
from app.domain.ai_issue_trial_current import IssueTrialCurrent
from app.domain.ai_issue_trial_protocols import IssueTrialProtocols

router = APIRouter(prefix="/api/projects/{project_id}/ai-issue-trials", tags=["work-items"])
Context = Annotated[AuthContext, Depends(current_context)]
Database = Annotated[Engine, Depends(get_engine)]


@router.get("/preparation")
def preparation(project_id: UUID, response: Response, context: Context, engine: Database) -> Any:
    return _invoke(response, lambda: IssueTrialProtocols(engine).preparation(context, project_id))


@router.get("")
def history(
    project_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    before_id: UUID | None = None,
) -> Any:
    return _invoke(
        response, lambda: IssueTrialProtocols(engine).history(context, project_id, before_id)
    )


@router.get("/{protocol_id}")
def get(
    project_id: UUID, protocol_id: UUID, response: Response, context: Context, engine: Database
) -> Any:
    return _invoke(
        response, lambda: IssueTrialProtocols(engine).get(context, project_id, protocol_id)
    )


@router.post("")
def register(
    project_id: UUID,
    body: RegisterIssueTrial,
    response: Response,
    context: Context,
    engine: Database,
) -> Any:
    return _invoke(
        response, lambda: IssueTrialProtocols(engine).register(context, project_id, body)
    )


def _collection_call(response: Response, callback: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return _invoke(response, callback)
    except ObservationError as error:
        raise HTTPException(
            409,
            detail={"code": error.code, "message": error.message},
            headers={"Cache-Control": "no-store"},
        ) from error


@router.get("/{protocol_id}/current")
def current_trial(
    project_id: UUID,
    protocol_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
) -> Any:
    return _collection_call(
        response, lambda: IssueTrialCurrent(engine).get(context, project_id, protocol_id)
    )


@router.get("/{protocol_id}/collections")
def collections(
    project_id: UUID,
    protocol_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    before_id: UUID | None = None,
) -> Any:
    return _collection_call(
        response,
        lambda: IssueTrialCollections(engine).history(context, project_id, protocol_id, before_id),
    )


@router.get("/{protocol_id}/collections/{collection_id}")
def collection(
    project_id: UUID,
    protocol_id: UUID,
    collection_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
) -> Any:
    return _collection_call(
        response,
        lambda: IssueTrialCollections(engine).get(context, project_id, protocol_id, collection_id),
    )


@router.post("/{protocol_id}/collections")
def collect_trial(
    project_id: UUID,
    protocol_id: UUID,
    body: CollectIssueTrial,
    response: Response,
    context: Context,
    engine: Database,
) -> Any:
    return _collection_call(
        response,
        lambda: IssueTrialCollections(engine).collect(context, project_id, protocol_id, body),
    )
