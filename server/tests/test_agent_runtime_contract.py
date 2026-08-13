from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ai.runtime_contract import (
    AgentKey,
    AgentRunStatus,
    EventReference,
    FrozenRunContext,
    InvalidRunTransitionError,
    agents_for_event,
    allowed_run_transition,
    empty_multimodal_context,
    user_context_for_agent,
)


def context() -> FrozenRunContext:
    tenant_id = uuid4()
    project_id = uuid4()
    return FrozenRunContext(
        tenant_id=tenant_id,
        project_id=project_id,
        run_id=uuid4(),
        agent_key=AgentKey.PROJECT_INTELLIGENCE,
        built_at=datetime(2026, 8, 11, 20, tzinfo=UTC),
        window_started_at=datetime(2026, 8, 11, 19, 45, tzinfo=UTC),
        window_ended_at=datetime(2026, 8, 11, 20, tzinfo=UTC),
        trigger_events=(
            EventReference(
                id=42,
                event_type="ISSUE_CREATED",
                entity="issue",
                entity_id=uuid4(),
                timestamp=datetime(2026, 8, 11, 19, 48, tzinfo=UTC),
            ),
        ),
        project={
            "id": project_id,
            "code": "PRJ-001",
            "name": "Drive Unit",
            "status": "active",
            "current_stage": {"code": "dvt", "name": "DVT", "sequence": 5},
        },
        execution={
            "open_issue_count": 3,
            "open_risk_count": 1,
            "overdue_task_count": 2,
            "stage_progress_percent": 71,
        },
        multimodal=empty_multimodal_context(),
        user=user_context_for_agent(AgentKey.PROJECT_INTELLIGENCE),
    )


def test_static_phase_one_event_routes_are_exact_and_unknown_events_are_ignored() -> None:
    assert agents_for_event("PROJECT_STAGE_CHANGED") == (AgentKey.PROJECT_INTELLIGENCE,)
    assert agents_for_event("ISSUE_CREATED") == (AgentKey.PROJECT_INTELLIGENCE,)
    assert agents_for_event("TEST_FAILED") == (
        AgentKey.PROJECT_INTELLIGENCE,
        AgentKey.QUALITY_INTELLIGENCE,
    )
    assert agents_for_event("GATE_APPROVED") == (AgentKey.KNOWLEDGE_LITE,)
    assert agents_for_event("DOCUMENT_UPLOADED") == (AgentKey.KNOWLEDGE_LITE,)
    assert agents_for_event("DEVELOPMENT_BOM_CREATED") == (AgentKey.ENGINEERING_INTELLIGENCE,)
    assert agents_for_event("DEVELOPMENT_BOM_ITEM_ADDED") == (AgentKey.ENGINEERING_INTELLIGENCE,)
    assert agents_for_event("CHANGE_RECORD_CHANGED") == (AgentKey.ENGINEERING_INTELLIGENCE,)
    assert agents_for_event("COMPLAINT_CREATED") == (AgentKey.QUALITY_INTELLIGENCE,)
    assert agents_for_event("PROJECT_CREATED") == ()
    assert agents_for_event("UNREGISTERED_INJECTION") == ()


def test_run_context_is_frozen_strict_and_carries_only_server_bound_scope() -> None:
    frozen = context()

    assert frozen.schema_version == 2
    assert frozen.trigger_events[0].id == 42
    with pytest.raises(ValidationError):
        FrozenRunContext.model_validate({**frozen.model_dump(), "model": "attacker-choice"})
    with pytest.raises(ValidationError):
        frozen.project_id = uuid4()


@pytest.mark.parametrize(
    ("current", "next_status"),
    [
        (AgentRunStatus.DEBOUNCING, AgentRunStatus.QUEUED),
        (AgentRunStatus.QUEUED, AgentRunStatus.RUNNING),
        (AgentRunStatus.RUNNING, AgentRunStatus.SUCCEEDED),
        (AgentRunStatus.RUNNING, AgentRunStatus.DEGRADED),
        (AgentRunStatus.RUNNING, AgentRunStatus.FAILED),
    ],
)
def test_run_state_machine_allows_only_the_frozen_forward_edges(
    current: AgentRunStatus,
    next_status: AgentRunStatus,
) -> None:
    assert allowed_run_transition(current, next_status) is next_status


@pytest.mark.parametrize(
    ("current", "next_status"),
    [
        (AgentRunStatus.DEBOUNCING, AgentRunStatus.RUNNING),
        (AgentRunStatus.QUEUED, AgentRunStatus.SUCCEEDED),
        (AgentRunStatus.FAILED, AgentRunStatus.QUEUED),
        (AgentRunStatus.SUCCEEDED, AgentRunStatus.RUNNING),
    ],
)
def test_run_state_machine_rejects_skips_retries_and_terminal_mutation(
    current: AgentRunStatus,
    next_status: AgentRunStatus,
) -> None:
    with pytest.raises(InvalidRunTransitionError):
        allowed_run_transition(current, next_status)
