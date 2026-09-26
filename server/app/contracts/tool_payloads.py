"""N0-02 model-visible tool payloads; service scope never comes from these DTOs.

Handles are scoped lookups issued by the server. Parsing one is not permission
or evidence of existence. Domain adapters must resolve and reauthorize them.
"""

from __future__ import annotations

from datetime import date
from typing import Literal, Self

from pydantic import AwareDatetime, ConfigDict, Field, HttpUrl, model_validator

from app.contracts.common_objects import (
    Contract,
    Digest,
    Key,
    Nonnegative,
    Positive,
    Quantity,
    Text,
    Unit,
)


class BoundHandle(Contract):
    handle: Key
    version: Positive | None = None
    digest: Digest | None = None

    @model_validator(mode="after")
    def pinned_reference(self) -> Self:
        if self.version is None and self.digest is None:
            raise ValueError("handle_requires_version_or_digest")
        return self


class CitedStatement(Contract):
    text: Text
    nature: Literal["observed", "derived", "hypothesis"]
    citations: tuple[BoundHandle, ...]
    missing: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def sourced_fact(self) -> Self:
        if self.nature != "hypothesis" and not self.citations:
            raise ValueError("factual_statement_requires_citation")
        return self


class SearchSourcesInput(Contract):
    query: Text
    region: Text | None = None
    date_from: date | None = None
    date_to: date | None = None
    limit: Positive = Field(default=10, le=20)
    continuation: Text | None = None

    @model_validator(mode="after")
    def valid_window(self) -> Self:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("search_date_window_reversed")
        return self


class CaptureSnapshotInput(Contract):
    url: HttpUrl
    purpose: Text

    @model_validator(mode="after")
    def no_url_credentials(self) -> Self:
        if self.url.username is not None or self.url.password is not None:
            raise ValueError("public_capture_cannot_include_credentials")
        return self


class SearchKnowledgeInput(Contract):
    query: Text
    applicability: tuple[BoundHandle, ...]
    limit: Positive = Field(default=10, le=20)
    continuation: Text | None = None


class GetVerificationEvidenceInput(Contract):
    targets: tuple[BoundHandle, ...] = Field(min_length=1, max_length=50)
    facets: tuple[Literal["spec", "case", "sample", "build", "run", "certification"], ...]
    continuation: Text | None = None


class EvaluateReadinessInput(Contract):
    target: BoundHandle
    action: Key
    policy_version: Key


class DraftTask(Contract):
    node_key: Key
    title: Text
    discipline: Key
    owner: BoundHandle | None
    receiver: BoundHandle | None
    expected_output: Text
    acceptance_criteria: Text
    effort_hours: Quantity | None = Field(ge=0)
    waiting_days: Nonnegative = 0
    estimate_basis: CitedStatement | None = None
    missing: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def estimate_needs_basis(self) -> Self:
        if self.effort_hours is not None and self.estimate_basis is None:
            raise ValueError("task_estimate_requires_basis")
        return self


class DraftDependency(Contract):
    predecessor: Key
    successor: Key
    relation: Literal["fs", "ss", "ff", "sf"]
    lag: Quantity
    lag_unit: Literal["working_hours", "calendar_days"]


class PlanDraft(Contract):
    template: BoundHandle
    tasks: tuple[DraftTask, ...] = Field(min_length=1, max_length=500)
    dependencies: tuple[DraftDependency, ...] = Field(max_length=5000)
    source_handles: tuple[BoundHandle, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def graph_integrity(self) -> Self:
        keys = {task.node_key for task in self.tasks}
        if len(keys) != len(self.tasks):
            raise ValueError("duplicate_draft_node")
        incoming = dict.fromkeys(keys, 0)
        outgoing: dict[str, list[str]] = {key: [] for key in keys}
        edges = set()
        for edge in self.dependencies:
            identity = (edge.predecessor, edge.successor, edge.relation)
            if edge.predecessor not in keys or edge.successor not in keys:
                raise ValueError("draft_dependency_orphan")
            if identity in edges:
                raise ValueError("duplicate_draft_edge")
            edges.add(identity)
            outgoing[edge.predecessor].append(edge.successor)
            incoming[edge.successor] += 1
        ready = [key for key, count in incoming.items() if count == 0]
        visited = 0
        while ready:
            key = ready.pop()
            visited += 1
            for target in outgoing[key]:
                incoming[target] -= 1
                if incoming[target] == 0:
                    ready.append(target)
        if visited != len(keys):
            raise ValueError("draft_dependency_cycle")
        return self


class EvaluateScenarioInput(Contract):
    draft: PlanDraft
    calendars: tuple[BoundHandle, ...]
    capacities: tuple[BoundHandle, ...]
    expected_input_digest: Digest
    algorithm_version: Key


class TraceImpactInput(Contract):
    changed_objects: tuple[BoundHandle, ...] = Field(min_length=1, max_length=50)
    proposed_change: Text
    depth: Positive = Field(default=3, le=5)
    continuation: Text | None = None


class DraftSpecification(Contract):
    item_key: Key
    title: Text
    target_text: Text | None
    target_value: Quantity | None
    unit: Unit | None
    conditions: tuple[Text, ...]
    priority: Literal["must", "should", "could"]
    rationale: CitedStatement
    verification_method: Text | None
    acceptance_criterion: Text | None
    missing: tuple[Text, ...]

    @model_validator(mode="after")
    def preserve_units(self) -> Self:
        if self.target_value is not None and self.unit is None:
            raise ValueError("draft_numeric_spec_requires_unit")
        return self


class PrepareDefinitionInput(Contract):
    strategy: BoundHandle
    product: BoundHandle
    title: Text
    target_users: tuple[Text, ...] = Field(min_length=1)
    scenarios: tuple[Text, ...] = Field(min_length=1)
    included_features: tuple[Key, ...]
    excluded_features: tuple[Key, ...]
    items: tuple[DraftSpecification, ...] = Field(min_length=1, max_length=500)
    constraints: tuple[CitedStatement, ...]
    missing: tuple[Text, ...]

    @model_validator(mode="after")
    def distinct_items_and_features(self) -> Self:
        if set(self.included_features) & set(self.excluded_features):
            raise ValueError("draft_feature_conflict")
        if len({item.item_key for item in self.items}) != len(self.items):
            raise ValueError("duplicate_draft_specification")
        return self


class PrepareInitialPlanInput(Contract):
    case: BoundHandle
    definition: BoundHandle
    draft: PlanDraft
    scenario_result: BoundHandle | None
    current_missing: tuple[Text, ...]


class ProposedTest(Contract):
    item_key: Key
    feature: Key
    title: Text
    method: Text | None
    conditions: tuple[Text, ...]
    acceptance_criterion: Text | None
    applicability: CitedStatement
    missing: tuple[Text, ...]


class PreparePlanChangeInput(Contract):
    plan: BoundHandle
    reason: CitedStatement
    additions: tuple[ProposedTest, ...]
    retire_item_keys: tuple[Key, ...]
    changed_requirements: tuple[BoundHandle, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def effective_diff(self) -> Self:
        if not self.additions and not self.retire_item_keys:
            raise ValueError("plan_change_requires_diff")
        keys = [item.item_key for item in self.additions]
        if len(keys) != len(set(keys)) or len(set(self.retire_item_keys)) != len(
            self.retire_item_keys
        ):
            raise ValueError("duplicate_test_plan_change_key")
        if set(keys) & set(self.retire_item_keys):
            raise ValueError("test_plan_change_add_retire_conflict")
        return self


class PreviewImportInput(Contract):
    batch: BoundHandle
    plan: BoundHandle
    mapping: BoundHandle | None
    continuation: Text | None = None


class ProposedAction(Contract):
    action_key: Key
    title: Text
    owner: BoundHandle | None
    output: Text
    verification: Text
    predecessors: tuple[Key, ...]
    evidence: tuple[BoundHandle, ...]


class PrepareChangePackageInput(Contract):
    change: BoundHandle
    impact_result: BoundHandle
    rationale: CitedStatement
    actions: tuple[ProposedAction, ...] = Field(min_length=1, max_length=200)
    affected_versions: tuple[BoundHandle, ...] = Field(min_length=1)
    missing: tuple[Text, ...]


class PrepareCapaInput(Contract):
    issue: BoundHandle
    failure_evidence: tuple[BoundHandle, ...] = Field(min_length=1)
    root_cause_hypotheses: tuple[CitedStatement, ...] = Field(min_length=1)
    containment: tuple[ProposedAction, ...]
    corrective_actions: tuple[ProposedAction, ...] = Field(min_length=1)
    effectiveness_plan: Text
    missing: tuple[Text, ...]


class PrepareHandoffInput(Contract):
    target: BoundHandle
    approved_versions: tuple[BoundHandle, ...]
    delivery_evidence: tuple[BoundHandle, ...]
    sender: BoundHandle | None
    receiver: BoundHandle | None
    open_items: tuple[CitedStatement, ...]
    mode: Literal["readiness_only", "propose_package"]


class EvidenceCard(Contract):
    reference: BoundHandle
    title: Text
    excerpt: Text
    locator: Text | None
    as_of: AwareDatetime
    freshness: Literal["current", "stale", "unknown"]
    taint: Literal["untrusted_external", "internal", "verified"]


class EvidenceData(Contract):
    kind: Literal["evidence"] = "evidence"
    cards: tuple[EvidenceCard, ...]
    missing: tuple[Text, ...]


class SearchHit(Contract):
    url: HttpUrl
    title: Text
    snippet: Text
    citable: Literal[False] = False


class SearchData(Contract):
    kind: Literal["search"] = "search"
    hits: tuple[SearchHit, ...]
    query: Text
    provider_version: Key


class ReadinessData(Contract):
    kind: Literal["readiness"] = "readiness"
    target: BoundHandle
    eligible: bool
    blockers: tuple[Text, ...]
    sources: tuple[BoundHandle, ...]
    policy_version: Key

    @model_validator(mode="after")
    def no_false_green(self) -> Self:
        if self.eligible == bool(self.blockers):
            raise ValueError("readiness_blockers_inconsistent")
        return self


class ScenarioNodeTime(Contract):
    node_key: Key
    start: AwareDatetime | None
    end: AwareDatetime | None

    @model_validator(mode="after")
    def chronology(self) -> Self:
        if self.start and self.end and self.end < self.start:
            raise ValueError("scenario_time_reversed")
        return self


class ScenarioData(Contract):
    kind: Literal["scenario"] = "scenario"
    input_digest: Digest
    algorithm_version: Key
    completeness: Literal["complete", "partial", "not_computable"]
    node_times: tuple[ScenarioNodeTime, ...]
    critical_path: tuple[Key, ...]
    conflicts: tuple[Text, ...]
    missing: tuple[Text, ...]

    @model_validator(mode="after")
    def missing_is_not_an_invented_date(self) -> Self:
        keys = {item.node_key for item in self.node_times}
        if len(keys) != len(self.node_times) or not set(self.critical_path).issubset(keys):
            raise ValueError("scenario_node_reference_invalid")
        if self.completeness == "complete" and (self.missing or not keys):
            raise ValueError("complete_scenario_requires_known_nodes")
        if self.completeness == "not_computable" and (keys or not self.missing):
            raise ValueError("uncomputable_scenario_cannot_invent_dates")
        return self


class ImpactLink(Contract):
    source: BoundHandle
    target: BoundHandle
    relation: Key
    rationale: CitedStatement


class ImpactData(Contract):
    kind: Literal["impact"] = "impact"
    links: tuple[ImpactLink, ...]
    missing: tuple[Text, ...]


class FindingData(Contract):
    kind: Literal["finding"] = "finding"
    finding: BoundHandle
    finding_type: Key
    status: Literal["pending_review"] = "pending_review"
    candidate_digest: Digest
    missing: tuple[Text, ...]
    receipt: BoundHandle


class RawCell(Contract):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    locator: Text
    original_text: str = Field(max_length=10000)
    mapped_item: Key | None
    issue: Text | None


class ImportPreviewData(Contract):
    kind: Literal["import_preview"] = "import_preview"
    batch: BoundHandle
    mapping_status: Literal["confirmed", "proposed", "missing"]
    cells: tuple[RawCell, ...]
    missing: tuple[Text, ...]


class ToolUsage(Contract):
    elapsed_ms: Nonnegative
    payload_bytes: Nonnegative
    tool_cost_microusd: Nonnegative | None
    price_status: Literal["priced", "unknown", "test_fixture"]

    @model_validator(mode="after")
    def unknown_cost_is_null(self) -> Self:
        if self.price_status == "unknown" and self.tool_cost_microusd is not None:
            raise ValueError("unknown_tool_cost_must_be_null")
        return self


class ToolError(Contract):
    code: Literal[
        "tool_unavailable",
        "scope_denied",
        "source_unavailable",
        "source_stale",
        "context_incomplete",
        "input_invalid",
        "dependency_unmet",
        "budget_exhausted",
        "rate_limited",
        "timeout",
        "cancelled",
        "version_conflict",
        "not_ready",
    ]
    message: Text
    retryable: bool


class ToolResult[DataT: Contract](Contract):
    operation_id: Key
    tool_call_id: Key
    tool_version: Key
    status: Literal["completed", "partial", "zero_results", "duplicate_reused", "failed"]
    data: DataT | None
    evidence_refs: tuple[BoundHandle, ...]
    source_versions: tuple[BoundHandle, ...]
    as_of: AwareDatetime
    continuation: Text | None
    error: ToolError | None
    usage: ToolUsage

    @model_validator(mode="after")
    def honest_result(self) -> Self:
        if self.status == "failed":
            if self.error is None or self.data is not None:
                raise ValueError("failed_tool_requires_error_without_data")
        elif self.error is not None or self.data is None:
            raise ValueError("successful_tool_requires_data_without_error")
        if self.status == "zero_results":
            if isinstance(self.data, SearchData) and self.data.hits:
                raise ValueError("zero_results_has_search_hits")
            if isinstance(self.data, EvidenceData) and self.data.cards:
                raise ValueError("zero_results_has_evidence")
            if not isinstance(self.data, (SearchData, EvidenceData)):
                raise ValueError("zero_results_only_for_retrieval")
        return self


class SearchSourcesResult(ToolResult[SearchData]):
    pass


class EvidenceResult(ToolResult[EvidenceData]):
    pass


class ReadinessResult(ToolResult[ReadinessData]):
    pass


class ScenarioResult(ToolResult[ScenarioData]):
    pass


class ImpactResult(ToolResult[ImpactData]):
    pass


class FindingResult(ToolResult[FindingData]):
    pass


class ImportPreviewResult(ToolResult[ImportPreviewData]):
    pass


class HandoffResult(ToolResult[ReadinessData | FindingData]):
    pass


class BriefOption(Contract):
    option_key: Key
    proposal: CitedStatement
    benefits: tuple[CitedStatement, ...]
    costs: tuple[CitedStatement, ...]
    dissent: tuple[CitedStatement, ...]


class DecisionBrief(Contract):
    topic: Text
    context: tuple[CitedStatement, ...]
    consensus: tuple[CitedStatement, ...]
    options: tuple[BriefOption, ...] = Field(min_length=1)
    recommended_option: Key | None
    rationale: tuple[CitedStatement, ...]
    unresolved: tuple[Text, ...]
    source_handles: tuple[BoundHandle, ...] = Field(min_length=1)
    intended_use: Literal["read_only", "business_proposal"]
    finding: BoundHandle | None
    stop_reason: Literal[
        "sufficient_evidence", "no_information_gain", "budget_limit", "missing_input", "cancelled"
    ]

    @model_validator(mode="after")
    def proposal_is_not_a_decision(self) -> Self:
        keys = {option.option_key for option in self.options}
        if len(keys) != len(self.options) or (
            self.recommended_option and self.recommended_option not in keys
        ):
            raise ValueError("brief_option_reference_invalid")
        if (self.intended_use == "business_proposal") != (self.finding is not None):
            raise ValueError("brief_business_proposal_requires_finding")
        return self
