"""Selected management scope and cited, read-only executive explanations."""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contracts.change_work_package import Statement
from app.contracts.common_objects import Contract, Text


class ExecutiveSelection(Contract):
    project_ids: list[UUID] = Field(min_length=1, max_length=10)

    @field_validator("project_ids")
    @classmethod
    def ordered(cls, value: list[UUID]) -> list[UUID]:
        return sorted(value)

    @model_validator(mode="after")
    def distinct(self) -> Self:
        if len(set(self.project_ids)) != len(self.project_ids):
            raise ValueError("管理摘要项目不可重复")
        return self


class ProjectBrief(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: UUID
    situation: Statement
    exceptions: tuple[Statement, ...] = Field(max_length=8)
    human_next_steps: tuple[Statement, ...] = Field(max_length=8)
    missing: tuple[Text, ...] = Field(max_length=15)


class ExecutiveBrief(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    disposition: Literal["explained", "insufficient_evidence"]
    portfolio_observations: tuple[Statement, ...] = Field(max_length=10)
    projects: tuple[ProjectBrief, ...] = Field(min_length=1, max_length=10)
    missing: tuple[Text, ...] = Field(max_length=30)
    coverage_limits: Text

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if len({v.project_id for v in self.projects}) != len(self.projects):
            raise ValueError("每个项目仅解释一次")
        if self.disposition == "insufficient_evidence" and not self.missing:
            raise ValueError("资料不足须明确缺项")
        return self
