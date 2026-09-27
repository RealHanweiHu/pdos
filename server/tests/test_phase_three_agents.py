from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Literal
from uuid import uuid4

import pytest

from app.ai import capability_contract as registry
from app.ai.capability_contract import CapabilityRollout
from app.ai.executor import INSTRUCTIONS, PROMPT_VERSIONS, SYSTEM_PROMPTS, AgentAssessment
from app.ai.finding_writer import FindingPreflightError, preflight_assessment
from app.ai.phase_three_suite import load_phase_three_golden_suite
from app.ai.rollout_guard import CapabilityUnavailableError
from app.ai.runtime_contract import (
    PHASE_THREE_AGENT_KEYS,
    AgentKey,
    EventReference,
    FrozenRunContext,
    agents_for_event,
    empty_multimodal_context,
    user_context_for_agent,
)
from app.domain.findings import RiskSuggestionPayload

SERVER_ROOT = Path(__file__).resolve().parents[1]


def enable_offline_contract_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise archived golden contracts without promoting runtime capabilities."""
    entries = dict(registry.CAPABILITY_CONTRACTS)
    for key, contract in entries.items():
        if contract.agent_key in PHASE_THREE_AGENT_KEYS:
            entries[key] = contract.model_copy(update={"rollout": CapabilityRollout.LIVE})
    monkeypatch.setattr(registry, "CAPABILITY_CONTRACTS", MappingProxyType(entries))


def run_context(*, agent_key: AgentKey, event_type: str) -> FrozenRunContext:
    now = datetime(2026, 8, 13, 20, tzinfo=UTC)
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
        multimodal=empty_multimodal_context(),
        user=user_context_for_agent(agent_key),
    )


def assessment(
    candidate_type: Literal["supplier_delay_risk", "executive_portfolio_brief"],
) -> AgentAssessment:
    return AgentAssessment(
        disposition="human_review_candidate",
        candidate_type=candidate_type,
        summary="The frozen evidence warrants human review.",
        proposed_payload=RiskSuggestionPayload(
            title="Review the scoped portfolio risk",
            description="Only server-bound evidence was considered.",
            likelihood=3,
            impact=4,
        ),
        evidence_event_ids=(42,),
        confidence=0.8,
    )


def test_phase_three_prompts_are_versioned_and_routes_are_exact() -> None:
    assert {key: PROMPT_VERSIONS[key] for key in PHASE_THREE_AGENT_KEYS} == {
        AgentKey.SUPPLIER_INTELLIGENCE: "supplier-intelligence-v3",
        AgentKey.EXECUTIVE_INTELLIGENCE: "executive-intelligence-v3",
    }
    assert (
        SYSTEM_PROMPTS[AgentKey.SUPPLIER_INTELLIGENCE]
        != SYSTEM_PROMPTS[AgentKey.EXECUTIVE_INTELLIGENCE]
    )
    assert (
        INSTRUCTIONS[AgentKey.SUPPLIER_INTELLIGENCE]
        != INSTRUCTIONS[AgentKey.EXECUTIVE_INTELLIGENCE]
    )
    assert agents_for_event("SUPPLIER_DELAY_REPORTED") == (AgentKey.SUPPLIER_INTELLIGENCE,)
    assert agents_for_event("PROJECT_STAGE_CHANGED") == (
        AgentKey.PROJECT_INTELLIGENCE,
        AgentKey.EXECUTIVE_INTELLIGENCE,
    )
    assert agents_for_event("GATE_APPROVED") == (
        AgentKey.KNOWLEDGE_LITE,
        AgentKey.EXECUTIVE_INTELLIGENCE,
    )


@pytest.mark.parametrize(
    ("agent_key", "event_type", "candidate_type"),
    [
        (
            AgentKey.SUPPLIER_INTELLIGENCE,
            "SUPPLIER_DELAY_REPORTED",
            "supplier_delay_risk",
        ),
        (
            AgentKey.EXECUTIVE_INTELLIGENCE,
            "PROJECT_STAGE_CHANGED",
            "executive_portfolio_brief",
        ),
        (
            AgentKey.EXECUTIVE_INTELLIGENCE,
            "GATE_APPROVED",
            "executive_portfolio_brief",
        ),
    ],
)
def test_phase_three_preflight_accepts_only_agent_event_type_contract(
    monkeypatch: pytest.MonkeyPatch,
    agent_key: AgentKey,
    event_type: str,
    candidate_type: Literal["supplier_delay_risk", "executive_portfolio_brief"],
) -> None:
    with pytest.raises(CapabilityUnavailableError, match="CAPABILITY_SHADOW"):
        preflight_assessment(
            assessment(candidate_type),
            context=run_context(agent_key=agent_key, event_type=event_type),
        )
    enable_offline_contract_check(monkeypatch)
    candidate = preflight_assessment(
        assessment(candidate_type),
        context=run_context(agent_key=agent_key, event_type=event_type),
    )

    assert candidate is not None
    assert candidate.finding_type == candidate_type
    assert isinstance(candidate.payload, RiskSuggestionPayload)


def test_phase_three_preflight_rejects_cross_agent_and_cross_run_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_offline_contract_check(monkeypatch)
    executive_context = run_context(
        agent_key=AgentKey.EXECUTIVE_INTELLIGENCE,
        event_type="PROJECT_STAGE_CHANGED",
    )
    wrong_evidence = assessment("executive_portfolio_brief").model_copy(
        update={"evidence_event_ids": (999,)}
    )

    with pytest.raises(FindingPreflightError):
        preflight_assessment(
            assessment("supplier_delay_risk"),
            context=executive_context,
        )
    with pytest.raises(FindingPreflightError):
        preflight_assessment(wrong_evidence, context=executive_context)


def test_checked_in_phase_three_golden_cases_match_prompts_routes_and_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_offline_contract_check(monkeypatch)
    suite = load_phase_three_golden_suite(SERVER_ROOT / "golden" / "phase-three-agents-v1.json")

    assert suite.prompt_versions == {key: PROMPT_VERSIONS[key] for key in PHASE_THREE_AGENT_KEYS}
    assert {case.event_type for case in suite.cases} == {
        "SUPPLIER_DELAY_REPORTED",
        "PROJECT_STAGE_CHANGED",
        "GATE_APPROVED",
    }
    for case in suite.cases:
        candidate = preflight_assessment(
            case.output,
            context=run_context(agent_key=case.agent_key, event_type=case.event_type),
        )
        assert (candidate.finding_type if candidate is not None else None) == (
            case.expected_finding_type
        )
