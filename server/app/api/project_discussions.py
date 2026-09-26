"""Private project topic discussions with explicit, currently authorized evidence."""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError

from app.ai.budget_ledger import BudgetLedgerError
from app.ai.change_discussion_queue import HumanInput, control
from app.ai.change_discussion_runs import ChangeDiscussionRuns, Request, authorize, listing
from app.ai.project_discussion_sources import Preparation, options, state
from app.ai.rollout_guard import CapabilityUnavailableError
from app.api.auth import current_context, no_store
from app.api.change_governance import _error
from app.auth.repository import AuthContext
from app.db.engine import get_engine
from app.domain.change_discussion_briefs import Review, review
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError

router = APIRouter(
    prefix="/api/projects/{project_id}/changes/discussion-topics", tags=["discussion-topics"]
)
Context = Annotated[AuthContext, Depends(current_context)]
Database = Annotated[Engine, Depends(get_engine)]


class TopicRequest(Request, Preparation):
    depth: Literal[1] = 1


@router.get("/sources", dependencies=[Depends(no_store)])
def sources(project_id: UUID, context: Context, engine: Database) -> dict[str, Any]:
    authorize(engine, context, project_id, edit=False)
    try:
        with engine.connect() as c:
            return options(c, context, project_id)
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise _error(error) from error


@router.post("/prepare", dependencies=[Depends(no_store)])
def prepare(
    project_id: UUID, body: Preparation, context: Context, engine: Database
) -> dict[str, Any]:
    authorize(engine, context, project_id, edit=False)
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
            return state(
                c,
                context.tenant.id,
                project_id,
                context.user.id,
                [v.model_dump(mode="json") for v in body.selections],
            )
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise _error(error) from error


@router.get("", dependencies=[Depends(no_store)])
def history(
    project_id: UUID,
    context: Context,
    engine: Database,
    before_id: UUID | None = None,
    run_id: UUID | None = None,
) -> dict[str, Any]:
    try:
        return listing(engine, context, project_id, None, before_id, run_id)
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise _error(error) from error


@router.post("")
def submit(
    project_id: UUID, body: TopicRequest, context: Context, engine: Database
) -> dict[str, Any]:
    from app.ai.application_gateway import configured_application_gateway

    try:
        with configured_application_gateway(engine) as gateway:
            return ChangeDiscussionRuns(engine, gateway=gateway).submit(
                context, project_id, None, body
            )
    except (BudgetLedgerError, CapabilityUnavailableError) as error:
        raise HTTPException(
            status_code=409,
            detail={"code": error.code, "message": "本次讨论的能力、预算或授权尚未就绪"},
        ) from error
    except (ProductWorkError, ProductWorkAccessError, IntegrityError) as error:
        raise _error(error) from error


@router.post("/{run_id}/control/{action}")
def operate(
    project_id: UUID,
    run_id: UUID,
    action: Literal["cancel", "recover", "cancel_related"],
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    try:
        return control(engine, context, project_id, None, run_id, action)
    except (ProductWorkError, ProductWorkAccessError, IntegrityError) as error:
        raise _error(error) from error


@router.post("/{run_id}/inputs")
def input_turn(
    project_id: UUID, run_id: UUID, body: HumanInput, context: Context, engine: Database
) -> dict[str, Any]:
    try:
        return control(engine, context, project_id, None, run_id, "input", body)
    except (ProductWorkError, ProductWorkAccessError, IntegrityError) as error:
        raise _error(error) from error


@router.post("/{run_id}/brief-reviews")
def compare(
    project_id: UUID, run_id: UUID, body: Review, context: Context, engine: Database
) -> dict[str, Any]:
    try:
        return review(engine, context, project_id, None, run_id, body)
    except (ProductWorkError, ProductWorkAccessError, IntegrityError) as error:
        raise _error(error) from error
