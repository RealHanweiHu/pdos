"""Project-bound in-progress intake and initialization proposals."""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.api.conversations import error_response
from app.auth.repository import AuthContext
from app.db.engine import get_engine
from app.domain.decision_intake_batch_progress import DecisionIntakeBatchProgress
from app.domain.decision_intake_correction_batches import (
    DecisionCorrectionBatch,
    DecisionIntakeCorrectionBatches,
)
from app.domain.decision_intake_references import DecisionIntakeReferences, ReferenceKind
from app.domain.project_intake import IntakeApply, IntakeProposal, ProjectIntakeService
from app.domain.project_intake_results import InitializationResult, ProjectIntakeResults

router = APIRouter(prefix="/api/projects/{project_id}/intake", tags=["project-intake"])
Context = Annotated[AuthContext, Depends(current_context)]
Database = Annotated[Engine, Depends(get_engine)]


@router.get("")
def overview(
    project_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    before_revision: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectIntakeService(engine).overview(context, project_id, before_revision)
    except Exception as error:
        raise error_response(error) from error


@router.get("/sources")
def sources(
    project_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    search: str = Query(default="", max_length=200),
    before_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectIntakeService(engine).sources(context, project_id, search, before_id)
    except Exception as error:
        raise error_response(error) from error


@router.get("/sources/{document_id}")
def source_text(
    project_id: UUID,
    document_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    after_ordinal: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectIntakeService(engine).source_text(
            context, project_id, document_id, after_ordinal
        )
    except Exception as error:
        raise error_response(error) from error


@router.get("/tasks")
def tasks(
    project_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    search: str = Query(default="", max_length=200),
    before_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectIntakeService(engine).task_options(context, project_id, search, before_id)
    except Exception as error:
        raise error_response(error) from error


@router.post("/proposals")
def save(
    project_id: UUID, body: IntakeProposal, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectIntakeService(engine).save(context, project_id, body)
    except Exception as error:
        raise error_response(error) from error


@router.get("/proposals/{proposal_id}")
def detail(
    project_id: UUID, proposal_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectIntakeService(engine).get(context, project_id, proposal_id)
    except Exception as error:
        raise error_response(error) from error


@router.post("/proposals/{proposal_id}/apply")
def apply(
    project_id: UUID,
    proposal_id: UUID,
    body: IntakeApply,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectIntakeService(engine).apply(context, project_id, proposal_id, body)
    except Exception as error:
        raise error_response(error) from error


@router.get("/work-sources")
def work_sources(
    project_id: UUID,
    kind: Literal["issue", "risk", "decision"],
    response: Response,
    context: Context,
    engine: Database,
    search: str = Query(default="", max_length=200),
    before_id: UUID | None = None,
    target_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectIntakeService(engine).work_sources(
            context, project_id, kind, search, before_id, target_id
        )
    except Exception as error:
        raise error_response(error) from error


@router.get("/proposals/{proposal_id}/earlier-work")
def earlier_work(
    project_id: UUID,
    proposal_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    before_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectIntakeService(engine).earlier_work(
            context, project_id, proposal_id, before_id
        )
    except Exception as error:
        raise error_response(error) from error


@router.get("/decision-work/{decision_id}")
def decision_work(
    project_id: UUID,
    decision_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    before_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectIntakeService(engine).decision_work(
            context, project_id, decision_id, before_id
        )
    except Exception as error:
        raise error_response(error) from error


@router.get("/work/{binding_id}/results")
def work_results(
    project_id: UUID,
    binding_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    before_revision: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectIntakeResults(engine).read(context, project_id, binding_id, before_revision)
    except Exception as error:
        raise error_response(error) from error


@router.post("/work/{binding_id}/results")
def save_work_result(
    project_id: UUID,
    binding_id: UUID,
    body: InitializationResult,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectIntakeResults(engine).save(context, project_id, binding_id, body)
    except Exception as error:
        raise error_response(error) from error


@router.get("/decision-batches/{batch_id}/progress")
def decision_batch_progress(
    project_id: UUID,
    batch_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    before_source_id: UUID | None = None,
    before_decision_id: UUID | None = None,
    before_binding_id: UUID | None = None,
    expected_scope_digest: str | None = Query(default=None, pattern=r"^[0-9a-f]{64}$"),
) -> dict[str, Any]:
    no_store(response)
    try:
        return DecisionIntakeBatchProgress(engine).read(
            context,
            project_id,
            batch_id,
            before_source_id=before_source_id,
            before_decision_id=before_decision_id,
            before_binding_id=before_binding_id,
            expected_scope_digest=expected_scope_digest,
        )
    except Exception as error:
        raise error_response(error) from error


@router.get("/decision-sources/{source_id}/batches")
def decision_source_batches(
    project_id: UUID,
    source_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    before_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return DecisionIntakeBatchProgress(engine).batches(
            context, project_id, source_id, before_id
        )
    except Exception as error:
        raise error_response(error) from error


@router.get("/decision-batches/{batch_id}/corrections")
def decision_corrections_preview(
    project_id: UUID,
    batch_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    offset: int = Query(default=0, ge=0, le=200),
    before_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return DecisionIntakeCorrectionBatches(engine).preview(
            context, project_id, batch_id, offset, before_id
        )
    except Exception as error:
        raise error_response(error) from error


@router.post("/decision-batches/{batch_id}/corrections")
def decision_corrections_apply(
    project_id: UUID,
    batch_id: UUID,
    body: DecisionCorrectionBatch,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return DecisionIntakeCorrectionBatches(engine).apply(context, project_id, batch_id, body)
    except Exception as error:
        raise error_response(error) from error


@router.get("/decision-work/{decision_id}/references")
def decision_references(
    project_id: UUID,
    decision_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    kind: ReferenceKind = "follow_up",
    before_id: UUID | None = None,
    before_path_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return DecisionIntakeReferences(engine).read(
            context, project_id, decision_id, kind, before_id, before_path_id
        )
    except Exception as error:
        raise error_response(error) from error
