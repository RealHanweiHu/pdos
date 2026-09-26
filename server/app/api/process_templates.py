"""Organization template administration; all publication is an explicit human action."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import Engine

from app.ai.application_gateway import configured_application_gateway
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.process_template_runs import ProcessTemplateRunService
from app.ai.process_template_runs import Request as GenerationRequest
from app.ai.rollout_guard import CapabilityUnavailableError
from app.api.auth import current_context, no_store
from app.auth.errors import ObjectPermissionDeniedError
from app.auth.repository import AuthContext
from app.db.engine import get_engine
from app.domain.process_template_briefs import ProcessTemplateBriefService, TemplateBriefInput
from app.domain.process_template_fields import TemplateFieldError
from app.domain.process_template_findings import (
    ProcessTemplateFindingService,
    TemplateFindingApply,
    TemplateFindingPreview,
    TemplateFindingReview,
)
from app.domain.process_templates import (
    ProcessTemplateService,
    TemplatePreviewInput,
    TemplateReleaseInput,
    TemplateRevisionInput,
)
from app.domain.product_workspace import ProductWorkAccessError
from app.domain.project_templates import ProjectTemplateError

router = APIRouter(prefix="/api/admin/organization/process-templates", tags=["organization"])

Context = Annotated[AuthContext, Depends(current_context)]
Database = Annotated[Engine, Depends(get_engine)]


def failure(error: Exception) -> HTTPException:
    if isinstance(error, BudgetLedgerError):
        message = (
            "此要求链已停止，不能恢复；若要重新开始，请保存新的独立要求。"
            if error.code == "BUDGET_LINEAGE_CANCELLED"
            else "当前请求不能继续，请查看运行详情并核对预算、来源和截止时间。"
        )
        return HTTPException(409, detail={"message": message})
    if isinstance(error, CapabilityUnavailableError):
        return HTTPException(409, detail={"message": "组织配置智能建议尚未开放，请先保留原始要求"})
    if isinstance(error, ProductWorkAccessError):
        return HTTPException(403, detail={"message": str(error)})
    if isinstance(error, ObjectPermissionDeniedError):
        return HTTPException(403, detail={"message": "请由原发起人查看或停止本次生成"})
    if isinstance(error, (ProjectTemplateError, TemplateFieldError)):
        return HTTPException(409, detail={"message": str(error)})
    return HTTPException(503, detail={"message": "组织模板暂不可用，请保留输入后重试"})


@router.get("/briefs")
def briefs(
    response: Response, context: Context, engine: Database, before_id: UUID | None = None
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProcessTemplateBriefService(engine).list(context, before_id)
    except Exception as error:
        raise failure(error) from error


@router.post("/briefs")
def create_brief(
    body: TemplateBriefInput, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProcessTemplateBriefService(engine).create(context, body)
    except Exception as error:
        raise failure(error) from error


@router.get("/briefs/{brief_id}")
def get_brief(
    brief_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProcessTemplateBriefService(engine).get(context, brief_id)
    except Exception as error:
        raise failure(error) from error


@router.post("/briefs/{brief_id}/generate")
def generate(
    brief_id: UUID, body: GenerationRequest, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        from app.ai.rollout_guard import require_live_key
        from app.domain.process_template_findings import CAPABILITY

        require_live_key(CAPABILITY)
        with configured_application_gateway(engine) as gateway:
            return ProcessTemplateRunService(engine, gateway).create(context, brief_id, body)
    except Exception as error:
        raise failure(error) from error


@router.get("/findings/{finding_id}")
def finding(
    finding_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProcessTemplateFindingService(engine).get(context, finding_id)
    except Exception as error:
        raise failure(error) from error


@router.get("/runs/{run_id}/progress")
def run_progress(
    run_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        from app.ai.process_template_runs import run_row
        from app.ai.run_progress import read_progress

        with engine.connect() as c:
            run_row(c, context, run_id)
        return read_progress(engine, context=context, project_id=None, run_id=run_id).model_dump(
            mode="json"
        )
    except Exception as error:
        raise failure(error) from error


@router.post("/runs/{run_id}/cancel")
def cancel_run(
    run_id: UUID, body: TemplateFindingApply, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        from app.ai.application_control import cancel_application_run
        from app.ai.process_template_runs import receipt, run_row

        with engine.connect() as c:
            run_row(c, context, run_id)
        result = cancel_application_run(engine, context=context, run_id=run_id)
        with engine.connect() as c:
            current = receipt(run_row(c, context, run_id))
        return {"cancellation": result.model_dump(mode="json"), "run": current}
    except Exception as error:
        raise failure(error) from error


@router.post("/findings/{finding_id}/preview-review")
def preview_finding(
    finding_id: UUID,
    body: TemplateFindingPreview,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProcessTemplateFindingService(engine).preview(context, finding_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/findings/{finding_id}/review")
def review_finding(
    finding_id: UUID,
    body: TemplateFindingReview,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProcessTemplateFindingService(engine).review(context, finding_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/findings/{finding_id}/apply")
def apply_finding(
    finding_id: UUID,
    body: TemplateFindingApply,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProcessTemplateFindingService(engine).apply(context, finding_id)
    except Exception as error:
        raise failure(error) from error


@router.get("")
def catalog(response: Response, context: Context, engine: Database) -> dict[str, Any]:
    no_store(response)
    try:
        return ProcessTemplateService(engine).overview(context)
    except Exception as error:
        raise failure(error) from error


@router.post("/revisions")
def create(
    body: TemplateRevisionInput, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProcessTemplateService(engine).create(context, body)
    except Exception as error:
        raise failure(error) from error


@router.get("/revisions/{revision_id}")
def get(
    revision_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProcessTemplateService(engine).get(context, revision_id)
    except Exception as error:
        raise failure(error) from error


@router.post("/revisions/{revision_id}/preview")
def preview(
    revision_id: UUID,
    body: TemplatePreviewInput,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProcessTemplateService(engine).preview(
            context,
            revision_id,
            body.cases,
            body.routing_cases,
            body.reminder_cases,
            body.approval_cases,
            body.field_cases,
            body.task_field_cases,
            body.signer_cases,
            body.risk_field_cases,
        )
    except Exception as error:
        raise failure(error) from error


@router.post("/revisions/{revision_id}/release")
def release(
    revision_id: UUID,
    body: TemplateReleaseInput,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProcessTemplateService(engine).release(context, revision_id, body)
    except Exception as error:
        raise failure(error) from error
