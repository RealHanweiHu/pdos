from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest

from app.ai.executor import (
    INSTRUCTIONS,
    PROMPT_VERSIONS,
    SYSTEM_PROMPTS,
    AgentAssessment,
)
from app.ai.finding_writer import FindingPreflightError, preflight_assessment
from app.ai.phase_one_suite import load_phase_one_golden_suite
from app.ai.runtime_contract import (
    PHASE_ONE_AGENT_KEYS,
    AgentKey,
    EventReference,
    FrozenRunContext,
    empty_multimodal_context,
    user_context_for_agent,
)
from app.domain.findings import KnowledgeDraftPayload, RiskSuggestionPayload

SERVER_ROOT = Path(__file__).resolve().parents[1]


def run_context(*, agent_key: AgentKey, event_type: str) -> FrozenRunContext:
    now = datetime(2026, 8, 11, 20, tzinfo=UTC)
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
                entity="project",
                entity_id=uuid4(),
                timestamp=now,
            ),
        ),
        project={"id": str(uuid4()), "status": "active"},
        execution={},
        multimodal=empty_multimodal_context(),
        user=user_context_for_agent(agent_key),
    )


def risk_assessment(
    candidate_type: Literal["risk_suggestion", "blocker_alert", "gate_readiness_anomaly"],
) -> AgentAssessment:
    return AgentAssessment(
        disposition="human_review_candidate",
        candidate_type=candidate_type,
        summary="The current evidence needs human review.",
        proposed_payload=RiskSuggestionPayload(
            title="Review delivery exposure",
            description="The scoped evidence may affect delivery.",
            likelihood=3,
            impact=4,
        ),
        evidence_event_ids=(42,),
        confidence=0.82,
    )


def test_phase_one_prompts_are_separately_versioned_and_keep_dynamic_scope_out() -> None:
    assert {key: PROMPT_VERSIONS[key] for key in PHASE_ONE_AGENT_KEYS} == {
        AgentKey.PROJECT_INTELLIGENCE: "project-intelligence-v2",
        AgentKey.KNOWLEDGE_LITE: "knowledge-lite-v2",
    }
    assert SYSTEM_PROMPTS[AgentKey.PROJECT_INTELLIGENCE] != SYSTEM_PROMPTS[AgentKey.KNOWLEDGE_LITE]
    assert INSTRUCTIONS[AgentKey.PROJECT_INTELLIGENCE] != INSTRUCTIONS[AgentKey.KNOWLEDGE_LITE]
    dynamic_scope_marker = str(uuid4())
    for agent_key in PHASE_ONE_AGENT_KEYS:
        assert "FROZEN_READ_ONLY_TOOLS" in SYSTEM_PROMPTS[agent_key]
        assert dynamic_scope_marker not in SYSTEM_PROMPTS[agent_key]


@pytest.mark.parametrize(
    "candidate_type",
    ["risk_suggestion", "blocker_alert", "gate_readiness_anomaly"],
)
def test_project_intelligence_preflight_maps_all_three_candidate_types(
    candidate_type: Literal["risk_suggestion", "blocker_alert", "gate_readiness_anomaly"],
) -> None:
    context = run_context(
        agent_key=AgentKey.PROJECT_INTELLIGENCE,
        event_type="ISSUE_CREATED",
    )

    candidate = preflight_assessment(risk_assessment(candidate_type), context=context)

    assert candidate is not None
    assert candidate.finding_type == candidate_type
    assert isinstance(candidate.payload, RiskSuggestionPayload)
    assert candidate.origin_key == f"{candidate_type}:42"


def test_knowledge_lite_preflight_creates_only_an_unverified_knowledge_draft() -> None:
    context = run_context(
        agent_key=AgentKey.KNOWLEDGE_LITE,
        event_type="DOCUMENT_UPLOADED",
    )
    assessment = AgentAssessment(
        disposition="human_review_candidate",
        candidate_type="knowledge_draft",
        summary="The approved source may contain a reusable lesson.",
        proposed_payload=KnowledgeDraftPayload(
            title="Connector validation lesson",
            draft_text="Validate connector pin mapping before the DVT build.",
            applicability="Projects using the same connector family.",
        ),
        evidence_event_ids=(42,),
        confidence=0.76,
    )

    candidate = preflight_assessment(assessment, context=context)

    assert candidate is not None
    assert candidate.finding_type == "knowledge_draft"
    assert isinstance(candidate.payload, KnowledgeDraftPayload)
    assert "verified" not in candidate.payload.model_dump()


def test_agent_preflight_rejects_cross_agent_candidate_types() -> None:
    knowledge_context = run_context(
        agent_key=AgentKey.KNOWLEDGE_LITE,
        event_type="GATE_APPROVED",
    )
    project_context = run_context(
        agent_key=AgentKey.PROJECT_INTELLIGENCE,
        event_type="TEST_FAILED",
    )
    knowledge = AgentAssessment(
        disposition="human_review_candidate",
        candidate_type="knowledge_draft",
        summary="Draft a reusable test lesson.",
        proposed_payload=KnowledgeDraftPayload(
            title="Test lesson",
            draft_text="Retain the scoped failure mode for human verification.",
        ),
        evidence_event_ids=(42,),
        confidence=0.7,
    )

    with pytest.raises(FindingPreflightError):
        preflight_assessment(risk_assessment("risk_suggestion"), context=knowledge_context)
    with pytest.raises(FindingPreflightError):
        preflight_assessment(knowledge, context=project_context)


def test_agent_preflight_rejects_an_event_outside_its_static_subscription() -> None:
    wrong_route = run_context(
        agent_key=AgentKey.KNOWLEDGE_LITE,
        event_type="ISSUE_CREATED",
    )
    knowledge = AgentAssessment(
        disposition="human_review_candidate",
        candidate_type="knowledge_draft",
        summary="Draft a reusable issue lesson.",
        proposed_payload=KnowledgeDraftPayload(
            title="Issue lesson",
            draft_text="This event is outside the Knowledge Lite subscription.",
        ),
        evidence_event_ids=(42,),
        confidence=0.7,
    )

    with pytest.raises(FindingPreflightError):
        preflight_assessment(knowledge, context=wrong_route)


def test_no_action_has_no_candidate_payload() -> None:
    assessment = AgentAssessment(
        disposition="no_action",
        candidate_type=None,
        summary="No evidence-backed action is warranted.",
        proposed_payload=None,
        evidence_event_ids=(),
        confidence=0.95,
    )

    assert (
        preflight_assessment(
            assessment,
            context=run_context(
                agent_key=AgentKey.PROJECT_INTELLIGENCE,
                event_type="PROJECT_STAGE_CHANGED",
            ),
        )
        is None
    )


def test_checked_in_phase_one_golden_cases_match_frozen_prompts_and_preflight() -> None:
    suite = load_phase_one_golden_suite(SERVER_ROOT / "golden" / "phase-one-agents-v1.json")

    assert suite.prompt_versions == {key: PROMPT_VERSIONS[key] for key in PHASE_ONE_AGENT_KEYS}
    assert {case.event_type for case in suite.cases} == {
        "PROJECT_STAGE_CHANGED",
        "ISSUE_CREATED",
        "TEST_FAILED",
        "GATE_APPROVED",
        "DOCUMENT_UPLOADED",
    }
    for case in suite.cases:
        candidate = preflight_assessment(
            case.output,
            context=run_context(agent_key=case.agent_key, event_type=case.event_type),
        )
        assert (candidate.finding_type if candidate is not None else None) == (
            case.expected_finding_type
        )
