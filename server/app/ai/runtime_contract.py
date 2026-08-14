"""Frozen Phase 1 Agent routing, run context, and lifecycle contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgentKey(StrEnum):
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

_RUN_EDGES: dict[AgentRunStatus, frozenset[AgentRunStatus]] = {
    AgentRunStatus.DEBOUNCING: frozenset({AgentRunStatus.QUEUED}),
    AgentRunStatus.QUEUED: frozenset({AgentRunStatus.RUNNING}),
    AgentRunStatus.RUNNING: frozenset(
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
