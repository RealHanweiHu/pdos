"""Strategy/definition drafts without authority, personnel decisions or release state."""

from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from app.contracts.common_objects import Key, Quantity, Text, Unit
from app.contracts.product_records import FactStatement, StrategyCanvas
from app.contracts.product_work_ai import ProductWorkAssessment
from app.domain.product_strategies import MANUFACTURING_DISCIPLINES, RouteComparison
from app.domain.product_workspace import Input


class ConstraintContent(Input):
    discipline: Key
    statement: FactStatement
    work_item_id: UUID | None = None


class StrategyCandidate(Input):
    opportunity_id: UUID
    supersedes_id: UUID | None = None
    title: Text
    canvas: StrategyCanvas
    route_comparisons: tuple[RouteComparison, ...] = Field(min_length=3, max_length=30)
    professional_constraints: tuple[ConstraintContent, ...] = Field(min_length=3, max_length=100)
    unknowns: tuple[Text, ...] = Field(default=(), max_length=100)
    decision_reason: Text

    @model_validator(mode="after")
    def distinct_routes_and_disciplines(self) -> Self:
        if len({r.solution_id for r in self.route_comparisons}) != len(self.route_comparisons):
            raise ValueError("路线不能重复")
        disciplines = {c.discipline.lower() for c in self.professional_constraints}
        if not {"dqe", "sqe"}.issubset(disciplines) or not (
            disciplines & MANUFACTURING_DISCIPLINES
        ):
            raise ValueError("须列出DQE/SQE及PIE（兼容IE）专业约束，缺证据保留待核对")
        return self


class SpecificationContent(Input):
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

    @model_validator(mode="after")
    def numeric_unit(self) -> Self:
        if self.target_value is not None and self.unit is None:
            raise ValueError("数值规格须有单位")
        return self


class DefinitionCandidate(Input):
    product_id: UUID
    strategy_id: UUID
    supersedes_id: UUID | None = None
    title: Text
    target_users: tuple[Text, ...] = Field(min_length=1, max_length=100)
    scenarios: tuple[Text, ...] = Field(min_length=1, max_length=100)
    included_features: tuple[Key, ...] = Field(default=(), max_length=100)
    excluded_features: tuple[Key, ...] = Field(default=(), max_length=100)
    region_constraints: tuple[FactStatement, ...] = Field(default=(), max_length=100)
    target_cost: FactStatement
    price_position: FactStatement
    launch_window: FactStatement
    service_requirements: tuple[FactStatement, ...] = Field(default=(), max_length=100)
    success_criteria: tuple[FactStatement, ...] = Field(min_length=1, max_length=100)
    items: tuple[SpecificationContent, ...] = Field(min_length=1, max_length=300)
    change_reason: Text

    @model_validator(mode="after")
    def identity_and_features(self) -> Self:
        if len({item.item_key for item in self.items}) != len(self.items):
            raise ValueError("规格条目标识不能重复")
        if set(self.included_features) & set(self.excluded_features):
            raise ValueError("包含与排除功能不能重复")
        for values in (self.included_features, self.excluded_features):
            if len(set(values)) != len(values):
                raise ValueError("功能标识不能重复")
        return self


class ProductPlanningAssessment(ProductWorkAssessment):
    product_strategies: tuple[StrategyCandidate, ...] = Field(default=(), max_length=6)
    product_definitions: tuple[DefinitionCandidate, ...] = Field(default=(), max_length=6)

    @model_validator(mode="after")
    def matching_domain(self) -> Self:
        if self.capability not in ("product_strategy", "product_definition"):
            raise ValueError("规划候选只用于策略与定义")
        if (self.capability == "product_strategy" and self.product_definitions) or (
            self.capability == "product_definition" and self.product_strategies
        ):
            raise ValueError("候选须与原能力一致")
        if (self.product_strategies or self.product_definitions) and not self.summary:
            raise ValueError("候选须有引用原字段的分析依据")
        return self
