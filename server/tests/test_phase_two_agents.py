from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest

from app.ai.executor import INSTRUCTIONS, PROMPT_VERSIONS, SYSTEM_PROMPTS, AgentAssessment
from app.ai.finding_writer import FindingPreflightError, preflight_assessment
from app.ai.phase_two_suite import load_phase_two_golden_suite
from app.ai.runtime_contract import (
    PHASE_TWO_AGENT_KEYS,
    AgentKey,
    EventReference,
    FrozenRunContext,
    agents_for_event,
)
from app.domain.findings import RiskSuggestionPayload

SERVER_ROOT = Path(__file__).resolve().parents[1]


def run_context(*, agent_key: AgentKey, event_type: str) -> FrozenRunContext:
    now = datetime(2026, 8, 12, 23, tzinfo=UTC)
    return FrozenRunContext(
        tenant_id=uuid4(),
        project_id=uuid4(),
        run_id=uuid4(),
        agent_key=agent_key,
        built_at=now,
        window_started_at=now,
        window_ended_at=now,
        trigger_events=(
            EventReference(
                id=42,
                event_type=event_type,
                entity="project_evidence",
                entity_id=uuid4(),
                timestamp=now,
            ),
        ),
        project={"id": str(uuid4()), "status": "active"},
        execution={},
    )


def assessment(
    candidate_type: Literal[
        "bom_impact_suggestion",
        "change_impact_suggestion",
        "quality_cluster_alert",
        "capa_suggestion",
    ],
) -> AgentAssessment:
    return AgentAssessment(
        disposition="human_review_candidate",
        candidate_type=candidate_type,
        summary="The scoped evidence warrants human review.",
        proposed_payload=RiskSuggestionPayload(
            title="Review scoped impact",
            description="Only the frozen evidence was considered.",
            likelihood=3,
            impact=4,
        ),
        evidence_event_ids=(42,),
        confidence=0.8,
    )


def test_phase_two_prompts_are_versioned_and_routes_are_exact() -> None:
    assert {key: PROMPT_VERSIONS[key] for key in PHASE_TWO_AGENT_KEYS} == {
        AgentKey.ENGINEERING_INTELLIGENCE: "engineering-intelligence-v1",
        AgentKey.QUALITY_INTELLIGENCE: "quality-intelligence-v1",
    }
    assert (
        SYSTEM_PROMPTS[AgentKey.ENGINEERING_INTELLIGENCE]
        != SYSTEM_PROMPTS[AgentKey.QUALITY_INTELLIGENCE]
    )
    assert (
        INSTRUCTIONS[AgentKey.ENGINEERING_INTELLIGENCE]
        != INSTRUCTIONS[AgentKey.QUALITY_INTELLIGENCE]
    )
    assert agents_for_event("DEVELOPMENT_BOM_CREATED") == (AgentKey.ENGINEERING_INTELLIGENCE,)
    assert agents_for_event("DEVELOPMENT_BOM_ITEM_ADDED") == (AgentKey.ENGINEERING_INTELLIGENCE,)
    assert agents_for_event("CHANGE_RECORD_CHANGED") == (AgentKey.ENGINEERING_INTELLIGENCE,)
    assert agents_for_event("COMPLAINT_CREATED") == (AgentKey.QUALITY_INTELLIGENCE,)
    assert agents_for_event("TEST_FAILED") == (
        AgentKey.PROJECT_INTELLIGENCE,
        AgentKey.QUALITY_INTELLIGENCE,
    )


@pytest.mark.parametrize(
    ("agent_key", "event_type", "candidate_type"),
    [
        (
            AgentKey.ENGINEERING_INTELLIGENCE,
            "DEVELOPMENT_BOM_ITEM_ADDED",
            "bom_impact_suggestion",
        ),
        (
            AgentKey.ENGINEERING_INTELLIGENCE,
            "CHANGE_RECORD_CHANGED",
            "change_impact_suggestion",
        ),
        (AgentKey.QUALITY_INTELLIGENCE, "TEST_FAILED", "quality_cluster_alert"),
        (AgentKey.QUALITY_INTELLIGENCE, "COMPLAINT_CREATED", "capa_suggestion"),
    ],
)
def test_phase_two_preflight_accepts_only_agent_event_type_contract(
    agent_key: AgentKey,
    event_type: str,
    candidate_type: Literal[
        "bom_impact_suggestion",
        "change_impact_suggestion",
        "quality_cluster_alert",
        "capa_suggestion",
    ],
) -> None:
    candidate = preflight_assessment(
        assessment(candidate_type),
        context=run_context(agent_key=agent_key, event_type=event_type),
    )

    assert candidate is not None
    assert candidate.finding_type == candidate_type
    assert isinstance(candidate.payload, RiskSuggestionPayload)


def test_phase_two_preflight_rejects_cross_agent_and_cross_run_evidence() -> None:
    quality_context = run_context(
        agent_key=AgentKey.QUALITY_INTELLIGENCE,
        event_type="COMPLAINT_CREATED",
    )
    wrong_evidence = assessment("capa_suggestion").model_copy(update={"evidence_event_ids": (999,)})

    with pytest.raises(FindingPreflightError):
        preflight_assessment(
            assessment("bom_impact_suggestion"),
            context=quality_context,
        )
    with pytest.raises(FindingPreflightError):
        preflight_assessment(wrong_evidence, context=quality_context)


def test_checked_in_phase_two_golden_cases_match_prompts_routes_and_preflight() -> None:
    suite = load_phase_two_golden_suite(SERVER_ROOT / "golden" / "phase-two-agents-v1.json")

    assert suite.prompt_versions == {key: PROMPT_VERSIONS[key] for key in PHASE_TWO_AGENT_KEYS}
    assert {case.event_type for case in suite.cases} == {
        "DEVELOPMENT_BOM_ITEM_ADDED",
        "CHANGE_RECORD_CHANGED",
        "TEST_FAILED",
        "COMPLAINT_CREATED",
    }
    for case in suite.cases:
        candidate = preflight_assessment(
            case.output,
            context=run_context(agent_key=case.agent_key, event_type=case.event_type),
        )
        assert (candidate.finding_type if candidate is not None else None) == (
            case.expected_finding_type
        )
