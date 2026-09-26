"""Synchronous AI API surface with server-enforced scope and evidence contracts."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine, func, select

from app.ai.application_control import ApplicationCancelReceipt
from app.ai.application_gateway import (
    ApplicationModelGateway,
    configured_application_gateway,
)
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.capability_contract import CAPABILITY_CONTRACTS
from app.ai.chat import ChatEvidence, ChatService
from app.ai.chat_queue import ChatQueue, ChatQueueReceipt
from app.ai.chat_runs import ChatRequestConflictError
from app.ai.embeddings import EmbeddingError, EmbeddingGateway, configured_embedding_gateway
from app.ai.event_control import EventPauseError, cancel_visible_run, control_pause
from app.ai.quality import FindingQualityService
from app.ai.risk_queue import RiskQueue, RiskQueueReceipt
from app.ai.risk_suggestions import (
    RiskSuggestionEvidenceError,
    RiskSuggestionEvidenceInUseError,
    RiskSuggestionRequestConflictError,
    RiskSuggestionService,
)
from app.ai.rollout_guard import CapabilityUnavailableError, employee_finding_visibility
from app.ai.run_progress import RunProgress, read_progress
from app.api.auth import current_context, no_store
from app.api.model_governance import get_model_governance_service
from app.api.work_items import authorize_project
from app.auth.errors import ObjectPermissionDeniedError
from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.db.engine import get_engine
from app.db.schema import tables
from app.domain import input_wait_responsibilities
from app.domain.documents import MAX_DOCUMENT_BYTES, DocumentError, DocumentService
from app.domain.findings import FindingService
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError
from app.domain.review_inbox import ReviewInboxService
from app.storage.documents import DocumentObjectStore, get_document_object_store

router = APIRouter(prefix="/api/ai", tags=["ai"])


class DocumentFragmentResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    ordinal: int
    locator: str
    href: str
    excerpt: str


class DocumentAnalysisResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: UUID
    project_id: UUID
    filename: str
    media_type: str
    classification: str
    size_bytes: int
    sha256: str
    extraction_status: str
    fragments: list[DocumentFragmentResponse]


class DocumentSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: UUID
    project_id: UUID
    filename: str
    media_type: str
    classification: str
    size_bytes: int
    sha256: str
    extraction_status: str
    created_at: datetime


class DocumentListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[DocumentSummaryResponse]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    question: str = Field(min_length=1, max_length=2_000)
    request_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=128)

    @field_validator("question", "request_id", mode="before")
    @classmethod
    def normalize_question(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ChatResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    answer: str | None
    citations: list[ChatEvidence]
    error_code: str | None = None


class RiskSuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    request_id: str = Field(min_length=1, max_length=128)
    concern: str = Field(min_length=1, max_length=2_000)
    evidence_event_ids: tuple[int, ...] = Field(min_length=1, max_length=100)

    @field_validator("request_id", "concern", mode="before")
    @classmethod
    def normalize_risk_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class RiskSuggestionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    run_id: UUID
    finding_id: UUID | None
    error_code: str | None


class AiBriefEvidenceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_row_id: int
    label: str
    href: str


class AiBriefItemResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    finding_id: UUID
    project_id: UUID
    finding_type: str
    finding_status: str
    title: str
    summary: str
    evidence: list[AiBriefEvidenceResponse]
    created_at: datetime
    href: str


class AiQualityControlResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_key: str
    finding_type: str
    status: str
    minimum_review_count: int
    acceptance_threshold_basis_points: int
    reviewed_count: int
    accepted_count: int
    applied_count: int
    acceptance_rate_basis_points: int | None
    narrowed_at: datetime | None
    narrowed_reason: str | None


class AiBriefResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["active", "unavailable"]
    error_code: str | None
    pending_review_count: int
    latest_finding_at: datetime | None
    reviewed_count: int
    accepted_count: int
    applied_count: int
    acceptance_rate_basis_points: int | None
    narrowed_output_count: int
    quality_controls: list[AiQualityControlResponse]
    items: list[AiBriefItemResponse]


def require_ai_action(context: AuthContext, action: Action) -> None:
    if not is_allowed(context.user.role, action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "OBJECT_PERMISSION_DENIED", "message": "AI action is not allowed"},
        )


def get_application_gateway(
    request: Request,
    engine: Annotated[Engine, Depends(get_engine)],
) -> Iterator[ApplicationModelGateway]:
    is_test_plan = getattr(request.scope.get("route"), "name", None) == "suggest_test_plan_changes"
    with configured_application_gateway(
        engine,
        request_timeout_seconds=90.0 if is_test_plan else 30.0,
        max_structured_attempts=1 if is_test_plan else 2,
    ) as gateway:
        yield gateway


def get_optional_embedding_gateway() -> Iterator[EmbeddingGateway | None]:
    try:
        with configured_embedding_gateway() as gateway:
            yield gateway
    except EmbeddingError as error:
        if error.code == "EMBEDDING_NOT_CONFIGURED":
            yield None
            return
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": error.code, "message": "Memory search is unavailable"},
        ) from error


@router.get("/projects/{project_id}/documents", response_model=DocumentListResponse)
def list_documents(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> DocumentListResponse:
    require_ai_action(context, Action.DOCUMENT_ANALYZE)
    authorize_project(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.PROJECT_VIEW,
    )
    no_store(response)
    return DocumentListResponse(
        items=[
            DocumentSummaryResponse(
                document_id=document.id,
                project_id=document.project_id,
                filename=document.filename,
                media_type=document.media_type,
                classification=document.classification,
                size_bytes=document.size_bytes,
                sha256=document.sha256,
                extraction_status=document.extraction_status,
                created_at=document.created_at,
            )
            for document in DocumentService(engine).list(
                tenant_id=context.tenant.id,
                project_id=project_id,
            )
        ]
    )


class RunInputWaitResponse(BaseModel):
    id: UUID
    finding_id: UUID
    owner_user_id: UUID
    questions: list[str]
    summary: str
    expires_at: datetime
    resolved_at: datetime | None
    resolution: str | None
    continuation_run_id: UUID | None


class AgentRunSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    agent_key: str
    status: str
    window_started_at: datetime
    window_ended_at: datetime
    dispatch_policy: str | None = None
    dispatch_deadline: datetime | None = None
    event_count: int
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    created_at: datetime
    input_wait: RunInputWaitResponse | None = None
    can_cancel: bool = False
    can_pause: bool = False
    can_resume: bool = False


class AgentRunListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[AgentRunSummaryResponse]
    pending_review_findings: int


@router.get("/projects/{project_id}/runs", response_model=AgentRunListResponse)
def list_agent_runs(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AgentRunListResponse:
    require_ai_action(context, Action.FINDING_VIEW)
    authorize_project(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.PROJECT_VIEW,
    )
    no_store(response)
    with engine.connect() as connection:
        rows = connection.execute(
            select(
                tables.agent_runs.c.id,
                tables.agent_runs.c.agent_key,
                tables.agent_runs.c.request_id,
                tables.agent_runs.c.subscription_id,
                tables.agent_runs.c.status,
                tables.agent_runs.c.window_started_at,
                tables.agent_runs.c.window_ended_at,
                tables.agent_runs.c.dispatch_policy,
                tables.agent_runs.c.dispatch_deadline,
                tables.agent_runs.c.event_count,
                tables.agent_runs.c.started_at,
                tables.agent_runs.c.completed_at,
                tables.agent_runs.c.error_code,
                tables.agent_runs.c.created_at,
                tables.event_run_pauses.c.id.label("pause_id"),
                tables.event_run_pauses.c.honored_at.label("pause_honored_at"),
                tables.budget_run_links.c.lineage_id,
                func.coalesce(
                    tables.agent_runs.c.requested_by_user_id,
                    tables.application_authorizations.c.principal_id,
                ).label("requested_by_user_id"),
            )
            .outerjoin(
                tables.application_authorizations,
                (tables.application_authorizations.c.tenant_id == tables.agent_runs.c.tenant_id)
                & (tables.application_authorizations.c.run_id == tables.agent_runs.c.id),
            )
            .outerjoin(
                tables.event_run_pauses,
                (tables.event_run_pauses.c.tenant_id == tables.agent_runs.c.tenant_id)
                & (tables.event_run_pauses.c.run_id == tables.agent_runs.c.id)
                & tables.event_run_pauses.c.resolved_at.is_(None),
            )
            .outerjoin(
                tables.budget_run_links,
                (tables.budget_run_links.c.tenant_id == tables.agent_runs.c.tenant_id)
                & (tables.budget_run_links.c.run_id == tables.agent_runs.c.id),
            )
            .where(
                tables.agent_runs.c.tenant_id == context.tenant.id,
                tables.agent_runs.c.project_id == project_id,
                func.coalesce(
                    tables.agent_runs.c.requested_by_user_id,
                    tables.application_authorizations.c.principal_id,
                ).is_(None)
                | (
                    func.coalesce(
                        tables.agent_runs.c.requested_by_user_id,
                        tables.application_authorizations.c.principal_id,
                    )
                    == context.user.id
                ),
            )
            .order_by(tables.agent_runs.c.created_at.desc(), tables.agent_runs.c.id.desc())
            .limit(limit)
        ).all()
        waits = {
            w["run_id"]: RunInputWaitResponse(
                id=w["id"],
                finding_id=w["finding_id"],
                owner_user_id=w["owner_user_id"],
                questions=w["body"]["questions"],
                summary=w["body"]["summary"],
                expires_at=w["expires_at"],
                resolved_at=w["resolved_at"],
                resolution=w["resolution"],
                continuation_run_id=w["continuation_run_id"],
            )
            for w in connection.execute(
                select(tables.application_input_waits).where(
                    tables.application_input_waits.c.tenant_id == context.tenant.id,
                    tables.application_input_waits.c.run_id.in_([row.id for row in rows]),
                )
            ).mappings()
        }
        pending = connection.execute(
            select(func.count()).where(
                tables.findings.c.tenant_id == context.tenant.id,
                tables.findings.c.project_id == project_id,
                tables.findings.c.status == "pending_review",
                employee_finding_visibility(),
            )
        ).scalar_one()
    return AgentRunListResponse(
        items=[
            AgentRunSummaryResponse(
                id=row.id,
                agent_key=row.agent_key,
                status="cancelled"
                if row.error_code in {"APPLICATION_REQUEST_CANCELLED", "EVENT_RUN_CANCELLED"}
                else "paused"
                if row.pause_id and row.pause_honored_at
                else "pausing"
                if row.pause_id
                else row.status,
                can_pause=(
                    row.pause_id is None
                    and row.lineage_id is not None
                    and row.requested_by_user_id is None
                    and row.request_id is None
                    and row.subscription_id is not None
                    and is_allowed(context.user.role, Action.PROJECT_EDIT)
                    and row.status in {"debouncing", "queued", "running"}
                ),
                can_resume=(
                    row.pause_id is not None
                    and is_allowed(context.user.role, Action.PROJECT_EDIT)
                    and row.status in {"debouncing", "queued", "running"}
                ),
                can_cancel=(
                    (
                        row.requested_by_user_id == context.user.id
                        and (
                            row.status in {"queued", "running", "waiting_input"}
                            or row.status == "degraded"
                            and row.error_code == "APPLICATION_RUN_LEASE_EXPIRED"
                        )
                    )
                    or (
                        row.requested_by_user_id is None
                        and row.request_id is None
                        and row.subscription_id is not None
                        and is_allowed(context.user.role, Action.PROJECT_EDIT)
                        and row.status in {"debouncing", "queued", "running", "waiting_input"}
                    )
                ),
                window_started_at=row.window_started_at,
                window_ended_at=row.window_ended_at,
                dispatch_policy=row.dispatch_policy,
                dispatch_deadline=row.dispatch_deadline,
                event_count=row.event_count,
                started_at=row.started_at,
                completed_at=row.completed_at,
                error_code=row.error_code,
                created_at=row.created_at,
                input_wait=waits.get(row.id),
            )
            for row in rows
        ],
        pending_review_findings=int(pending),
    )


@router.get("/projects/{project_id}/runs/{run_id}", response_model=RunProgress)
def agent_run_progress(
    project_id: UUID,
    run_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RunProgress:
    require_ai_action(context, Action.FINDING_VIEW)
    authorize_project(
        engine=engine, context=context, project_id=project_id, action=Action.PROJECT_VIEW
    )
    no_store(response)
    try:
        return read_progress(engine, context=context, project_id=project_id, run_id=run_id)
    except ObjectPermissionDeniedError as error:
        raise HTTPException(403, detail={"code": "RUN_PROGRESS_ACCESS_DENIED"}) from error


@router.post("/runs/{run_id}/cancel", response_model=ApplicationCancelReceipt)
def cancel_run(
    run_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ApplicationCancelReceipt:
    no_store(response)
    try:
        return cancel_visible_run(engine, context=context, run_id=run_id)
    except ObjectPermissionDeniedError as error:
        raise HTTPException(403, detail={"code": "APPLICATION_CONTROL_ACCESS_DENIED"}) from error


def _pause_response(
    engine: Engine, context: AuthContext, run_id: UUID, response: Response, *, resume: bool
) -> dict[str, object]:
    no_store(response)
    try:
        return control_pause(engine, context=context, run_id=run_id, resume=resume)
    except ObjectPermissionDeniedError as error:
        raise HTTPException(403, detail={"code": "APPLICATION_CONTROL_ACCESS_DENIED"}) from error
    except EventPauseError as error:
        raise HTTPException(409, detail={"code": str(error)}) from error


@router.post("/runs/{run_id}/pause")
def pause_event(
    run_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, object]:
    return _pause_response(engine, context, run_id, response, resume=False)


@router.post("/runs/{run_id}/resume")
def resume_event(
    run_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, object]:
    return _pause_response(engine, context, run_id, response, resume=True)


@router.get("/brief", response_model=AiBriefResponse)
def ai_brief(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> AiBriefResponse:
    require_ai_action(context, Action.FINDING_VIEW)
    records = FindingService(engine).list(
        tenant_id=context.tenant.id,
        actor_user_id=context.user.id,
        member_user_id=(None if context.user.role in {"owner", "admin"} else context.user.id),
    )
    try:
        governance = get_model_governance_service(engine).get(tenant_id=context.tenant.id)
        active = (
            governance.selection is not None
            and governance.selection.available
            and not governance.budget.exhausted
        )
        error_code = None if active else "MODEL_UNAVAILABLE"
    except HTTPException:
        active = False
        error_code = "MODEL_CATALOG_UNAVAILABLE"
    pending_count = sum(record.status == "pending_review" for record in records)
    quality = FindingQualityService(engine).snapshot(tenant_id=context.tenant.id)
    no_store(response)
    return AiBriefResponse(
        status="active" if active else "unavailable",
        error_code=error_code,
        pending_review_count=pending_count,
        latest_finding_at=records[0].created_at if records else None,
        reviewed_count=quality.reviewed_count,
        accepted_count=quality.accepted_count,
        applied_count=quality.applied_count,
        acceptance_rate_basis_points=quality.acceptance_rate_basis_points,
        narrowed_output_count=quality.narrowed_output_count,
        quality_controls=[
            AiQualityControlResponse(**control.__dict__) for control in quality.controls
        ],
        items=[
            AiBriefItemResponse(
                finding_id=record.id,
                project_id=record.project_id,
                finding_type=record.finding_type,
                finding_status=record.status,
                title=record.title,
                summary=record.summary,
                evidence=[
                    AiBriefEvidenceResponse(
                        event_row_id=event_id,
                        label=f"事件 #{event_id}",
                        href=(
                            f"/projects?project={record.project_id}"
                            f"&tab=overview&event_id={event_id}"
                        ),
                    )
                    for event_id in record.evidence_event_ids
                ],
                created_at=record.created_at,
                href=f"/ai-review?finding={record.id}",
            )
            for record in records[:5]
        ],
    )


class AiCapabilityResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    capability_key: str
    agent_key: str
    zone: str
    rollout: str
    prompt_version: str
    finding_types: list[str]
    projections: list[str]
    tools: list[str]
    quality_control: str
    controls: list[AiQualityControlResponse]


class AiCapabilityListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[AiCapabilityResponse]


@router.get("/capabilities", response_model=AiCapabilityListResponse)
def list_capabilities(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> AiCapabilityListResponse:
    require_ai_action(context, Action.FINDING_VIEW)
    no_store(response)
    quality = FindingQualityService(engine).snapshot(tenant_id=context.tenant.id)
    controls_by_pair: dict[tuple[str, str], list[AiQualityControlResponse]] = {}
    for control in quality.controls:
        controls_by_pair.setdefault((control.agent_key, control.finding_type), []).append(
            AiQualityControlResponse(**control.__dict__)
        )
    return AiCapabilityListResponse(
        items=[
            AiCapabilityResponse(
                capability_key=contract.key.value,
                agent_key=contract.agent_key.value,
                zone=contract.zone.value,
                rollout=contract.rollout.value,
                prompt_version=contract.prompt_version,
                finding_types=list(contract.finding_types),
                projections=list(contract.projections),
                tools=list(contract.tools),
                quality_control=contract.quality_control,
                controls=[
                    item
                    for finding_type in contract.finding_types
                    for item in controls_by_pair.get((contract.agent_key.value, finding_type), [])
                ],
            )
            for contract in CAPABILITY_CONTRACTS.values()
        ]
    )


class ReviewInboxItemResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str
    id: UUID
    title: str
    agent_key: str | None
    finding_type: str | None
    confidence_basis_points: int | None
    quality_acceptance_basis_points: int | None
    href: str
    created_at: datetime


class ReviewInboxGroupResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    project_name: str
    items: list[ReviewInboxItemResponse]


class ReviewInboxResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    groups: list[ReviewInboxGroupResponse]
    finding_count: int
    risk_candidate_count: int
    import_batch_count: int
    archived_count: int


@router.get("/review-inbox", response_model=ReviewInboxResponse)
def review_inbox(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ReviewInboxResponse:
    require_ai_action(context, Action.FINDING_VIEW)
    no_store(response)
    digest = ReviewInboxService(engine).digest(
        tenant_id=context.tenant.id,
        member_user_id=(None if context.user.role in {"owner", "admin"} else context.user.id),
    )
    return ReviewInboxResponse(
        groups=[
            ReviewInboxGroupResponse(
                project_id=group.project_id,
                project_name=group.project_name,
                items=[
                    ReviewInboxItemResponse(
                        kind=item.kind,
                        id=item.id,
                        title=item.title,
                        agent_key=item.agent_key,
                        finding_type=item.finding_type,
                        confidence_basis_points=item.confidence_basis_points,
                        quality_acceptance_basis_points=item.quality_acceptance_basis_points,
                        href=item.href,
                        created_at=item.created_at,
                    )
                    for item in group.items
                ],
            )
            for group in digest.groups
        ],
        finding_count=digest.finding_count,
        risk_candidate_count=digest.risk_candidate_count,
        import_batch_count=digest.import_batch_count,
        archived_count=digest.archived_count,
    )


class AiTouchpointResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    state: str  # 'enabled' | 'degraded' | 'disabled'
    reason_code: str | None
    manual_alternative: str


class AiTouchpointListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[AiTouchpointResponse]


_AI_TOUCHPOINTS: tuple[tuple[str, str, str, str], ...] = (
    # (key, label, degraded-instead-of-disabled?, manual alternative)
    ("ai_brief", "AI 简报", "disabled", "直接查看待审 Finding 列表与项目时间线"),
    ("ai_chat", "AI 问答", "disabled", "查看项目时间线、工作项与知识库检索"),
    ("document_analyze", "文档解析", "disabled", "手工阅读文档并在对应对象上录入要点"),
    ("risk_suggestion_api", "风险建议", "disabled", "在项目风险页手工创建风险并填写缓解计划"),
    (
        "test_report_import",
        "测试报告 AI 导入",
        "degraded",
        "已识别过的模板仍可零模型复用映射；新模板请按导入模板整理列或逐条录入测试结果",
    ),
    ("agent_runs", "事件驱动 Agent", "disabled", "关注规则引擎风险候选与提醒，人工巡检项目状态"),
)


@router.get("/touchpoints", response_model=AiTouchpointListResponse)
def list_touchpoints(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> AiTouchpointListResponse:
    require_ai_action(context, Action.FINDING_VIEW)
    no_store(response)
    reason_code: str | None
    try:
        governance = get_model_governance_service(engine).get(tenant_id=context.tenant.id)
        if governance.selection is None or not governance.selection.available:
            reason_code = "MODEL_UNAVAILABLE"
        elif governance.budget.exhausted:
            reason_code = "BUDGET_EXCEEDED"
        else:
            reason_code = None
    except HTTPException:
        reason_code = "MODEL_CATALOG_UNAVAILABLE"
    return AiTouchpointListResponse(
        items=[
            AiTouchpointResponse(
                key=key,
                label=label,
                state="enabled" if reason_code is None else off_state,
                reason_code=reason_code,
                manual_alternative=manual_alternative,
            )
            for key, label, off_state, manual_alternative in _AI_TOUCHPOINTS
        ]
    )


class AiUsageRowResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_key: str
    prompt_version: str
    invocation_count: int
    succeeded_count: int
    total_tokens: int


class AiUsageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    daily_token_budget: int | None
    used_tokens_today: int | None
    remaining_tokens_today: int | None
    budget_exhausted: bool
    rows: list[AiUsageRowResponse]


@router.get("/usage", response_model=AiUsageResponse)
def ai_usage(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> AiUsageResponse:
    require_ai_action(context, Action.FINDING_VIEW)
    no_store(response)
    try:
        budget = get_model_governance_service(engine).get(tenant_id=context.tenant.id).budget
    except HTTPException:
        budget = None
    from sqlalchemy import case, func, select

    from app.db.schema import tables

    with engine.connect() as connection:
        rows = connection.execute(
            select(
                tables.model_invocations.c.agent_key,
                tables.model_invocations.c.prompt_version,
                func.count().label("invocation_count"),
                func.sum(
                    case((tables.model_invocations.c.status == "succeeded", 1), else_=0)
                ).label("succeeded_count"),
                func.coalesce(func.sum(tables.model_invocations.c.total_tokens), 0).label(
                    "total_tokens"
                ),
            )
            .where(tables.model_invocations.c.tenant_id == context.tenant.id)
            .group_by(
                tables.model_invocations.c.agent_key,
                tables.model_invocations.c.prompt_version,
            )
            .order_by(
                tables.model_invocations.c.agent_key,
                tables.model_invocations.c.prompt_version,
            )
        ).all()
    return AiUsageResponse(
        daily_token_budget=budget.daily_token_budget if budget else None,
        used_tokens_today=budget.used_tokens_today if budget else None,
        remaining_tokens_today=budget.remaining_tokens_today if budget else None,
        budget_exhausted=bool(budget and budget.exhausted),
        rows=[
            AiUsageRowResponse(
                agent_key=row.agent_key,
                prompt_version=row.prompt_version,
                invocation_count=int(row.invocation_count),
                succeeded_count=int(row.succeeded_count),
                total_tokens=int(row.total_tokens),
            )
            for row in rows
        ],
    )


@router.post("/chat/requests", response_model=ChatQueueReceipt, status_code=202)
def enqueue_chat(
    request: ChatRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    gateway: Annotated[ApplicationModelGateway, Depends(get_application_gateway)],
) -> ChatQueueReceipt:
    require_ai_action(context, Action.AI_CHAT_USE)
    no_store(response)
    try:
        return ChatQueue(engine, gateway=gateway).submit(
            context=context,
            project_id=request.project_id,
            question=request.question,
            request_id=request.request_id,
        )
    except ObjectPermissionDeniedError as error:
        raise HTTPException(403, detail={"code": "CHAT_ACCESS_DENIED"}) from error
    except (BudgetLedgerError, ChatRequestConflictError) as error:
        raise HTTPException(
            409, detail={"code": getattr(error, "code", "CHAT_REQUEST_CONFLICT")}
        ) from error


@router.get("/chat/requests/{run_id}", response_model=ChatQueueReceipt)
def get_chat_request(
    run_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    gateway: Annotated[ApplicationModelGateway, Depends(get_application_gateway)],
) -> ChatQueueReceipt:
    no_store(response)
    try:
        return ChatQueue(engine, gateway=gateway).get(context=context, run_id=run_id)
    except ObjectPermissionDeniedError as error:
        raise HTTPException(403, detail={"code": "CHAT_ACCESS_DENIED"}) from error


@router.post("/chat/requests/{run_id}/cancel", response_model=ChatQueueReceipt)
def cancel_chat_request(
    run_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    gateway: Annotated[ApplicationModelGateway, Depends(get_application_gateway)],
) -> ChatQueueReceipt:
    no_store(response)
    try:
        return ChatQueue(engine, gateway=gateway).cancel(context=context, run_id=run_id)
    except ObjectPermissionDeniedError as error:
        raise HTTPException(403, detail={"code": "CHAT_ACCESS_DENIED"}) from error


@router.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    gateway: Annotated[ApplicationModelGateway, Depends(get_application_gateway)],
    embedding_gateway: Annotated[
        EmbeddingGateway | None,
        Depends(get_optional_embedding_gateway),
    ],
) -> ChatResponse:
    require_ai_action(context, Action.AI_CHAT_USE)
    authorize_project(
        engine=engine,
        context=context,
        project_id=request.project_id,
        action=Action.PROJECT_VIEW,
    )
    try:
        result = ChatService(
            engine,
            gateway=gateway,
            embedding_gateway=embedding_gateway,
        ).answer(
            context=context,
            project_id=request.project_id,
            question=request.question,
            request_id=request.request_id,
        )
    except BudgetLedgerError as error:
        raise HTTPException(
            status_code=403 if error.code == "APPLICATION_AUTHORIZATION_DENIED" else 409,
            detail={"code": error.code, "message": "当前请求无法获得运行授权"},
        ) from error
    except ChatRequestConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CHAT_REQUEST_CONFLICT",
                "message": "Request is in progress or conflicts with its original content or user",
            },
        ) from error
    except ObjectPermissionDeniedError as error:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "CHAT_ACCESS_DENIED",
                "message": "Chat access is no longer available",
            },
        ) from error
    no_store(response)
    return ChatResponse(
        status=result.status,
        answer=result.answer,
        citations=list(result.citations),
        error_code=result.error_code,
    )


@router.post("/risk-suggestions/requests", response_model=RiskQueueReceipt, status_code=202)
def enqueue_risk_suggestion(
    request: RiskSuggestionRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    gateway: Annotated[ApplicationModelGateway, Depends(get_application_gateway)],
) -> RiskQueueReceipt:
    no_store(response)
    try:
        return RiskQueue(engine, gateway=gateway).submit(context=context, **request.model_dump())
    except ObjectPermissionDeniedError as error:
        raise HTTPException(403, detail={"code": "RISK_ACCESS_DENIED"}) from error
    except RiskSuggestionEvidenceError as error:
        raise HTTPException(422, detail={"code": "RISK_EVIDENCE_INVALID"}) from error
    except (
        BudgetLedgerError,
        CapabilityUnavailableError,
        RiskSuggestionRequestConflictError,
    ) as error:
        raise HTTPException(
            409, detail={"code": getattr(error, "code", "RISK_REQUEST_CONFLICT")}
        ) from error


@router.get("/risk-suggestions/requests/{run_id}", response_model=RiskQueueReceipt)
def get_risk_request(
    run_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    gateway: Annotated[ApplicationModelGateway, Depends(get_application_gateway)],
) -> RiskQueueReceipt:
    no_store(response)
    try:
        return RiskQueue(engine, gateway=gateway).get(context=context, run_id=run_id)
    except ObjectPermissionDeniedError as error:
        raise HTTPException(403, detail={"code": "RISK_ACCESS_DENIED"}) from error


@router.post("/create-risk-suggestion", response_model=RiskSuggestionResponse)
def create_risk_suggestion(
    request: RiskSuggestionRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    gateway: Annotated[ApplicationModelGateway, Depends(get_application_gateway)],
) -> RiskSuggestionResponse:
    require_ai_action(context, Action.RISK_SUGGESTION_CREATE)
    authorize_project(
        engine=engine,
        context=context,
        project_id=request.project_id,
        action=Action.PROJECT_VIEW,
    )
    try:
        result = RiskSuggestionService(engine, gateway=gateway).create(
            tenant_id=context.tenant.id,
            project_id=request.project_id,
            actor_user_id=context.user.id,
            request_id=request.request_id,
            concern=request.concern,
            evidence_event_ids=request.evidence_event_ids,
            auth_version=context.user.auth_version,
        )
    except CapabilityUnavailableError as error:
        raise HTTPException(
            status_code=409, detail={"code": error.code, "message": "该能力当前不可用"}
        ) from error
    except BudgetLedgerError as error:
        raise HTTPException(
            status_code=403 if error.code == "APPLICATION_AUTHORIZATION_DENIED" else 409,
            detail={"code": error.code, "message": "当前请求无法获得运行授权"},
        ) from error
    except RiskSuggestionEvidenceError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "RISK_EVIDENCE_INVALID", "message": str(error)},
        ) from error
    except RiskSuggestionEvidenceInUseError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": error.code,
                "message": "所选最早证据已有风险建议运行；请沿原建议办理，或以更新的证据事件发起",
            },
        ) from error
    except RiskSuggestionRequestConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "RISK_REQUEST_CONFLICT",
                "message": "request_id was already used with another request",
            },
        ) from error
    no_store(response)
    return RiskSuggestionResponse(
        status=result.status,
        run_id=result.run_id,
        finding_id=result.finding_id,
        error_code=result.error_code,
    )


@router.post(
    "/analyze-document",
    response_model=DocumentAnalysisResponse,
    status_code=status.HTTP_201_CREATED,
)
async def analyze_document(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    object_store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
    file: Annotated[UploadFile, File()],
    project_id: Annotated[UUID, Form()],
    classification: Annotated[
        str,
        Form(pattern=r"^(internal|confidential|restricted)$"),
    ] = "internal",
) -> DocumentAnalysisResponse:
    require_ai_action(context, Action.DOCUMENT_ANALYZE)
    authorize_project(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.PROJECT_VIEW,
    )
    content = await file.read(MAX_DOCUMENT_BYTES + 1)
    try:
        document = DocumentService(engine, object_store=object_store).analyze(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            filename=file.filename or "",
            classification=classification,
            content=content,
        )
    except DocumentError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": error.code, "message": str(error)},
        ) from error
    no_store(response)
    return DocumentAnalysisResponse(
        document_id=document.id,
        project_id=document.project_id,
        filename=document.filename,
        media_type=document.media_type,
        classification=document.classification,
        size_bytes=document.size_bytes,
        sha256=document.sha256,
        extraction_status=document.extraction_status,
        fragments=[
            DocumentFragmentResponse(
                ordinal=fragment.ordinal,
                locator=fragment.locator,
                href=(
                    f"/projects?project={document.project_id}"
                    f"&tab=overview&document_id={document.id}&entity_id={document.id}"
                    f"&fragment={fragment.ordinal}"
                ),
                excerpt=fragment.text[:500],
            )
            for fragment in document.fragments
        ],
    )


@router.get("/projects/{project_id}/input-waits/{wait_id}/responsibility")
def get_input_wait_responsibility(
    project_id: UUID,
    wait_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before_id: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, object]:
    no_store(response)
    try:
        return input_wait_responsibilities.read(engine, context, project_id, wait_id, before_id)
    except ProductWorkAccessError as exc:
        raise HTTPException(403, detail={"message": str(exc)}) from exc
    except ProductWorkError as exc:
        raise HTTPException(409, detail={"message": str(exc)}) from exc


@router.post("/projects/{project_id}/input-waits/{wait_id}/responsibility")
def reassign_input_wait_responsibility(
    project_id: UUID,
    wait_id: UUID,
    body: input_wait_responsibilities.Reassign,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> dict[str, object]:
    no_store(response)
    try:
        return input_wait_responsibilities.reassign(engine, context, project_id, wait_id, body)
    except ProductWorkAccessError as exc:
        raise HTTPException(403, detail={"message": str(exc)}) from exc
    except ProductWorkError as exc:
        raise HTTPException(409, detail={"message": str(exc)}) from exc
