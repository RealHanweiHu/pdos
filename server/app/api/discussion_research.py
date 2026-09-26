"""Project-bound access to existing public snapshots for an active discussion."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError

from app.ai.change_discussion_runs import authorize, binding
from app.ai.discussion_research import Addition, Preview, append, choices, preview
from app.ai.discussion_sources import require_disclosure
from app.api.auth import current_context, no_store
from app.api.change_governance import _error
from app.auth.repository import AuthContext
from app.db.engine import get_engine
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError

router = APIRouter(
    prefix="/api/projects/{project_id}/changes/discussion-runs/{run_id}/research",
    tags=["discussion-research"],
)
Context = Annotated[AuthContext, Depends(current_context)]
Database = Annotated[Engine, Depends(get_engine)]


def read(
    engine: Engine, context: AuthContext, project: UUID, run: UUID, selection: Preview | None = None
) -> dict[str, Any]:
    authorize(engine, context, project, edit=False)
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        found = c.execute(
            select(tables.agent_runs.c.id).where(
                tables.agent_runs.c.tenant_id == context.tenant.id,
                tables.agent_runs.c.id == run,
                tables.agent_runs.c.project_id == project,
            )
        ).first()
        if found is None:
            raise ProductWorkError("原讨论不属于当前项目")
        bound = binding(c, context.tenant.id, run)
        require_disclosure(c, context.tenant.id, context.user.id, bound)
        return preview(c, context, selection) if selection else choices(c, context)


@router.get("/sources", dependencies=[Depends(no_store)])
def sources(project_id: UUID, run_id: UUID, context: Context, engine: Database) -> dict[str, Any]:
    try:
        return read(engine, context, project_id, run_id)
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise _error(error) from error


@router.post("/preview", dependencies=[Depends(no_store)])
def source_preview(
    project_id: UUID, run_id: UUID, body: Preview, context: Context, engine: Database
) -> dict[str, Any]:
    try:
        return read(engine, context, project_id, run_id, body)
    except (ProductWorkError, ProductWorkAccessError) as error:
        raise _error(error) from error


@router.post("")
def add(
    project_id: UUID, run_id: UUID, body: Addition, context: Context, engine: Database
) -> dict[str, Any]:
    try:
        return append(engine, context, project_id, run_id, body)
    except (ProductWorkError, ProductWorkAccessError, IntegrityError) as error:
        raise _error(error) from error
