"""Project source-association corrections and their original business context."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import AwareDatetime
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.api.conversations import error_response
from app.auth.repository import AuthContext
from app.db.engine import get_engine
from app.domain.issue_intake_batch_progress import IssueIntakeBatchProgress
from app.domain.issue_intake_compensation_results import (
    CompensationResult,
    IssueIntakeCompensationResults,
)
from app.domain.issue_intake_compensations import (
    CompensationBatch,
    CompensationSources,
    IssueIntakeCompensations,
)
from app.domain.issue_intake_correction_batches import (
    CorrectionBatch,
    CorrectionPreview,
    IssueIntakeCorrectionBatches,
)
from app.domain.issue_intake_corrections import IssueIntakeCorrections, SourceCorrection
from app.domain.issue_intake_references import IssueIntakeReferences, ReferenceKind
from app.domain.issue_intake_reuse import project_issue_options

router = APIRouter(prefix="/api/projects/{project_id}/issue-intake-sources", tags=["issues"])


@router.get("/{source_id}")
def get_source(
    project_id: UUID,
    source_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_revision: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    no_store(response)
    try:
        return IssueIntakeCorrections(engine).detail(
            context, project_id, source_id, before_revision=before_revision
        )
    except Exception as error:
        raise error_response(error) from error


@router.get("/{source_id}/issue-options")
def source_issue_options(
    project_id: UUID,
    source_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    search: str = Query(default="", max_length=200),
    issue_id: UUID | None = None,
    before_updated_at: AwareDatetime | None = None,
    before_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        with engine.connect() as c:
            IssueIntakeCorrections.source(c, context, project_id, source_id)
            return project_issue_options(
                c,
                context.tenant.id,
                project_id,
                search=search,
                issue_id=issue_id,
                before_updated_at=before_updated_at,
                before_id=before_id,
            )
    except Exception as error:
        raise error_response(error) from error


@router.post("/{source_id}/corrections")
def correct_source(
    project_id: UUID,
    source_id: UUID,
    body: SourceCorrection,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return IssueIntakeCorrections(engine).correct(context, project_id, source_id, body)
    except Exception as error:
        raise error_response(error) from error


compensation_router = APIRouter(
    prefix="/api/projects/{project_id}/issue-intake-compensations", tags=["issues"]
)


@compensation_router.post("/preview")
def preview_compensations(
    project_id: UUID,
    body: CompensationSources,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return IssueIntakeCompensations(engine).preview(context, project_id, body)
    except Exception as error:
        raise error_response(error) from error


@compensation_router.post("")
def assign_compensations(
    project_id: UUID,
    body: CompensationBatch,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return IssueIntakeCompensations(engine).assign(context, project_id, body)
    except Exception as error:
        raise error_response(error) from error


@compensation_router.get("/{batch_id}")
def get_compensation_batch(
    project_id: UUID,
    batch_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from sqlalchemy import select

    from app.auth.roles import Action
    from app.db.schema import tables
    from app.domain.conversations import ConversationError
    from app.domain.knowledge_corrections import KnowledgeCorrectionService
    from app.domain.product_workspace import _plain

    no_store(response)
    try:
        with engine.connect() as c:
            KnowledgeCorrectionService._authorize(
                c, context.tenant.id, context.user.id, project_id, Action.WORK_ITEM_VIEW
            )
            t = tables.issue_intake_compensation_batches
            row = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.project_id == project_id,
                        t.c.id == batch_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ConversationError("本项目不存在此任务安排批次")
            return _plain(row)
    except Exception as error:
        raise error_response(error) from error


@compensation_router.get("/bindings/{binding_id}/results")
def get_compensation_results(
    project_id: UUID,
    binding_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_revision: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    no_store(response)
    try:
        return IssueIntakeCompensationResults(engine).read(
            context, project_id, binding_id, before_revision=before_revision
        )
    except Exception as error:
        raise error_response(error) from error


@compensation_router.post("/bindings/{binding_id}/results")
def record_compensation_result(
    project_id: UUID,
    binding_id: UUID,
    body: CompensationResult,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return IssueIntakeCompensationResults(engine).save(context, project_id, binding_id, body)
    except Exception as error:
        raise error_response(error) from error


@compensation_router.get("/bindings/{binding_id}/evidence")
def compensation_evidence(
    project_id: UUID,
    binding_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    search: str = Query(default="", max_length=200),
    before_created_at: AwareDatetime | None = None,
    before_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return IssueIntakeCompensationResults(engine).evidence(
            context,
            project_id,
            binding_id,
            search=search,
            before_created_at=before_created_at,
            before_id=before_id,
        )
    except Exception as error:
        raise error_response(error) from error


@router.get("/{source_id}/references")
def source_references(
    project_id: UUID,
    source_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    kind: ReferenceKind = "task",
    issue_id: UUID | None = None,
    before_id: UUID | None = None,
    before_issue_id: UUID | None = None,
    before_path_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return IssueIntakeReferences(engine).read(
            context,
            project_id,
            source_id,
            kind=kind,
            issue_id=issue_id,
            before_id=before_id,
            before_issue_id=before_issue_id,
            before_path_id=before_path_id,
        )
    except Exception as error:
        raise error_response(error) from error


@router.post("/batches/preview")
def preview_correction_batch(
    project_id: UUID,
    body: CorrectionPreview,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return IssueIntakeCorrectionBatches(engine).preview(context, project_id, body)
    except Exception as error:
        raise error_response(error) from error


@router.post("/batches")
def apply_correction_batch(
    project_id: UUID,
    body: CorrectionBatch,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return IssueIntakeCorrectionBatches(engine).apply(context, project_id, body)
    except Exception as error:
        raise error_response(error) from error


@router.get("/batches/{batch_id}")
def get_correction_batch(
    project_id: UUID,
    batch_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return IssueIntakeCorrectionBatches(engine).read(context, project_id, batch_id)
    except Exception as error:
        raise error_response(error) from error


@router.get("/batches/{batch_id}/progress")
def correction_batch_progress(
    project_id: UUID,
    batch_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_source_id: UUID | None = None,
    before_issue_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return IssueIntakeBatchProgress(engine).read(
            context,
            project_id,
            batch_id,
            before_source_id=before_source_id,
            before_issue_id=before_issue_id,
        )
    except Exception as error:
        raise error_response(error) from error
