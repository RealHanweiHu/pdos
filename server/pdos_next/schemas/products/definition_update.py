"""T1 header update of a product definition (P120 第 3 项, D311).

The person names the fixed revision they read and the complete new header. The
server creates the next draft revision with this header and copies the current
items and sources; the read revision itself never changes. Item edits stay with
``product.definition.item.patch``.
"""

from typing import Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from pdos_next.core.schema_base import StrictModel

HEADER = ("title", "purpose", "use_cases", "requirements", "constraints", "unknowns", "exclusions")


class DefinitionUpdatePayload(StrictModel):
    definition_id: UUID
    expected_definition_revision: int = Field(ge=1, strict=True)
    title: str = Field(min_length=2, max_length=200)
    purpose: str = Field(min_length=3, max_length=2000)
    use_cases: list[str] = Field(min_length=1)
    requirements: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    change_reason: str = Field(min_length=3, max_length=2000)
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)

    @field_validator("title", "purpose", "change_reason")
    @classmethod
    def stripped(cls, value):
        if not value.strip():
            raise ValueError("不能只填空白")
        return value.strip()

    @field_validator("use_cases", "requirements", "constraints", "unknowns", "exclusions")
    @classmethod
    def valid_entries(cls, values):
        if any(not v.strip() or len(v) > 2000 for v in values):
            raise ValueError("条目须为非空文字且不超过2000字")
        values = [v.strip() for v in values]
        if len(set(values)) != len(values):
            raise ValueError("条目不能重复")
        return values

    @model_validator(mode="after")
    def requirements_not_excluded(self) -> Self:
        if set(self.requirements) & set(self.exclusions):
            raise ValueError("同一条目不能既是需求又是排除项")
        return self

    def header(self):
        return {name: getattr(self, name) for name in HEADER}
