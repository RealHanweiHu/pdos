"""Human-requested public collection into the shared evidence base."""

from dataclasses import asdict
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, select
from sqlalchemy.exc import IntegrityError

from app.ai.product_matrix_preparation import ProductMatrixPreparationService
from app.ai.product_matrix_runs import Request as MatrixRunRequest
from app.ai.product_work_preparation import ProductWorkPreparation
from app.ai.product_work_runs import Request as ProductRunRequest
from app.ai.reach import (
    ReachDeniedError,
    ReachFetchError,
    ReachPolicy,
    ReachRateLimitedError,
)
from app.api.auth import no_store
from app.api.evidence import evidence_error, snapshot_response
from app.api.product_workspace import Context, Database, _error
from app.auth.roles import Action, Role, is_allowed
from app.contracts.product_matrix_explanation import MatrixExplanationSelection
from app.contracts.product_work_ai import (
    ProductCapability,
    ProductWorkOptions,
    ProductWorkSelection,
)
from app.db.schema import tables
from app.domain.competitors import ComparisonRequest, CompetitorDraft, CompetitorService
from app.domain.cost_definition_feedback import CostDefinitionFeedbackService
from app.domain.definition_exports import (
    DefinitionExportService,
    ExportHistory,
    ExportOptions,
    ExportPreview,
    ExportSave,
)
from app.domain.definition_intake import DefinitionIntakeService, PackageAction, PackageDraft
from app.domain.derived_definitions import DerivedDefinitionService, DeriveDefinition, MergeParent
from app.domain.evidence import EvidenceContentUnavailableError, EvidenceService
from app.domain.experiment_feedback import (
    ExperimentFeedbackService,
)
from app.domain.experiment_feedback import (
    FeedbackOptions as ExperimentFeedbackOptions,
)
from app.domain.experiment_feedback import (
    FeedbackRead as ExperimentFeedbackRead,
)
from app.domain.experiment_feedback import (
    FeedbackTargetRead as ExperimentFeedbackTargetRead,
)
from app.domain.experiment_feedback import (
    FeedbackWrite as ExperimentFeedbackWrite,
)
from app.domain.experiments import (
    ExperimentAction,
    ExperimentDraft,
    ExperimentEdit,
    ExperimentService,
)
from app.domain.market_analysis import (
    MarketAnalysisService,
    MarketSegmentDraft,
    MarketSizing,
    calculate_market,
)
from app.domain.opportunities import OpportunityDraft, OpportunityService
from app.domain.opportunity_requirements import OpportunityRequirementService
from app.domain.product_definitions import (
    DefinitionAction,
    DefinitionDraft,
    DefinitionEdit,
    DefinitionReview,
    ProductDefinitionService,
)
from app.domain.product_evidence_findings import Apply as EvidenceFindingApply
from app.domain.product_evidence_findings import ProductEvidenceFindings
from app.domain.product_evidence_findings import Read as EvidenceFindingRead
from app.domain.product_evidence_findings import Review as EvidenceFindingReview
from app.domain.product_matrix import MatrixComparison, MatrixQuery, ProductMatrixService
from app.domain.product_matrix_coverage import (
    CoverageCalculation,
    CoverageOptions,
    CoveragePreparation,
    ProductMatrixCoverageService,
)
from app.domain.product_matrix_dispositions import (
    DispositionRead,
    DispositionWrite,
    ProductMatrixDispositionService,
)
from app.domain.product_matrix_outcomes import (
    OutcomeRead,
    OutcomeWrite,
    ProductMatrixOutcomeService,
)
from app.domain.product_matrix_records import (
    MatrixRecordHistory,
    MatrixRecordRead,
    MatrixRecordSave,
    ProductMatrixRecordService,
)
from app.domain.product_metric_calculations import (
    MetricContext,
    MetricPreview,
    MetricReplay,
    MetricSave,
    ProductMetricCalculationService,
)
from app.domain.product_research_findings import Apply as ResearchFindingApply
from app.domain.product_research_findings import ProductResearchFindings
from app.domain.product_research_findings import Read as ResearchFindingRead
from app.domain.product_research_findings import Review as ResearchFindingReview
from app.domain.product_result_feedback import (
    ProductResultFeedbackService,
    ResultHistory,
    ResultOptions,
    ResultRead,
    ResultSave,
)
from app.domain.product_result_followups import (
    FollowupInbox,
    FollowupOptions,
    FollowupPreview,
    FollowupRead,
    FollowupSave,
    ProductResultFollowupService,
)
from app.domain.product_rfq_requirements import Confirm as RfqConfirm
from app.domain.product_rfq_requirements import ProductRfqRequirements
from app.domain.product_rfq_requirements import Read as RfqRead
from app.domain.product_roadmap import ProductRoadmapService, RoadmapRead, RoadmapWrite
from app.domain.product_source_files import FileRegistration, ProductSourceFiles
from app.domain.product_strategies import (
    ProductStrategyService,
    StrategyAction,
    StrategyDraft,
    StrategyEdit,
)
from app.domain.product_work_attention import AttentionScope, product_work_attention
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _role,
    _space,
)
from app.domain.research_collection import collect_page
from app.domain.research_search import ResearchSearchRequest, ResearchSearchService
from app.domain.research_subscriptions import (
    ResearchSubscriptionService,
    SubscriptionAction,
    SubscriptionDraft,
)
from app.domain.retirement_feedback import (
    RetirementFeedbackService,
    RetirementOptions,
    RetirementRead,
    RetirementSave,
)
from app.settings import get_settings
from app.storage.documents import DocumentObjectStore, get_document_object_store

router = APIRouter(prefix="/api/product-work", tags=["product-research"])


@router.post("/spaces/{space_id}/product-ai-options")
def product_ai_options(
    space_id: UUID, body: ProductWorkOptions, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductWorkPreparation(engine).options(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/product-ai-context")
def product_ai_context(
    space_id: UUID,
    body: ProductWorkSelection,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductWorkPreparation(engine).prepare(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/definition-export-options")
def definition_export_options(
    space_id: UUID, body: ExportOptions, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return DefinitionExportService(engine).options(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/definition-export-preview")
def definition_export_preview(
    space_id: UUID, body: ExportPreview, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return DefinitionExportService(engine).preview(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/definition-export-save")
def definition_export_save(
    space_id: UUID, body: ExportSave, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return DefinitionExportService(engine).save(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/definition-export-history")
def definition_export_history(
    space_id: UUID, body: ExportHistory, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return DefinitionExportService(engine).history(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.get("/spaces/{space_id}/definition-exports/{export_id}/download")
def definition_export_download(
    space_id: UUID, export_id: UUID, context: Context, engine: Database
) -> Response:
    try:
        content, mime, filename = DefinitionExportService(engine).download(
            context, space_id, export_id
        )
        response = Response(
            content,
            media_type=mime,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Content-Type-Options": "nosniff",
            },
        )
        no_store(response)
        return response
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/result-followup-inbox")
def result_followup_inbox(
    space_id: UUID, body: FollowupInbox, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductResultFollowupService(engine).inbox(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/result-followup-options")
def result_followup_options(
    space_id: UUID, body: FollowupOptions, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductResultFollowupService(engine).options(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/result-followup-read")
def result_followup_read(
    space_id: UUID, body: FollowupRead, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductResultFollowupService(engine).read(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/result-followup-preview")
def result_followup_preview(
    space_id: UUID, body: FollowupPreview, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductResultFollowupService(engine).preview(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/result-followup-save")
def result_followup_save(
    space_id: UUID, body: FollowupSave, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductResultFollowupService(engine).save(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/result-metric-context")
def result_metric_context(
    space_id: UUID, body: MetricContext, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductMetricCalculationService(engine).context(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/result-metric-preview")
def result_metric_preview(
    space_id: UUID, body: MetricPreview, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductMetricCalculationService(engine).preview(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/result-metric-save")
def result_metric_save(
    space_id: UUID, body: MetricSave, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductMetricCalculationService(engine).save(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/result-metric-replay")
def result_metric_replay(
    space_id: UUID, body: MetricReplay, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductMetricCalculationService(engine).replay(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/retirement-feedback-options")
def retirement_feedback_options(
    space_id: UUID, body: RetirementOptions, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return RetirementFeedbackService(engine).options(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/retirement-feedback")
def retirement_feedback_read(
    space_id: UUID, body: RetirementRead, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return RetirementFeedbackService(engine).read(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/retirement-feedback-save")
def retirement_feedback_save(
    space_id: UUID, body: RetirementSave, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return RetirementFeedbackService(engine).save(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/result-feedback-options")
def result_feedback_options(
    space_id: UUID, body: ResultOptions, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductResultFeedbackService(engine).options(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/result-feedback-history")
def result_feedback_history(
    space_id: UUID, body: ResultHistory, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductResultFeedbackService(engine).history(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/result-feedback")
def result_feedback_read(
    space_id: UUID, body: ResultRead, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductResultFeedbackService(engine).read(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/result-feedback-save")
def result_feedback_save(
    space_id: UUID, body: ResultSave, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductResultFeedbackService(engine).save(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/experiment-feedback-target")
def experiment_feedback_target(
    space_id: UUID,
    body: ExperimentFeedbackTargetRead,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ExperimentFeedbackService(engine).for_target(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/experiment-feedback-options")
def experiment_feedback_options(
    space_id: UUID,
    body: ExperimentFeedbackOptions,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ExperimentFeedbackService(engine).options(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/experiment-feedback")
def experiment_feedback_read(
    space_id: UUID,
    body: ExperimentFeedbackRead,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ExperimentFeedbackService(engine).read(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/experiment-feedback-save")
def experiment_feedback_save(
    space_id: UUID,
    body: ExperimentFeedbackWrite,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ExperimentFeedbackService(engine).save(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/matrix-outcomes")
def matrix_outcomes(
    space_id: UUID, body: OutcomeRead, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductMatrixOutcomeService(engine).read(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/matrix-outcome-save")
def matrix_outcome_save(
    space_id: UUID, body: OutcomeWrite, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductMatrixOutcomeService(engine).save(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/matrix-dispositions")
def matrix_dispositions(
    space_id: UUID, body: DispositionRead, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductMatrixDispositionService(engine).read(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/matrix-disposition-save")
def matrix_disposition_save(
    space_id: UUID, body: DispositionWrite, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductMatrixDispositionService(engine).save(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


class ProductRunHistory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capability: ProductCapability
    product_line_id: UUID | None = None
    before_id: UUID | None = None
    run_id: UUID | None = None


class ProductRunRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID


@router.post("/spaces/{space_id}/product-work-attention")
def read_product_work_attention(
    space_id: UUID, body: AttentionScope, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return product_work_attention(engine, context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/product-ai-runs")
def product_ai_run(
    space_id: UUID, body: ProductRunRequest, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    from app.ai.application_gateway import configured_application_gateway
    from app.ai.product_work_context import key
    from app.ai.product_work_runs import ProductWorkRuns
    from app.ai.rollout_guard import require_live_key

    no_store(response)
    try:
        require_live_key(key(body.selection.capability))
        with configured_application_gateway(engine) as gateway:
            return ProductWorkRuns(engine, gateway=gateway).create(
                context=context, space_id=space_id, request=body
            )
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/product-ai-history")
def product_ai_history(
    space_id: UUID, body: ProductRunHistory, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    from app.ai.product_work_runs import ProductWorkRuns

    no_store(response)
    try:
        return ProductWorkRuns.list_results(
            engine,
            context=context,
            space_id=space_id,
            capability=body.capability,
            product_line_id=body.product_line_id,
            before_id=body.before_id,
            run_id=body.run_id,
        )
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/product-ai-run-read")
def product_ai_run_read(
    space_id: UUID, body: ProductRunRead, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    from app.ai.product_work_runs import ProductWorkRuns

    no_store(response)
    try:
        return ProductWorkRuns.list_results(
            engine, context=context, space_id=space_id, run_id=body.run_id
        )
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/product-ai-progress")
def product_ai_progress(
    space_id: UUID, body: ProductRunRead, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    from app.ai.product_work_runs import run_row
    from app.ai.run_progress import read_progress

    no_store(response)
    try:
        with engine.connect() as c:
            run_row(c, context, space_id, body.run_id)
        return read_progress(
            engine, context=context, project_id=None, market_space_id=space_id, run_id=body.run_id
        ).model_dump(mode="json")
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/product-ai-cancel")
def product_ai_cancel(
    space_id: UUID, body: ProductRunRead, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    from app.ai.application_control import cancel_application_run
    from app.ai.product_work_runs import receipt, run_row

    no_store(response)
    try:
        with engine.connect() as c:
            run_row(c, context, space_id, body.run_id)
        result = cancel_application_run(engine, context=context, run_id=body.run_id)
        with engine.connect() as c:
            current = receipt(run_row(c, context, space_id, body.run_id))
        return {"cancellation": result.model_dump(mode="json"), "run": current}
    except Exception as error:
        raise _failure(error) from error


class MatrixRunHistory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_id: UUID
    before_id: UUID | None = None
    run_id: UUID | None = None


class MatrixRunRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID


@router.post("/spaces/{space_id}/matrix-ai-runs")
def matrix_ai_run(
    space_id: UUID, body: MatrixRunRequest, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    from app.ai.application_gateway import configured_application_gateway
    from app.ai.product_matrix_runs import KEY, ProductMatrixRuns
    from app.ai.rollout_guard import require_live_key

    no_store(response)
    try:
        require_live_key(KEY)
        with configured_application_gateway(engine) as gateway:
            return ProductMatrixRuns(engine, gateway=gateway).create(
                context=context, space_id=space_id, request=body
            )
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/matrix-ai-history")
def matrix_ai_history(
    space_id: UUID, body: MatrixRunHistory, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    from app.ai.product_matrix_runs import ProductMatrixRuns

    no_store(response)
    try:
        return ProductMatrixRuns.list_results(
            engine,
            context=context,
            space_id=space_id,
            record_id=body.record_id,
            before_id=body.before_id,
            run_id=body.run_id,
        )
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/matrix-ai-progress")
def matrix_ai_progress(
    space_id: UUID, body: MatrixRunRead, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    from app.ai.run_progress import read_progress

    no_store(response)
    try:
        return read_progress(
            engine, context=context, project_id=None, market_space_id=space_id, run_id=body.run_id
        ).model_dump(mode="json")
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/matrix-ai-cancel")
def matrix_ai_cancel(
    space_id: UUID, body: MatrixRunRead, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    from app.ai.application_control import cancel_application_run
    from app.ai.product_matrix_runs import receipt, run_row

    no_store(response)
    try:
        with engine.connect() as c:
            run_row(c, context, space_id, body.run_id)
        result = cancel_application_run(engine, context=context, run_id=body.run_id)
        with engine.connect() as c:
            current = receipt(run_row(c, context, space_id, body.run_id))
        return {"cancellation": result.model_dump(mode="json"), "run": current}
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/matrix-ai-options")
def matrix_ai_options(
    space_id: UUID, body: MatrixRecordRead, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductMatrixPreparationService(engine).options(context, space_id, body.record_id)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/matrix-ai-context")
def matrix_ai_context(
    space_id: UUID,
    body: MatrixExplanationSelection,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductMatrixPreparationService(engine).read(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/matrix-record-save")
def matrix_record_save(
    space_id: UUID, body: MatrixRecordSave, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductMatrixRecordService(engine).save(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/matrix-record-history")
def matrix_record_history(
    space_id: UUID,
    body: MatrixRecordHistory,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductMatrixRecordService(engine).history(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/matrix-record-read")
def matrix_record_read(
    space_id: UUID, body: MatrixRecordRead, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductMatrixRecordService(engine).read(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/matrix-record-replay")
def matrix_record_replay(
    space_id: UUID, body: MatrixRecordRead, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductMatrixRecordService(engine).replay(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/matrix-record-refresh")
def matrix_record_refresh(
    space_id: UUID, body: MatrixRecordRead, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductMatrixRecordService(engine).refresh_inputs(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/matrix-market-options")
def matrix_market_options(
    space_id: UUID, body: CoverageOptions, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductMatrixCoverageService(engine).options(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/matrix-coverage-context")
def matrix_coverage_context(
    space_id: UUID,
    body: CoveragePreparation,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductMatrixCoverageService(engine).prepare(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/matrix-coverage-calculation")
def matrix_coverage_calculation(
    space_id: UUID,
    body: CoverageCalculation,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductMatrixCoverageService(engine).calculate(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/product-roadmap")
def product_roadmap(
    space_id: UUID, body: RoadmapRead, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductRoadmapService(engine).read(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/product-roadmap-history")
def product_roadmap_history(
    space_id: UUID, body: RoadmapRead, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductRoadmapService(engine).history(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/product-roadmap-save")
def product_roadmap_save(
    space_id: UUID, body: RoadmapWrite, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductRoadmapService(engine).save(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/product-matrix")
def product_matrix(
    space_id: UUID, body: MatrixQuery, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductMatrixService(engine).overview(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/product-matrix-comparison")
def product_matrix_comparison(
    space_id: UUID, body: MatrixComparison, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductMatrixService(engine).compare(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


class SourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=256)
    base_url: str = Field(min_length=1, max_length=1024)
    allowed_use: Literal["internal_analysis", "internal_citation", "redistribution"]
    license_note: str = Field(min_length=1, max_length=2048)
    retention_policy: Literal["standard", "extended", "minimal"] = "standard"
    trust_tier: Literal["official", "public", "community", "unknown"] = "unknown"


class PageCapture(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_id: UUID
    url: str = Field(min_length=1, max_length=1024)
    product_line_id: UUID | None = None
    freshness_days: int | None = Field(default=None, ge=1, le=366)


def _failure(error: Exception) -> HTTPException:
    from app.ai.budget_ledger import BudgetLedgerError
    from app.ai.rollout_guard import CapabilityUnavailableError
    from app.auth.errors import ObjectPermissionDeniedError

    if isinstance(error, CapabilityUnavailableError):
        return HTTPException(
            409, detail={"code": error.code, "message": "此项产品分析待阶段评测，尚未开放生成"}
        )
    if isinstance(error, BudgetLedgerError):
        return HTTPException(
            409,
            detail={
                "code": error.code,
                "message": "原请求暂不能继续，请核对运行预算、来源和截止时间；已停止请求不能恢复",
            },
        )
    if isinstance(error, ObjectPermissionDeniedError):
        return HTTPException(403, detail={"message": "请由有权读取原资料的发起人查看或停止运行"})
    if isinstance(error, ReachDeniedError):
        return HTTPException(422, detail={"code": error.reason, "message": str(error)})
    if isinstance(error, (ReachFetchError, ReachRateLimitedError)):
        return HTTPException(
            502, detail={"code": "RESEARCH_SOURCE_UNAVAILABLE", "message": str(error)}
        )
    if isinstance(error, EvidenceContentUnavailableError):
        return HTTPException(
            409, detail={"code": "EVIDENCE_CONTENT_UNAVAILABLE", "message": str(error)}
        )
    if isinstance(error, IntegrityError):
        return HTTPException(
            409,
            detail={
                "code": "RESEARCH_SOURCE_CONFLICT",
                "message": "来源名称已存在，请刷新后选择已有来源",
            },
        )
    if isinstance(error, (ProductWorkAccessError, ProductWorkError)):
        return _error(error)
    return evidence_error(error)


@router.get("/spaces/{space_id}/sources")
def sources(
    space_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        with engine.connect() as connection:
            _space(connection, context, space_id)
        _role(context, Action.EVIDENCE_VIEW)
        return {
            "items": [
                asdict(item)
                for item in EvidenceService(engine).list_sources(tenant_id=context.tenant.id)
                if item.source_type in {"web", "api"}
            ],
            "search_available": bool(get_settings().research_search_endpoint),
            "subscription_available": get_settings().research_subscriptions_enabled,
        }
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/sources", status_code=201)
def create_source(
    space_id: UUID, body: SourceCreate, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        _role(context, Action.RESEARCH_SOURCE_MANAGE)
        with engine.connect() as connection:
            _space(connection, context, space_id, access="manager")
        ReachPolicy().assert_url_allowed(body.base_url)

        def authorize(connection: Connection) -> None:
            current = (
                connection.execute(
                    select(tables.users.c.is_active, tables.users.c.role).where(
                        tables.users.c.tenant_id == context.tenant.id,
                        tables.users.c.id == context.user.id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if (
                current is None
                or not current["is_active"]
                or current["role"] != context.user.role.value
                or not is_allowed(Role(current["role"]), Action.RESEARCH_SOURCE_MANAGE)
            ):
                raise ProductWorkAccessError("当前账号或岗位授权已变化，请重新登录")
            _space(connection, context, space_id, access="manager", lock=True)

        item = EvidenceService(engine, authorize_write=authorize).create_source(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            name=body.name,
            source_type="web",
            base_url=body.base_url,
            allowed_use=body.allowed_use,
            collection_frequency="on_demand",
            retention_policy=body.retention_policy,
            trust_tier=body.trust_tier,
            license_note=body.license_note,
        )
        return asdict(item)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/capture", status_code=201)
def capture(
    space_id: UUID, body: PageCapture, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        collected = collect_page(
            engine,
            context,
            space_id=space_id,
            line_id=body.product_line_id,
            source_id=body.source_id,
            url=body.url,
            freshness_days=body.freshness_days,
        )
        snapshot = collected.snapshot
        result = collected.read
        return {
            "snapshot": snapshot_response(snapshot).model_dump(mode="json"),
            "redirect_chain": list(result.redirect_chain),
            "reused_existing": result.reused_existing,
            "message": "页面已采集，可在研究结论或专业工作中引用此快照",
        }
    except Exception as error:
        raise _failure(error) from error


@router.get("/spaces/{space_id}/evidence/{snapshot_id}/content")
def content(
    space_id: UUID, snapshot_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        _role(context, Action.EVIDENCE_VIEW)
        with engine.connect() as connection:
            _space(connection, context, space_id)
        return EvidenceService(engine).read_content(
            tenant_id=context.tenant.id, snapshot_id=snapshot_id
        )
    except Exception as error:
        raise _failure(error) from error


@router.get("/spaces/{space_id}/searches")
def search_history(
    space_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return {
            "items": ResearchSearchService(
                engine, endpoint=get_settings().research_search_endpoint
            ).history(context, space_id)
        }
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/searches", status_code=201)
def search_sources(
    space_id: UUID,
    body: ResearchSearchRequest,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        value = ResearchSearchService(
            engine, endpoint=get_settings().research_search_endpoint
        ).search(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error
    if value["status"] in {"not_configured", "unavailable"}:
        # Preserve the original observation for history and exact replay; an unavailable
        # dependency is not a successful search or a zero-hit result.
        missing = value["status"] == "not_configured"
        raise HTTPException(
            503,
            headers={"Cache-Control": "no-store"},
            detail={
                "code": "SEARCH_NOT_CONFIGURED" if missing else "SEARCH_UNAVAILABLE",
                "message": ("搜索服务尚未配置" if missing else "搜索服务暂不可用")
                + "，请刷新结果核对原查询；恢复后再发起新查询",
                "observation_id": value["id"],
                "request_id": value["request_id"],
            },
        )
    return value


@router.get("/spaces/{space_id}/subscriptions")
def subscriptions(
    space_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    subscription_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return {
            **ResearchSubscriptionService(engine).list(context, space_id, subscription_id),
            "worker_enabled": get_settings().research_subscriptions_enabled,
        }
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/subscriptions", status_code=201)
def create_subscription(
    space_id: UUID, body: SubscriptionDraft, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResearchSubscriptionService(engine).create(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/subscriptions/{subscription_id}/actions")
def subscription_action(
    space_id: UUID,
    subscription_id: UUID,
    body: SubscriptionAction,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResearchSubscriptionService(engine).act(context, space_id, subscription_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.get("/spaces/{space_id}/competitors")
def competitor_observations(
    space_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return CompetitorService(engine).list(context, space_id)
    except Exception as error:
        raise _failure(error) from error


@router.get("/spaces/{space_id}/competitors/{record_id}")
def competitor_observation_detail(
    space_id: UUID, record_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return CompetitorService(engine).detail(context, space_id, record_id)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/competitors", status_code=201)
def record_competitor(
    space_id: UUID, body: CompetitorDraft, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return CompetitorService(engine).create(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/competitor-comparison")
def compare_competitors(
    space_id: UUID, body: ComparisonRequest, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return CompetitorService(engine).compare(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.get("/spaces/{space_id}/market-segments")
def market_segments(
    space_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return MarketAnalysisService(engine).list(context, space_id)
    except Exception as error:
        raise _failure(error) from error


@router.get("/spaces/{space_id}/market-segments/{record_id}")
def market_segment_detail(
    space_id: UUID, record_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return MarketAnalysisService(engine).detail(context, space_id, record_id)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/market-segments", status_code=201)
def create_market_segment(
    space_id: UUID, body: MarketSegmentDraft, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return MarketAnalysisService(engine).create(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/market-sizing")
def preview_market_sizing(
    space_id: UUID, body: MarketSizing, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        with engine.connect() as connection:
            _space(connection, context, space_id)
        return calculate_market(body)
    except Exception as error:
        raise _failure(error) from error


@router.get("/spaces/{space_id}/opportunities")
def opportunities(
    space_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return OpportunityService(engine).list(context, space_id)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/opportunities", status_code=201)
def create_opportunity(
    space_id: UUID, body: OpportunityDraft, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return OpportunityService(engine).create(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.get("/spaces/{space_id}/experiments")
def experiments(
    space_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ExperimentService(engine).list(context, space_id)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/experiments", status_code=201)
def create_experiment(
    space_id: UUID, body: ExperimentDraft, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ExperimentService(engine).create(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/experiments/{experiment_id}/changes")
def edit_experiment(
    space_id: UUID,
    experiment_id: UUID,
    body: ExperimentEdit,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ExperimentService(engine).change(context, space_id, experiment_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/experiments/{experiment_id}/actions")
def experiment_action(
    space_id: UUID,
    experiment_id: UUID,
    body: ExperimentAction,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ExperimentService(engine).change(context, space_id, experiment_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.get("/spaces/{space_id}/experiments/{experiment_id}/history")
def experiment_history(
    space_id: UUID, experiment_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ExperimentService(engine).history(context, space_id, experiment_id)
    except Exception as error:
        raise _failure(error) from error


@router.get("/spaces/{space_id}/experiments/{experiment_id}")
def experiment_detail(
    space_id: UUID, experiment_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ExperimentService(engine).detail(context, space_id, experiment_id)
    except Exception as error:
        raise _failure(error) from error


@router.get("/spaces/{space_id}/requirement-options")
def opportunity_requirement_options(
    space_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    q: str = Query(default="", max_length=120),
) -> dict[str, Any]:
    no_store(response)
    try:
        return OpportunityRequirementService(engine).options(context, space_id, q)
    except Exception as error:
        raise _failure(error) from error


@router.get("/requirements/{requirement_id}/opportunities")
def requirement_opportunity_backlinks(
    requirement_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return OpportunityRequirementService(engine).backlinks(context, requirement_id)
    except Exception as error:
        raise _failure(error) from error


@router.get("/spaces/{space_id}/opportunities/{opportunity_id}")
def opportunity_detail(
    space_id: UUID, opportunity_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return OpportunityService(engine).detail(context, space_id, opportunity_id)
    except Exception as error:
        raise _failure(error) from error


@router.get("/spaces/{space_id}/strategies")
def product_strategies(
    space_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductStrategyService(engine).list(context, space_id)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/strategies", status_code=201)
def create_product_strategy(
    space_id: UUID, body: StrategyDraft, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductStrategyService(engine).create(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/strategies/{strategy_id}/changes")
def edit_product_strategy(
    space_id: UUID,
    strategy_id: UUID,
    body: StrategyEdit,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductStrategyService(engine).change(context, space_id, strategy_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/strategies/{strategy_id}/actions")
def product_strategy_action(
    space_id: UUID,
    strategy_id: UUID,
    body: StrategyAction,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductStrategyService(engine).change(context, space_id, strategy_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.get("/spaces/{space_id}/strategies/{strategy_id}/history")
def product_strategy_history(
    space_id: UUID, strategy_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductStrategyService(engine).history(context, space_id, strategy_id)
    except Exception as error:
        raise _failure(error) from error


@router.get("/spaces/{space_id}/strategies/{strategy_id}")
def product_strategy_detail(
    space_id: UUID, strategy_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductStrategyService(engine).detail(context, space_id, strategy_id)
    except Exception as error:
        raise _failure(error) from error


@router.get("/spaces/{space_id}/definitions")
def product_definitions(
    space_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductDefinitionService(engine).list(context, space_id)
    except Exception as error:
        raise _failure(error) from error


@router.get("/spaces/{space_id}/definitions/{definition_id}")
def product_definition_detail(
    space_id: UUID, definition_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductDefinitionService(engine).detail(context, space_id, definition_id)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/definitions", status_code=201)
def create_product_definition(
    space_id: UUID, body: DefinitionDraft, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductDefinitionService(engine).create(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/definitions/{definition_id}/changes")
def edit_product_definition(
    space_id: UUID,
    definition_id: UUID,
    body: DefinitionEdit,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductDefinitionService(engine).change(context, space_id, definition_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/definitions/{definition_id}/actions")
def product_definition_action(
    space_id: UUID,
    definition_id: UUID,
    body: DefinitionAction,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductDefinitionService(engine).change(context, space_id, definition_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/definitions/{definition_id}/reviews")
def review_product_definition(
    space_id: UUID,
    definition_id: UUID,
    body: DefinitionReview,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductDefinitionService(engine).change(context, space_id, definition_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.get("/spaces/{space_id}/definitions/{definition_id}/history")
def product_definition_history(
    space_id: UUID, definition_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductDefinitionService(engine).history(context, space_id, definition_id)
    except Exception as error:
        raise _failure(error) from error


@router.get("/spaces/{space_id}/requirement-packages")
def definition_requirement_packages(
    space_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return DefinitionIntakeService(engine).list(context, space_id)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/requirement-packages", status_code=201)
def create_definition_requirement_package(
    space_id: UUID, body: PackageDraft, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return DefinitionIntakeService(engine).create(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/requirement-packages/{package_id}/actions")
def definition_requirement_package_action(
    space_id: UUID,
    package_id: UUID,
    body: PackageAction,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return DefinitionIntakeService(engine).change(context, space_id, package_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.get("/spaces/{space_id}/definitions/{definition_id}/reuse-options")
def definition_requirement_reuse_options(
    space_id: UUID, definition_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return DefinitionIntakeService(engine).reuse_options(context, space_id, definition_id)
    except Exception as error:
        raise _failure(error) from error


@router.get("/spaces/{space_id}/requirement-packages/{package_id}")
def definition_requirement_package_detail(
    space_id: UUID, package_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return DefinitionIntakeService(engine).detail(context, space_id, package_id)
    except Exception as error:
        raise _failure(error) from error


@router.get("/requirements/{requirement_id}/definition-sources")
def requirement_definition_sources(
    requirement_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return DefinitionIntakeService(engine).requirement_sources(context, requirement_id)
    except Exception as error:
        raise _failure(error) from error


@router.get("/spaces/{space_id}/definitions/{definition_id}/cost-feedback")
def definition_cost_feedback(
    space_id: UUID,
    definition_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    before: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostDefinitionFeedbackService(engine).get(
            context, space=space_id, definition_id=definition_id, before=before
        )
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/research-ai-finding")
def research_ai_finding(
    space_id: UUID,
    body: ResearchFindingRead,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductResearchFindings(engine).read(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/research-ai-review")
def research_ai_review(
    space_id: UUID,
    body: ResearchFindingReview,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductResearchFindings(engine).review(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/research-ai-apply")
def research_ai_apply(
    space_id: UUID,
    body: ResearchFindingApply,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductResearchFindings(engine).apply(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/evidence-ai-finding")
def evidence_ai_finding(
    space_id: UUID,
    body: EvidenceFindingRead,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductEvidenceFindings(engine).read(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/evidence-ai-review")
def evidence_ai_review(
    space_id: UUID,
    body: EvidenceFindingReview,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductEvidenceFindings(engine).review(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/evidence-ai-apply")
def evidence_ai_apply(
    space_id: UUID,
    body: EvidenceFindingApply,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductEvidenceFindings(engine).apply(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/definitions/{definition_id}/derive", status_code=201)
def derive_product_definition(
    space_id: UUID,
    definition_id: UUID,
    body: DeriveDefinition,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return DerivedDefinitionService(engine).derive(context, space_id, definition_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.get("/spaces/{space_id}/definitions/{definition_id}/parent-comparison")
def compare_parent_definition(
    space_id: UUID, definition_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return DerivedDefinitionService(engine).compare(context, space_id, definition_id)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/definitions/{definition_id}/parent-merge")
def merge_parent_definition(
    space_id: UUID,
    definition_id: UUID,
    body: MergeParent,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return DerivedDefinitionService(engine).merge(context, space_id, definition_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/source-files", status_code=201)
def register_product_source_file(
    space_id: UUID, body: FileRegistration, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductSourceFiles(engine).register(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.get("/spaces/{space_id}/source-files")
def list_product_source_files(
    space_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    product_line_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductSourceFiles(engine).list(context, space_id, product_line_id)
    except Exception as error:
        raise _failure(error) from error


@router.get("/spaces/{space_id}/source-files/{file_id}")
def read_product_source_file(
    space_id: UUID,
    file_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    after_ordinal: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductSourceFiles(engine).read(context, space_id, file_id, after_ordinal)
    except Exception as error:
        raise _failure(error) from error


@router.put("/spaces/{space_id}/source-files/{file_id}/upload")
async def upload_product_source_file(
    space_id: UUID,
    file_id: UUID,
    request: Request,
    response: Response,
    context: Context,
    engine: Database,
    object_store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
) -> dict[str, Any]:
    from starlette.concurrency import run_in_threadpool

    from app.domain.documents import MAX_DOCUMENT_BYTES

    no_store(response)
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_DOCUMENT_BYTES:
            raise HTTPException(413, detail={"message": "单文件不能超过20 MiB"})
    try:
        return await run_in_threadpool(
            ProductSourceFiles(engine, object_store).upload,
            context,
            space_id,
            file_id,
            bytes(content),
        )
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/source-files/{file_id}/parse")
def parse_product_source_file(
    space_id: UUID,
    file_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    object_store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductSourceFiles(engine, object_store).parse(context, space_id, file_id)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/source-files/{file_id}/revoke")
def revoke_product_source_file(
    space_id: UUID, file_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductSourceFiles(engine).revoke(context, space_id, file_id)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/rfq-ai-finding")
def rfq_ai_finding(
    space_id: UUID, body: RfqRead, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductRfqRequirements(engine).read(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/spaces/{space_id}/rfq-ai-confirm")
def rfq_ai_confirm(
    space_id: UUID, body: RfqConfirm, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductRfqRequirements(engine).confirm(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error
