"""Source-cited cost proposals; amounts and actual approvals are never synthesized."""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.change_work_package import Statement
from app.contracts.common_objects import Contract, Text


class Selection(Contract):
    observation_id: UUID
    alternative_ids: list[UUID] = Field(default_factory=list, max_length=5)
    backtest_ids: list[UUID] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def unique(self) -> Self:
        if any(
            len(values) != len(set(values)) for values in (self.alternative_ids, self.backtest_ids)
        ):
            raise ValueError("同类成本资料不可重复选择")
        return self


class Preparation(Selection):
    discussion_run_id: UUID | None = None


class CostOption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_-]+$")
    title: Text
    scope: Statement
    expected_cost_effect: Statement
    quality_impact: Statement
    schedule_impact: Statement
    supplier_impact: Statement
    nre_impact: Statement
    verification: Statement
    correspondence_basis: Statement
    missing: tuple[Text, ...] = Field(max_length=20)


class CostAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    disposition: Literal["proposal", "insufficient_evidence"]
    observations: tuple[Statement, ...] = Field(max_length=20)
    options: tuple[CostOption, ...] = Field(max_length=6)
    missing: tuple[Text, ...] = Field(max_length=30)
    coverage_limits: Text

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if any(v.nature != "observed" for v in self.observations):
            raise ValueError("事实观察须基于原资料，预测另列")
        if len({v.key for v in self.options}) != len(self.options):
            raise ValueError("每份备选方案需要唯一标识")
        if self.disposition == "proposal" and not self.options:
            raise ValueError("成本建议须有实际备选方案")
        if self.disposition == "insufficient_evidence" and (self.options or not self.missing):
            raise ValueError("资料不足时保留待补项，不编造备选方案")
        return self
