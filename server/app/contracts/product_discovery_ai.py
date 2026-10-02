"""Exploration and experiment candidates; scope, decisions and approval remain server bound."""

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.contracts.common_objects import Quantity, SourceRef, Text
from app.contracts.product_records import FactStatement
from app.contracts.product_work_ai import ProductWorkAssessment
from app.domain.product_workspace import Input


class SolutionContent(Input):
    title: Text
    approach: Literal["new_development", "platform_reuse", "upgrade", "other"]
    rationale: FactStatement
    constraints: tuple[FactStatement, ...] = Field(default=(), max_length=30)
    unknowns: tuple[Text, ...] = Field(default=(), max_length=30)


class OpportunityContent(Input):
    segment_id: UUID
    parent_opportunity_id: UUID | None = None
    title: Text
    importance: Quantity | None = Field(ge=0, le=1)
    satisfaction: Quantity | None = Field(ge=0, le=1)
    importance_basis: FactStatement
    satisfaction_basis: FactStatement
    solutions: tuple[SolutionContent, ...] = Field(min_length=3, max_length=30)
    revision_reason: Text

    @model_validator(mode="after")
    def genuine_alternatives(self) -> Self:
        if len({s.title.casefold() for s in self.solutions}) != len(self.solutions):
            raise ValueError("候选方案名称不能重复")
        facts = [self.importance_basis, self.satisfaction_basis]
        for solution in self.solutions:
            facts.extend((solution.rationale, *solution.constraints))
        if any(fact.approval is not None for fact in facts):
            raise ValueError("探索候选不接受批准引用")
        return self


class ExperimentContent(Input):
    opportunity_id: UUID
    solution_id: UUID
    dimension: Literal["value", "usability", "viability", "feasibility"]
    hypothesis: Text
    method: Text
    sample_basis: Text
    success_criterion: Text
    falsification_criterion: Text
    due_at: AwareDatetime | None = None
    sources: tuple[SourceRef, ...] = Field(default=(), max_length=30)


class ProductDiscoveryAssessment(ProductWorkAssessment):
    opportunities: tuple[OpportunityContent, ...] = Field(default=(), max_length=6)
    experiments: tuple[ExperimentContent, ...] = Field(default=(), max_length=6)

    @model_validator(mode="after")
    def matching_domain(self) -> Self:
        if self.capability not in ("opportunity_mapping", "experiment_design"):
            raise ValueError("探索候选只用于机会与实验")
        if (self.capability == "opportunity_mapping" and self.experiments) or (
            self.capability == "experiment_design" and self.opportunities
        ):
            raise ValueError("候选须与原能力一致")
        if (self.opportunities or self.experiments) and not self.summary:
            raise ValueError("候选须有引用原字段的分析依据")
        return self
