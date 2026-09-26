"""Shared project correction endpoints for historical Decision provenance."""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import AwareDatetime
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.api.conversations import error_response
from app.auth.repository import AuthContext
from app.db.engine import get_engine
from app.domain.decision_intake_amendments import DecisionIntakeAmendments, HistoricalAmendment
from app.domain.decision_intake_corrections import (
    DecisionIntakeCorrections,
    DecisionSourceCorrection,
    source,
)
from app.domain.decision_intake_targets import project_options

router = APIRouter(prefix="/api/projects/{project_id}/decision-intake-sources", tags=["decisions"])


@router.get("/{source_id}")
def detail(
    project_id: UUID,
    source_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_revision: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    no_store(response)
    try:
        return DecisionIntakeCorrections(engine).detail(
            context, project_id, source_id, before_revision=before_revision
        )
    except Exception as error:
        raise error_response(error) from error


@router.post("/{source_id}/corrections")
def correct(
    project_id: UUID,
    source_id: UUID,
    body: DecisionSourceCorrection,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return DecisionIntakeCorrections(engine).correct(context, project_id, source_id, body)
    except Exception as error:
        raise error_response(error) from error


@router.get("/{source_id}/target-options")
def targets(
    project_id: UUID,
    source_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    kind: Literal["decision", "issue"],
    search: str = Query(default="", max_length=200),
    target_id: UUID | None = None,
    before_updated_at: AwareDatetime | None = None,
    before_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        with engine.connect() as c:
            source(c, context, project_id, source_id)
            return project_options(
                c,
                context.tenant.id,
                project_id,
                kind=kind,
                search=search,
                target_id=target_id,
                before_updated_at=before_updated_at,
                before_id=before_id,
            )
    except Exception as error:
        raise error_response(error) from error


@router.get("/{source_id}/amendments")
def historical_amendments(
    project_id: UUID,
    source_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_revision: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    no_store(response)
    try:
        return DecisionIntakeAmendments(engine).read(
            context, project_id, source_id, before_revision=before_revision
        )
    except Exception as error:
        raise error_response(error) from error


@router.post("/{source_id}/amendments")
def amend_historical_content(
    project_id: UUID,
    source_id: UUID,
    body: HistoricalAmendment,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return DecisionIntakeAmendments(engine).save(context, project_id, source_id, body)
    except Exception as error:
        raise error_response(error) from error


@router.get("/{source_id}/amendment-evidence")
def amendment_evidence(
    project_id: UUID,
    source_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    search: str = Query(default="", max_length=200),
    before_created_at: AwareDatetime | None = None,
    before_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return DecisionIntakeAmendments(engine).evidence(
            context,
            project_id,
            source_id,
            search=search,
            before_created_at=before_created_at,
            before_id=before_id,
        )
    except Exception as error:
        raise error_response(error) from error
