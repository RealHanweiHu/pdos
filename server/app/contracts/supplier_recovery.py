"""Cited supply recovery options for independent human review and application."""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.change_work_package import Statement
from app.contracts.common_objects import Contract


class RecoveryOption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_-]+$")
    kind: Literal["expediting", "substitution", "borrowing", "tooling_recovery"]
    target_reference_ids: tuple[str, ...] = Field(min_length=1, max_length=20)
    description: str = Field(min_length=1, max_length=4000)
    basis: Statement
    required_verification: tuple[str, ...] = Field(min_length=1, max_length=20)
    completion_criteria: str | None = Field(min_length=1, max_length=4000)
    missing: tuple[str, ...] = Field(max_length=20)
    communication_draft: str | None = Field(min_length=1, max_length=6000)

    @model_validator(mode="after")
    def actionable(self) -> Self:
        if len(set(self.target_reference_ids)) != len(self.target_reference_ids):
            raise ValueError("同一恢复方案对象不可重复")
        if self.completion_criteria is None and not self.missing:
            raise ValueError("完成条件未知须明确待补依据")
        if any(
            not value.strip() or len(value) > 4000
            for value in (*self.required_verification, *self.missing)
        ):
            raise ValueError("核对与待补要求须非空且不超过4000字")
        return self


class SupplierRecoveryAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    disposition: Literal["proposal", "insufficient_evidence"]
    observations: tuple[Statement, ...] = Field(max_length=20)
    options: tuple[RecoveryOption, ...] = Field(max_length=30)
    missing: tuple[str, ...] = Field(max_length=50)
    coverage_limits: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if any(item.nature != "observed" for item in self.observations):
            raise ValueError("事实观察须引用原资料，不以假设代替")
        if len({item.key for item in self.options}) != len(self.options):
            raise ValueError("每个方案须有唯一编号")
        if self.disposition == "proposal" and not self.options:
            raise ValueError("恢复建议须包含具体方案")
        if self.disposition == "insufficient_evidence" and (not self.missing or self.options):
            raise ValueError("证据不足时列出待补资料，不提供恢复方案")
        if any(not value.strip() or len(value) > 4000 for value in self.missing):
            raise ValueError("待补说明须非空且不超过4000字")
        return self


class Selection(Contract):
    exception_ids: list[UUID] = Field(default_factory=list, max_length=20)
    tooling_ids: list[UUID] = Field(default_factory=list, max_length=20)
    supplier_ids: list[UUID] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def selected(self) -> Self:
        if not self.exception_ids and not self.tooling_ids:
            raise ValueError("请选择实际物料异常或工装轮次")
        if any(
            len(values) != len(set(values))
            for values in (self.exception_ids, self.tooling_ids, self.supplier_ids)
        ):
            raise ValueError("同类原资料不可重复选择")
        return self
