"""Cited product-position explanations without replacing deterministic coverage."""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.change_work_package import Statement
from app.contracts.common_objects import Contract, Key, Text


class MatrixExplanationSelection(Contract):
    record_id: UUID
    roadmap_ids: tuple[UUID, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def distinct(self) -> Self:
        if len(set(self.roadmap_ids)) != len(self.roadmap_ids):
            raise ValueError("路线图版本不能重复")
        return self


class ProductPosition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    product_id: UUID
    positioning: Statement
    coverage: Statement
    missing: tuple[Text, ...] = Field(max_length=15)


class CriterionExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    criterion_key: Key
    explanation: Statement
    human_next_steps: tuple[Statement, ...] = Field(max_length=5)


class PositioningHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    product_ids: tuple[UUID, ...] = Field(min_length=2, max_length=8)
    hypothesis: Statement
    verification_needed: tuple[Text, ...] = Field(min_length=1, max_length=15)

    @model_validator(mode="after")
    def unverified(self) -> Self:
        if len(set(self.product_ids)) != len(self.product_ids):
            raise ValueError("定位或复用假设的产品不能重复")
        if self.hypothesis.nature != "hypothesis":
            raise ValueError("重叠蚕食与工程复用仅能作为待验证假设")
        return self


class ProductMatrixExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    disposition: Literal["explained", "insufficient_evidence"]
    summary: tuple[Statement, ...] = Field(max_length=10)
    products: tuple[ProductPosition, ...] = Field(min_length=2, max_length=8)
    criteria: tuple[CriterionExplanation, ...] = Field(min_length=1, max_length=20)
    positioning_hypotheses: tuple[PositioningHypothesis, ...] = Field(max_length=8)
    platform_reuse_hypotheses: tuple[PositioningHypothesis, ...] = Field(max_length=8)
    missing: tuple[Text, ...] = Field(max_length=30)
    coverage_limits: Text

    @model_validator(mode="after")
    def complete(self) -> Self:
        if len({item.product_id for item in self.products}) != len(self.products):
            raise ValueError("每个产品只能解释一次")
        if len({item.criterion_key for item in self.criteria}) != len(self.criteria):
            raise ValueError("每项原判据只能解释一次")
        if self.disposition == "insufficient_evidence" and not self.missing:
            raise ValueError("资料不足须说明待补项")
        return self
