"""N0-01 product objects before Project exists; candidate contracts, no persistence."""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.contracts.common_objects import (
    ApprovalRef,
    Contract,
    Key,
    Quantity,
    ScopedRecord,
    SourceRef,
    Text,
    Unit,
)


class ProductNode(ScopedRecord):
    code: Key
    name: Text
    level: Literal["line", "family", "platform", "series", "model", "variant"]
    parent_id: UUID | None
    lifecycle: Literal["proposed", "developing", "available", "retired"]
    regions: tuple[Key, ...] = ()
    channels: tuple[Key, ...] = ()
    definition_ref: SourceRef | None = None

    @model_validator(mode="after")
    def parent_shape(self) -> Self:
        if (self.level == "line") != (self.parent_id is None):
            raise ValueError("product_parent_required_except_line")
        if self.parent_id == self.id:
            raise ValueError("product_self_parent")
        if self.definition_ref is not None and self.definition_ref.tenant_id != self.tenant_id:
            raise ValueError("product_definition_tenant_mismatch")
        return self


class ProductHierarchy(Contract):
    """Complete input subtree including its line root; partial queries use ProductNode."""

    tenant_id: UUID
    nodes: tuple[ProductNode, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def hierarchy_integrity(self) -> Self:
        nodes = {node.id: node for node in self.nodes}
        if len(nodes) != len(self.nodes):
            raise ValueError("duplicate_product_id")
        if len({node.code for node in self.nodes}) != len(self.nodes):
            raise ValueError("duplicate_product_code")
        parent_levels = {
            "family": "line",
            "platform": "family",
            "series": "platform",
            "model": "series",
            "variant": "model",
        }
        for node in self.nodes:
            if node.tenant_id != self.tenant_id:
                raise ValueError("product_tenant_mismatch")
            if node.parent_id is not None:
                parent = nodes.get(node.parent_id)
                if parent is None or parent.level != parent_levels[node.level]:
                    raise ValueError("product_parent_level_or_reference_invalid")
        # Strictly increasing levels preclude a cycle without a second graph truth.
        return self


class MarketSpace(ScopedRecord):
    code: Key
    title: Text
    user_groups: tuple[Text, ...]
    regions: tuple[Text, ...]
    use_scenarios: tuple[Text, ...]
    lifecycle: Literal["draft", "active", "archived"]
    research_questions: tuple[Text, ...]


class ResearchTask(ScopedRecord):
    question: Text
    user_groups: tuple[Text, ...]
    regions: tuple[Text, ...]
    time_scope: Text
    method: Text
    expected_decision: Text
    stop_conditions: tuple[Text, ...] = Field(min_length=1)
    state: Literal["draft", "active", "completed", "cancelled"]
    findings: tuple[Text, ...] = ()
    unresolved: tuple[Text, ...] = ()
    conclusion: Text | None = None
    completed_at: AwareDatetime | None = None
    cancellation_reason: Text | None = None

    @model_validator(mode="after")
    def honest_research_completion(self) -> Self:
        if self.state in {"active", "completed"} and self.owner_user_id is None:
            raise ValueError("research_owner_required")
        if self.state == "completed":
            if self.conclusion is None or self.completed_at is None:
                raise ValueError("research_conclusion_required")
            if self.findings and not self.sources:
                raise ValueError("research_findings_require_sources")
        elif self.completed_at is not None:
            raise ValueError("unfinished_research_has_completion")
        if self.state == "cancelled" and self.cancellation_reason is None:
            raise ValueError("research_cancellation_reason_required")
        return self


class FactStatement(Contract):
    text: Text
    fact_kind: Literal["observed", "derived", "hypothesis"]
    sources: tuple[SourceRef, ...] = ()
    approval: ApprovalRef | None = None
    derivation_version: Key | None = None

    @model_validator(mode="after")
    def fact_is_not_approval(self) -> Self:
        if self.fact_kind != "hypothesis" and not self.sources:
            raise ValueError("fact_requires_sources")
        if self.fact_kind == "derived" and self.derivation_version is None:
            raise ValueError("derived_fact_requires_method")
        return self


class DesiredOutcome(ScopedRecord):
    statement: Text
    metric_key: Key
    unit: Unit
    baseline_value: Quantity | None
    target_value: Quantity | None
    measurement_method: Text
    window: Text


class SolutionCandidate(Contract):
    id: UUID
    title: Text
    approach: Literal["new_development", "platform_reuse", "upgrade", "other"]
    rationale: FactStatement
    constraints: tuple[FactStatement, ...]
    unknowns: tuple[Text, ...]


class Opportunity(ScopedRecord):
    title: Text
    segment: Text
    job_to_be_done: Text
    desired_outcome_id: UUID
    parent_opportunity_id: UUID | None
    importance: Quantity | None = Field(ge=0, le=1)
    satisfaction: Quantity | None = Field(ge=0, le=1)
    scoring_policy_version: Key | None
    solutions: tuple[SolutionCandidate, ...]
    selected_solution_id: UUID | None
    requirement_refs: tuple[SourceRef, ...] = ()
    state: Literal["exploring", "evaluating", "selected", "deferred", "closed"]

    @model_validator(mode="after")
    def selection_requires_real_alternatives(self) -> Self:
        if self.parent_opportunity_id == self.id:
            raise ValueError("opportunity_self_parent")
        ids = {solution.id for solution in self.solutions}
        if len(ids) != len(self.solutions):
            raise ValueError("duplicate_solution_id")
        if self.selected_solution_id is not None and (
            len(ids) < 3 or self.selected_solution_id not in ids
        ):
            raise ValueError("selection_requires_three_alternatives_and_member")
        if self.state == "selected" and self.selected_solution_id is None:
            raise ValueError("selected_opportunity_requires_solution")
        if (
            self.importance is not None or self.satisfaction is not None
        ) and self.scoring_policy_version is None:
            raise ValueError("opportunity_scoring_policy_required")
        refs = self.requirement_refs
        for solution in self.solutions:
            refs += solution.rationale.sources
            for constraint in solution.constraints:
                refs += constraint.sources
        if any(ref.tenant_id != self.tenant_id for ref in refs):
            raise ValueError("opportunity_source_tenant_mismatch")
        return self


class Experiment(ScopedRecord):
    opportunity_id: UUID
    solution_id: UUID
    dimension: Literal["value", "usability", "viability", "feasibility"]
    hypothesis: Text
    method: Text
    sample_basis: Text
    success_criterion: Text
    falsification_criterion: Text
    due_at: AwareDatetime | None
    state: Literal["draft", "approved", "running", "concluded", "cancelled"]
    approval: ApprovalRef | None
    result: Literal["supported", "refuted", "inconclusive"] | None
    result_evidence: tuple[SourceRef, ...] = ()
    result_explanation: Text | None = None
    concluded_at: AwareDatetime | None = None
    cancellation_reason: Text | None = None

    @model_validator(mode="after")
    def experiment_plan_is_not_result(self) -> Self:
        if self.state in {"approved", "running", "concluded"} and (
            self.approval is None or self.owner_user_id is None
        ):
            raise ValueError("experiment_approval_and_owner_required")
        if self.state == "concluded":
            if self.result is None or self.concluded_at is None or self.result_explanation is None:
                raise ValueError("experiment_conclusion_required")
            if self.result in {"supported", "refuted"} and not self.result_evidence:
                raise ValueError("decisive_experiment_requires_evidence")
        elif self.result is not None or self.concluded_at is not None or self.result_evidence:
            raise ValueError("unfinished_experiment_has_result")
        if any(ref.tenant_id != self.tenant_id for ref in self.result_evidence):
            raise ValueError("experiment_evidence_tenant_mismatch")
        if self.state == "cancelled" and self.cancellation_reason is None:
            raise ValueError("experiment_cancellation_reason_required")
        return self


class StrategyCanvas(Contract):
    vision: FactStatement
    segment_jtbd: FactStatement
    relative_cost: FactStatement
    value_proposition: FactStatement
    trade_offs: FactStatement
    success_metrics: FactStatement
    growth_path: FactStatement
    capabilities_partners: FactStatement
    defensibility: FactStatement


class ProductStrategy(ScopedRecord):
    opportunity_id: UUID
    selected_solution_id: UUID | None
    canvas: StrategyCanvas
    compared_solution_ids: tuple[UUID, ...]
    professional_constraints: tuple[FactStatement, ...]
    state: Literal["draft", "in_review", "published"]
    approval: ApprovalRef | None
    unknowns: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def strategy_publication(self) -> Self:
        if len(set(self.compared_solution_ids)) != len(self.compared_solution_ids):
            raise ValueError("strategy_duplicate_alternative")
        if (
            self.selected_solution_id is not None
            and self.selected_solution_id not in self.compared_solution_ids
        ):
            raise ValueError("strategy_selection_not_compared")
        statements = tuple(getattr(self.canvas, key) for key in StrategyCanvas.model_fields)
        statements += self.professional_constraints
        if any(
            ref.tenant_id != self.tenant_id for statement in statements for ref in statement.sources
        ):
            raise ValueError("strategy_source_tenant_mismatch")
        if self.state == "published" and (self.approval is None or self.owner_user_id is None):
            raise ValueError("strategy_publication_requires_approval_owner")
        if self.state == "published" and (
            len(self.compared_solution_ids) < 3 or self.selected_solution_id is None
        ):
            raise ValueError("published_strategy_requires_three_alternatives_and_selection")
        if self.state != "published" and self.approval is not None:
            raise ValueError("unpublished_strategy_has_approval")
        return self


class SpecificationItem(Contract):
    item_key: Key
    title: Text
    target_text: Text | None
    target_value: Quantity | None
    unit: Unit | None
    tolerance: Text | None
    conditions: tuple[Text, ...]
    priority: Literal["must", "should", "could"]
    required_for_release: bool
    rationale: FactStatement
    verification_method: Text | None
    acceptance_criterion: Text | None
    verification_stage: Key | None
    owner_user_id: UUID | None
    state: Literal["proposed", "needs_confirmation", "confirmed", "not_applicable"]
    disposition_reason: Text | None = None

    @model_validator(mode="after")
    def specification_is_verifiable(self) -> Self:
        if self.target_value is not None and self.unit is None:
            raise ValueError("numeric_spec_requires_unit")
        if self.state == "confirmed" and (
            (self.target_text is None and self.target_value is None)
            or self.verification_method is None
            or self.acceptance_criterion is None
            or self.verification_stage is None
            or self.owner_user_id is None
        ):
            raise ValueError("confirmed_spec_requires_target_verification_owner")
        if self.state == "not_applicable" and self.disposition_reason is None:
            raise ValueError("spec_exclusion_requires_reason")
        return self


class ProductDefinition(ScopedRecord):
    product_id: UUID
    strategy_ref: SourceRef
    title: Text
    target_users: tuple[Text, ...] = Field(min_length=1)
    scenarios: tuple[Text, ...] = Field(min_length=1)
    included_features: tuple[Key, ...]
    excluded_features: tuple[Key, ...]
    region_constraints: tuple[FactStatement, ...]
    target_cost: FactStatement
    price_position: FactStatement
    launch_window: FactStatement
    service_requirements: tuple[FactStatement, ...]
    success_criteria: tuple[FactStatement, ...] = Field(min_length=1)
    items: tuple[SpecificationItem, ...] = Field(min_length=1)
    state: Literal["draft", "in_review", "published"]
    approval: ApprovalRef | None
    published_at: AwareDatetime | None

    @model_validator(mode="after")
    def publish_current_verifiable_definition(self) -> Self:
        if self.strategy_ref.kind != "product_strategy":
            raise ValueError("definition_requires_strategy_reference")
        if set(self.included_features) & set(self.excluded_features):
            raise ValueError("definition_feature_conflict")
        if len({item.item_key for item in self.items}) != len(self.items):
            raise ValueError("duplicate_specification_item_key")
        statements = self.region_constraints + self.service_requirements + self.success_criteria
        statements += (self.target_cost, self.price_position, self.launch_window)
        statements += tuple(item.rationale for item in self.items)
        refs = (self.strategy_ref,) + tuple(
            ref for statement in statements for ref in statement.sources
        )
        if any(ref.tenant_id != self.tenant_id for ref in refs):
            raise ValueError("definition_source_tenant_mismatch")
        if self.state == "published":
            if self.approval is None or self.published_at is None or self.owner_user_id is None:
                raise ValueError("definition_publication_requires_approval_owner_time")
            if any(item.required_for_release and item.state != "confirmed" for item in self.items):
                raise ValueError("definition_required_items_unconfirmed")
        elif self.approval is not None or self.published_at is not None:
            raise ValueError("unpublished_definition_has_publication")
        return self
