"""Read-only, cited explanations of saved deterministic portfolio comparisons."""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.change_work_package import Statement
from app.contracts.common_objects import Contract, Text


class Selection(Contract):
    comparison_id: UUID


class AlternativeExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    alternative_key: str = Field(min_length=1, max_length=80)
    eligibility: Statement
    time: Statement
    cost: Statement
    quality: Statement
    capacity: Statement
    tradeoffs: tuple[Statement, ...] = Field(max_length=6)
    missing: tuple[Text, ...] = Field(max_length=20)


class PortfolioExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    disposition: Literal["explained", "insufficient_evidence"]
    observations: tuple[Statement, ...] = Field(max_length=12)
    alternatives: tuple[AlternativeExplanation, ...] = Field(min_length=2, max_length=8)
    missing: tuple[Text, ...] = Field(max_length=30)
    coverage_limits: Text

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if len({v.alternative_key for v in self.alternatives}) != len(self.alternatives):
            raise ValueError("每项原方案仅解释一次")
        if self.disposition == "insufficient_evidence" and not self.missing:
            raise ValueError("资料不足时须明确待补项")
        return self
