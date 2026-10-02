"""Capability declarations and DC-11 operation-specific write classifications.

FREE/CONFIRM/HARD_GATE mean T0/T1/T2 for explicitly registered write operations.
Read-only capabilities confer no mutation permission. Runtime rollout, tenant
policy, qualification and independent AI scope remain separate execution gates.
Unmigrated operations retain their existing Finding review/apply boundary.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field

from app.ai.runtime_contract import (
    PHASE_THREE_AGENT_KEYS,
    AgentKey,
    agents_for_event,
)
from app.ai.tools import tool_definitions_for_agent
from app.ai.write_policy import WRITE_OPERATIONS, WriteTier, operation_keys_for_capability


class UnknownCapabilityError(LookupError):
    """Raised when runtime code references a capability outside the registry."""


class CapabilityZone(StrEnum):
    FREE = "free"
    CONFIRM = "confirm"
    HARD_GATE = "hard_gate"


class CapabilityRollout(StrEnum):
    LIVE = "live"
    SHADOW = "shadow"
    DISABLED = "disabled"


class CapabilityKey(StrEnum):
    QUALITY_EVENT_ISSUE = "quality_intelligence.event_issue"
    PRODUCT_RFQ_REQUIREMENTS = "product_management_intelligence.rfq_requirements"
    PRODUCT_MATRIX = "product_management_intelligence.product_matrix"
    PRODUCT_RESEARCH_PLANNING = "product_management_intelligence.research_planning"
    PRODUCT_COMPETITOR_ANALYSIS = "product_management_intelligence.competitor_analysis"
    PRODUCT_MARKET_ANALYSIS = "product_management_intelligence.market_analysis"
    PRODUCT_OPPORTUNITY_MAPPING = "product_management_intelligence.opportunity_mapping"
    PRODUCT_EXPERIMENT_DESIGN = "product_management_intelligence.experiment_design"
    PRODUCT_STRATEGY = "product_management_intelligence.product_strategy"
    PRODUCT_DEFINITION = "product_management_intelligence.product_definition"
    EXECUTIVE_PORTFOLIO_EXPLANATION = "executive_intelligence.portfolio_explanation"
    EXECUTIVE_BRIEF = "executive_intelligence.executive_brief"
    KNOWLEDGE_MEETING_PLANNING = "knowledge_lite.meeting_planning"
    KNOWLEDGE_INTAKE_ORGANIZATION = "knowledge_lite.intake_organization"
    KNOWLEDGE_PROCESS_TEMPLATE = "knowledge_lite.process_template_configuration"
    ENGINEERING_DISCUSSION_FOLLOWUP = "engineering_intelligence.discussion_followup"
    ENGINEERING_DISCUSSION_CONVENE = "engineering_intelligence.discussion_convene"
    ENGINEERING_DISCUSSION_RESEARCH = "engineering_intelligence.discussion_research"
    ENGINEERING_CHANGE_DISCUSSION = "engineering_intelligence.change_discussion"
    ENGINEERING_DISCUSSION_INITIATION = "engineering_intelligence.discussion_initiation"
    ENGINEERING_NOTICE_DISCUSSION = "engineering_intelligence.notice_discussion"
    ENGINEERING_NOTICE_WORK_PACKAGE = "engineering_intelligence.notice_work_package"
    ENGINEERING_CHANGE_WORK_PACKAGE = "engineering_intelligence.change_work_package"
    KNOWLEDGE_MEETING_BUSINESS = "knowledge_lite.meeting_business"
    KNOWLEDGE_MEETING_DECISIONS = "knowledge_lite.meeting_decisions"
    KNOWLEDGE_MEETING_ACTIONS = "knowledge_lite.meeting_actions"
    KNOWLEDGE_MEETING_MINUTES = "knowledge_lite.meeting_minutes"
    KNOWLEDGE_MEETING_READING = "knowledge_lite.meeting_reading"
    PROJECT_RISK_SUGGESTION = "project_intelligence.risk_suggestion"
    PROJECT_BLOCKER_ALERT = "project_intelligence.blocker_alert"
    PROJECT_GATE_READINESS_ANOMALY = "project_intelligence.gate_readiness_anomaly"
    PROJECT_RISK_SUGGESTION_API = "project_intelligence.risk_suggestion_api"
    KNOWLEDGE_DRAFT = "knowledge_lite.knowledge_draft"
    ENGINEERING_BOM_IMPACT = "engineering_intelligence.bom_impact_suggestion"
    ENGINEERING_CHANGE_IMPACT = "engineering_intelligence.change_impact_suggestion"
    QUALITY_CLUSTER_ALERT = "quality_intelligence.quality_cluster_alert"
    QUALITY_CAPA_WORK_PACKAGE = "quality_intelligence.capa_work_package"
    QUALITY_CAPA_SUGGESTION = "quality_intelligence.capa_suggestion"
    QUALITY_TEST_PLAN_CHANGE = "quality_intelligence.test_plan_change"
    QUALITY_TEST_REPORT_IMPORT = "quality_intelligence.test_report_import"
    ENGINEERING_COST_DISCUSSION_FOLLOWUP = "engineering_intelligence.cost_discussion_followup"
    ENGINEERING_COST_REDUCTION = "engineering_intelligence.cost_reduction"
    SUPPLIER_RECOVERY = "supplier_intelligence.supplier_recovery"
    SUPPLIER_DELAY_RISK = "supplier_intelligence.supplier_delay_risk"
    EXECUTIVE_PORTFOLIO_BRIEF = "executive_intelligence.executive_portfolio_brief"


class CapabilityContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: CapabilityKey
    agent_key: AgentKey
    zone: CapabilityZone
    rollout: CapabilityRollout
    prompt_version: str = Field(min_length=1, max_length=128)
    finding_types: tuple[str, ...] = ()
    projections: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    event_driven: bool = True
    quality_control: str = Field(min_length=1, max_length=64)

    @property
    def write_operations(self) -> tuple[str, ...]:
        return operation_keys_for_capability(self.key.value)

    @property
    def write_tier(self) -> WriteTier | None:
        tiers = {WRITE_OPERATIONS[key].write_tier for key in self.write_operations}
        return next(iter(tiers)) if len(tiers) == 1 else None


_EVENT_AGENT_PROJECTIONS: tuple[str, ...] = (
    "project_context",
    "recent_events",
    "memory",
    "domain_evidence",
)


def _finding_capability(
    key: CapabilityKey,
    agent_key: AgentKey,
    finding_type: str,
    *,
    prompt_version: str,
) -> CapabilityContract:
    return CapabilityContract(
        key=key,
        agent_key=agent_key,
        zone=CapabilityZone.HARD_GATE,
        rollout=(
            CapabilityRollout.SHADOW
            if agent_key in PHASE_THREE_AGENT_KEYS
            else CapabilityRollout.LIVE
        ),
        prompt_version=prompt_version,
        finding_types=(finding_type,),
        projections=_EVENT_AGENT_PROJECTIONS,
        tools=tuple(definition.name for definition in tool_definitions_for_agent(agent_key)),
        quality_control="finding_quality_control",
    )


CAPABILITY_CONTRACTS: MappingProxyType[CapabilityKey, CapabilityContract] = MappingProxyType(
    {
        CapabilityKey.QUALITY_EVENT_ISSUE: CapabilityContract(
            key=CapabilityKey.QUALITY_EVENT_ISSUE,
            agent_key=AgentKey.QUALITY_INTELLIGENCE,
            zone=CapabilityZone.FREE,
            rollout=CapabilityRollout.SHADOW,
            prompt_version="issue-event-v1",
            projections=("event_issue_source", "references", "question"),
            tools=(),
            event_driven=False,
            quality_control="event_issue_source_citation_control",
        ),
        **{
            capability: CapabilityContract(
                key=capability,
                agent_key=AgentKey.PRODUCT_MANAGEMENT_INTELLIGENCE,
                zone=CapabilityZone.HARD_GATE
                if capability
                in (
                    CapabilityKey.PRODUCT_RESEARCH_PLANNING,
                    CapabilityKey.PRODUCT_STRATEGY,
                    CapabilityKey.PRODUCT_DEFINITION,
                    CapabilityKey.PRODUCT_OPPORTUNITY_MAPPING,
                    CapabilityKey.PRODUCT_EXPERIMENT_DESIGN,
                    CapabilityKey.PRODUCT_COMPETITOR_ANALYSIS,
                    CapabilityKey.PRODUCT_MARKET_ANALYSIS,
                )
                else CapabilityZone.FREE,
                rollout=CapabilityRollout.SHADOW,
                prompt_version="product-research-v2"
                if capability is CapabilityKey.PRODUCT_RESEARCH_PLANNING
                else "product-evidence-v3"
                if capability
                in (
                    CapabilityKey.PRODUCT_COMPETITOR_ANALYSIS,
                    CapabilityKey.PRODUCT_MARKET_ANALYSIS,
                )
                else "product-discovery-v4"
                if capability
                in (
                    CapabilityKey.PRODUCT_OPPORTUNITY_MAPPING,
                    CapabilityKey.PRODUCT_EXPERIMENT_DESIGN,
                )
                else "product-planning-v6",
                finding_types=("product_research_plan",)
                if capability is CapabilityKey.PRODUCT_RESEARCH_PLANNING
                else ("product_competitor_observations",)
                if capability is CapabilityKey.PRODUCT_COMPETITOR_ANALYSIS
                else ("product_market_segments",)
                if capability is CapabilityKey.PRODUCT_MARKET_ANALYSIS
                else ("product_opportunities",)
                if capability is CapabilityKey.PRODUCT_OPPORTUNITY_MAPPING
                else ("product_experiments",)
                if capability is CapabilityKey.PRODUCT_EXPERIMENT_DESIGN
                else ("product_strategy_drafts",)
                if capability is CapabilityKey.PRODUCT_STRATEGY
                else ("product_definition_drafts",),
                projections=("product_work_source", "references", "question"),
                tools=(),
                event_driven=False,
                quality_control="finding_quality_control"
                if capability
                in (
                    CapabilityKey.PRODUCT_RESEARCH_PLANNING,
                    CapabilityKey.PRODUCT_STRATEGY,
                    CapabilityKey.PRODUCT_DEFINITION,
                    CapabilityKey.PRODUCT_OPPORTUNITY_MAPPING,
                    CapabilityKey.PRODUCT_EXPERIMENT_DESIGN,
                    CapabilityKey.PRODUCT_COMPETITOR_ANALYSIS,
                    CapabilityKey.PRODUCT_MARKET_ANALYSIS,
                )
                else "product_work_citation_control",
            )
            for capability in (
                CapabilityKey.PRODUCT_RESEARCH_PLANNING,
                CapabilityKey.PRODUCT_COMPETITOR_ANALYSIS,
                CapabilityKey.PRODUCT_MARKET_ANALYSIS,
                CapabilityKey.PRODUCT_OPPORTUNITY_MAPPING,
                CapabilityKey.PRODUCT_EXPERIMENT_DESIGN,
                CapabilityKey.PRODUCT_STRATEGY,
                CapabilityKey.PRODUCT_DEFINITION,
            )
        },
        CapabilityKey.PRODUCT_RFQ_REQUIREMENTS: CapabilityContract(
            key=CapabilityKey.PRODUCT_RFQ_REQUIREMENTS,
            agent_key=AgentKey.PRODUCT_MANAGEMENT_INTELLIGENCE,
            zone=CapabilityZone.CONFIRM,
            rollout=CapabilityRollout.SHADOW,
            prompt_version="product-rfq-v6",
            finding_types=("product_rfq_requirements",),
            projections=("product_work_source", "references", "question"),
            tools=(),
            event_driven=False,
            quality_control="finding_quality_control",
        ),
        CapabilityKey.PRODUCT_MATRIX: CapabilityContract(
            key=CapabilityKey.PRODUCT_MATRIX,
            agent_key=AgentKey.PRODUCT_MANAGEMENT_INTELLIGENCE,
            zone=CapabilityZone.FREE,
            rollout=CapabilityRollout.SHADOW,
            prompt_version="product-matrix-v1",
            projections=("market_matrix", "references", "question"),
            tools=(),
            event_driven=False,
            quality_control="product_matrix_citation_control",
        ),
        CapabilityKey.KNOWLEDGE_MEETING_PLANNING: CapabilityContract(
            key=CapabilityKey.KNOWLEDGE_MEETING_PLANNING,
            agent_key=AgentKey.KNOWLEDGE_LITE,
            zone=CapabilityZone.HARD_GATE,
            rollout=CapabilityRollout.SHADOW,
            prompt_version="meeting-planning-v1",
            finding_types=("meeting_plan",),
            projections=("meeting_planning_brief",),
            event_driven=False,
            quality_control="finding_quality_control",
        ),
        CapabilityKey.KNOWLEDGE_INTAKE_ORGANIZATION: CapabilityContract(
            key=CapabilityKey.KNOWLEDGE_INTAKE_ORGANIZATION,
            agent_key=AgentKey.KNOWLEDGE_LITE,
            zone=CapabilityZone.CONFIRM,
            rollout=CapabilityRollout.SHADOW,
            prompt_version="intake-organization-v1",
            finding_types=("intake_organization",),
            projections=("intake_ai_brief",),
            event_driven=False,
            quality_control="finding_quality_control",
        ),
        CapabilityKey.KNOWLEDGE_PROCESS_TEMPLATE: CapabilityContract(
            key=CapabilityKey.KNOWLEDGE_PROCESS_TEMPLATE,
            agent_key=AgentKey.KNOWLEDGE_LITE,
            zone=CapabilityZone.HARD_GATE,
            rollout=CapabilityRollout.SHADOW,
            prompt_version="process-template-configuration-v9",
            finding_types=("process_template_configuration",),
            projections=("process_template_brief",),
            event_driven=False,
            quality_control="finding_quality_control",
        ),
        CapabilityKey.ENGINEERING_DISCUSSION_FOLLOWUP: CapabilityContract(
            key=CapabilityKey.ENGINEERING_DISCUSSION_FOLLOWUP,
            agent_key=AgentKey.ENGINEERING_INTELLIGENCE,
            zone=CapabilityZone.HARD_GATE,
            rollout=CapabilityRollout.SHADOW,
            prompt_version="change-work-package-v4",
            projections=("change_impact_sources", "completed_discussion_brief"),
            tools=("engineering.trace_impact", "change.prepare_work_package"),
            event_driven=False,
            quality_control="finding_quality_control",
        ),
        CapabilityKey.ENGINEERING_DISCUSSION_CONVENE: CapabilityContract(
            key=CapabilityKey.ENGINEERING_DISCUSSION_CONVENE,
            agent_key=AgentKey.ENGINEERING_INTELLIGENCE,
            zone=CapabilityZone.FREE,
            rollout=CapabilityRollout.SHADOW,
            prompt_version="discussion-convene-v1",
            projections=("change_professional_projections",),
            tools=("discussion.convene",),
            event_driven=False,
            quality_control="discussion_origin_control",
        ),
        CapabilityKey.ENGINEERING_DISCUSSION_RESEARCH: CapabilityContract(
            key=CapabilityKey.ENGINEERING_DISCUSSION_RESEARCH,
            agent_key=AgentKey.ENGINEERING_INTELLIGENCE,
            zone=CapabilityZone.FREE,
            rollout=CapabilityRollout.SHADOW,
            prompt_version="discussion-research-v1",
            projections=("change_professional_projections",),
            tools=("research.search_public", "research.capture_snapshot"),
            event_driven=False,
            quality_control="discussion_research_observation_control",
        ),
        CapabilityKey.ENGINEERING_DISCUSSION_INITIATION: CapabilityContract(
            key=CapabilityKey.ENGINEERING_DISCUSSION_INITIATION,
            agent_key=AgentKey.ENGINEERING_INTELLIGENCE,
            zone=CapabilityZone.FREE,
            rollout=CapabilityRollout.SHADOW,
            prompt_version="discussion-initiation-v1",
            projections=("change_professional_projections",),
            event_driven=False,
            quality_control="discussion_initiation_receipt_control",
        ),
        CapabilityKey.ENGINEERING_CHANGE_DISCUSSION: CapabilityContract(
            key=CapabilityKey.ENGINEERING_CHANGE_DISCUSSION,
            agent_key=AgentKey.ENGINEERING_INTELLIGENCE,
            zone=CapabilityZone.FREE,
            rollout=CapabilityRollout.SHADOW,
            prompt_version="change-discussion-v1",
            projections=("change_professional_projections",),
            event_driven=False,
            quality_control="discussion_source_control",
        ),
        CapabilityKey.ENGINEERING_NOTICE_DISCUSSION: CapabilityContract(
            key=CapabilityKey.ENGINEERING_NOTICE_DISCUSSION,
            agent_key=AgentKey.ENGINEERING_INTELLIGENCE,
            zone=CapabilityZone.HARD_GATE,
            rollout=CapabilityRollout.SHADOW,
            prompt_version="change-work-package-v6",
            projections=("change_notice_sources", "change_professional_projections"),
            event_driven=False,
            quality_control="discussion_source_control",
        ),
        CapabilityKey.ENGINEERING_NOTICE_WORK_PACKAGE: CapabilityContract(
            key=CapabilityKey.ENGINEERING_NOTICE_WORK_PACKAGE,
            agent_key=AgentKey.ENGINEERING_INTELLIGENCE,
            zone=CapabilityZone.HARD_GATE,
            rollout=CapabilityRollout.SHADOW,
            prompt_version="change-work-package-v5",
            projections=("change_notice_sources",),
            tools=("engineering.trace_impact", "change.prepare_work_package"),
            event_driven=False,
            quality_control="finding_quality_control",
        ),
        CapabilityKey.ENGINEERING_CHANGE_WORK_PACKAGE: CapabilityContract(
            key=CapabilityKey.ENGINEERING_CHANGE_WORK_PACKAGE,
            agent_key=AgentKey.ENGINEERING_INTELLIGENCE,
            zone=CapabilityZone.HARD_GATE,
            rollout=CapabilityRollout.SHADOW,
            prompt_version="change-work-package-v3",
            finding_types=("change_work_package",),
            projections=("change_impact_sources",),
            tools=("engineering.trace_impact", "change.prepare_work_package"),
            event_driven=False,
            quality_control="finding_quality_control",
        ),
        CapabilityKey.KNOWLEDGE_MEETING_BUSINESS: CapabilityContract(
            key=CapabilityKey.KNOWLEDGE_MEETING_BUSINESS,
            agent_key=AgentKey.KNOWLEDGE_LITE,
            zone=CapabilityZone.HARD_GATE,
            rollout=CapabilityRollout.SHADOW,
            prompt_version="meeting-business-v1",
            finding_types=("meeting_issue", "meeting_risk", "meeting_change"),
            projections=("transcript_segments",),
            event_driven=False,
            quality_control="finding_quality_control",
        ),
        CapabilityKey.KNOWLEDGE_MEETING_DECISIONS: CapabilityContract(
            key=CapabilityKey.KNOWLEDGE_MEETING_DECISIONS,
            agent_key=AgentKey.KNOWLEDGE_LITE,
            zone=CapabilityZone.FREE,
            rollout=CapabilityRollout.SHADOW,
            prompt_version="meeting-decisions-v1",
            finding_types=("meeting_decision",),
            projections=("transcript_segments",),
            event_driven=False,
            quality_control="finding_quality_control",
        ),
        CapabilityKey.KNOWLEDGE_MEETING_ACTIONS: CapabilityContract(
            key=CapabilityKey.KNOWLEDGE_MEETING_ACTIONS,
            agent_key=AgentKey.KNOWLEDGE_LITE,
            zone=CapabilityZone.FREE,
            rollout=CapabilityRollout.SHADOW,
            prompt_version="meeting-actions-v1",
            finding_types=("meeting_action",),
            projections=("transcript_segments", "meeting_agenda"),
            event_driven=False,
            quality_control="finding_quality_control",
        ),
        CapabilityKey.KNOWLEDGE_MEETING_MINUTES: CapabilityContract(
            key=CapabilityKey.KNOWLEDGE_MEETING_MINUTES,
            agent_key=AgentKey.KNOWLEDGE_LITE,
            zone=CapabilityZone.FREE,
            rollout=CapabilityRollout.SHADOW,
            prompt_version="meeting-reading-v1",
            finding_types=("meeting_minutes",),
            projections=("transcript_segments", "minutes_base"),
            event_driven=False,
            quality_control="finding_quality_control",
        ),
        CapabilityKey.KNOWLEDGE_MEETING_READING: CapabilityContract(
            key=CapabilityKey.KNOWLEDGE_MEETING_READING,
            agent_key=AgentKey.KNOWLEDGE_LITE,
            zone=CapabilityZone.FREE,
            rollout=CapabilityRollout.SHADOW,
            prompt_version="meeting-reading-v1",
            projections=("transcript_segments",),
            event_driven=False,
            quality_control="meeting_citation_evaluation",
        ),
        CapabilityKey.PROJECT_RISK_SUGGESTION: _finding_capability(
            CapabilityKey.PROJECT_RISK_SUGGESTION,
            AgentKey.PROJECT_INTELLIGENCE,
            "risk_suggestion",
            prompt_version="project-intelligence-v3",
        ),
        CapabilityKey.PROJECT_BLOCKER_ALERT: _finding_capability(
            CapabilityKey.PROJECT_BLOCKER_ALERT,
            AgentKey.PROJECT_INTELLIGENCE,
            "blocker_alert",
            prompt_version="project-intelligence-v3",
        ),
        CapabilityKey.PROJECT_GATE_READINESS_ANOMALY: _finding_capability(
            CapabilityKey.PROJECT_GATE_READINESS_ANOMALY,
            AgentKey.PROJECT_INTELLIGENCE,
            "gate_readiness_anomaly",
            prompt_version="project-intelligence-v3",
        ),
        CapabilityKey.PROJECT_RISK_SUGGESTION_API: CapabilityContract(
            key=CapabilityKey.PROJECT_RISK_SUGGESTION_API,
            agent_key=AgentKey.PROJECT_INTELLIGENCE,
            zone=CapabilityZone.CONFIRM,
            rollout=CapabilityRollout.LIVE,
            prompt_version="risk-suggestion-api-v1",
            projections=("project_context",),
            quality_control="human_accept_per_call",
        ),
        CapabilityKey.KNOWLEDGE_DRAFT: _finding_capability(
            CapabilityKey.KNOWLEDGE_DRAFT,
            AgentKey.KNOWLEDGE_LITE,
            "knowledge_draft",
            prompt_version="knowledge-lite-v3",
        ),
        CapabilityKey.ENGINEERING_BOM_IMPACT: _finding_capability(
            CapabilityKey.ENGINEERING_BOM_IMPACT,
            AgentKey.ENGINEERING_INTELLIGENCE,
            "bom_impact_suggestion",
            prompt_version="engineering-intelligence-v3",
        ),
        CapabilityKey.ENGINEERING_CHANGE_IMPACT: _finding_capability(
            CapabilityKey.ENGINEERING_CHANGE_IMPACT,
            AgentKey.ENGINEERING_INTELLIGENCE,
            "change_impact_suggestion",
            prompt_version="engineering-intelligence-v3",
        ),
        CapabilityKey.QUALITY_CLUSTER_ALERT: _finding_capability(
            CapabilityKey.QUALITY_CLUSTER_ALERT,
            AgentKey.QUALITY_INTELLIGENCE,
            "quality_cluster_alert",
            prompt_version="quality-intelligence-v3",
        ),
        CapabilityKey.ENGINEERING_COST_DISCUSSION_FOLLOWUP: CapabilityContract(
            key=CapabilityKey.ENGINEERING_COST_DISCUSSION_FOLLOWUP,
            agent_key=AgentKey.ENGINEERING_INTELLIGENCE,
            zone=CapabilityZone.HARD_GATE,
            rollout=CapabilityRollout.SHADOW,
            prompt_version="cost-reduction-v2",
            projections=("cost_reduction_sources", "completed_discussion_brief"),
            tools=(),
            event_driven=False,
            quality_control="finding_quality_control",
        ),
        CapabilityKey.EXECUTIVE_BRIEF: CapabilityContract(
            key=CapabilityKey.EXECUTIVE_BRIEF,
            agent_key=AgentKey.EXECUTIVE_INTELLIGENCE,
            zone=CapabilityZone.FREE,
            rollout=CapabilityRollout.SHADOW,
            prompt_version="executive-control-tower-v1",
            projections=("executive_control_tower", "references", "question"),
            tools=(),
            event_driven=False,
            quality_control="executive_brief_citation_control",
        ),
        CapabilityKey.EXECUTIVE_PORTFOLIO_EXPLANATION: CapabilityContract(
            key=CapabilityKey.EXECUTIVE_PORTFOLIO_EXPLANATION,
            agent_key=AgentKey.EXECUTIVE_INTELLIGENCE,
            zone=CapabilityZone.FREE,
            rollout=CapabilityRollout.SHADOW,
            prompt_version="portfolio-explanation-v1",
            projections=("portfolio_comparison", "references", "question"),
            tools=(),
            event_driven=False,
            quality_control="portfolio_explanation_citation_control",
        ),
        CapabilityKey.ENGINEERING_COST_REDUCTION: CapabilityContract(
            key=CapabilityKey.ENGINEERING_COST_REDUCTION,
            agent_key=AgentKey.ENGINEERING_INTELLIGENCE,
            zone=CapabilityZone.HARD_GATE,
            rollout=CapabilityRollout.SHADOW,
            prompt_version="cost-reduction-v1",
            finding_types=("cost_reduction",),
            projections=("cost_reduction_sources", "references", "question"),
            tools=(),
            event_driven=False,
            quality_control="finding_quality_control",
        ),
        CapabilityKey.SUPPLIER_RECOVERY: CapabilityContract(
            key=CapabilityKey.SUPPLIER_RECOVERY,
            agent_key=AgentKey.SUPPLIER_INTELLIGENCE,
            zone=CapabilityZone.HARD_GATE,
            rollout=CapabilityRollout.SHADOW,
            prompt_version="supplier-recovery-v1",
            finding_types=("supplier_recovery",),
            projections=("supplier_recovery_sources", "references", "question"),
            tools=(),
            event_driven=False,
            quality_control="finding_quality_control",
        ),
        CapabilityKey.QUALITY_CAPA_WORK_PACKAGE: CapabilityContract(
            key=CapabilityKey.QUALITY_CAPA_WORK_PACKAGE,
            agent_key=AgentKey.QUALITY_INTELLIGENCE,
            zone=CapabilityZone.HARD_GATE,
            rollout=CapabilityRollout.SHADOW,
            prompt_version="quality-work-package-v1",
            finding_types=("capa_work_package",),
            projections=("quality_sources", "references", "question"),
            tools=("quality.prepare_capa",),
            event_driven=False,
            quality_control="finding_quality_control",
        ),
        CapabilityKey.QUALITY_CAPA_SUGGESTION: _finding_capability(
            CapabilityKey.QUALITY_CAPA_SUGGESTION,
            AgentKey.QUALITY_INTELLIGENCE,
            "capa_suggestion",
            prompt_version="quality-intelligence-v3",
        ),
        CapabilityKey.QUALITY_TEST_PLAN_CHANGE: CapabilityContract(
            key=CapabilityKey.QUALITY_TEST_PLAN_CHANGE,
            agent_key=AgentKey.QUALITY_INTELLIGENCE,
            zone=CapabilityZone.HARD_GATE,
            rollout=CapabilityRollout.LIVE,
            prompt_version="test-plan-change-v5",
            finding_types=("test_plan_change",),
            projections=("test_plan", "references", "question"),
            tools=(),
            event_driven=False,
            quality_control="finding_quality_control",
        ),
        CapabilityKey.QUALITY_TEST_REPORT_IMPORT: CapabilityContract(
            key=CapabilityKey.QUALITY_TEST_REPORT_IMPORT,
            agent_key=AgentKey.QUALITY_INTELLIGENCE,
            zone=CapabilityZone.CONFIRM,
            rollout=CapabilityRollout.LIVE,
            prompt_version="test-report-import-v1",
            projections=(),
            quality_control="import_batch_confirm",
        ),
        CapabilityKey.SUPPLIER_DELAY_RISK: _finding_capability(
            CapabilityKey.SUPPLIER_DELAY_RISK,
            AgentKey.SUPPLIER_INTELLIGENCE,
            "supplier_delay_risk",
            prompt_version="supplier-intelligence-v3",
        ),
        CapabilityKey.EXECUTIVE_PORTFOLIO_BRIEF: _finding_capability(
            CapabilityKey.EXECUTIVE_PORTFOLIO_BRIEF,
            AgentKey.EXECUTIVE_INTELLIGENCE,
            "executive_portfolio_brief",
            prompt_version="executive-intelligence-v3",
        ),
    }
)

_FINDING_TYPE_INDEX: MappingProxyType[tuple[AgentKey, str], CapabilityKey] = MappingProxyType(
    {
        (contract.agent_key, finding_type): key
        for key, contract in CAPABILITY_CONTRACTS.items()
        for finding_type in contract.finding_types
    }
)


def resolve_capability(key: str) -> CapabilityContract:
    """Resolve a capability key string; unknown keys fail closed."""
    try:
        return CAPABILITY_CONTRACTS[CapabilityKey(key)]
    except (ValueError, KeyError) as error:
        raise UnknownCapabilityError(f"unknown capability key: {key!r}") from error


def capability_for_finding(agent_key: AgentKey, finding_type: str) -> CapabilityContract:
    """Resolve the capability that owns (agent, finding type); fail closed."""
    key = _FINDING_TYPE_INDEX.get((agent_key, finding_type))
    if key is None:
        raise UnknownCapabilityError(
            f"no capability owns finding type {finding_type!r} for agent {agent_key.value!r}"
        )
    return resolve_capability(key.value)


def capabilities_for_event(event_type: str) -> tuple[CapabilityKey, ...]:
    """Resolve an event to capability keys via the frozen agent route table."""
    return tuple(
        key
        for agent_key in agents_for_event(event_type)
        for key, contract in CAPABILITY_CONTRACTS.items()
        if contract.agent_key is agent_key
        and bool(contract.finding_types)
        and contract.event_driven
    )
