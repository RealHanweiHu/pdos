"""Tenant- and project-bound NPI execution HTTP boundary."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError

from app.ai.budget_ledger import BudgetLedgerError
from app.ai.cost_reduction_runs import Request as CostReductionRequest
from app.ai.gateway import StructuredModelGateway
from app.ai.import_mapping_runs import ImportMappingRunError
from app.ai.report_import_queue import ReportImportQueue
from app.ai.rollout_guard import CapabilityUnavailableError
from app.ai.supplier_recovery_preparation import Selection as SupplierRecoverySelection
from app.ai.supplier_recovery_preparation import SupplierRecoveryPreparation
from app.ai.supplier_recovery_runs import Request as SupplierRecoveryRequest
from app.ai.test_plan_queue import TestPlanQueue
from app.ai.test_plan_suggestions import TestPlanSuggestionService
from app.api.ai import get_application_gateway
from app.api.auth import current_context, no_store
from app.api.work_items import authorize_project
from app.auth.errors import ObjectPermissionDeniedError
from app.auth.repository import AuthContext
from app.auth.roles import Action, Role
from app.contracts.cost_reduction import Preparation as CostReductionPreparation
from app.contracts.cost_reduction import Selection as CostReductionSelection
from app.db.engine import get_engine
from app.db.schema import tables
from app.domain.build_material_changes import (
    BuildMaterialChangeService,
    MaterialRevisionApply,
    MaterialRevisionSelection,
)
from app.domain.build_materials import (
    BuildMaterialError,
    BuildMaterialService,
    MaterialFreeze,
    MaterialSelection,
)
from app.domain.change_compliance import ChangeComplianceService
from app.domain.change_compliance import ReviewDraft as ChangeComplianceReview
from app.domain.cost_alternatives import AlternativeDraft, AlternativeSave, CostAlternativeService
from app.domain.cost_backtests import BacktestDraft, BacktestSave, CostBacktestService
from app.domain.cost_definition_feedback import (
    CostDefinitionFeedbackService,
    DispositionDraft,
    DispositionSave,
    FeedbackDraft,
    FeedbackSave,
)
from app.domain.cost_definition_feedback import SourceKind as CostFeedbackSourceKind
from app.domain.cost_freezes import (
    CostFreezeService,
    FreezeDecide,
    FreezeDecision,
    FreezeDraft,
    FreezeRequest,
)
from app.domain.cost_gaps import CostGapService, GapDraft, GapObservation, GapObserve, GapSave
from app.domain.cost_imports import (
    CostImportConfirm,
    CostImportDraft,
    CostImportInspect,
    CostImportService,
)
from app.domain.cost_inputs import (
    CostInputService,
)
from app.domain.cost_inputs import (
    InputApply as CostInputApply,
)
from app.domain.cost_inputs import (
    InputPreview as CostInputPreview,
)
from app.domain.cost_rollups import CostRollupService, RollupDraft, RollupSave
from app.domain.document_previews import DocumentPreviewError, DocumentPreviewMissing
from app.domain.documents import DocumentError
from app.domain.firmware_package_tasks import PackageTaskDraft
from app.domain.firmware_task_results import ResultDraft as FirmwareResultDraft
from app.domain.firmware_work_packages import FirmwarePackageDraft
from app.domain.firmware_work_packages import SourceKind as FirmwareSourceKind
from app.domain.knowledge_push import KnowledgeAccessError
from app.domain.material_admission import (
    MaterialAdmissionBlocked,
    MaterialAdmissionService,
    PolicyDraft,
    TargetKind,
    WaiverDecision,
    WaiverDraft,
)
from app.domain.material_allocations import (
    AllocationApply,
    AllocationRelease,
    AllocationSelection,
    MaterialAllocationError,
    MaterialAllocationService,
)
from app.domain.material_corrections import (
    CorrectionApply,
    CorrectionDraft,
    MaterialCorrectionService,
)
from app.domain.material_coverage import CoverageSelection, MaterialCoverageService
from app.domain.material_exceptions import (
    ExceptionCreate,
    ExceptionReview,
    MaterialExceptionService,
)
from app.domain.material_exposure import AttributionDraft, MaterialExposureService
from app.domain.material_movements import (
    MaterialMovementService,
    MaterialReconciliationService,
    MovementApply,
    MovementDraft,
    ReconciliationDraft,
)
from app.domain.material_schedule import BindingDraft, MaterialScheduleService
from app.domain.npi_execution import (
    NpiAudienceError,
    NpiConflictError,
    NpiExecutionService,
    NpiNotFoundError,
    NpiScopeError,
    NpiTransitionError,
)
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError
from app.domain.sample_configurations import (
    SampleConfigDraft,
    SampleConfigNotFoundError,
    SampleConfigRecord,
    SampleConfigService,
    SampleConfigValueError,
)
from app.domain.supplier_compliance import (
    ComplianceApply,
    ComplianceDraft,
    SupplierComplianceService,
)
from app.domain.supplier_engineering import (
    EngineeringApply,
    EngineeringDraft,
    SupplierEngineeringService,
)
from app.domain.supplier_notice_applications import ApplicationDraft as NoticeApplicationDraft
from app.domain.supplier_notice_applications import ApplicationSave as NoticeApplicationSave
from app.domain.supplier_notice_applications import SupplierNoticeApplications
from app.domain.supplier_notice_applications import TargetKind as NoticeTargetKind
from app.domain.supplier_notice_dispatches import RetryRequest as NoticeDispatchRetry
from app.domain.supplier_notice_dispatches import SupplierNoticeDispatches
from app.domain.supplier_notice_reviews import ReviewDraft as NoticeReviewDraft
from app.domain.supplier_notice_reviews import ReviewSave as NoticeReviewSave
from app.domain.supplier_notice_reviews import SupplierNoticeReviews
from app.domain.supplier_notice_scans import ScanRequest as NoticeScanRequest
from app.domain.supplier_notice_scans import SupplierNoticeScans
from app.domain.supplier_notice_watches import (
    SupplierNoticeWatches,
)
from app.domain.supplier_notice_watches import (
    WatchApply as NoticeWatchApply,
)
from app.domain.supplier_notice_watches import (
    WatchDraft as NoticeWatchDraft,
)
from app.domain.supplier_recovery_results import (
    ReportApply as RecoveryResultApply,
)
from app.domain.supplier_recovery_results import (
    ReportDraft as RecoveryResultDraft,
)
from app.domain.supplier_recovery_results import (
    SupplierRecoveryResults,
)
from app.domain.supplier_recovery_reviews import (
    ReviewApply as RecoveryReviewApply,
)
from app.domain.supplier_recovery_reviews import (
    ReviewDraft as RecoveryReviewDraft,
)
from app.domain.supplier_recovery_reviews import (
    SupplierRecoveryReviews,
)
from app.domain.supply_imports import (
    InspectSupply,
    SupplyImportConfirm,
    SupplyImportDraft,
    SupplyImportError,
    SupplyImportService,
)
from app.domain.supply_sharing import ShareDecision, ShareOffer, SupplySharingService
from app.domain.test_execution_preparations import PreparationDraft as TestPreparationDraft
from app.domain.test_plan_changes import TestPlanChangeError
from app.domain.test_plan_sources import PlanSourceError, SourceKind, SourceSelection, list_sources
from app.domain.test_report_import import (
    ExcelImportMapping,
    ImportBatchResult,
    ImportError_,
    TestReportImportService,
)
from app.domain.test_runs import (
    TestRunDraft,
    TestRunFactError,
    TestRunNotFoundError,
    TestRunRecord,
    TestRunScopeError,
    TestRunService,
    TestRunStateError,
)
from app.domain.test_templates import TemplateError, TemplateSelection, project_catalog
from app.domain.tooling_rounds import RoundApply, RoundDraft, ToolingRoundService
from app.storage.documents import DocumentObjectStore, get_document_object_store

router = APIRouter(prefix="/api/projects/{project_id}/npi", tags=["npi"])


@router.get("/firmware-work-packages")
def firmware_package_history(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_id: UUID | None = None,
) -> dict[str, Any]:
    from app.domain.firmware_work_packages import FirmwarePackageError, list_packages

    no_store(response)
    try:
        return list_packages(engine, context=context, project_id=project_id, before_id=before_id)
    except FirmwarePackageError as error:
        raise HTTPException(409, detail={"message": str(error)}) from error


@router.get("/firmware-work-packages/current")
def firmware_package_current(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    version: Annotated[str, Query(min_length=1, max_length=64)],
) -> dict[str, Any]:
    from app.domain.firmware_work_packages import current_package

    no_store(response)
    return current_package(engine, context=context, project_id=project_id, version=version.strip())


@router.get("/firmware-work-packages/sources")
def firmware_package_sources(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    kind: FirmwareSourceKind,
    after_id: UUID | None = None,
) -> dict[str, Any]:
    from app.domain.firmware_work_packages import source_options

    no_store(response)
    return source_options(
        engine, context=context, project_id=project_id, kind=kind, after_id=after_id
    )


@router.post("/firmware-work-packages")
def firmware_package_save(
    project_id: UUID,
    body: FirmwarePackageDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.firmware_work_packages import FirmwarePackageError, save

    no_store(response)
    try:
        return save(engine, context=context, project_id=project_id, draft=body)
    except FirmwarePackageError as error:
        raise HTTPException(
            409, detail={"code": "FIRMWARE_PACKAGE_CHANGED", "message": str(error)}
        ) from error


@router.get("/firmware-work-packages/{package_id}/tasks")
def firmware_package_task_read(
    project_id: UUID,
    package_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.firmware_package_tasks import read
    from app.domain.firmware_work_packages import FirmwarePackageError

    no_store(response)
    try:
        return read(engine, context=context, project_id=project_id, package_id=package_id)
    except FirmwarePackageError as error:
        raise HTTPException(409, detail={"message": str(error)}) from error


@router.post("/firmware-work-packages/{package_id}/tasks")
def firmware_package_task_save(
    project_id: UUID,
    package_id: UUID,
    body: PackageTaskDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.firmware_package_tasks import save

    no_store(response)
    try:
        return save(
            engine, context=context, project_id=project_id, package_id=package_id, draft=body
        )
    except (ValueError, LookupError) as error:
        raise HTTPException(
            409,
            detail={
                "code": "FIRMWARE_TASK_CHANGED",
                "message": str(error) or "任务负责人、阶段或日期已变化，请重新核对",
            },
        ) from error


@router.get("/firmware-task-results/{binding_id}")
def firmware_task_result_read(
    project_id: UUID,
    binding_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_revision: Annotated[int | None, Query(gt=0)] = None,
) -> dict[str, Any]:
    from app.domain.firmware_task_results import read
    from app.domain.firmware_work_packages import FirmwarePackageError

    no_store(response)
    try:
        return read(
            engine,
            context=context,
            project_id=project_id,
            binding_id=binding_id,
            before_revision=before_revision,
        )
    except FirmwarePackageError as error:
        raise HTTPException(409, detail={"message": str(error)}) from error


@router.get("/firmware-task-results/{binding_id}/runs")
def firmware_task_result_runs(
    project_id: UUID,
    binding_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    after_id: UUID | None = None,
) -> dict[str, Any]:
    from app.domain.firmware_task_results import run_options
    from app.domain.firmware_work_packages import FirmwarePackageError

    no_store(response)
    try:
        return run_options(
            engine, context=context, project_id=project_id, binding_id=binding_id, after_id=after_id
        )
    except FirmwarePackageError as error:
        raise HTTPException(409, detail={"message": str(error)}) from error


@router.post("/firmware-task-results/{binding_id}")
def firmware_task_result_save(
    project_id: UUID,
    binding_id: UUID,
    body: FirmwareResultDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.firmware_task_results import save
    from app.domain.firmware_work_packages import FirmwarePackageError

    no_store(response)
    try:
        return save(
            engine, context=context, project_id=project_id, binding_id=binding_id, draft=body
        )
    except FirmwarePackageError as error:
        raise HTTPException(
            409, detail={"code": "FIRMWARE_RESULT_CHANGED", "message": str(error)}
        ) from error


class BuildCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage_id: UUID
    phase: Literal["evt", "dvt", "pvt"]
    purpose: Literal[
        "engineering_build",
        "certification_sample",
        "customer_sample",
        "reliability_test",
        "production_trial",
    ] = "engineering_build"
    code: str = Field(min_length=1, max_length=64)
    planned_quantity: int = Field(gt=0)
    notes: str | None = Field(default=None, max_length=20_000)


class BuildUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["in_progress", "completed", "cancelled"]
    completed_quantity: int = Field(ge=0)


class SampleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    serial_number: str = Field(min_length=1, max_length=128)
    parent_sample_id: UUID | None = None
    prototype_bom_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=20_000)


class SampleSignoffCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phase: Literal["evt", "dvt", "pvt"]
    title: str = Field(min_length=1, max_length=512)
    signoff_type: Literal[
        "evt_sample", "dvt_sample", "pvt_sample", "golden_sample", "first_article", "other"
    ]
    audience: Literal["internal", "supplier", "customer"]
    sample_ids: list[UUID] = Field(min_length=1, max_length=100)
    due_date: date | None = None

    @model_validator(mode="after")
    def unique_samples(self) -> SampleSignoffCreateRequest:
        if len(set(self.sample_ids)) != len(self.sample_ids):
            raise ValueError("sample_ids must be unique")
        return self


class SampleSignoffResponseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["approved", "rejected", "waived"]
    note: str | None = Field(default=None, max_length=20_000)


class TestPlanCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage_id: UUID
    phase: Literal["evt", "dvt", "pvt"]
    title: str = Field(min_length=1, max_length=512)
    scope: str | None = Field(default=None, max_length=20_000)
    sample_size: int = Field(gt=0)
    status: Literal["draft", "active"] = "draft"
    template: TemplateSelection | None = None


class TestCaseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=512)
    category: str = Field(min_length=1, max_length=64)
    acceptance_criteria: str = Field(min_length=1, max_length=20_000)
    method: str | None = Field(default=None, max_length=20_000)
    severity: Literal["minor", "major", "critical"] = "major"
    sample_ids: list[UUID] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_samples(self) -> TestCaseCreateRequest:
        if len(set(self.sample_ids)) != len(self.sample_ids):
            raise ValueError("sample_ids must be unique")
        return self


class TestResultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["planned", "passed", "failed", "blocked", "waived"]
    result_notes: str | None = Field(default=None, max_length=20_000)
    related_issue_id: UUID | None = None


class TestReportCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_number: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    result: Literal["pass", "fail", "conditional"]
    summary: str = Field(min_length=1, max_length=20_000)


class TestReportReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_status: Literal["approved", "rejected"]
    note: str | None = Field(default=None, max_length=20_000)


class CertificationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner_user_id: UUID | None = None
    certificate_type: Literal[
        "un38_3",
        "msds",
        "battery_safety",
        "product_safety",
        "component_safety",
        "market_access",
        "regulatory_compliance",
    ]
    certificate_number: str | None = Field(default=None, max_length=256)
    issuing_body: str | None = Field(default=None, max_length=256)
    target_markets: list[str] = Field(default_factory=list, max_length=100)
    status: Literal["draft", "valid", "expired", "revoked"] = "draft"
    is_required: bool = False
    valid_from: date | None = None
    valid_until: date | None = None
    evidence_reference: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def valid_certificate_has_identity(self) -> CertificationCreateRequest:
        if (
            self.valid_until is not None
            and self.valid_from is not None
            and self.valid_until < self.valid_from
        ):
            raise ValueError("valid_until cannot precede valid_from")
        if self.status == "valid" and (not self.certificate_number or self.valid_until is None):
            raise ValueError("valid certification requires certificate_number and valid_until")
        return self


class CertificationScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_of: date


def _clean(value: str | None) -> str | None:
    normalized = value.strip() if value else ""
    return normalized or None


def _access(engine: Engine, context: AuthContext, project_id: UUID, action: Action) -> None:
    authorize_project(engine=engine, context=context, project_id=project_id, action=action)


def _error(error: Exception) -> HTTPException:
    from app.domain.schedule_execution import ScheduleExecutionBlocked

    if isinstance(error, ProductWorkAccessError):
        return HTTPException(
            403, detail={"code": "PRODUCT_WORK_ACCESS_DENIED", "message": str(error)}
        )
    if isinstance(error, ProductWorkError):
        return HTTPException(409, detail={"code": "PROJECT_SOURCE_CHANGED", "message": str(error)})
    if isinstance(error, MaterialAdmissionBlocked):
        return HTTPException(
            409,
            detail={
                "code": "MATERIAL_ADMISSION_BLOCKED",
                "message": str(error),
                "blockers": error.check["blockers"],
            },
        )
    if isinstance(error, ScheduleExecutionBlocked):
        return HTTPException(
            status_code=409,
            detail={
                "code": "SCHEDULE_EXECUTION_BLOCKED",
                "message": str(error),
                "blockers": error.blockers,
            },
        )
    if isinstance(error, (SupplyImportError, DocumentPreviewError, DocumentPreviewMissing)):
        return HTTPException(409, detail={"code": "SUPPLY_SOURCE_CHANGED", "message": str(error)})
    if isinstance(error, (BuildMaterialError, MaterialAllocationError)):
        return HTTPException(409, detail={"code": "BUILD_MATERIAL_CHANGED", "message": str(error)})
    if isinstance(error, KnowledgeAccessError):
        return HTTPException(403, detail={"code": "PROJECT_ACCESS_DENIED", "message": str(error)})
    if isinstance(error, TemplateError):
        return HTTPException(
            status_code=409, detail={"code": "TEST_TEMPLATE_CONFLICT", "message": str(error)}
        )
    if isinstance(error, NpiNotFoundError):
        return HTTPException(
            status_code=404, detail={"code": "NPI_NOT_FOUND", "message": "NPI record was not found"}
        )
    if isinstance(error, (NpiScopeError, NpiTransitionError, NpiConflictError, IntegrityError)):
        return HTTPException(
            status_code=409,
            detail={
                "code": "NPI_CONFLICT",
                "message": "NPI operation conflicts with project truth",
            },
        )
    if isinstance(error, NpiAudienceError):
        return HTTPException(
            status_code=403,
            detail={
                "code": "NPI_AUDIENCE_DENIED",
                "message": "Signoff audience does not match actor",
            },
        )
    raise error


@router.get("")
def get_npi(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, list[dict[str, Any]]]:
    no_store(response)
    _access(engine, context, project_id, Action.PROJECT_VIEW)
    return NpiExecutionService(engine).snapshot(
        tenant_id=context.tenant.id, project_id=project_id, role=context.user.role
    )


@router.get("/supply-imports")
def supply_imports(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    object_store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
) -> dict[str, Any]:
    no_store(response)
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_VIEW)
    try:
        return SupplyImportService(engine, object_store).list(context, project_id)
    except Exception as error:
        raise _error(error) from error


@router.post("/supply-imports/inspect")
def inspect_supply_import(
    project_id: UUID,
    body: InspectSupply,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    object_store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
) -> dict[str, Any]:
    no_store(response)
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_VIEW)
    try:
        return SupplyImportService(engine, object_store).inspect(
            context, project_id, body.document_id
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/supply-imports/preview")
def preview_supply_import(
    project_id: UUID,
    body: SupplyImportDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    object_store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
) -> dict[str, Any]:
    no_store(response)
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_VIEW)
    try:
        return SupplyImportService(engine, object_store).preview(context, project_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/supply-imports/confirm")
def confirm_supply_import(
    project_id: UUID,
    body: SupplyImportConfirm,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    object_store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
) -> dict[str, Any]:
    no_store(response)
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_EDIT)
    try:
        return SupplyImportService(engine, object_store).confirm(context, project_id, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/supply-imports/{batch_id}")
def supply_import_detail(
    project_id: UUID,
    batch_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    object_store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
) -> dict[str, Any]:
    no_store(response)
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_VIEW)
    try:
        return SupplyImportService(engine, object_store).detail(context, project_id, batch_id)
    except Exception as error:
        raise _error(error) from error


@router.get("/build-options")
def get_build_options(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_VIEW)
    try:
        return NpiExecutionService(engine).build_options(
            tenant_id=context.tenant.id, project_id=project_id
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/builds", status_code=status.HTTP_201_CREATED)
def create_build(
    project_id: UUID,
    body: BuildCreateRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_EDIT)
    try:
        return NpiExecutionService(engine).create_build(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            stage_id=body.stage_id,
            phase=body.phase,
            code=body.code.strip(),
            purpose=body.purpose,
            planned_quantity=body.planned_quantity,
            notes=_clean(body.notes),
        )
    except Exception as error:
        raise _error(error) from error


@router.get("/builds/{build_id}/supply-allocations")
def build_supply_allocations(
    project_id: UUID,
    build_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_VIEW)
    try:
        return MaterialAllocationService(engine).get(context, project_id, build_id)
    except Exception as error:
        raise _error(error) from error


@router.post("/builds/{build_id}/supply-allocations/preview")
def preview_supply_allocations(
    project_id: UUID,
    build_id: UUID,
    body: AllocationSelection,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_VIEW)
    try:
        return MaterialAllocationService(engine).preview(context, project_id, build_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/builds/{build_id}/supply-allocations/allocate")
def allocate_build_supply(
    project_id: UUID,
    build_id: UUID,
    body: AllocationApply,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_EDIT)
    try:
        return MaterialAllocationService(engine).apply(context, project_id, build_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/builds/{build_id}/supply-allocations/release")
def release_build_supply(
    project_id: UUID,
    build_id: UUID,
    body: AllocationRelease,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_EDIT)
    try:
        return MaterialAllocationService(engine).apply(context, project_id, build_id, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/builds/{build_id}/supply-allocations/receipts/{receipt_id}")
def build_supply_allocation_receipt(
    project_id: UUID,
    build_id: UUID,
    receipt_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_VIEW)
    try:
        return MaterialAllocationService(engine).receipt(context, project_id, build_id, receipt_id)
    except Exception as error:
        raise _error(error) from error


@router.post("/builds/{build_id}/supply-allocations/coverage-preview")
def preview_build_supply_coverage(
    project_id: UUID,
    build_id: UUID,
    body: CoverageSelection,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_VIEW)
    try:
        return MaterialCoverageService(engine).preview(context, project_id, build_id, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/supply-snapshots/{source_id}/sharing")
def supply_share_options(
    project_id: UUID,
    source_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplySharingService(engine).options(context, project_id, source_id)
    except Exception as error:
        raise _error(error) from error


@router.post("/supply-snapshots/{source_id}/sharing")
def offer_supply_share(
    project_id: UUID,
    source_id: UUID,
    body: ShareOffer,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplySharingService(engine).offer(context, project_id, source_id, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/supply-sharing")
def list_supply_sharing(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    grant_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplySharingService(engine).list(context, project_id, grant_id)
    except Exception as error:
        raise _error(error) from error


@router.post("/supply-sharing/{grant_id}/decision")
def decide_supply_share(
    project_id: UUID,
    grant_id: UUID,
    body: ShareDecision,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplySharingService(engine).decide(context, project_id, grant_id, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/builds/{build_id}/material-movements")
def material_movement_history(
    project_id: UUID,
    build_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    movement_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return MaterialMovementService(engine).get(context, project_id, build_id, movement_id)
    except Exception as error:
        raise _error(error) from error


@router.post("/builds/{build_id}/material-movements/preview")
def preview_material_movement(
    project_id: UUID,
    build_id: UUID,
    body: MovementDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return MaterialMovementService(engine).preview(context, project_id, build_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/builds/{build_id}/material-movements")
def register_material_movement(
    project_id: UUID,
    build_id: UUID,
    body: MovementApply,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return MaterialMovementService(engine).apply(context, project_id, build_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/builds/{build_id}/material-movements/{movement_id}/correction/preview")
def preview_material_correction(
    project_id: UUID,
    build_id: UUID,
    movement_id: UUID,
    body: CorrectionDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return MaterialCorrectionService(engine).preview(
            context, project_id, build_id, movement_id, body
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/builds/{build_id}/material-movements/{movement_id}/correction")
def correct_material_movement(
    project_id: UUID,
    build_id: UUID,
    movement_id: UUID,
    body: CorrectionApply,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return MaterialCorrectionService(engine).apply(
            context, project_id, build_id, movement_id, body
        )
    except Exception as error:
        raise _error(error) from error


@router.get("/supply-snapshots/{source_id}/movements")
def material_movement_reconciliation(
    project_id: UUID,
    source_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    after: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return MaterialReconciliationService(engine).get(context, project_id, source_id, after)
    except Exception as error:
        raise _error(error) from error


@router.post("/material-movements/{movement_id}/reconcile")
def reconcile_material_movements(
    project_id: UUID,
    movement_id: UUID,
    body: ReconciliationDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return MaterialReconciliationService(engine).apply(context, project_id, movement_id, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/changes/{ecr_id}/compliance")
def change_compliance_matrix(
    project_id: UUID,
    ecr_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    after: UUID | None = None,
    record_id: UUID | None = None,
    before_version: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    no_store(response)
    try:
        return ChangeComplianceService(engine).get(
            context, project_id, ecr_id, after, record_id, before_version
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/changes/{ecr_id}/compliance/{record_id}")
def review_change_compliance(
    project_id: UUID,
    ecr_id: UUID,
    record_id: UUID,
    body: ChangeComplianceReview,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return ChangeComplianceService(engine).apply(context, project_id, ecr_id, record_id, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/supplier-compliance")
def supplier_compliance_matrix(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    after: UUID | None = None,
    record_id: UUID | None = None,
    before_version: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierComplianceService(engine).get(
            context, project_id, after, record_id, before_version
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/supplier-compliance/{record_id}/preview")
def preview_supplier_compliance(
    project_id: UUID,
    record_id: UUID,
    body: ComplianceDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierComplianceService(engine).preview(context, project_id, record_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/supplier-compliance/{record_id}")
def apply_supplier_compliance(
    project_id: UUID,
    record_id: UUID,
    body: ComplianceApply,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierComplianceService(engine).apply(context, project_id, record_id, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/supplier-recovery/runs")
def supplier_recovery_runs(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_id: UUID | None = None,
    run_id: UUID | None = None,
) -> dict[str, Any]:
    from app.ai.supplier_recovery_runs import SupplierRecoveryRuns

    no_store(response)
    try:
        return SupplierRecoveryRuns.list_results(
            engine, context=context, project_id=project_id, before_id=before_id, run_id=run_id
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/supplier-recovery/runs")
def create_supplier_recovery_run(
    project_id: UUID,
    body: SupplierRecoveryRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.ai.application_gateway import configured_application_gateway
    from app.ai.rollout_guard import require_live_key
    from app.ai.supplier_recovery_runs import KEY, SupplierRecoveryRuns
    from app.ai.supplier_recovery_runs import _access as supply_access

    no_store(response)
    try:
        supply_access(engine, context, project_id, Action.PRODUCT_ENGINEERING_EDIT)
        require_live_key(KEY)
        with configured_application_gateway(engine) as gateway:
            return SupplierRecoveryRuns(engine, gateway=gateway).create(
                context=context, project_id=project_id, request=body
            )
    except (BudgetLedgerError, CapabilityUnavailableError) as error:
        raise HTTPException(
            409,
            detail={"code": error.code, "message": "供应恢复能力、预算或授权尚未就绪；原记录保留"},
        ) from error
    except Exception as error:
        raise _error(error) from error


@router.get("/supplier-recovery/sources")
def supplier_recovery_sources(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierRecoveryPreparation(engine).choices(context, project_id)
    except Exception as error:
        raise _error(error) from error


@router.post("/supplier-recovery/context")
def supplier_recovery_context(
    project_id: UUID,
    body: SupplierRecoverySelection,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierRecoveryPreparation(engine).get(context, project_id, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/tooling-rounds")
def tooling_round_history(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    after: UUID | None = None,
    round_id: UUID | None = None,
    before_version: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    no_store(response)
    try:
        return ToolingRoundService(engine).get(context, project_id, after, round_id, before_version)
    except Exception as error:
        raise _error(error) from error


@router.post("/tooling-rounds/{round_id}/preview")
def preview_tooling_round(
    project_id: UUID,
    round_id: UUID,
    body: RoundDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return ToolingRoundService(engine).preview(context, project_id, round_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/tooling-rounds/{round_id}")
def apply_tooling_round(
    project_id: UUID,
    round_id: UUID,
    body: RoundApply,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return ToolingRoundService(engine).apply(context, project_id, round_id, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/supplier-engineering")
def supplier_engineering_profile(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    supplier_id: UUID | None = None,
    after: UUID | None = None,
    record_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierEngineeringService(engine).get(
            context, project_id, supplier_id, after, record_id
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/suppliers/{supplier_id}/engineering-records/{record_id}/preview")
def preview_supplier_engineering_record(
    project_id: UUID,
    supplier_id: UUID,
    record_id: UUID,
    body: EngineeringDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierEngineeringService(engine).preview(
            context, project_id, supplier_id, record_id, body
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/suppliers/{supplier_id}/engineering-records/{record_id}")
def apply_supplier_engineering_record(
    project_id: UUID,
    supplier_id: UUID,
    record_id: UUID,
    body: EngineeringApply,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierEngineeringService(engine).apply(
            context, project_id, supplier_id, record_id, body
        )
    except Exception as error:
        raise _error(error) from error


@router.get("/material-exposure")
def material_exposure(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    material_reference: str | None = Query(default=None, min_length=1, max_length=256),
    supplier_id: UUID | None = None,
    scope_project_id: UUID | None = None,
    after: UUID | None = None,
    include_finished: bool = False,
) -> dict[str, Any]:
    no_store(response)
    try:
        return MaterialExposureService(engine).list(
            context,
            project_id,
            material_reference=material_reference,
            supplier_id=supplier_id,
            scope_project_id=scope_project_id,
            after=after,
            include_finished=include_finished,
        )
    except Exception as error:
        raise _error(error) from error


@router.get("/supply-snapshots/{source_id}/supplier")
def material_supplier_attribution(
    project_id: UUID,
    source_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return MaterialExposureService(engine).attribution(context, project_id, source_id)
    except Exception as error:
        raise _error(error) from error


@router.post("/supply-snapshots/{source_id}/supplier")
def attribute_material_supplier(
    project_id: UUID,
    source_id: UUID,
    body: AttributionDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return MaterialExposureService(engine).attribute(context, project_id, source_id, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/material-admission/{target_kind}/{target_id}")
def get_material_admission(
    project_id: UUID,
    target_kind: TargetKind,
    target_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return MaterialAdmissionService(engine).get(context, project_id, target_kind, target_id)
    except Exception as error:
        raise _error(error) from error


@router.post("/material-admission/{target_kind}/{target_id}/policy")
def configure_material_admission(
    project_id: UUID,
    target_kind: TargetKind,
    target_id: UUID,
    body: PolicyDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return MaterialAdmissionService(engine).configure(
            context, project_id, target_kind, target_id, body
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/material-admission/{target_kind}/{target_id}/waivers")
def request_material_waiver(
    project_id: UUID,
    target_kind: TargetKind,
    target_id: UUID,
    body: WaiverDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return MaterialAdmissionService(engine).request_waiver(
            context, project_id, target_kind, target_id, body
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/material-admission/{target_kind}/{target_id}/waivers/{waiver_id}/decide")
def decide_material_waiver(
    project_id: UUID,
    target_kind: TargetKind,
    target_id: UUID,
    waiver_id: UUID,
    body: WaiverDecision,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return MaterialAdmissionService(engine).decide(
            context, project_id, target_kind, target_id, waiver_id, body
        )
    except Exception as error:
        raise _error(error) from error


@router.get("/material-exceptions/{exception_id}/schedule")
def material_exception_schedule(
    project_id: UUID,
    exception_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    version: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    no_store(response)
    try:
        return MaterialScheduleService(engine).get(
            context, project_id, exception_id, version=version
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/material-exceptions/{exception_id}/schedule")
def apply_material_exception_schedule(
    project_id: UUID,
    exception_id: UUID,
    body: BindingDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return MaterialScheduleService(engine).apply(context, project_id, exception_id, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/material-exceptions")
def list_material_exceptions(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    build_id: UUID | None = None,
    issue_id: UUID | None = None,
    material_key: str | None = Query(default=None, pattern=r"^[a-f0-9]{64}$"),
) -> dict[str, Any]:
    no_store(response)
    try:
        return MaterialExceptionService(engine).list(
            context, project_id, build_id=build_id, issue_id=issue_id, material_key=material_key
        )
    except Exception as error:
        raise _error(error) from error


@router.get("/material-exceptions/{exception_id}")
def get_material_exception(
    project_id: UUID,
    exception_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    version: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    no_store(response)
    try:
        return MaterialExceptionService(engine).get(
            context, project_id, exception_id, version=version
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/builds/{build_id}/material-exceptions")
def create_material_exception(
    project_id: UUID,
    build_id: UUID,
    body: ExceptionCreate,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return MaterialExceptionService(engine).create(context, project_id, build_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/material-exceptions/{exception_id}/review")
def review_material_exception(
    project_id: UUID,
    exception_id: UUID,
    body: ExceptionReview,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return MaterialExceptionService(engine).review(context, project_id, exception_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/material-exceptions/{exception_id}/preview")
def preview_material_exception(
    project_id: UUID,
    exception_id: UUID,
    body: CoverageSelection,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return MaterialExceptionService(engine).get(
            context, project_id, exception_id, selection=body
        )
    except Exception as error:
        raise _error(error) from error


@router.get("/builds/{build_id}/materials")
def build_materials(
    project_id: UUID,
    build_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_VIEW)
    try:
        return BuildMaterialService(engine).get(context, project_id, build_id)
    except Exception as error:
        raise _error(error) from error


@router.post("/builds/{build_id}/materials/preview")
def preview_build_materials(
    project_id: UUID,
    build_id: UUID,
    body: MaterialSelection,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_VIEW)
    try:
        return BuildMaterialService(engine).preview(context, project_id, build_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/builds/{build_id}/materials/freeze")
def freeze_build_materials(
    project_id: UUID,
    build_id: UUID,
    body: MaterialFreeze,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_EDIT)
    try:
        return BuildMaterialService(engine).freeze(context, project_id, build_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/builds/{build_id}/materials/revision-preview")
def preview_build_material_revision(
    project_id: UUID,
    build_id: UUID,
    body: MaterialRevisionSelection,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_VIEW)
    try:
        return BuildMaterialChangeService(engine).preview(context, project_id, build_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/builds/{build_id}/materials/revise")
def apply_build_material_revision(
    project_id: UUID,
    build_id: UUID,
    body: MaterialRevisionApply,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    _access(engine, context, project_id, Action.CHANGE_APPROVE)
    try:
        return BuildMaterialChangeService(engine).apply(context, project_id, build_id, body)
    except Exception as error:
        raise _error(error) from error


@router.patch("/builds/{build_id}")
def update_build(
    project_id: UUID,
    build_id: UUID,
    body: BuildUpdateRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_EDIT)
    try:
        return NpiExecutionService(engine).update_build(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            build_id=build_id,
            status=body.status,
            completed_quantity=body.completed_quantity,
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/builds/{build_id}/samples", status_code=status.HTTP_201_CREATED)
def create_sample(
    project_id: UUID,
    build_id: UUID,
    body: SampleCreateRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_EDIT)
    try:
        return NpiExecutionService(engine).create_sample(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            build_id=build_id,
            serial_number=body.serial_number.strip(),
            parent_sample_id=body.parent_sample_id,
            prototype_bom_id=body.prototype_bom_id,
            notes=_clean(body.notes),
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/sample-signoffs", status_code=status.HTTP_201_CREATED)
def create_signoff(
    project_id: UUID,
    body: SampleSignoffCreateRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_EDIT)
    try:
        return NpiExecutionService(engine).create_signoff(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            phase=body.phase,
            title=body.title.strip(),
            signoff_type=body.signoff_type,
            audience=body.audience,
            sample_ids=body.sample_ids,
            due_date=body.due_date,
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/sample-signoffs/{signoff_id}/respond")
def respond_signoff(
    project_id: UUID,
    signoff_id: UUID,
    body: SampleSignoffResponseRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    action = (
        Action.EXTERNAL_RESPOND
        if context.user.role in {Role.SUPPLIER, Role.CUSTOMER}
        else Action.QUALITY_MANAGE
    )
    _access(engine, context, project_id, action)
    try:
        return NpiExecutionService(engine).respond_signoff(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            actor_role=context.user.role,
            signoff_id=signoff_id,
            status=body.status,
            note=_clean(body.note),
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/test-plans", status_code=status.HTTP_201_CREATED)
def create_test_plan(
    project_id: UUID,
    body: TestPlanCreateRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.WORK_ITEM_EDIT)
    try:
        return NpiExecutionService(engine).create_test_plan(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            stage_id=body.stage_id,
            phase=body.phase,
            title=body.title.strip(),
            scope=_clean(body.scope),
            sample_size=body.sample_size,
            status=body.status,
            template=body.template,
        )
    except Exception as error:
        raise _error(error) from error


@router.get("/test-templates")
def get_test_templates(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    _access(engine, context, project_id, Action.WORK_ITEM_EDIT)
    with engine.connect() as connection:
        stages = [
            dict(row)
            for row in connection.execute(
                select(tables.stages.c.id, tables.stages.c.code, tables.stages.c.name)
                .join(tables.projects, tables.projects.c.workflow_id == tables.stages.c.workflow_id)
                .where(
                    tables.projects.c.tenant_id == context.tenant.id,
                    tables.stages.c.tenant_id == context.tenant.id,
                    tables.projects.c.id == project_id,
                    tables.stages.c.code.in_(["evt", "dvt", "pvt"]),
                )
                .order_by(tables.stages.c.sequence)
            ).mappings()
        ]
        options = project_catalog(connection, tenant_id=context.tenant.id, project_id=project_id)
    return {**options, "stages": stages}


@router.post("/test-plans/{plan_id}/template")
def bind_test_template(
    project_id: UUID,
    plan_id: UUID,
    body: TemplateSelection,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.WORK_ITEM_EDIT)
    try:
        return NpiExecutionService(engine).bind_test_template(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            plan_id=plan_id,
            selection=body,
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/test-plans/{plan_id}/cases", status_code=status.HTTP_201_CREATED)
def create_test_case(
    project_id: UUID,
    plan_id: UUID,
    body: TestCaseCreateRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.WORK_ITEM_EDIT)
    try:
        return NpiExecutionService(engine).create_test_case(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            plan_id=plan_id,
            title=body.title.strip(),
            category=body.category.strip(),
            acceptance_criteria=body.acceptance_criteria.strip(),
            method=_clean(body.method),
            severity=body.severity,
            sample_ids=body.sample_ids,
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/test-cases/{test_case_id}/result")
def record_test_result(
    project_id: UUID,
    test_case_id: UUID,
    body: TestResultRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.WORK_ITEM_EDIT)
    try:
        return NpiExecutionService(engine).record_test_result(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            test_case_id=test_case_id,
            status=body.status,
            result_notes=_clean(body.result_notes),
            related_issue_id=body.related_issue_id,
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/test-plans/{plan_id}/reports", status_code=status.HTTP_201_CREATED)
def create_test_report(
    project_id: UUID,
    plan_id: UUID,
    body: TestReportCreateRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.WORK_ITEM_EDIT)
    try:
        return NpiExecutionService(engine).create_test_report(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            plan_id=plan_id,
            report_number=body.report_number.strip(),
            title=body.title.strip(),
            result=body.result,
            summary=body.summary.strip(),
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/test-reports/{report_id}/review")
def review_test_report(
    project_id: UUID,
    report_id: UUID,
    body: TestReportReviewRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.QUALITY_MANAGE)
    try:
        return NpiExecutionService(engine).review_test_report(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            report_id=report_id,
            review_status=body.review_status,
            note=_clean(body.note),
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/certifications", status_code=status.HTTP_201_CREATED)
def create_certification(
    project_id: UUID,
    body: CertificationCreateRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.QUALITY_MANAGE)
    values = body.model_dump(exclude={"owner_user_id"})
    values["certificate_number"] = _clean(body.certificate_number)
    values["issuing_body"] = _clean(body.issuing_body)
    values["evidence_reference"] = _clean(body.evidence_reference)
    values["target_markets"] = sorted(
        {market.strip().upper() for market in body.target_markets if market.strip()}
    )
    try:
        return NpiExecutionService(engine).create_certification(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            owner_user_id=body.owner_user_id or context.user.id,
            values=values,
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/certifications/scan")
def scan_certifications(
    project_id: UUID,
    body: CertificationScanRequest,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, int]:
    _access(engine, context, project_id, Action.QUALITY_MANAGE)
    try:
        return NpiExecutionService(engine).scan_certifications(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            as_of=body.as_of,
        )
    except Exception as error:
        raise _error(error) from error


@router.get("/test-cases/{test_case_id}/execution-preparation")
def get_test_execution_preparation(
    project_id: UUID,
    test_case_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.test_execution_preparations import read
    from app.domain.test_verification_paths import VerificationPathError

    no_store(response)
    try:
        return read(engine, context=context, project_id=project_id, case_id=test_case_id)
    except VerificationPathError as error:
        raise HTTPException(
            status_code=409, detail={"code": "TEST_PREPARATION_CHANGED", "message": str(error)}
        ) from error


@router.post("/test-cases/{test_case_id}/execution-preparation")
def save_test_execution_preparation(
    project_id: UUID,
    test_case_id: UUID,
    body: TestPreparationDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.test_execution_preparations import save

    no_store(response)
    try:
        return save(
            engine, context=context, project_id=project_id, case_id=test_case_id, draft=body
        )
    except (ValueError, LookupError) as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "TEST_PREPARATION_CHANGED",
                "message": str(error) or "任务、样机或资源已变化，请重新核对工作包",
            },
        ) from error


class VerificationPathRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    specification_id: UUID | None = None
    specification_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    method: str = Field(min_length=1, max_length=10_000)
    acceptance_criteria: str = Field(min_length=1, max_length=10_000)
    reason: str = Field(min_length=1, max_length=2000)


@router.get("/test-cases/{test_case_id}/verification-path")
def get_verification_path(
    project_id: UUID,
    test_case_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.test_verification_paths import VerificationPathError, options

    no_store(response)
    try:
        return options(engine, context=context, project_id=project_id, case_id=test_case_id)
    except VerificationPathError as error:
        raise HTTPException(
            status_code=409, detail={"code": "VERIFICATION_PATH_CHANGED", "message": str(error)}
        ) from error


@router.put("/test-cases/{test_case_id}/verification-path")
def save_verification_path(
    project_id: UUID,
    test_case_id: UUID,
    body: VerificationPathRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.test_verification_paths import VerificationPathError, save

    no_store(response)
    try:
        return save(
            engine,
            context=context,
            project_id=project_id,
            case_id=test_case_id,
            **body.model_dump(),
        )
    except VerificationPathError as error:
        raise HTTPException(
            status_code=409, detail={"code": "VERIFICATION_PATH_CHANGED", "message": str(error)}
        ) from error


class TestRunMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    value: float | int | str
    unit: str | None = Field(default=None, max_length=32)
    target: float | int | str | None = None
    verdict: str | None = Field(default=None, pattern=r"^(pass|fail|info)$")


class TestRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(pattern=r"^(in_progress|passed|failed|aborted)$")
    sample_id: UUID | None = None
    conditions: dict[str, object] = Field(default_factory=dict)
    metrics: list[TestRunMetric] = Field(default_factory=list, max_length=100)
    equipment: str | None = Field(default=None, max_length=256)
    environment: str | None = Field(default=None, max_length=256)
    result_notes: str | None = Field(default=None, max_length=20_000)
    expected_completion_at: datetime | None = None
    evidence_document_id: UUID | None = None
    executed_at: datetime | None = None
    execution_time_precision: Literal["unknown", "day", "instant"] = "unknown"
    execution_time_reason: str | None = Field(default=None, max_length=2000)

    configuration_mode: Literal["current", "revision", "unknown"] = "current"
    configuration_revision_id: UUID | None = None
    configuration_reason: str | None = Field(default=None, max_length=2000)


class TestRunCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(pattern=r"^(passed|failed|aborted)$")
    metrics: list[TestRunMetric] = Field(default_factory=list, max_length=100)
    result_notes: str | None = Field(default=None, max_length=20_000)
    evidence_document_id: UUID | None = None
    executed_at: datetime | None = None
    execution_time_precision: Literal["unknown", "day", "instant"] = "unknown"
    execution_time_reason: str | None = Field(default=None, max_length=2000)


class TestRunResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    source_field_capture_id: UUID | None = None
    project_id: UUID
    test_case_id: UUID
    sample_id: UUID | None
    sample_configuration_revision_id: UUID | None
    configuration_revision: dict[str, Any] | None
    import_successor_batch_id: UUID | None
    import_batch_id: UUID | None = None
    execution_time_precision: str
    execution_time_source: str
    operator_name: str | None = None
    test_preparation_id: UUID | None = None
    test_preparation: dict[str, Any] | None = None
    operator_user_id: UUID | None
    evidence_document_id: UUID | None
    run_number: int
    status: str
    draft_state: str
    conditions: dict[str, object]
    metrics: list[dict[str, object]]
    equipment: str | None
    environment: str | None
    result_notes: str | None
    started_at: datetime | None
    expected_completion_at: datetime | None
    executed_at: datetime | None
    related_issue_id: UUID | None
    created_at: datetime
    updated_at: datetime


class TestRunListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[TestRunResponse]


def _test_run_response(record: TestRunRecord) -> TestRunResponse:
    return TestRunResponse(
        id=record.id,
        source_field_capture_id=record.source_field_capture_id,
        project_id=record.project_id,
        test_case_id=record.test_case_id,
        sample_id=record.sample_id,
        sample_configuration_revision_id=record.sample_configuration_revision_id,
        configuration_revision=record.configuration_revision,
        import_successor_batch_id=record.import_successor_batch_id,
        import_batch_id=record.import_batch_id,
        execution_time_precision=record.execution_time_precision,
        execution_time_source=record.execution_time_source,
        operator_user_id=record.operator_user_id,
        operator_name=record.operator_name,
        test_preparation_id=record.test_preparation_id,
        test_preparation=record.test_preparation,
        evidence_document_id=record.evidence_document_id,
        run_number=record.run_number,
        status=record.status,
        draft_state=record.draft_state,
        conditions=record.conditions,
        metrics=[dict(item) for item in record.metrics],
        equipment=record.equipment,
        environment=record.environment,
        result_notes=record.result_notes,
        started_at=record.started_at,
        expected_completion_at=record.expected_completion_at,
        executed_at=record.executed_at,
        related_issue_id=record.related_issue_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _test_run_error(error: Exception) -> HTTPException:
    from app.domain.schedule_execution import ScheduleExecutionBlocked

    if isinstance(error, ScheduleExecutionBlocked):
        return HTTPException(
            status_code=409,
            detail={
                "code": "SCHEDULE_EXECUTION_BLOCKED",
                "message": str(error),
                "blockers": error.blockers,
            },
        )
    if isinstance(error, TestRunFactError):
        return HTTPException(
            status_code=409, detail={"code": "TEST_RUN_FACT_INVALID", "message": str(error)}
        )
    if isinstance(error, TestRunNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TEST_RUN_NOT_FOUND", "message": "Test run or case was not found"},
        )
    if isinstance(error, TestRunScopeError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "TEST_RUN_RELATED_OBJECT_NOT_FOUND",
                "message": "Related sample or document was not found in this project",
            },
        )
    if isinstance(error, TestRunStateError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "TEST_RUN_INVALID_STATE",
                "message": "Only in-progress runs can be completed with a terminal result",
            },
        )
    raise error


@router.get("/test-cases/{test_case_id}/runs", response_model=TestRunListResponse)
def list_test_runs(
    project_id: UUID,
    test_case_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> TestRunListResponse:
    no_store(response)
    _access(engine, context, project_id, Action.PROJECT_VIEW)
    return TestRunListResponse(
        items=[
            _test_run_response(record)
            for record in TestRunService(engine).list_runs(
                tenant_id=context.tenant.id,
                project_id=project_id,
                test_case_id=test_case_id,
            )
        ]
    )


@router.post(
    "/test-cases/{test_case_id}/runs",
    response_model=TestRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def record_test_run(
    project_id: UUID,
    test_case_id: UUID,
    body: TestRunCreateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> TestRunResponse:
    no_store(response)
    _access(engine, context, project_id, Action.TEST_RUN_RECORD)
    try:
        record = TestRunService(engine).record_run(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            test_case_id=test_case_id,
            draft=TestRunDraft(
                status=body.status,
                sample_id=body.sample_id,
                conditions=body.conditions,
                metrics=tuple(metric.model_dump() for metric in body.metrics),
                equipment=body.equipment,
                environment=body.environment,
                result_notes=body.result_notes,
                expected_completion_at=body.expected_completion_at,
                evidence_document_id=body.evidence_document_id,
                executed_at=body.executed_at,
                execution_time_precision=body.execution_time_precision,
                execution_time_reason=body.execution_time_reason,
                configuration_mode=body.configuration_mode,
                configuration_revision_id=body.configuration_revision_id,
                configuration_reason=body.configuration_reason,
            ),
        )
    except Exception as error:
        raise _test_run_error(error) from error
    return _test_run_response(record)


@router.post("/test-cases/{test_case_id}/runs/{run_id}/complete", response_model=TestRunResponse)
def complete_test_run(
    project_id: UUID,
    test_case_id: UUID,
    run_id: UUID,
    body: TestRunCompleteRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> TestRunResponse:
    no_store(response)
    _access(engine, context, project_id, Action.TEST_RUN_RECORD)
    try:
        record = TestRunService(engine).complete_run(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            test_case_id=test_case_id,
            run_id=run_id,
            status=body.status,
            metrics=tuple(metric.model_dump() for metric in body.metrics),
            result_notes=body.result_notes,
            evidence_document_id=body.evidence_document_id,
            executed_at=body.executed_at,
            execution_time_precision=body.execution_time_precision,
            execution_time_reason=body.execution_time_reason,
        )
    except Exception as error:
        raise _test_run_error(error) from error
    return _test_run_response(record)


class ImportBatchResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    plan_id: UUID
    document_id: UUID
    template_fingerprint: str
    mapping_source: str
    status: str
    confidence: float | None
    created_run_ids: list[UUID]
    skipped_rows: list[dict[str, object]]
    reused_existing: bool = False


def _import_batch_response(result: ImportBatchResult) -> ImportBatchResponse:
    return ImportBatchResponse(
        id=result.id,
        project_id=result.project_id,
        plan_id=result.plan_id,
        document_id=result.document_id,
        template_fingerprint=result.template_fingerprint,
        mapping_source=result.mapping_source,
        status=result.status,
        confidence=result.confidence,
        created_run_ids=list(result.created_run_ids),
        skipped_rows=[dict(item) for item in result.skipped_rows],
        reused_existing=result.reused_existing,
    )


@router.post(
    "/test-imports", response_model=ImportBatchResponse, status_code=status.HTTP_201_CREATED
)
async def start_test_report_import(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    object_store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
    gateway: Annotated[StructuredModelGateway, Depends(get_application_gateway)],
    file: Annotated[UploadFile, File()],
    plan_id: Annotated[UUID, Form()],
) -> ImportBatchResponse:
    no_store(response)
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_EDIT)
    content = await file.read(30 * 1024 * 1024)
    service = TestReportImportService(engine, object_store=object_store, gateway=gateway)
    try:
        result = service.start_import(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            plan_id=plan_id,
            filename=file.filename or "report.xlsx",
            content=content,
            auth_version=context.user.auth_version,
        )
    except ImportError_ as error:
        raise HTTPException(
            status_code=(
                status.HTTP_403_FORBIDDEN
                if error.code == "IMPORT_ACCESS_DENIED"
                else status.HTTP_409_CONFLICT
                if error.code == "IMPORT_MAPPING_REQUEST_CONFLICT"
                else status.HTTP_422_UNPROCESSABLE_CONTENT
            ),
            detail={"code": error.code, "message": str(error)},
        ) from error
    except DocumentError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": error.code, "message": str(error)},
        ) from error
    if result.reused_existing:
        response.status_code = status.HTTP_200_OK
    return _import_batch_response(result)


class ImportOperationResponse(BaseModel):
    run_id: UUID | None
    status: str
    batch: ImportBatchResponse | None
    error_code: str | None


def _import_operation_error(error: Exception) -> HTTPException:
    code = getattr(error, "code", str(error))
    return HTTPException(
        status_code=403
        if code == "IMPORT_ACCESS_DENIED"
        else 409
        if isinstance(error, (BudgetLedgerError, ImportMappingRunError))
        else 422,
        detail={"code": code, "message": str(error)},
    )


@router.post("/test-import-requests", response_model=ImportOperationResponse, status_code=202)
async def queue_test_report_import(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    object_store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
    gateway: Annotated[StructuredModelGateway, Depends(get_application_gateway)],
    file: Annotated[UploadFile, File()],
    plan_id: Annotated[UUID, Form()],
) -> ImportOperationResponse:
    no_store(response)
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_EDIT)
    content = await file.read(20 * 1024 * 1024 + 1)
    try:
        result = ReportImportQueue(engine, object_store=object_store, gateway=gateway).submit(
            context=context,
            project_id=project_id,
            plan_id=plan_id,
            filename=file.filename or "report.xlsx",
            content=content,
        )
    except (ImportError_, DocumentError, BudgetLedgerError, ImportMappingRunError) as error:
        raise _import_operation_error(error) from error
    return ImportOperationResponse.model_validate(result)


@router.get("/test-import-requests/{run_id}", response_model=ImportOperationResponse)
def read_test_report_import(
    project_id: UUID,
    run_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ImportOperationResponse:
    no_store(response)
    try:
        return ImportOperationResponse.model_validate(
            ReportImportQueue(engine).get(context=context, project_id=project_id, run_id=run_id)
        )
    except ImportError_ as error:
        raise _import_operation_error(error) from error


class ImportConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_digest: str = Field(pattern="^[0-9a-f]{64}$")


@router.get("/test-plans/{plan_id}/imports")
def read_import_history(
    project_id: UUID,
    plan_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_id: UUID | None = None,
) -> dict[str, Any]:
    from app.domain.test_import_history import history

    no_store(response)
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_VIEW)
    try:
        return history(engine, context, project_id, plan_id, before_id)
    except ImportError_ as error:
        raise HTTPException(409, detail={"code": error.code, "message": str(error)}) from error


@router.get("/test-imports/{batch_id}/preview")
def read_import_preview(
    project_id: UUID,
    batch_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.test_import_preview import get_preview

    no_store(response)
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_VIEW)
    try:
        return get_preview(engine, context=context, project_id=project_id, batch_id=batch_id)
    except ImportError_ as error:
        raise HTTPException(409, detail={"code": error.code, "message": str(error)}) from error


class NewImportSampleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    serial_number: str = Field(min_length=1, max_length=128)
    build_id: UUID
    built_date: date
    parent_sample_id: UUID | None = None
    prototype_bom_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=20000)


class ImportSampleResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_digest: str = Field(pattern="^[0-9a-f]{64}$")
    run_ids: list[UUID] = Field(min_length=1, max_length=100)
    sample_id: UUID | None = None
    new_sample: NewImportSampleRequest | None = None
    reason: str = Field(min_length=1, max_length=2000)


@router.get("/test-imports/{batch_id}/sample-options")
def import_sample_options(
    project_id: UUID,
    batch_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    search: str = Query(default="", max_length=128),
) -> dict[str, Any]:
    from app.domain.test_import_samples import sample_options

    no_store(response)
    try:
        return sample_options(
            engine, context=context, project_id=project_id, batch_id=batch_id, search=search
        )
    except ImportError_ as error:
        raise HTTPException(409, detail={"code": error.code, "message": str(error)}) from error


@router.post("/test-imports/{batch_id}/resolve-samples")
def resolve_import_samples(
    project_id: UUID,
    batch_id: UUID,
    body: ImportSampleResolutionRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.test_import_samples import NewReportSample, resolve_samples

    no_store(response)
    try:
        return resolve_samples(
            engine,
            context=context,
            project_id=project_id,
            batch_id=batch_id,
            request_id=body.request_id,
            expected_digest=body.expected_digest,
            run_ids=tuple(body.run_ids),
            reason=body.reason,
            sample_id=body.sample_id,
            new_sample=NewReportSample(**body.new_sample.model_dump()) if body.new_sample else None,
        )
    except ImportError_ as error:
        raise HTTPException(409, detail={"code": error.code, "message": str(error)}) from error


class MappingRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_digest: str = Field(pattern="^[0-9a-f]{64}$")
    mapping: ExcelImportMapping
    reason: str = Field(min_length=1, max_length=2000)


@router.get("/test-imports/{batch_id}/mapping-options")
def import_mapping_options(
    project_id: UUID,
    batch_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    object_store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
) -> dict[str, Any]:
    from app.domain.test_import_revisions import TestImportRevisions

    no_store(response)
    try:
        return TestImportRevisions(engine, object_store).options(
            context=context, project_id=project_id, batch_id=batch_id
        )
    except ImportError_ as error:
        raise HTTPException(409, detail={"code": error.code, "message": str(error)}) from error


@router.post("/test-imports/{batch_id}/reparse")
def reparse_import_mapping(
    project_id: UUID,
    batch_id: UUID,
    body: MappingRevisionRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    object_store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
) -> dict[str, Any]:
    from app.domain.test_import_revisions import TestImportRevisions

    no_store(response)
    try:
        return TestImportRevisions(engine, object_store).reparse(
            context=context,
            project_id=project_id,
            batch_id=batch_id,
            request_id=body.request_id,
            expected_digest=body.expected_digest,
            mapping=body.mapping,
            reason=body.reason,
        )
    except ImportError_ as error:
        raise HTTPException(409, detail={"code": error.code, "message": str(error)}) from error


@router.get("/test-imports/{batch_id}/comparison")
def compare_import_revision(
    project_id: UUID,
    batch_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.test_import_revisions import comparison

    no_store(response)
    try:
        return comparison(engine, context=context, project_id=project_id, batch_id=batch_id)
    except ImportError_ as error:
        raise HTTPException(409, detail={"code": error.code, "message": str(error)}) from error


class ExecutionTimeAmendment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    executed_date: date | None = None
    executed_at: datetime | None = None
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def require_one_time(self) -> ExecutionTimeAmendment:
        if (self.executed_date is None) == (self.executed_at is None):
            raise ValueError("填写实际日期或精确时间中的一项")
        if self.executed_at is not None and self.executed_at.tzinfo is None:
            raise ValueError("精确时间必须含时区")
        return self


class ExecutionTimesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_digest: str = Field(pattern="^[0-9a-f]{64}$")
    items: list[ExecutionTimeAmendment] = Field(min_length=1, max_length=100)


@router.post("/test-imports/{batch_id}/execution-times")
def amend_import_execution_times(
    project_id: UUID,
    batch_id: UUID,
    body: ExecutionTimesRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, object]:
    from app.domain.test_import_execution_times import ExecutionTimeInput, amend_execution_times

    no_store(response)
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_EDIT)
    inputs = []
    for item in body.items:
        actual = item.executed_at
        if actual is None:
            if item.executed_date is None:
                raise HTTPException(422, detail="实际测试时间不能为空")
            actual = datetime.combine(item.executed_date, datetime.min.time(), tzinfo=UTC)
        inputs.append(
            ExecutionTimeInput(
                run_id=item.run_id,
                executed_at=actual,
                precision="instant" if item.executed_at is not None else "day",
                reason=item.reason,
            )
        )
    try:
        return amend_execution_times(
            engine,
            context=context,
            project_id=project_id,
            batch_id=batch_id,
            expected_digest=body.expected_digest,
            items=tuple(inputs),
        )
    except ImportError_ as error:
        raise HTTPException(409, detail={"code": error.code, "message": str(error)}) from error


@router.post("/test-imports/{batch_id}/confirm", response_model=ImportBatchResponse)
def confirm_test_report_import(
    project_id: UUID,
    batch_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    body: ImportConfirmationRequest | None = None,
) -> ImportBatchResponse:
    no_store(response)
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_EDIT)
    service = TestReportImportService(engine, object_store=None, gateway=None)
    try:
        result = service.confirm(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            batch_id=batch_id,
            expected_digest=body.expected_digest if body else None,
            auth_version=context.user.auth_version,
        )
    except ImportError_ as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT
            if error.code
            in {
                "IMPORT_BATCH_NOT_PENDING",
                "IMPORT_CASE_WAIVED",
                "IMPORT_NO_CONFIRMABLE_RUNS",
                "IMPORT_PREVIEW_CHANGED",
                "IMPORT_CONFIRMATION_BLOCKED",
                "IMPORT_SOURCE_UNAVAILABLE",
            }
            else status.HTTP_404_NOT_FOUND,
            detail={"code": error.code, "message": str(error)},
        ) from error
    return _import_batch_response(result)


class SampleConfigUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pcb_version: str | None = Field(default=None, max_length=64)
    structure_version: str | None = Field(default=None, max_length=64)
    fw_version: str | None = Field(default=None, max_length=64)
    development_bom_id: UUID | None = None
    key_component_suppliers: dict[str, object] | None = None
    build_date: date | None = None
    clear_fields: list[
        Literal[
            "pcb_version",
            "structure_version",
            "fw_version",
            "development_bom_id",
            "key_component_suppliers",
            "build_date",
        ]
    ] = Field(default_factory=list, max_length=6)
    expected_digest: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    reason: str | None = Field(default=None, min_length=1, max_length=2000)


class SampleConfigResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    sample_id: UUID
    current_revision_id: UUID | None
    sample_serial: str | None
    fw_release_id: UUID | None
    fw_version: str | None
    development_bom_id: UUID | None
    bom_code: str | None
    bom_version: int | None
    source_document_id: UUID | None
    pcb_version: str | None
    structure_version: str | None
    key_component_suppliers: dict[str, object]
    build_date: date | None
    source: str
    draft_state: str


class SampleConfigListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[SampleConfigResponse]


def _sample_config_response(record: SampleConfigRecord) -> SampleConfigResponse:
    return SampleConfigResponse(
        id=record.id,
        project_id=record.project_id,
        sample_id=record.sample_id,
        current_revision_id=record.current_revision_id,
        sample_serial=record.sample_serial,
        fw_release_id=record.fw_release_id,
        fw_version=record.fw_version,
        development_bom_id=record.development_bom_id,
        bom_code=record.bom_code,
        bom_version=record.bom_version,
        source_document_id=record.source_document_id,
        pcb_version=record.pcb_version,
        structure_version=record.structure_version,
        key_component_suppliers=record.key_component_suppliers,
        build_date=record.build_date,
        source=record.source,
        draft_state=record.draft_state,
    )


@router.get("/sample-configurations", response_model=SampleConfigListResponse)
def list_sample_configurations(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> SampleConfigListResponse:
    no_store(response)
    _access(engine, context, project_id, Action.PROJECT_VIEW)
    return SampleConfigListResponse(
        items=[
            _sample_config_response(record)
            for record in SampleConfigService(engine).list_configurations(
                tenant_id=context.tenant.id, project_id=project_id
            )
        ]
    )


@router.put("/samples/{sample_id}/build-configuration", response_model=SampleConfigResponse)
def upsert_sample_configuration(
    project_id: UUID,
    sample_id: UUID,
    body: SampleConfigUpsertRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> SampleConfigResponse:
    no_store(response)
    _access(engine, context, project_id, Action.PRODUCT_ENGINEERING_EDIT)
    try:
        record = SampleConfigService(engine).upsert_manual(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            sample_id=sample_id,
            draft=SampleConfigDraft(
                pcb_version=body.pcb_version,
                structure_version=body.structure_version,
                fw_version=body.fw_version,
                development_bom_id=body.development_bom_id,
                key_component_suppliers=body.key_component_suppliers,
                build_date=body.build_date,
                clear_fields=tuple(body.clear_fields),
            ),
            expected_digest=body.expected_digest,
            reason=body.reason,
            auth_version=context.user.auth_version,
        )
    except SampleConfigValueError as error:
        raise HTTPException(
            409, detail={"code": "SAMPLE_CONFIGURATION_CONFLICT", "message": str(error)}
        ) from error
    except SampleConfigNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SAMPLE_NOT_FOUND", "message": "Sample was not found"},
        ) from error
    return _sample_config_response(record)


@router.get("/samples/{sample_id}/configuration-edit-options")
def sample_configuration_edit_options(
    project_id: UUID,
    sample_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.sample_configuration_comparison import (
        ConfigurationComparisonError,
        edit_options,
    )

    no_store(response)
    try:
        return edit_options(engine, context=context, project_id=project_id, sample_id=sample_id)
    except ConfigurationComparisonError as error:
        raise HTTPException(409, detail={"message": str(error)}) from error


class ConfigurationSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["current", "revision", "test_run"]
    id: UUID


class ConfigurationVersionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selections: list[ConfigurationSelection] = Field(min_length=2, max_length=10)


@router.post("/sample-configurations/compare-versions")
def compare_configuration_versions(
    project_id: UUID,
    body: ConfigurationVersionsRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.sample_configuration_comparison import (
        ConfigurationComparisonError,
        compare_selected,
    )

    no_store(response)
    try:
        return compare_selected(
            engine,
            context=context,
            project_id=project_id,
            selections=tuple((item.kind, item.id) for item in body.selections),
        )
    except ConfigurationComparisonError as error:
        raise HTTPException(409, detail={"message": str(error)}) from error


@router.get("/samples/{sample_id}/configuration-history")
def sample_configuration_history(
    project_id: UUID,
    sample_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_number: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    from app.domain.sample_configuration_comparison import ConfigurationComparisonError, history

    no_store(response)
    try:
        return history(
            engine,
            context=context,
            project_id=project_id,
            sample_id=sample_id,
            before_number=before_number,
        )
    except ConfigurationComparisonError as error:
        raise HTTPException(409, detail={"message": str(error)}) from error


class SampleComparisonResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    samples: list[SampleConfigResponse]
    field_values: dict[str, list[Any]]
    differing_fields: list[str]
    missing_configuration_sample_ids: list[UUID]


class SampleComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_ids: list[UUID] = Field(min_length=2, max_length=10)

    @model_validator(mode="after")
    def unique_samples(self) -> SampleComparisonRequest:
        if len(set(self.sample_ids)) != len(self.sample_ids):
            raise ValueError("sample_ids must be unique")
        return self


@router.post("/sample-configurations/compare", response_model=SampleComparisonResponse)
def compare_sample_configurations(
    project_id: UUID,
    body: SampleComparisonRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> SampleComparisonResponse:
    no_store(response)
    _access(engine, context, project_id, Action.PROJECT_VIEW)
    comparison = SampleConfigService(engine).compare(
        tenant_id=context.tenant.id,
        project_id=project_id,
        sample_ids=tuple(body.sample_ids),
    )
    return SampleComparisonResponse(
        samples=[_sample_config_response(record) for record in comparison.samples],
        field_values=comparison.field_values,
        differing_fields=list(comparison.differing_fields),
        missing_configuration_sample_ids=list(comparison.missing_configuration_sample_ids),
    )


class TestPlanSuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=4000)
    request_id: UUID
    previous_finding_id: UUID | None = None
    prompt_version: Literal["test-plan-change-v5", "test-plan-change-v6"] | None = None
    sources: list[SourceSelection] | None = Field(default=None, max_length=8)


@router.get("/test-plans/{plan_id}/suggestion-sources")
def test_plan_suggestion_sources(
    project_id: UUID,
    plan_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    kind: SourceKind = "document",
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    with engine.connect() as connection:
        if (
            connection.execute(
                select(tables.test_plans.c.id).where(
                    tables.test_plans.c.id == plan_id,
                    tables.test_plans.c.tenant_id == context.tenant.id,
                    tables.test_plans.c.project_id == project_id,
                )
            ).scalar_one_or_none()
            is None
        ):
            raise HTTPException(status_code=404, detail="测试计划不存在")
        return list_sources(
            connection, tenant_id=context.tenant.id, project_id=project_id, kind=kind, offset=offset
        )


@router.post("/test-plans/{plan_id}/suggestion-requests", status_code=202)
def enqueue_test_plan_suggestion(
    project_id: UUID,
    plan_id: UUID,
    body: TestPlanSuggestionRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    gateway: Annotated[StructuredModelGateway, Depends(get_application_gateway)],
) -> dict[str, Any]:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    try:
        return TestPlanQueue(engine, gateway=gateway).submit(
            context=context,
            project_id=project_id,
            plan_id=plan_id,
            message=body.message,
            request_id=body.request_id,
            previous_finding_id=body.previous_finding_id,
            prompt_version=body.prompt_version,
            sources=body.sources,
        )
    except ObjectPermissionDeniedError as error:
        raise HTTPException(403, detail={"code": "TEST_PLAN_ACCESS_DENIED"}) from error
    except (TestPlanChangeError, PlanSourceError, CapabilityUnavailableError) as error:
        raise HTTPException(
            409,
            detail={
                "code": getattr(error, "code", "TEST_PLAN_REQUEST_CONFLICT"),
                "message": str(error),
            },
        ) from error


@router.get("/test-plans/{plan_id}/suggestion-requests/{run_id}")
def get_test_plan_request(
    project_id: UUID,
    plan_id: UUID,
    run_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return TestPlanQueue(engine).get(
            context=context, project_id=project_id, plan_id=plan_id, run_id=run_id
        )
    except ObjectPermissionDeniedError as error:
        raise HTTPException(403, detail={"code": "TEST_PLAN_ACCESS_DENIED"}) from error


@router.post("/test-plans/{plan_id}/suggestions")
def suggest_test_plan_changes(
    project_id: UUID,
    plan_id: UUID,
    body: TestPlanSuggestionRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    gateway: Annotated[StructuredModelGateway, Depends(get_application_gateway)],
) -> dict[str, Any]:
    no_store(response)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    try:
        return TestPlanSuggestionService(engine, gateway=gateway).create(
            tenant_id=context.tenant.id,
            project_id=project_id,
            plan_id=plan_id,
            actor_user_id=context.user.id,
            message=body.message,
            request_id=body.request_id,
            previous_finding_id=body.previous_finding_id,
            prompt_version=body.prompt_version,
            sources=body.sources,
            auth_version=context.user.auth_version,
        )
    except CapabilityUnavailableError as error:
        raise HTTPException(
            status_code=409, detail={"code": error.code, "message": "该能力当前不可用"}
        ) from error
    except (TestPlanChangeError, PlanSourceError) as error:
        raise HTTPException(
            status_code=403 if str(error) == "APPLICATION_AUTHORIZATION_DENIED" else 409,
            detail={"code": "TEST_PLAN_CHANGE_CONFLICT", "message": str(error)},
        ) from error
    except (NpiNotFoundError, NpiScopeError) as error:
        raise _error(error) from error


@router.get("/supplier-recovery/work-packages")
def supplier_recovery_work_packages(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    finding_id: UUID | None = None,
) -> dict[str, Any]:
    from app.domain.material_exceptions import _authorize
    from app.domain.supplier_recovery_findings import applications, review_context

    no_store(response)
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
            _authorize(c, context, project_id)
            result = review_context(c, context.tenant.id, project_id)
            if finding_id is not None:
                result.update(applications(c, context.tenant.id, project_id, finding_id))
            return result
    except Exception as error:
        raise _error(error) from error


@router.get("/supplier-recovery/items/{item_id}/results")
def supplier_recovery_results(
    project_id: UUID,
    item_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_version: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierRecoveryResults(engine).get(context, project_id, item_id, before_version)
    except Exception as error:
        raise _error(error) from error


@router.post("/supplier-recovery/items/{item_id}/results/preview")
def preview_supplier_recovery_result(
    project_id: UUID,
    item_id: UUID,
    body: RecoveryResultDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierRecoveryResults(engine).preview(context, project_id, item_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/supplier-recovery/items/{item_id}/results")
def record_supplier_recovery_result(
    project_id: UUID,
    item_id: UUID,
    body: RecoveryResultApply,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierRecoveryResults(engine).apply(context, project_id, item_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/supplier-recovery/items/{item_id}/reviews/preview")
def preview_supplier_recovery_review(
    project_id: UUID,
    item_id: UUID,
    body: RecoveryReviewDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierRecoveryReviews(engine).preview(context, project_id, item_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/supplier-recovery/items/{item_id}/reviews")
def record_supplier_recovery_review(
    project_id: UUID,
    item_id: UUID,
    body: RecoveryReviewApply,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierRecoveryReviews(engine).apply(context, project_id, item_id, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/supplier-notices/watches")
def supplier_notice_watches(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    watch_id: UUID | None = None,
    before_version: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierNoticeWatches(engine).get(context, project_id, watch_id, before_version)
    except Exception as error:
        raise _error(error) from error


@router.post("/supplier-notices/watches/preview")
def preview_supplier_notice_watch(
    project_id: UUID,
    body: NoticeWatchDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierNoticeWatches(engine).preview(context, project_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/supplier-notices/watches")
def save_supplier_notice_watch(
    project_id: UUID,
    body: NoticeWatchApply,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierNoticeWatches(engine).apply(context, project_id, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/supplier-notices/watches/{watch_id}/scans")
def supplier_notice_scans(
    project_id: UUID,
    watch_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierNoticeScans(engine).get(context, project_id, watch_id, before_id)
    except Exception as error:
        raise _error(error) from error


@router.post("/supplier-notices/watches/{watch_id}/scans")
def scan_supplier_notice(
    project_id: UUID,
    watch_id: UUID,
    body: NoticeScanRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierNoticeScans(engine).scan(context, project_id, watch_id, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/supplier-notices/watches/{watch_id}/dispatches")
def supplier_notice_dispatches(
    project_id: UUID,
    watch_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierNoticeDispatches(engine).get(context, project_id, watch_id, before_id)
    except Exception as error:
        raise _error(error) from error


@router.post("/supplier-notices/watches/{watch_id}/dispatches/{dispatch_id}/retry")
def retry_supplier_notice_dispatch(
    project_id: UUID,
    watch_id: UUID,
    dispatch_id: UUID,
    body: NoticeDispatchRetry,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierNoticeDispatches(engine).retry(
            context, project_id, watch_id, dispatch_id, body
        )
    except Exception as error:
        raise _error(error) from error


@router.get("/supplier-notices/candidates/{candidate_id}/reviews")
def supplier_notice_reviews(
    project_id: UUID,
    candidate_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_version: int | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierNoticeReviews(engine).get(context, project_id, candidate_id, before_version)
    except Exception as error:
        raise _error(error) from error


@router.get("/supplier-notices/candidates/{candidate_id}/text")
def supplier_notice_text(
    project_id: UUID,
    candidate_id: UUID,
    snapshot_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    offset: int = 0,
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierNoticeReviews(engine).text(
            context, project_id, candidate_id, snapshot_id, offset
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/supplier-notices/candidates/{candidate_id}/reviews/preview")
def preview_supplier_notice_review(
    project_id: UUID,
    candidate_id: UUID,
    body: NoticeReviewDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierNoticeReviews(engine).preview(context, project_id, candidate_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/supplier-notices/candidates/{candidate_id}/reviews")
def save_supplier_notice_review(
    project_id: UUID,
    candidate_id: UUID,
    body: NoticeReviewSave,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierNoticeReviews(engine).save(context, project_id, candidate_id, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/supplier-notices/candidates/{candidate_id}/applications")
def supplier_notice_applications(
    project_id: UUID,
    candidate_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierNoticeApplications(engine).get(context, project_id, candidate_id)
    except Exception as error:
        raise _error(error) from error


@router.get("/supplier-notices/links")
def supplier_notice_business_links(
    project_id: UUID,
    target_kind: NoticeTargetKind,
    target_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_id: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierNoticeApplications(engine).linked(
            context, project_id, target_kind, target_id, before_id
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/supplier-notices/candidates/{candidate_id}/applications/preview")
def preview_supplier_notice_application(
    project_id: UUID,
    candidate_id: UUID,
    body: NoticeApplicationDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierNoticeApplications(engine).preview(context, project_id, candidate_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/supplier-notices/candidates/{candidate_id}/applications")
def apply_supplier_notice(
    project_id: UUID,
    candidate_id: UUID,
    body: NoticeApplicationSave,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return SupplierNoticeApplications(engine).apply(context, project_id, candidate_id, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/supplier-notices/ecrs/{ecr_id}/impact")
def supplier_notice_impact(
    project_id: UUID,
    ecr_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.supplier_notice_impact import SupplierNoticeImpact

    no_store(response)
    try:
        return SupplierNoticeImpact(engine).get(context, project_id, ecr_id)
    except Exception as error:
        raise _error(error) from error


@router.get("/supplier-notices/ecrs/{ecr_id}/analysis-context")
def supplier_notice_analysis_context(
    project_id: UUID,
    ecr_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    depth: int = 3,
) -> dict[str, Any]:
    from app.ai.change_notice_preparation import read

    no_store(response)
    try:
        return read(engine, context, project_id, ecr_id, depth)
    except Exception as error:
        raise _error(error) from error


@router.get("/cost-inputs")
def cost_inputs_read(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    after: UUID | None = None,
    record_id: UUID | None = None,
    before_version: int | None = Query(default=None, ge=1),
    search: str | None = Query(default=None, min_length=1, max_length=128),
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostInputService(engine).get(
            context,
            project_id,
            after=after,
            record=record_id,
            before_version=before_version,
            search=search,
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/cost-inputs/{record_id}/preview")
def cost_input_preview(
    project_id: UUID,
    record_id: UUID,
    body: CostInputPreview,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostInputService(engine).preview(context, project_id, record_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/cost-inputs/{record_id}")
def cost_input_apply(
    project_id: UUID,
    record_id: UUID,
    body: CostInputApply,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostInputService(engine).apply(context, project_id, record_id, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/cost-rollups/options")
def cost_rollup_options(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    bom_id: UUID | None = None,
    after: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostRollupService(engine).options(context, project_id, bom_id, after)
    except Exception as error:
        raise _error(error) from error


@router.post("/cost-rollups/preview")
def cost_rollup_preview(
    project_id: UUID,
    body: RollupDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostRollupService(engine).prepare(context, project_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/cost-rollups")
def cost_rollup_save(
    project_id: UUID,
    body: RollupSave,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostRollupService(engine).save(context, project_id, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/cost-rollups")
def cost_rollup_history(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    rollup_id: UUID | None = None,
    before: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostRollupService(engine).get(context, project_id, rollup_id, before)
    except Exception as error:
        raise _error(error) from error


@router.get("/cost-freezes")
def cost_freeze_history(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    after: UUID | None = None,
    identity: UUID | None = None,
    search: str | None = Query(default=None, max_length=256),
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostFreezeService(engine).get(context, project_id, after, identity, search)
    except Exception as error:
        raise _error(error) from error


@router.post("/cost-freezes/preview")
def cost_freeze_preview(
    project_id: UUID,
    body: FreezeDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostFreezeService(engine).preview(context, project_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/cost-freezes")
def cost_freeze_request(
    project_id: UUID,
    body: FreezeRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostFreezeService(engine).request(context, project_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/cost-freezes/{identity}/decision-preview")
def cost_freeze_decision_preview(
    project_id: UUID,
    identity: UUID,
    body: FreezeDecision,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostFreezeService(engine).preview_decision(context, project_id, identity, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/cost-freezes/{identity}/decide")
def cost_freeze_decide(
    project_id: UUID,
    identity: UUID,
    body: FreezeDecide,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostFreezeService(engine).decide(context, project_id, identity, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/cost-backtests")
def cost_backtest_history(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    identity: UUID | None = None,
    before: UUID | None = None,
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostBacktestService(engine).get(context, project_id, identity, before)
    except Exception as error:
        raise _error(error) from error


@router.post("/cost-backtests/preview")
def cost_backtest_preview(
    project_id: UUID,
    body: BacktestDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostBacktestService(engine).preview(context, project_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/cost-backtests")
def cost_backtest_save(
    project_id: UUID,
    body: BacktestSave,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostBacktestService(engine).save(context, project_id, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/cost-imports")
def cost_import_history(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    object_store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
    identity: UUID | None = None,
    before: UUID | None = None,
    search: str | None = Query(default=None, max_length=256),
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostImportService(engine, object_store).get(
            context, project_id, identity, before, search
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/cost-imports/inspect")
def cost_import_inspect(
    project_id: UUID,
    body: CostImportInspect,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    object_store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostImportService(engine, object_store).inspect(
            context, project_id, body.document_id
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/cost-imports/preview")
def cost_import_preview(
    project_id: UUID,
    body: CostImportDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    object_store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostImportService(engine, object_store).preview(context, project_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/cost-imports/confirm")
def cost_import_confirm(
    project_id: UUID,
    body: CostImportConfirm,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    object_store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostImportService(engine, object_store).confirm(context, project_id, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/cost-gaps")
def cost_gap_history(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    identity: UUID | None = None,
    issue_id: UUID | None = None,
    before: UUID | None = None,
    observation_id: UUID | None = None,
    before_version: int | None = Query(default=None, ge=1),
    search: str | None = Query(default=None, max_length=256),
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostGapService(engine).get(
            context, project_id, identity, issue_id, before, observation_id, before_version, search
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/cost-gaps/preview")
def cost_gap_preview(
    project_id: UUID,
    body: GapDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostGapService(engine).preview(context, project_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/cost-gaps")
def cost_gap_create(
    project_id: UUID,
    body: GapSave,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostGapService(engine).create(context, project_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/cost-gaps/{identity}/preview")
def cost_gap_preview_observation(
    project_id: UUID,
    identity: UUID,
    body: GapObservation,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostGapService(engine).preview_observation(context, project_id, identity, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/cost-gaps/{identity}/observations")
def cost_gap_observe(
    project_id: UUID,
    identity: UUID,
    body: GapObserve,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostGapService(engine).observe(context, project_id, identity, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/cost-alternatives")
def cost_alternative_history(
    project_id: UUID,
    case_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    identity: UUID | None = None,
    root_id: UUID | None = None,
    before: UUID | None = None,
    search: str | None = Query(default=None, max_length=256),
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostAlternativeService(engine).get(
            context, project_id, case_id, identity, root_id, before, search
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/cost-alternatives/preview")
def cost_alternative_preview(
    project_id: UUID,
    body: AlternativeDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostAlternativeService(engine).preview(context, project_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/cost-alternatives")
def cost_alternative_save(
    project_id: UUID,
    body: AlternativeSave,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostAlternativeService(engine).save(context, project_id, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/cost-definition-feedback")
def cost_feedback_history(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    identity: UUID | None = None,
    source_kind: CostFeedbackSourceKind | None = None,
    source_id: UUID | None = None,
    before: UUID | None = None,
    before_version: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostDefinitionFeedbackService(engine).get(
            context,
            project=project_id,
            identity=identity,
            source_kind=source_kind,
            source_id=source_id,
            before=before,
            before_version=before_version,
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/cost-definition-feedback/preview")
def cost_feedback_preview(
    project_id: UUID,
    body: FeedbackDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostDefinitionFeedbackService(engine).preview(context, project_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/cost-definition-feedback")
def cost_feedback_save(
    project_id: UUID,
    body: FeedbackSave,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostDefinitionFeedbackService(engine).save(context, project_id, body)
    except Exception as error:
        raise _error(error) from error


@router.post("/cost-definition-feedback/{identity}/preview")
def cost_feedback_decision_preview(
    project_id: UUID,
    identity: UUID,
    body: DispositionDraft,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostDefinitionFeedbackService(engine).preview_disposition(
            context, project_id, identity, body
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/cost-definition-feedback/{identity}/decisions")
def cost_feedback_decide(
    project_id: UUID,
    identity: UUID,
    body: DispositionSave,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CostDefinitionFeedbackService(engine).decide(context, project_id, identity, body)
    except Exception as error:
        raise _error(error) from error


@router.get("/cost-reduction/runs")
def cost_reduction_runs(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_id: UUID | None = None,
    run_id: UUID | None = None,
) -> dict[str, Any]:
    from app.ai.cost_reduction_runs import CostRuns

    no_store(response)
    try:
        return CostRuns.list_results(
            engine, context=context, project_id=project_id, before_id=before_id, run_id=run_id
        )
    except Exception as error:
        raise _error(error) from error


@router.post("/cost-reduction/runs")
def create_cost_reduction_run(
    project_id: UUID,
    body: CostReductionRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.ai.application_gateway import configured_application_gateway
    from app.ai.cost_reduction_runs import KEY, CostRuns
    from app.ai.cost_reduction_runs import _access as cost_access
    from app.ai.rollout_guard import require_live_key

    no_store(response)
    try:
        cost_access(engine, context, project_id, Action.PRODUCT_ENGINEERING_EDIT)
        require_live_key(KEY)
        with configured_application_gateway(engine) as gateway:
            return CostRuns(engine, gateway=gateway).create(
                context=context, project_id=project_id, request=body
            )
    except (BudgetLedgerError, CapabilityUnavailableError) as error:
        raise HTTPException(
            409,
            detail={"code": error.code, "message": "成本建议能力、预算或授权尚未就绪；原记录保留"},
        ) from error
    except Exception as error:
        raise _error(error) from error


@router.get("/cost-reduction/sources")
def cost_reduction_sources(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.ai.cost_discussion_sources import authorize, options

    no_store(response)
    try:
        with engine.connect() as c:
            authorize(c, context, project_id)
            return {"items": options(c, context, project_id)}
    except Exception as error:
        raise _error(error) from error


@router.post("/cost-reduction/context")
def cost_reduction_context(
    project_id: UUID,
    body: CostReductionPreparation,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.ai.cost_reduction_preparation import source_state

    no_store(response)
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
            return source_state(
                c,
                context.tenant.id,
                project_id,
                CostReductionSelection.model_validate(
                    body.model_dump(exclude={"discussion_run_id"})
                ),
                context.user.id,
                body.discussion_run_id,
            )
    except Exception as error:
        raise _error(error) from error


@router.get("/cost-reduction/review-context")
def cost_reduction_review_context(
    project_id: UUID,
    observation_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    search: str | None = Query(default=None, max_length=256),
) -> dict[str, Any]:
    from app.db.schema import tables
    from app.domain.cost_alternatives import CostAlternativeService
    from app.domain.cost_definition_feedback import cost_access
    from app.domain.cost_freezes import row

    no_store(response)
    try:
        with engine.connect() as c:
            cost_access(c, context, project_id)
            observed = row(
                c, context.tenant.id, project_id, tables.cost_gap_observations, observation_id
            )
            case_id = observed["case_id"]
        result = CostAlternativeService(engine).get(context, project_id, case_id, search=search)
        return {
            "case_id": str(case_id),
            "observation_id": str(observation_id),
            "documents": result["documents"],
            "documents_more": result["documents_more"],
        }
    except Exception as error:
        raise _error(error) from error


@router.get("/cost-reduction/applications")
def cost_reduction_applications(
    project_id: UUID,
    finding_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, Any]:
    from app.domain.cost_definition_feedback import cost_access
    from app.domain.cost_reduction_findings import applications

    no_store(response)
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
            cost_access(c, context, project_id)
            return applications(c, context.tenant.id, project_id, finding_id)
    except Exception as error:
        raise _error(error) from error


@router.get("/cost-reduction/discussions")
def cost_reduction_discussions(
    project_id: UUID,
    observation_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before: UUID | None = None,
) -> dict[str, Any]:
    from app.ai.cost_discussion_input import options

    no_store(response)
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
            return options(c, context, project_id, observation_id, before)
    except Exception as error:
        raise _error(error) from error
