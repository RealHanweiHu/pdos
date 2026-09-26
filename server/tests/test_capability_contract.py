"""Capability-key runtime contract freeze tests (vNext V1-C2, D2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

import pytest

from app.ai.capability_contract import (
    CAPABILITY_CONTRACTS,
    CapabilityKey,
    CapabilityRollout,
    CapabilityZone,
    UnknownCapabilityError,
    capabilities_for_event,
    capability_for_finding,
    resolve_capability,
)
from app.ai.executor import PROMPT_VERSIONS, FindingType
from app.ai.runtime_contract import (
    _EVENT_AGENT_ROUTES,
    PHASE_THREE_AGENT_KEYS,
    AgentKey,
    agents_for_event,
)

PROMPT_DIRECTORY = Path(__file__).resolve().parents[1] / "app" / "ai" / "prompts"

FROZEN_CAPABILITY_KEYS = [
    "project_intelligence.risk_suggestion",
    "project_intelligence.blocker_alert",
    "project_intelligence.gate_readiness_anomaly",
    "project_intelligence.risk_suggestion_api",
    "knowledge_lite.knowledge_draft",
    "engineering_intelligence.bom_impact_suggestion",
    "engineering_intelligence.change_impact_suggestion",
    "quality_intelligence.quality_cluster_alert",
    "quality_intelligence.capa_suggestion",
    "quality_intelligence.test_plan_change",
    "quality_intelligence.test_report_import",
    "supplier_intelligence.supplier_delay_risk",
    "executive_intelligence.executive_portfolio_brief",
]


# Approved vNext extensions are explicit, isolated SHADOW capabilities; the
# legacy worker contract below still applies unchanged to the original keys.
ADDED_CAPABILITY_CONTRACTS: dict[str, tuple[CapabilityZone, tuple[str, ...]]] = {
    "product_management_intelligence.product_matrix": (CapabilityZone.FREE, ()),
    "executive_intelligence.portfolio_explanation": (CapabilityZone.FREE, ()),
    "executive_intelligence.executive_brief": (CapabilityZone.FREE, ()),
    "knowledge_lite.meeting_planning": (CapabilityZone.HARD_GATE, ("meeting_plan",)),
    "knowledge_lite.intake_organization": (CapabilityZone.CONFIRM, ("intake_organization",)),
    "knowledge_lite.process_template_configuration": (
        CapabilityZone.HARD_GATE,
        ("process_template_configuration",),
    ),
    "engineering_intelligence.discussion_followup": (CapabilityZone.HARD_GATE, ()),
    "engineering_intelligence.discussion_convene": (CapabilityZone.FREE, ()),
    "engineering_intelligence.discussion_research": (CapabilityZone.FREE, ()),
    "engineering_intelligence.change_discussion": (CapabilityZone.FREE, ()),
    "engineering_intelligence.discussion_initiation": (CapabilityZone.FREE, ()),
    "engineering_intelligence.notice_discussion": (CapabilityZone.HARD_GATE, ()),
    "engineering_intelligence.notice_work_package": (CapabilityZone.HARD_GATE, ()),
    "engineering_intelligence.change_work_package": (
        CapabilityZone.HARD_GATE,
        ("change_work_package",),
    ),
    "knowledge_lite.meeting_business": (
        CapabilityZone.HARD_GATE,
        ("meeting_issue", "meeting_risk", "meeting_change"),
    ),
    "knowledge_lite.meeting_decisions": (CapabilityZone.HARD_GATE, ("meeting_decision",)),
    "knowledge_lite.meeting_actions": (CapabilityZone.HARD_GATE, ("meeting_action",)),
    "knowledge_lite.meeting_minutes": (CapabilityZone.HARD_GATE, ("meeting_minutes",)),
    "knowledge_lite.meeting_reading": (CapabilityZone.FREE, ()),
    "engineering_intelligence.cost_discussion_followup": (CapabilityZone.HARD_GATE, ()),
    "engineering_intelligence.cost_reduction": (CapabilityZone.HARD_GATE, ("cost_reduction",)),
    "supplier_intelligence.supplier_recovery": (CapabilityZone.HARD_GATE, ("supplier_recovery",)),
    "quality_intelligence.capa_work_package": (CapabilityZone.HARD_GATE, ("capa_work_package",)),
}


def test_capability_keys_are_frozen_and_agent_prefixed() -> None:
    assert set(CapabilityKey) == set(FROZEN_CAPABILITY_KEYS) | set(ADDED_CAPABILITY_CONTRACTS)
    assert [key.value for key in CapabilityKey if key.value in FROZEN_CAPABILITY_KEYS] == (
        FROZEN_CAPABILITY_KEYS
    )
    for key, contract in CAPABILITY_CONTRACTS.items():
        prefix, _, suffix = key.value.partition(".")
        assert prefix == contract.agent_key.value
        assert suffix, f"capability {key} must carry a suffix after the agent prefix"
    assert set(CAPABILITY_CONTRACTS) == set(CapabilityKey), (
        "every capability key must have exactly one contract"
    )


def test_every_finding_type_belongs_to_exactly_one_capability() -> None:
    owners: dict[str, CapabilityKey] = {}
    for key, contract in CAPABILITY_CONTRACTS.items():
        for finding_type in contract.finding_types:
            assert finding_type not in owners, f"{finding_type} owned twice"
            owners[finding_type] = key
    assert set(owners) == set(get_args(FindingType)) | {
        finding_type
        for _, finding_types in ADDED_CAPABILITY_CONTRACTS.values()
        for finding_type in finding_types
    }


def test_route_matrix_resolves_events_to_agent_and_capability() -> None:
    for event_type, agent_keys in _EVENT_AGENT_ROUTES.items():
        capability_keys = capabilities_for_event(event_type)
        assert capability_keys, f"routed event {event_type} resolves to no capability"
        resolved_agents = {CAPABILITY_CONTRACTS[key].agent_key for key in capability_keys}
        assert resolved_agents == set(agent_keys)
        for key in capability_keys:
            assert CAPABILITY_CONTRACTS[key].zone is CapabilityZone.HARD_GATE
    assert capabilities_for_event("NOT_A_ROUTED_EVENT") == ()
    assert agents_for_event("NOT_A_ROUTED_EVENT") == ()


def test_unknown_capability_fails_closed() -> None:
    with pytest.raises(UnknownCapabilityError):
        resolve_capability("project_intelligence.unregistered")
    with pytest.raises(UnknownCapabilityError):
        resolve_capability("not-even-a-key")
    with pytest.raises(UnknownCapabilityError):
        capability_for_finding(AgentKey.KNOWLEDGE_LITE, "risk_suggestion")
    with pytest.raises(UnknownCapabilityError):
        capability_for_finding(AgentKey.PROJECT_INTELLIGENCE, "unknown_type")


def test_prompt_versions_stay_in_sync_with_prompt_files() -> None:
    file_versions = {
        payload["version"]
        for payload in (json.loads(path.read_text()) for path in PROMPT_DIRECTORY.glob("*.json"))
    }
    for contract in CAPABILITY_CONTRACTS.values():
        assert contract.prompt_version in file_versions, (
            f"{contract.key} pins prompt version {contract.prompt_version!r} "
            "that no prompt file provides"
        )
        if contract.finding_types and contract.event_driven:
            assert contract.prompt_version == PROMPT_VERSIONS[contract.agent_key]


def test_zone_and_rollout_invariants() -> None:
    for contract in CAPABILITY_CONTRACTS.values():
        if contract.key.value in ADDED_CAPABILITY_CONTRACTS:
            zone, finding_types = ADDED_CAPABILITY_CONTRACTS[contract.key.value]
            assert (contract.zone, contract.finding_types) == (zone, finding_types)
            assert contract.rollout is CapabilityRollout.SHADOW
            assert not contract.event_driven
            continue
        # Hard-gate output must flow through Finding review with per-capability
        # quality control; confirm-zone output is draft + human confirm.
        if contract.zone is CapabilityZone.HARD_GATE:
            assert contract.finding_types
            assert contract.tools or not contract.event_driven, "event workers must declare tools"
            assert contract.quality_control == "finding_quality_control"
        else:
            assert not contract.finding_types
            assert contract.zone is CapabilityZone.CONFIRM, (
                "no model capability may ship in the free zone (D32: free-zone "
                "writes are reserved for deterministic rule engines)"
            )
        # Phase-three agents stay shadow until their phase opens.
        expected_rollout = (
            CapabilityRollout.SHADOW
            if contract.agent_key in PHASE_THREE_AGENT_KEYS
            and contract.zone is CapabilityZone.HARD_GATE
            else CapabilityRollout.LIVE
        )
        assert contract.rollout is expected_rollout


def test_disabled_output_is_blocked_even_when_another_agent_capability_is_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import MappingProxyType
    from uuid import uuid4

    from app.ai import capability_contract as registry
    from app.ai.executor import AgentAssessment
    from app.ai.finding_writer import preflight_assessment
    from app.ai.rollout_guard import CapabilityUnavailableError, require_employee_agent
    from app.domain.findings import RiskSuggestionPayload
    from tests.test_agent_tools import frozen_context

    key = CapabilityKey.PROJECT_BLOCKER_ALERT
    entries = dict(registry.CAPABILITY_CONTRACTS)
    entries[key] = entries[key].model_copy(update={"rollout": CapabilityRollout.DISABLED})
    monkeypatch.setattr(registry, "CAPABILITY_CONTRACTS", MappingProxyType(entries))
    require_employee_agent(AgentKey.PROJECT_INTELLIGENCE)
    context = frozen_context(tenant_id=uuid4(), project_id=uuid4())
    assessment = AgentAssessment(
        disposition="human_review_candidate",
        candidate_type="blocker_alert",
        summary="Scoped evidence",
        proposed_payload=RiskSuggestionPayload(title="Blocked", likelihood=2, impact=2),
        evidence_event_ids=(1,),
        confidence=0.8,
    )
    with pytest.raises(CapabilityUnavailableError, match="CAPABILITY_DISABLED"):
        preflight_assessment(assessment, context=context)


def test_missing_registered_key_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import MappingProxyType

    from app.ai import capability_contract as registry

    entries = dict(registry.CAPABILITY_CONTRACTS)
    del entries[CapabilityKey.PROJECT_BLOCKER_ALERT]
    monkeypatch.setattr(registry, "CAPABILITY_CONTRACTS", MappingProxyType(entries))
    with pytest.raises(UnknownCapabilityError):
        resolve_capability(CapabilityKey.PROJECT_BLOCKER_ALERT)
    with pytest.raises(UnknownCapabilityError):
        capability_for_finding(AgentKey.PROJECT_INTELLIGENCE, "blocker_alert")
