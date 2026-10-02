"""Calendar configuration and scenario calculations without baseline mutation."""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import Engine

from app.ai.executive_brief_preparation import ExecutivePreparationService
from app.ai.executive_brief_runs import History as ExecutiveBriefHistory
from app.ai.executive_brief_runs import Request as ExecutiveBriefRequest
from app.ai.portfolio_explanation_runs import Request as PortfolioExplanationRequest
from app.api.auth import no_store
from app.api.product_workspace import Context, Database
from app.auth.repository import AuthContext
from app.contracts.executive_brief import ExecutiveSelection
from app.contracts.portfolio_explanation import Selection as PortfolioExplanationSelection
from app.domain import (
    approval_responsibilities,
    id_design_responsibilities,
    reservation_owner_transfers,
)
from app.domain.baseline_change_application import BaselineApplicationService, BaselineApply
from app.domain.baseline_changes import (
    BaselineChangeDraft,
    BaselineChangeService,
    BaselineDecision,
    BaselinePolicyDraft,
)
from app.domain.certification_execution import (
    CertificationAction,
    CertificationExecutionService,
    RecertificationDraft,
)
from app.domain.cross_project_schedule import CrossProjectProposal, CrossProjectScheduleService
from app.domain.cross_project_schedule_application import (
    CrossProjectApplicationService,
    CrossProjectApply,
)
from app.domain.forecast_capacity import ForecastCapacityService
from app.domain.id_design import (
    DesignFeedbackDecision,
    DesignFeedbackDraft,
    DesignRevisionDraft,
    IdDesignService,
)
from app.domain.id_design_activation import IdActivationDraft, IdDesignActivationService
from app.domain.id_design_changes import IdChangeDisposition, IdDesignChangeService
from app.domain.id_design_checkpoints import IdCheckpointBinding, IdDesignCheckpointService
from app.domain.id_design_freeze import (
    IdDesignFreezeService,
    IdFreezeApply,
    IdFreezeDecision,
    IdFreezeRequest,
)
from app.domain.id_design_handoff import IdDesignHandoffService, IdHandoffResponse, IdHandoffSubmit
from app.domain.id_design_revision_branch import IdChangeBranchDraft, IdDesignRevisionBranchService
from app.domain.initial_plan_application import InitialPlanApplicationService, InitialPlanApply
from app.domain.initial_plan_reviews import (
    InitialPlanReviewService,
    PlanReviewAction,
    PlanReviewDraft,
)
from app.domain.milestone_designations import (
    DesignationHistory,
    MilestoneDesignation,
    MilestoneDesignationService,
)
from app.domain.plan_responsibilities import PlanResponsibilityService, ResponsibilityResponse
from app.domain.plan_scenarios import CalendarDraft, PlanScenarioService, ScenarioDraft
from app.domain.portfolio_application_plan import (
    PortfolioApplicationPlanService,
    PortfolioApplicationPreview,
)
from app.domain.portfolio_applications import PortfolioApplicationService, PortfolioApply
from app.domain.portfolio_comparisons import PortfolioComparisonService
from app.domain.portfolio_control_queue import ControlQueueRead, PortfolioControlQueue
from app.domain.portfolio_escalations import (
    EscalationDraft,
    EscalationHistory,
    EscalationRead,
    EscalationReply,
    EscalationSave,
    EscalationSource,
    PortfolioEscalationService,
)
from app.domain.portfolio_execution_preparations import (
    PortfolioExecutionPreparation,
    PortfolioExecutionPreparationService,
)
from app.domain.portfolio_health import HealthRead, PortfolioHealthService
from app.domain.portfolio_health_overview import HealthOverview, PortfolioHealthOverviewService
from app.domain.portfolio_health_policy import HealthPolicy, HealthPolicyService
from app.domain.portfolio_materials import (
    MaterialDetail,
    MaterialOverview,
    PortfolioMaterialService,
)
from app.domain.portfolio_milestones import (
    MilestoneHistory,
    MilestoneRead,
    PortfolioMilestoneService,
)
from app.domain.portfolio_product_pipeline import (
    OpportunityPipeline,
    PortfolioProductPipelineService,
    ReviewQueue,
)
from app.domain.portfolio_progress import (
    PortfolioProgressService,
    ProgressDetail,
    ProgressForecastHistory,
    ProgressRead,
)
from app.domain.portfolio_resources import (
    PortfolioResourceService,
    ResourceDetail,
    ResourceOverview,
)
from app.domain.portfolio_scoring import (
    PortfolioComparison,
    PortfolioComparisonSave,
    PortfolioPolicy,
)
from app.domain.portfolio_selections import (
    PortfolioSelectionDecision,
    PortfolioSelectionDraft,
    PortfolioSelectionSave,
    PortfolioSelectionService,
)
from app.domain.portfolio_suppliers import (
    PortfolioSupplierService,
    SupplierDetail,
    SupplierOverview,
)
from app.domain.product_workspace import ProductWorkAccessError
from app.domain.project_execution import (
    ExecutionAction,
    ExecutionPolicyDraft,
    ExecutionRequestDraft,
    ProjectExecutionService,
)
from app.domain.project_resource_schedules import (
    ProjectResourceScheduleService,
    ResourceScheduleDraft,
)
from app.domain.project_scenario_capacity import ProjectScenarioCapacityService
from app.domain.project_schedule_scenarios import (
    ProjectScenarioDraft,
    ProjectScheduleScenarioService,
)
from app.domain.reservation_replacements import (
    ReservationReplacement,
    ReservationReplacementService,
)
from app.domain.resource_allocation_release import Release as AllocationRelease
from app.domain.resource_capacity import (
    CapacityCheckDraft,
    CapacityDraft,
    ResourceCapacityService,
    ResourceDraft,
)
from app.domain.resource_inventory import ReconciliationDraft, ResourceInventoryService
from app.domain.resource_priorities import PriorityDraft, ResourcePriorityService
from app.domain.resource_reallocation_inputs import (
    ReallocationApply,
    ReallocationDecision,
    ReallocationDraft,
    ReallocationReview,
    ReallocationSubmit,
)
from app.domain.resource_reallocations import ResourceReallocationService
from app.domain.resource_reservations import (
    ReservationAction,
    ReservationDraft,
    ResourceReservationService,
)
from app.domain.resource_schedule_preparations import (
    ResourceSchedulePreparation,
    ResourceSchedulePreparationService,
)
from app.domain.schedule_actual_corrections import ActualCorrection, ActualCorrectionService
from app.domain.schedule_commitments import (
    CommitmentConfirm,
    CommitmentPolicyDraft,
    ScheduleCommitmentService,
)
from app.domain.schedule_execution import ScheduleExecutionService
from app.domain.schedule_forecasts import ForecastDraft, ScheduleForecastService
from app.domain.schedule_milestones import MilestoneComplete, ScheduleMilestoneService
from app.domain.schedule_nodes import NodeDraft, ScheduleNodeService
from app.domain.schedule_source_corrections import (
    SourceActualCorrection,
    SourceActualCorrectionService,
)

router = APIRouter(tags=["planning-scenarios"])


def failure(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=403 if isinstance(error, ProductWorkAccessError) else 409,
        detail={"code": "PLANNING_INPUT_UNAVAILABLE", "message": str(error)},
    )


@router.get("/api/planning/calendars")
def calendars(response: Response, context: Context, engine: Database) -> dict[str, Any]:
    no_store(response)
    try:
        return PlanScenarioService(engine).calendars(context)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/calendars")
def calendar_publish(
    payload: CalendarDraft, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PlanScenarioService(engine).publish_calendar(context, payload)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/initial-plans/{candidate_id}/scenarios")
def scenarios(
    candidate_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PlanScenarioService(engine).list(context, candidate_id)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/initial-plans/{candidate_id}/scenarios")
def calculate(
    candidate_id: UUID,
    payload: ScenarioDraft,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return PlanScenarioService(engine).calculate(context, candidate_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/initial-plans/{candidate_id}/responsibilities")
def responsibilities(
    candidate_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PlanResponsibilityService(engine).get(context, candidate_id)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/initial-plans/{candidate_id}/responsibilities")
def responsibility_respond(
    candidate_id: UUID,
    payload: ResponsibilityResponse,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return PlanResponsibilityService(engine).respond(context, candidate_id, payload)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/planning/resources")
def planning_resources(response: Response, context: Context, engine: Database) -> dict[str, Any]:
    no_store(response)
    try:
        return ResourceCapacityService(engine).list(context)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/resources")
def planning_resource_create(
    payload: ResourceDraft, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResourceCapacityService(engine).create(context, payload)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/capacities")
def resource_capacity_publish(
    payload: CapacityDraft, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResourceCapacityService(engine).publish(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/initial-plans/{candidate_id}/scenarios/{scenario_id}/capacity-checks")
def plan_capacity_checks(
    candidate_id: UUID, scenario_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResourceCapacityService(engine).checks(context, candidate_id, scenario_id)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/initial-plans/{candidate_id}/scenarios/{scenario_id}/capacity-checks")
def plan_capacity_check(
    candidate_id: UUID,
    scenario_id: UUID,
    payload: CapacityCheckDraft,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResourceCapacityService(engine).check(context, candidate_id, scenario_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/resource-reservations")
def resource_reservations(
    project_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    target_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResourceReservationService(engine).list(context, project_id, target_id=target_id)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/resource-reservations")
def reservation_propose(
    project_id: UUID,
    payload: ReservationDraft,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResourceReservationService(engine).propose(context, project_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/resource-reservations/{reservation_id}")
def reservation_action(
    project_id: UUID,
    reservation_id: UUID,
    payload: ReservationAction,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResourceReservationService(engine).act(context, project_id, reservation_id, payload)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/resource-reservations/{reservation_id}")
def reservation_history(
    project_id: UUID, reservation_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResourceReservationService(engine).history(context, project_id, reservation_id)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/resource-inventory")
def resource_inventory(
    project_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResourceInventoryService(engine).list(context, project_id)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/resource-inventory/{resource_id}/release")
def resource_allocation_read(
    project_id: UUID,
    resource_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    before_id: int | None = None,
) -> dict[str, Any]:
    from app.domain.resource_allocation_release import read

    no_store(response)
    try:
        return read(engine, context, project_id, resource_id, before_id)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/resource-inventory/{resource_id}/release")
def resource_allocation_release(
    project_id: UUID,
    resource_id: UUID,
    payload: AllocationRelease,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    from app.domain.resource_allocation_release import release

    no_store(response)
    try:
        return release(engine, context, project_id, resource_id, payload)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/resource-inventory")
def resource_reconcile(
    project_id: UUID,
    payload: ReconciliationDraft,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResourceInventoryService(engine).reconcile(context, project_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/initial-plans/{candidate_id}/reviews")
def initial_plan_reviews(
    candidate_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return InitialPlanReviewService(engine).list(context, candidate_id)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/initial-plans/{candidate_id}/reviews")
def initial_plan_review_prepare(
    candidate_id: UUID,
    payload: PlanReviewDraft,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return InitialPlanReviewService(engine).prepare(context, candidate_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/initial-plans/{candidate_id}/reviews/{review_id}")
def initial_plan_review_action(
    candidate_id: UUID,
    review_id: UUID,
    payload: PlanReviewAction,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return InitialPlanReviewService(engine).act(context, candidate_id, review_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/execution")
def project_execution(
    project_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    target_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectExecutionService(engine).list(context, project_id, target_id=target_id)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/policies")
def execution_policy_publish(
    project_id: UUID,
    payload: ExecutionPolicyDraft,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectExecutionService(engine).publish_policy(context, project_id, payload)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/requests")
def execution_request_prepare(
    project_id: UUID,
    payload: ExecutionRequestDraft,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectExecutionService(engine).prepare(context, project_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/requests/{execution_id}")
def execution_request_action(
    project_id: UUID,
    execution_id: UUID,
    payload: ExecutionAction,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectExecutionService(engine).act(context, project_id, execution_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/execution/application")
def initial_plan_application(
    project_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return InitialPlanApplicationService(engine).get(context, project_id)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/application")
def initial_plan_apply(
    project_id: UUID,
    payload: InitialPlanApply,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return InitialPlanApplicationService(engine).apply(context, project_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/execution/readiness")
def schedule_execution_readiness(
    project_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ScheduleExecutionService(engine).get(context, project_id)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/execution/forecasts")
def schedule_forecasts(
    project_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    record_id: UUID | None = None,
    before: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ScheduleForecastService(engine).get(
            context, project_id, record_id=record_id, before=before, limit=limit
        )
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/forecasts")
def schedule_forecast_recalculate(
    project_id: UUID, payload: ForecastDraft, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ScheduleForecastService(engine).recalculate(context, project_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/execution/forecasts/{record_id}/capacity-checks")
def forecast_capacity_checks(
    project_id: UUID, record_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ForecastCapacityService(engine).list(context, project_id, record_id)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/forecasts/{record_id}/capacity-checks")
def forecast_capacity_check(
    project_id: UUID,
    record_id: UUID,
    payload: CapacityCheckDraft,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ForecastCapacityService(engine).check(context, project_id, record_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/execution/commitments")
def schedule_commitments(
    project_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ScheduleCommitmentService(engine).get(context, project_id)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/commitments/policies")
def commitment_policy_publish(
    project_id: UUID,
    payload: CommitmentPolicyDraft,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ScheduleCommitmentService(engine).publish_policy(context, project_id, payload)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/commitments")
def commitment_confirm(
    project_id: UUID,
    payload: CommitmentConfirm,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ScheduleCommitmentService(engine).confirm(context, project_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/resource-reservations/{reservation_id}/replacement")
def reservation_replace(
    project_id: UUID,
    reservation_id: UUID,
    payload: ReservationReplacement,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ReservationReplacementService(engine).replace(
            context, project_id, reservation_id, payload
        )
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/execution/actual-corrections")
def schedule_actual_corrections(
    project_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ActualCorrectionService(engine).get(context, project_id)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/actual-corrections")
def schedule_actual_correct(
    project_id: UUID,
    payload: ActualCorrection,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ActualCorrectionService(engine).correct(context, project_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/execution/nodes")
def schedule_nodes_list(
    project_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ScheduleNodeService(engine).get(context, project_id)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/nodes")
def schedule_node_register(
    project_id: UUID, payload: NodeDraft, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ScheduleNodeService(engine).register(context, project_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/execution/scenarios")
def project_schedule_scenarios(
    project_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    target_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectScheduleScenarioService(engine).get(context, project_id, target_id)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/scenarios")
def project_schedule_scenario_evaluate(
    project_id: UUID,
    payload: ProjectScenarioDraft,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectScheduleScenarioService(engine).evaluate(context, project_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/execution/scenarios/{scenario_id}/capacity-checks")
def project_scenario_capacity_checks(
    project_id: UUID, scenario_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectScenarioCapacityService(engine).list(context, project_id, scenario_id)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/scenarios/{scenario_id}/capacity-checks")
def project_scenario_capacity_check(
    project_id: UUID,
    scenario_id: UUID,
    payload: CapacityCheckDraft,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectScenarioCapacityService(engine).check(
            context, project_id, scenario_id, payload
        )
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/execution/baseline-changes")
def baseline_changes(
    project_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    target_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return BaselineChangeService(engine).get(context, project_id, target_id=target_id)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/baseline-changes/policies")
def baseline_policy(
    project_id: UUID,
    payload: BaselinePolicyDraft,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return BaselineChangeService(engine).publish_policy(context, project_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/baseline-changes")
def baseline_change_prepare(
    project_id: UUID,
    payload: BaselineChangeDraft,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return BaselineChangeService(engine).prepare(context, project_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/baseline-changes/{change_id}")
def baseline_change_decide(
    project_id: UUID,
    change_id: UUID,
    payload: BaselineDecision,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return BaselineChangeService(engine).decide(context, project_id, change_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/baseline-changes/{change_id}/application")
def baseline_change_apply(
    project_id: UUID,
    change_id: UUID,
    payload: BaselineApply,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return BaselineApplicationService(engine).apply(context, project_id, change_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/execution/milestones")
def schedule_milestones(
    project_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ScheduleMilestoneService(engine).get(context, project_id)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/milestones/{node_id}")
def complete_schedule_milestone(
    project_id: UUID,
    node_id: UUID,
    payload: MilestoneComplete,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ScheduleMilestoneService(engine).complete(context, project_id, node_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/execution/certifications")
def certification_execution(
    project_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return CertificationExecutionService(engine).get(context, project_id)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/certifications/{certification_id}")
def certification_action(
    project_id: UUID,
    certification_id: UUID,
    payload: CertificationAction,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return CertificationExecutionService(engine).act(
            context, project_id, certification_id, payload
        )
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post(
    "/api/projects/{project_id}/execution/certifications/{certification_id}/recertification"
)
def recertification(
    project_id: UUID,
    certification_id: UUID,
    payload: RecertificationDraft,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return CertificationExecutionService(engine).recertify(
            context, project_id, certification_id, payload
        )
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/execution/source-actual-corrections")
def source_actual_corrections(
    project_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return SourceActualCorrectionService(engine).get(context, project_id)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/source-actual-corrections/{node_id}")
def correct_source_actual(
    project_id: UUID,
    node_id: UUID,
    payload: SourceActualCorrection,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return SourceActualCorrectionService(engine).correct(context, project_id, node_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/execution/cross-project-dependencies")
def cross_project_dependencies(
    project_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return CrossProjectScheduleService(engine).get(context, project_id)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/cross-project-dependencies")
def cross_project_prepare(
    project_id: UUID,
    payload: CrossProjectProposal,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return CrossProjectScheduleService(engine).prepare(context, project_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/cross-project-dependencies/{proposal_id}")
def cross_project_decide(
    project_id: UUID,
    proposal_id: UUID,
    payload: BaselineDecision,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return CrossProjectScheduleService(engine).decide(context, project_id, proposal_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post(
    "/api/projects/{project_id}/execution/cross-project-dependencies/{proposal_id}/application"
)
def cross_project_apply(
    project_id: UUID,
    proposal_id: UUID,
    payload: CrossProjectApply,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return CrossProjectApplicationService(engine).apply(
            context, project_id, proposal_id, payload
        )
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/execution/cross-project-dependencies/{proposal_id}")
def cross_project_proposal_detail(
    project_id: UUID, proposal_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return CrossProjectScheduleService(engine).get(context, project_id, proposal_id=proposal_id)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/execution/id-design")
def id_design_get(
    project_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return IdDesignService(engine).get(context, project_id)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/id-design")
def id_design_revise(
    project_id: UUID,
    payload: DesignRevisionDraft,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return IdDesignService(engine).revise(context, project_id, payload)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/id-design/revisions/{revision_id}/feedback")
def id_design_feedback(
    project_id: UUID,
    revision_id: UUID,
    payload: DesignFeedbackDraft,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return IdDesignService(engine).feedback(context, project_id, revision_id, payload)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/id-design/feedback/{feedback_id}")
def id_design_decide(
    project_id: UUID,
    feedback_id: UUID,
    payload: DesignFeedbackDecision,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return IdDesignService(engine).decide(context, project_id, feedback_id, payload)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/execution/id-design/freezes")
def id_freezes_get(
    project_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return IdDesignFreezeService(engine).get(context, project_id)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/id-design/freezes")
def id_freezes_prepare(
    project_id: UUID,
    payload: IdFreezeRequest,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return IdDesignFreezeService(engine).prepare(context, project_id, payload)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/id-design/freezes/{freeze_request_id}/decisions")
def id_freezes_decide(
    project_id: UUID,
    freeze_request_id: UUID,
    payload: IdFreezeDecision,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return IdDesignFreezeService(engine).decide(context, project_id, freeze_request_id, payload)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post(
    "/api/projects/{project_id}/execution/id-design/freezes/{freeze_request_id}/application"
)
def id_freezes_apply(
    project_id: UUID,
    freeze_request_id: UUID,
    payload: IdFreezeApply,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return IdDesignFreezeService(engine).apply(context, project_id, freeze_request_id, payload)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/execution/id-design/handoffs")
def id_handoffs_get(
    project_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return IdDesignHandoffService(engine).get(context, project_id)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/id-design/handoffs")
def id_handoffs_submit(
    project_id: UUID,
    payload: IdHandoffSubmit,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return IdDesignHandoffService(engine).submit(context, project_id, payload)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/id-design/handoffs/items/{item_id}")
def id_handoffs_respond(
    project_id: UUID,
    item_id: UUID,
    payload: IdHandoffResponse,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return IdDesignHandoffService(engine).respond(context, project_id, item_id, payload)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/execution/id-design/revisions/{revision_id}")
def id_design_revision_context(
    project_id: UUID, revision_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return IdDesignService(engine).revision_context(context, project_id, revision_id)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/id-design/changes/{candidate_id}")
def id_design_change_decide(
    project_id: UUID,
    candidate_id: UUID,
    payload: IdChangeDisposition,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return IdDesignChangeService(engine).decide(context, project_id, candidate_id, payload)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/id-design/changes/{candidate_id}/revision")
def id_design_change_branch(
    project_id: UUID,
    candidate_id: UUID,
    payload: IdChangeBranchDraft,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return IdDesignRevisionBranchService(engine).prepare(
            context, project_id, candidate_id, payload
        )
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/id-design/freezes/{freeze_id}/activation")
def id_design_activate(
    project_id: UUID,
    freeze_id: UUID,
    payload: IdActivationDraft,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return IdDesignActivationService(engine).apply(context, project_id, freeze_id, payload)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/execution/id-design/checkpoints")
def id_checkpoints_get(
    project_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return IdDesignCheckpointService(engine).get(context, project_id)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/id-design/checkpoints/{node_id}")
def id_checkpoint_bind(
    project_id: UUID,
    node_id: UUID,
    payload: IdCheckpointBinding,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return IdDesignCheckpointService(engine).bind(context, project_id, node_id, payload)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/resource-reservations/{reservation_id}/owner-transfer")
def reservation_owner_get(
    project_id: UUID,
    reservation_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    before_id: int | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return reservation_owner_transfers.read(
            engine, context, project_id, reservation_id, before_id
        )
    except (ValueError, ProductWorkAccessError) as exc:
        raise failure(exc) from exc


@router.post("/api/projects/{project_id}/resource-reservations/{reservation_id}/owner-transfer")
def reservation_owner_post(
    project_id: UUID,
    reservation_id: UUID,
    payload: reservation_owner_transfers.Reassign,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return reservation_owner_transfers.transfer(
            engine, context, project_id, reservation_id, payload
        )
    except (ValueError, ProductWorkAccessError) as exc:
        raise failure(exc) from exc


@router.get("/api/projects/{project_id}/execution/id-design/revisions/{revision_id}/responsibility")
def get_id_design_responsibility(
    project_id: UUID,
    revision_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    before_id: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return id_design_responsibilities.read(engine, context, project_id, revision_id, before_id)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post(
    "/api/projects/{project_id}/execution/id-design/revisions/{revision_id}/responsibility"
)
def reassign_id_design_responsibility(
    project_id: UUID,
    revision_id: UUID,
    payload: id_design_responsibilities.Reassign,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return id_design_responsibilities.reassign(
            engine, context, project_id, revision_id, payload
        )
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/execution/approval-responsibilities/{kind}/{policy_id}")
def get_approval_responsibility(
    project_id: UUID,
    kind: approval_responsibilities.Kind,
    policy_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    before_version: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return approval_responsibilities.read(
            engine, context, project_id, kind, policy_id, before_version
        )
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/planning/resource-priorities")
def resource_priorities(
    response: Response,
    context: Context,
    engine: Database,
    resource_id: UUID,
    before: int | None = Query(default=None, ge=1),
    search: str | None = Query(default=None, max_length=256),
    queue_before: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResourcePriorityService(engine).get(
            context, resource_id, before, search, queue_before
        )
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/resource-priorities")
def resource_priority_publish(
    payload: PriorityDraft, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResourcePriorityService(engine).save(context, payload)
    except (ValueError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/execution/scenarios/{scenario_id}/resource-schedules")
def project_resource_schedules(
    project_id: UUID,
    scenario_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    before: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectResourceScheduleService(engine).list(context, project_id, scenario_id, before)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/scenarios/{scenario_id}/resource-schedules")
def project_resource_schedule(
    project_id: UUID,
    scenario_id: UUID,
    payload: ResourceScheduleDraft,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectResourceScheduleService(engine).solve(
            context, project_id, scenario_id, payload
        )
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/resource-schedule-preparations")
def resource_schedule_preparation(
    project_id: UUID,
    payload: ResourceSchedulePreparation,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResourceSchedulePreparationService(engine).prepare(context, project_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/execution/resource-reallocation-options")
def reallocation_options(
    project_id: UUID,
    resource_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    search: str = Query(default="", max_length=100),
    before: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResourceReallocationService(engine).options(
            context, project_id, resource_id, search, before
        )
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/projects/{project_id}/execution/resource-reallocations")
def reallocations(
    project_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    before: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResourceReallocationService(engine).list(context, project_id, before)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/resource-reallocation-preview")
def reallocation_preview(
    project_id: UUID,
    payload: ReallocationDraft | ReallocationReview,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        if isinstance(payload, ReallocationReview):
            return ResourceReallocationService(engine).review(context, project_id, payload)
        return ResourceReallocationService(engine).preview(context, project_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/resource-reallocations")
def reallocation_submit(
    project_id: UUID,
    payload: ReallocationSubmit,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResourceReallocationService(engine).submit(context, project_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/resource-reallocation-decisions")
def reallocation_decide(
    project_id: UUID,
    payload: ReallocationDecision,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResourceReallocationService(engine).decide(context, project_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/projects/{project_id}/execution/resource-reallocation-applications")
def reallocation_apply(
    project_id: UUID,
    payload: ReallocationApply,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return ResourceReallocationService(engine).apply(context, project_id, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/planning/portfolio-policies")
def portfolio_policies(
    response: Response,
    context: Context,
    engine: Database,
    before: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioComparisonService(engine).policies(context, before)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/planning/portfolio-options")
def portfolio_options(
    project_id: UUID,
    kind: Literal["schedule", "cost", "evidence"],
    response: Response,
    context: Context,
    engine: Database,
    before: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioComparisonService(engine).options(context, project_id, kind, before)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/planning/portfolio-comparisons")
def portfolio_comparisons(
    response: Response,
    context: Context,
    engine: Database,
    before: UUID | None = None,
    record_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioComparisonService(engine).list(context, before, record_id)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-policies")
def portfolio_publish(
    payload: PortfolioPolicy, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioComparisonService(engine).publish(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-preview")
def portfolio_preview(
    payload: PortfolioComparison, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioComparisonService(engine).preview(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-comparisons")
def portfolio_save(
    payload: PortfolioComparisonSave, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioComparisonService(engine).save(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/planning/portfolio-selections")
def portfolio_selection_list(
    project_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    before: UUID | None = None,
    selection_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioSelectionService(engine).list(
            context, project_id, before=before, identity=selection_id
        )
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-selection-preview")
def portfolio_selection_preview(
    payload: PortfolioSelectionDraft, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioSelectionService(engine).preview(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-selections")
def portfolio_selection_submit(
    payload: PortfolioSelectionSave, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioSelectionService(engine).submit(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-selection-decisions")
def portfolio_selection_decide(
    payload: PortfolioSelectionDecision, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioSelectionService(engine).decide(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-execution-preparations")
def portfolio_execution_prepare(
    payload: PortfolioExecutionPreparation, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioExecutionPreparationService(engine).prepare(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-application-preview")
def portfolio_application_preview(
    payload: PortfolioApplicationPreview, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioApplicationPlanService(engine).preview(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-applications")
def portfolio_apply(
    payload: PortfolioApply, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioApplicationService(engine).apply(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


def portfolio_explanation_project(
    engine: Engine, context: AuthContext, comparison_id: UUID
) -> UUID:
    from app.domain.portfolio_comparisons import readable
    from app.domain.portfolio_selections import comparison

    with engine.connect() as c:
        saved = comparison(c, context, comparison_id)
        readable(c, context, saved["inputs"])
        return min(UUID(p["project_id"]) for p in saved["inputs"]["projects"])


@router.post("/api/planning/portfolio-explanation-context")
def portfolio_explanation_context(
    payload: PortfolioExplanationSelection, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    from app.ai.portfolio_explanation_preparation import source_state

    no_store(response)
    try:
        project = portfolio_explanation_project(engine, context, payload.comparison_id)
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
            return source_state(c, context.tenant.id, project, payload, context.user.id)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/planning/portfolio-explanation-runs")
def portfolio_explanation_runs(
    comparison_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    before_id: UUID | None = None,
    run_id: UUID | None = None,
) -> dict[str, Any]:
    from app.ai.portfolio_explanation_runs import PortfolioExplanationRuns

    no_store(response)
    try:
        project = portfolio_explanation_project(engine, context, comparison_id)
        return PortfolioExplanationRuns.list_results(
            engine,
            context=context,
            project_id=project,
            comparison_id=comparison_id,
            before_id=before_id,
            run_id=run_id,
        )
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-explanation-runs")
def create_portfolio_explanation(
    payload: PortfolioExplanationRequest, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    from app.ai.application_gateway import configured_application_gateway
    from app.ai.budget_ledger import BudgetLedgerError
    from app.ai.portfolio_explanation_runs import KEY, PortfolioExplanationRuns
    from app.ai.rollout_guard import CapabilityUnavailableError, require_live_key

    no_store(response)
    try:
        project = portfolio_explanation_project(engine, context, payload.selection.comparison_id)
        require_live_key(KEY)
        with configured_application_gateway(engine) as gateway:
            return PortfolioExplanationRuns(engine, gateway=gateway).create(
                context=context, project_id=project, request=payload
            )
    except (BudgetLedgerError, CapabilityUnavailableError) as error:
        raise HTTPException(
            409,
            detail={
                "code": error.code,
                "message": "组合解释能力、预算或授权尚未就绪；原比较与运行保留",
            },
        ) from error
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.get("/api/planning/portfolio-health-policies")
def portfolio_health_policies(
    response: Response, context: Context, engine: Database, before: int | None = None
) -> dict[str, Any]:
    no_store(response)
    try:
        return HealthPolicyService(engine).get(context, before)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-health-policies")
def portfolio_health_policy_publish(
    payload: HealthPolicy, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return HealthPolicyService(engine).publish(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-health")
def portfolio_health_read(
    payload: HealthRead, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioHealthService(engine).read(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-control-queue")
def portfolio_control_queue(
    payload: ControlQueueRead, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioControlQueue(engine).read(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-progress")
def portfolio_progress(
    payload: ProgressRead, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioProgressService(engine).read(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-progress-nodes")
def portfolio_progress_nodes(
    payload: ProgressDetail, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioProgressService(engine).detail(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-forecast-history")
def portfolio_forecast_history(
    payload: ProgressForecastHistory, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioProgressService(engine).history(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-suppliers")
def portfolio_suppliers(
    payload: SupplierOverview, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioSupplierService(engine).read(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-supplier-detail")
def portfolio_supplier_detail(
    payload: SupplierDetail, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioSupplierService(engine).detail(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/executive-brief-history")
def executive_brief_history(
    payload: ExecutiveBriefHistory, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    from app.ai.executive_brief_runs import ExecutiveBriefRuns

    no_store(response)
    try:
        return ExecutiveBriefRuns.list_results(
            engine,
            context=context,
            project_id=min(payload.selection.project_ids),
            selection=payload.selection,
            before_id=payload.before_id,
            run_id=payload.run_id,
        )
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/executive-brief-runs")
def create_executive_brief(
    payload: ExecutiveBriefRequest, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    from app.ai.application_gateway import configured_application_gateway
    from app.ai.budget_ledger import BudgetLedgerError
    from app.ai.executive_brief_runs import KEY, ExecutiveBriefRuns
    from app.ai.rollout_guard import CapabilityUnavailableError, require_live_key

    no_store(response)
    try:
        require_live_key(KEY)
        with configured_application_gateway(engine) as gateway:
            return ExecutiveBriefRuns(engine, gateway=gateway).create(
                context=context,
                project_id=min(payload.selection.project_ids),
                request=payload,
            )
    except (BudgetLedgerError, CapabilityUnavailableError) as error:
        raise HTTPException(
            409,
            detail={
                "code": error.code,
                "message": "管理摘要能力、预算或授权尚未就绪；原资料与运行保留",
            },
        ) from error
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/executive-brief-context")
def executive_brief_context(
    payload: ExecutiveSelection, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ExecutivePreparationService(engine).read(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/milestone-designations")
def milestone_designations(
    payload: MilestoneDesignation, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return MilestoneDesignationService(engine).save(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/milestone-designation-history")
def milestone_designation_history(
    payload: DesignationHistory, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return MilestoneDesignationService(engine).history(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-milestones")
def portfolio_milestones(
    payload: MilestoneRead, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioMilestoneService(engine).read(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-milestone-history")
def portfolio_milestone_history(
    payload: MilestoneHistory, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioMilestoneService(engine).history(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-health-overview")
def portfolio_health_overview(
    payload: HealthOverview, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioHealthOverviewService(engine).read(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-escalation-options")
def portfolio_escalation_options(
    payload: EscalationSource, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioEscalationService(engine).options(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-escalation-preview")
def portfolio_escalation_preview(
    payload: EscalationDraft, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioEscalationService(engine).preview(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-escalation-requests")
def portfolio_escalation_requests(
    payload: EscalationSave, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioEscalationService(engine).save(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-escalation-replies")
def portfolio_escalation_replies(
    payload: EscalationReply, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioEscalationService(engine).reply(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-escalations")
def portfolio_escalations(
    payload: EscalationRead, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioEscalationService(engine).read(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-escalation-history")
def portfolio_escalation_history(
    payload: EscalationHistory, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioEscalationService(engine).history(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-materials")
def portfolio_materials(
    payload: MaterialOverview, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioMaterialService(engine).read(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-material-detail")
def portfolio_material_detail(
    payload: MaterialDetail, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioMaterialService(engine).detail(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-opportunities")
def portfolio_opportunities(
    payload: OpportunityPipeline, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioProductPipelineService(engine).opportunities(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-case-reviews")
def portfolio_case_reviews(
    payload: ReviewQueue, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioProductPipelineService(engine).reviews(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-resources")
def portfolio_resources(
    payload: ResourceOverview, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioResourceService(engine).read(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error


@router.post("/api/planning/portfolio-resource-detail")
def portfolio_resource_detail(
    payload: ResourceDetail, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return PortfolioResourceService(engine).detail(context, payload)
    except (ValueError, OverflowError, ProductWorkAccessError) as error:
        raise failure(error) from error
