from datetime import UTC
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from pdos_next.domain.configurations.schemas import DefinitionReference as _DefinitionReference


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class DefinitionReference(_DefinitionReference):
    expected_revision: int = Field(ge=1, strict=True)
    line: int = Field(ge=1, strict=True)


class ApprovalBasis(DTO):
    system: str = Field(min_length=1, max_length=100)
    external_id: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    approved_by: str = Field(min_length=1, max_length=200)
    issued_at: AwareDatetime

    @field_validator("issued_at")
    @classmethod
    def utc(cls, value):
        return value.astimezone(UTC)


class FactInput(DTO):
    """Data only. Scope and nature come from the trusted issuer, not this DTO."""

    product_id: UUID
    project_id: UUID
    subject_id: UUID
    external_id: str = Field(min_length=1, max_length=200)
    kind: Literal["duty", "qualification"]
    role: Literal["engineering", "quality", "manufacturing", "knowledge"]
    operations: list[str] = Field(min_length=1)
    purposes: list[str] = Field(min_length=1)
    state: Literal["active", "withdrawn", "revoked"] = "active"
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    previous_id: UUID | None = None
    expected_previous_revision: int = Field(default=0, ge=0, strict=True)
    approval: ApprovalBasis
    sources: list[DefinitionReference] = Field(min_length=1)
    reason: str = Field(min_length=3, max_length=2000)

    @field_validator("valid_from", "valid_until")
    @classmethod
    def utc(cls, value):
        return value.astimezone(UTC)

    @field_validator("operations", "purposes")
    @classmethod
    def precise_list(cls, value):
        normalized = [item.strip() for item in value]
        if any(not item or len(item) > 2000 for item in normalized):
            raise ValueError("用途和操作须为明确的非空值")
        if len(set(normalized)) != len(normalized):
            raise ValueError("用途和操作不能重复")
        return sorted(normalized)

    @model_validator(mode="after")
    def bound(self) -> Self:
        if self.valid_until <= self.valid_from:
            raise ValueError("专业事实有效期须严格递增")
        if (self.previous_id is None) != (self.expected_previous_revision == 0):
            raise ValueError("初版前版为空且版本为0；续版须固定ID和版本")
        if (self.kind == "duty" and self.state == "revoked") or (
            self.kind == "qualification" and self.state == "withdrawn"
        ):
            raise ValueError("职责撤回与人员资格撤销须分别记录")
        if len(
            {(ref.artifact_id, ref.expected_revision, ref.line, ref.quote) for ref in self.sources}
        ) != len(self.sources):
            raise ValueError("精确来源不能重复")
        return self
