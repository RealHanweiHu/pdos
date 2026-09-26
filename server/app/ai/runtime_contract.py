"""Frozen Phase 1 Agent routing, run context, and lifecycle contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgentKey(StrEnum):
    PRODUCT_MANAGEMENT_INTELLIGENCE = "product_management_intelligence"
    PROJECT_INTELLIGENCE = "project_intelligence"
    KNOWLEDGE_LITE = "knowledge_lite"
    ENGINEERING_INTELLIGENCE = "engineering_intelligence"
    QUALITY_INTELLIGENCE = "quality_intelligence"
    SUPPLIER_INTELLIGENCE = "supplier_intelligence"
    EXECUTIVE_INTELLIGENCE = "executive_intelligence"


PHASE_ONE_AGENT_KEYS = frozenset({AgentKey.PROJECT_INTELLIGENCE, AgentKey.KNOWLEDGE_LITE})
PHASE_TWO_AGENT_KEYS = frozenset({AgentKey.ENGINEERING_INTELLIGENCE, AgentKey.QUALITY_INTELLIGENCE})
PHASE_THREE_AGENT_KEYS = frozenset(
    {AgentKey.SUPPLIER_INTELLIGENCE, AgentKey.EXECUTIVE_INTELLIGENCE}
)


class AgentRunStatus(StrEnum):
    DEBOUNCING = "debouncing"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    SUCCEEDED = "succeeded"
    DEGRADED = "degraded"
    FAILED = "failed"


class InvalidRunTransitionError(ValueError):
    """Raised when runtime code tries to skip or mutate the run lifecycle."""


_EVENT_AGENT_ROUTES: dict[str, tuple[AgentKey, ...]] = {
    "PROJECT_STAGE_CHANGED": (
        AgentKey.PROJECT_INTELLIGENCE,
        AgentKey.EXECUTIVE_INTELLIGENCE,
    ),
    "ISSUE_CREATED": (AgentKey.PROJECT_INTELLIGENCE,),
    "ISSUE_STATUS_CHANGED": (AgentKey.PROJECT_INTELLIGENCE,),
    "NCR_CREATED": (AgentKey.QUALITY_INTELLIGENCE,),
    "TEST_FAILED": (
        AgentKey.PROJECT_INTELLIGENCE,
        AgentKey.QUALITY_INTELLIGENCE,
    ),
    "GATE_APPROVED": (
        AgentKey.KNOWLEDGE_LITE,
        AgentKey.EXECUTIVE_INTELLIGENCE,
    ),
    "DOCUMENT_UPLOADED": (AgentKey.KNOWLEDGE_LITE,),
    "DEVELOPMENT_BOM_CREATED": (AgentKey.ENGINEERING_INTELLIGENCE,),
    "DEVELOPMENT_BOM_ITEM_ADDED": (AgentKey.ENGINEERING_INTELLIGENCE,),
    "CHANGE_RECORD_CHANGED": (AgentKey.ENGINEERING_INTELLIGENCE,),
    "COMPLAINT_CREATED": (AgentKey.QUALITY_INTELLIGENCE,),
    "SUPPLIER_DELAY_REPORTED": (AgentKey.SUPPLIER_INTELLIGENCE,),
}

# Explicit no-route decisions (vNext V1-A9): every catalog event type must appear
# either in the route table above or here, so adding an event forces a decision.
# Rationale buckets: identity/infra noise (USER_*, TENANT_*, DINGTALK_*, REMINDER_*),
# rule-engine-covered signals (TASK_*, RISK_*), agent-output feedback loops
# (AI_*, MEMORY_*), and low-signal CRUD updates already covered by a routed
# sibling event.
NO_ROUTE_EVENT_TYPES: frozenset[str] = frozenset(
    {
        # N7 consent, observations and independent reception receipts feed
        # descriptive calculations only; participation never requests model work.
        "RESEARCH_MEASUREMENT_RECORDED",
        "RESEARCH_WORKPACK_RECORDED",
        "VALUE_MEASUREMENT_RECORDED",
        "VALUE_WORKPACK_RECORDED",
        # Named output generation, release/withdrawal and evidence bundling are
        # deterministic export operations, not inputs to an implicit model run.
        "AUDIT_REPORT_BUNDLED",
        "CUSTOMER_REPORT_RECORDED",
        "PROJECT_REPORT_EXPORTED",
        "PROJECT_REPORT_WITHDRAWN",
        # Access and delivery audit facts retain their dedicated authorization
        # paths; an API call or webhook receipt cannot grant model execution.
        "OPEN_API_ACCESS_CHANGED",
        "OPEN_API_CALLED",
        "WEBHOOK_RECORDED",
        "TENCENT_MEETING_IDENTITY_CHANGED",  # Account binding is identity administration.
        # Capturing a source is not a delay finding. Supply projections use the
        # fixed snapshot; the existing SUPPLIER_DELAY_REPORTED route stays separate.
        "SUPPLY_SNAPSHOT_CAPTURED",
        # Human intake/source correction and versioned template/meeting briefs
        # are preparation records. AI preparation requires its explicit request.
        "DECISION_INTAKE_SOURCE_RECORDED",
        "ISSUE_INTAKE_SOURCE_RECORDED",
        "PROJECT_INTAKE_RECORDED",
        "PROCESS_TEMPLATE_BRIEF_CREATED",
        "PROCESS_TEMPLATE_CHANGED",
        "MEETING_PLANNING_CHANGED",
        # Human review/application receipts must not feed back into a new run.
        "INTAKE_AI_FINDING_RECORDED",
        "PROCESS_TEMPLATE_FINDING_RECORDED",
        "MEETING_PLAN_FINDING_RECORDED",
        "QUALITY_WORK_PACKAGE_APPLIED",
        # Recurring meeting setup and generation use the bounded scheduler;
        # changing recurrence does not request model preparation or external delivery.
        "MEETING_RECURRENCE_UPDATED",
        # Named quality commands and FMEA candidates/revisions/publications use
        # deterministic projections and human disposition, without model inference.
        "FMEA_CANDIDATE_RECORDED",
        "FMEA_VERSION_PUBLISHED",
        "FMEA_VERSION_RECORDED",
        "QUALITY_ISSUE_LINK_RECORDED",
        "QUALITY_OPERATION_RECORDED",
        # Scoring, follow-up and change-window decisions are deterministic or
        # human-owned; portfolio AI explanation remains an explicit request.
        "PORTFOLIO_COMPARISON_RECORDED",
        "PORTFOLIO_ESCALATION_CHANGED",
        "CHANGE_QUIET_PERIOD_RECORDED",
        # N0–N2 manual workflows currently emit audit facts only. Their planned
        # AI preparation capabilities require explicit runtime wiring before routing.
        "BASELINE_CHANGE_RECORDED",
        "CROSS_PROJECT_SCHEDULE_RECORDED",
        "DEFINITION_PUBLISHED",
        "FORECAST_CAPACITY_CHECKED",
        "ID_DESIGN_RECORDED",
        "INITIAL_PLAN_APPLIED",
        "INITIAL_PLAN_PREPARED",
        "INITIAL_PLAN_REVIEW_CHANGED",
        "LEGACY_RESOURCE_RECONCILED",
        "PLANNING_RESOURCE_CREATED",
        "PLAN_CAPACITY_CHECKED",
        "PLAN_RESPONSIBILITY_RESPONDED",
        "PLAN_SCENARIO_CALCULATED",
        "PREPROJECT_RECORD_CHANGED",
        "PROJECT_EXECUTION_CHANGED",
        "PROJECT_SCENARIO_CAPACITY_CHECKED",
        "PROJECT_SCHEDULE_SCENARIO_EVALUATED",
        "RESEARCH_TASK_CHANGED",
        "RESOURCE_CAPACITY_PUBLISHED",
        "RESOURCE_RESERVATION_CHANGED",
        "RESOURCE_RESERVATION_RECORDED",
        "RESOURCE_RESERVATION_REPLACED",
        "REVIEW_FINALIZED",
        "REVIEW_RECORD_CHANGED",
        "SCHEDULE_ACTUAL_CORRECTED",
        "SCHEDULE_COMMITMENT_CHANGED",
        "SCHEDULE_FORECAST_RECALCULATED",
        "SCHEDULE_MILESTONE_COMPLETED",
        "SCHEDULE_NODE_REGISTERED",
        "SCHEDULE_SOURCE_ACTUAL_CORRECTED",
        "WORK_CALENDAR_PUBLISHED",
        "AI_FEEDBACK_RECEIVED",
        "AI_FINDING_CREATED",
        "CAPA_ACTION_CREATED",
        "CAPA_ACTION_STATUS_CHANGED",
        "COMPLAINT_STATUS_CHANGED",
        "CRM_REQUIREMENT_RECEIVED",
        "CUSTOMER_CREATED",
        "DECISION_RECORDED",
        "DELIVERABLE_CHECK_CHANGED",
        "DEPARTMENT_CREATED",
        "DEVELOPMENT_CASE_CREATED",
        "DEVELOPMENT_CASE_STATUS_CHANGED",
        "DEVELOPMENT_CASE_UPDATED",
        "DINGTALK_APPROVAL_UPDATED",
        "DINGTALK_CARD_ACTION_RECEIVED",
        "DINGTALK_IDENTITY_LINKED",
        "DINGTALK_NOTIFICATION_DELIVERED",
        "EFFECTIVENESS_REVIEWED",
        "ERP_BOM_REFERENCE_ADDED",
        "ISSUE_UPDATED",
        # V2-1: meetings emit state changes, but no agent capability consumes
        # them until V2-5 lands `meeting_minutes`.
        "MEETING_STATE_CHANGED",
        # V2-9: a debate is convened explicitly (by an agent or a person), so
        # its state changes drive notifications, not another agent run.
        "DEBATE_STATE_CHANGED",
        # V2-7: evidence is captured by people today; V2-8 agent-reach adds the
        # agent path, still without a dispatcher route back into an agent run.
        "EVIDENCE_SNAPSHOT_CAPTURED",
        "RESEARCH_SOURCE_CHANGED",
        "KNOWLEDGE_CORRECTION_PROPOSED",  # Human correction queue, no automatic model work.
        "KNOWLEDGE_CORRECTION_REVIEWED",
        "KNOWLEDGE_REUSE_STATE_CHANGED",  # Retrieval receipt, never another agent run.
        "KNOWLEDGE_USE_RECORDED",  # Human use receipt; does not request model work.
        "MEMORY_ARCHIVED",
        "MEMORY_DRAFT_CREATED",
        "MEMORY_DRAFT_UPDATED",
        "MEMORY_EMBEDDED",
        "MEMORY_VERIFIED",
        "NCR_PREVENTIVE_DISPOSITION_APPROVED",
        "NCR_STATUS_CHANGED",
        "NPI_RECORD_CHANGED",
        "PROJECT_CREATED",
        "PROJECT_STATUS_CHANGED",
        "PROJECT_UPDATED",
        "RESOURCE_RESERVATION_OWNER_TRANSFERRED",
        "DECISION_RESPONSIBILITY_CHANGED",
        "APPLICATION_INPUT_RESPONSIBILITY_CHANGED",  # Human follow-up only.
        "QUALITY_RESPONSIBILITY_CHANGED",  # Human reassignment, no model work.
        "REMINDER_STATE_CHANGED",
        "REQUIREMENT_CONVERTED",
        "REQUIREMENT_CREATED",
        "REQUIREMENT_UPDATED",
        "RISK_CREATED",
        "RISK_STATUS_CHANGED",
        "RISK_UPDATED",
        "ROOT_CAUSE_ANALYSIS_CHANGED",
        "SPECIFICATION_CREATED",
        "TASK_TAKEOVER_RECORDED",  # Human handoff, never implicit model execution.
        "TASK_CREATED",
        "TASK_STATUS_CHANGED",
        "TASK_UPDATED",
        "TENANT_BOOTSTRAPPED",
        "TENANT_MODEL_SETTINGS_UPDATED",
        "USER_CREATED",
        "USER_DELEGATION_GRANTED",
        "USER_DELEGATION_REVOKED",
        "USER_RESPONSIBILITY_TRANSFERRED",
        "USER_PASSWORD_CHANGED",
        "USER_PASSWORD_RESET",
        "USER_SIGNED_IN",
        "USER_UPDATED",
    }
)

_RUN_EDGES: dict[AgentRunStatus, frozenset[AgentRunStatus]] = {
    AgentRunStatus.DEBOUNCING: frozenset({AgentRunStatus.QUEUED}),
    AgentRunStatus.QUEUED: frozenset({AgentRunStatus.RUNNING}),
    AgentRunStatus.RUNNING: frozenset(
        {
            AgentRunStatus.SUCCEEDED,
            AgentRunStatus.DEGRADED,
            AgentRunStatus.FAILED,
            AgentRunStatus.WAITING_INPUT,
        }
    ),
    AgentRunStatus.WAITING_INPUT: frozenset(
        {AgentRunStatus.SUCCEEDED, AgentRunStatus.DEGRADED, AgentRunStatus.FAILED}
    ),
    AgentRunStatus.SUCCEEDED: frozenset(),
    AgentRunStatus.DEGRADED: frozenset(),
    AgentRunStatus.FAILED: frozenset(),
}


def agents_for_event(event_type: str) -> tuple[AgentKey, ...]:
    return _EVENT_AGENT_ROUTES.get(event_type, ())


def allowed_run_transition(
    current: AgentRunStatus,
    next_status: AgentRunStatus,
) -> AgentRunStatus:
    if next_status not in _RUN_EDGES[current]:
        raise InvalidRunTransitionError(f"invalid Agent run transition: {current}->{next_status}")
    return next_status


class EventReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: int = Field(ge=1)
    event_type: str = Field(min_length=1, max_length=64)
    entity: str = Field(min_length=1, max_length=64)
    entity_id: UUID
    timestamp: datetime


class MultimodalFragment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reference_id: str = Field(min_length=1, max_length=768)
    document_id: UUID
    ordinal: int = Field(ge=1)
    locator: str = Field(min_length=1, max_length=256)
    excerpt: str = Field(min_length=1, max_length=1_000)


class MultimodalDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: UUID
    filename: str = Field(min_length=1, max_length=512)
    media_type: str = Field(min_length=1, max_length=128)
    extraction_status: Literal["extracted"] = "extracted"
    fragments: tuple[MultimodalFragment, ...] = Field(max_length=20)
    shown_fragment_count: int = Field(ge=0, le=20)
    total_fragment_count: int = Field(ge=1)
    truncated: bool

    @model_validator(mode="after")
    def validate_fragment_counts(self) -> MultimodalDocument:
        if self.shown_fragment_count != len(self.fragments):
            raise ValueError("shown fragment count does not match fragments")
        if self.total_fragment_count < self.shown_fragment_count:
            raise ValueError("total fragment count cannot be below shown count")
        if self.truncated != (self.total_fragment_count > self.shown_fragment_count):
            raise ValueError("document truncation flag is inconsistent")
        return self


class MultimodalContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["not_applicable", "ready", "not_available"]
    documents: tuple[MultimodalDocument, ...] = Field(max_length=5)
    requested_document_count: int = Field(ge=0)
    available_document_count: int = Field(ge=0, le=5)
    unavailable_document_count: int = Field(ge=0)
    shown_fragment_count: int = Field(ge=0, le=20)
    total_fragment_count: int = Field(ge=0)
    truncated: bool

    @model_validator(mode="after")
    def validate_status_and_counts(self) -> MultimodalContext:
        shown = sum(document.shown_fragment_count for document in self.documents)
        total = sum(document.total_fragment_count for document in self.documents)
        if shown != self.shown_fragment_count or total != self.total_fragment_count:
            raise ValueError("multimodal fragment counts are inconsistent")
        if len(self.documents) != self.available_document_count:
            raise ValueError("available document count does not match documents")
        if self.requested_document_count < (
            self.available_document_count + self.unavailable_document_count
        ):
            raise ValueError("requested document count is inconsistent")
        if self.status == "not_applicable" and (
            self.requested_document_count != 0 or self.documents
        ):
            raise ValueError("not_applicable multimodal context cannot contain documents")
        if self.status == "ready" and not self.documents:
            raise ValueError("ready multimodal context requires an available document")
        if self.status == "not_available" and (
            self.requested_document_count == 0 or self.documents
        ):
            raise ValueError("not_available multimodal context is inconsistent")
        if self.truncated != (
            self.requested_document_count > 5
            or self.total_fragment_count > self.shown_fragment_count
        ):
            raise ValueError("multimodal truncation flag is inconsistent")
        return self


class ProjectRoleSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal[
        "owner",
        "admin",
        "project_manager",
        "engineer",
        "quality",
        "supplier",
        "customer",
    ]
    active_member_count: int = Field(ge=1)


class UserContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    perspective_role: Literal["project_manager", "engineer", "quality", "supplier", "executive"]
    role_lens: str = Field(min_length=1, max_length=512)
    project_roles: tuple[ProjectRoleSummary, ...]
    decision_mode: Literal["advisory_only"] = "advisory_only"
    review_required: Literal[True] = True
    apply_requires_separate_human_action: Literal[True] = True


_PERSPECTIVE_ROLES = {
    AgentKey.PROJECT_INTELLIGENCE: "project_manager",
    AgentKey.KNOWLEDGE_LITE: "engineer",
    AgentKey.ENGINEERING_INTELLIGENCE: "engineer",
    AgentKey.QUALITY_INTELLIGENCE: "quality",
    AgentKey.SUPPLIER_INTELLIGENCE: "supplier",
    AgentKey.EXECUTIVE_INTELLIGENCE: "executive",
}
_ROLE_LENSES = {
    AgentKey.PROJECT_INTELLIGENCE: (
        "Prioritize cross-functional delivery, blockers, stage readiness, and explicit "
        "human ownership without claiming authority to change project truth."
    ),
    AgentKey.KNOWLEDGE_LITE: (
        "Prioritize reusable engineering knowledge with traceable evidence; treat every "
        "draft as unverified until a separate human verification action."
    ),
    AgentKey.ENGINEERING_INTELLIGENCE: (
        "Prioritize BOM and engineering-change impact for an engineer audience without "
        "approving or modifying engineering records."
    ),
    AgentKey.QUALITY_INTELLIGENCE: (
        "Prioritize containment, evidence clusters, and CAPA hypotheses for a quality "
        "audience without asserting root cause or modifying quality records."
    ),
    AgentKey.SUPPLIER_INTELLIGENCE: (
        "Prioritize recurring supplier-delay exposure and Project impact without changing "
        "supplier, schedule, sourcing, or delivery facts."
    ),
    AgentKey.EXECUTIVE_INTELLIGENCE: (
        "Prioritize bounded cross-Project portfolio exceptions for an executive audience "
        "without ranking people or changing Project truth."
    ),
}


def empty_multimodal_context() -> MultimodalContext:
    return MultimodalContext(
        status="not_applicable",
        documents=(),
        requested_document_count=0,
        available_document_count=0,
        unavailable_document_count=0,
        shown_fragment_count=0,
        total_fragment_count=0,
        truncated=False,
    )


def user_context_for_agent(
    agent_key: AgentKey,
    *,
    project_roles: tuple[ProjectRoleSummary, ...] = (),
) -> UserContext:
    return UserContext(
        perspective_role=_PERSPECTIVE_ROLES[agent_key],  # type: ignore[arg-type]
        role_lens=_ROLE_LENSES[agent_key],
        project_roles=project_roles,
    )


class FrozenRunContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[2] = 2
    tenant_id: UUID
    project_id: UUID
    run_id: UUID
    agent_key: AgentKey
    built_at: datetime
    window_started_at: datetime
    window_ended_at: datetime
    trigger_events: tuple[EventReference, ...] = Field(min_length=1, max_length=1_000)
    project: dict[str, Any]
    execution: dict[str, Any]
    multimodal: MultimodalContext
    user: UserContext

    @model_validator(mode="after")
    def validate_window(self) -> FrozenRunContext:
        if self.window_started_at > self.window_ended_at:
            raise ValueError("run context debounce window is inverted")
        if any(
            event.timestamp < self.window_started_at or event.timestamp > self.window_ended_at
            for event in self.trigger_events
        ):
            raise ValueError("trigger event is outside the run window")
        return self
