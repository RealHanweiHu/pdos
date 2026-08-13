"""Frozen Phase 1 Agent routing, run context, and lifecycle contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgentKey(StrEnum):
    PROJECT_INTELLIGENCE = "project_intelligence"
    KNOWLEDGE_LITE = "knowledge_lite"
    ENGINEERING_INTELLIGENCE = "engineering_intelligence"
    QUALITY_INTELLIGENCE = "quality_intelligence"


PHASE_ONE_AGENT_KEYS = frozenset({AgentKey.PROJECT_INTELLIGENCE, AgentKey.KNOWLEDGE_LITE})
PHASE_TWO_AGENT_KEYS = frozenset({AgentKey.ENGINEERING_INTELLIGENCE, AgentKey.QUALITY_INTELLIGENCE})


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
    "PROJECT_STAGE_CHANGED": (AgentKey.PROJECT_INTELLIGENCE,),
    "ISSUE_CREATED": (AgentKey.PROJECT_INTELLIGENCE,),
    "TEST_FAILED": (
        AgentKey.PROJECT_INTELLIGENCE,
        AgentKey.QUALITY_INTELLIGENCE,
    ),
    "GATE_APPROVED": (AgentKey.KNOWLEDGE_LITE,),
    "DOCUMENT_UPLOADED": (AgentKey.KNOWLEDGE_LITE,),
    "DEVELOPMENT_BOM_CREATED": (AgentKey.ENGINEERING_INTELLIGENCE,),
    "DEVELOPMENT_BOM_ITEM_ADDED": (AgentKey.ENGINEERING_INTELLIGENCE,),
    "CHANGE_RECORD_CHANGED": (AgentKey.ENGINEERING_INTELLIGENCE,),
    "COMPLAINT_CREATED": (AgentKey.QUALITY_INTELLIGENCE,),
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


class FrozenRunContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1, le=1)
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
