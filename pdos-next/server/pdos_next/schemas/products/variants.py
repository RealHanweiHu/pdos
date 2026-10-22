from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from pdos_next.schema_base import StrictModel
from pdos_next.schemas.products.definitions import DefinitionReference, DefinitionSpec


class VariantSpecOverride(DefinitionSpec):
    @model_validator(mode="after")
    def no_inherited_appointment(self) -> Self:
        if self.model_fields_set & {"owner_id", "state"}:
            raise ValueError("派生覆盖不接受负责人或确认状态；新规格仍待独立专业确认")
        return self


class VariantOverrides(StrictModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    purpose: str | None = Field(default=None, min_length=3, max_length=2000)
    use_cases: list[str] | None = Field(default=None, min_length=1)
    requirements: list[str] | None = Field(default=None)
    constraints: list[str] | None = Field(default=None)
    unknowns: list[str] | None = Field(default=None)
    exclusions: list[str] | None = Field(default=None)
    specs: list[VariantSpecOverride] | None = Field(default=None)

    @field_validator("use_cases", "requirements", "constraints", "unknowns", "exclusions")
    @classmethod
    def list_entries(cls, entries):
        if entries is None:
            return entries
        if any(not value.strip() or len(value) > 2000 for value in entries):
            raise ValueError("覆盖条目须为非空文字且不超过2000字")
        entries = [value.strip() for value in entries]
        if len(set(entries)) != len(entries):
            raise ValueError("覆盖条目不能重复")
        return entries

    @model_validator(mode="after")
    def no_null_or_duplicate_spec(self) -> Self:
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("不覆盖的字段须省略，不能用null清除")
        if self.specs is not None and len({spec.key for spec in self.specs}) != len(self.specs):
            raise ValueError("覆盖规格标识不能重复")
        return self


class VariantDerivePayload(StrictModel):
    name: str = Field(min_length=2, max_length=160)
    kind: Literal["customer", "region", "configuration"]
    applicability: list[str] = Field(min_length=1)
    parent_definition_id: UUID
    expected_parent_revision: int = Field(ge=1)
    visibility: Literal["private", "category", "audience"] = "private"
    overrides: VariantOverrides = Field(default_factory=VariantOverrides)
    sources: list[DefinitionReference] = Field(min_length=1)
    reason: str = Field(min_length=3, max_length=2000)
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)

    @field_validator("applicability")
    @classmethod
    def scope_entries(cls, entries):
        entries = [value.strip() for value in entries]
        if any(not value or len(value) > 1000 for value in entries) or len(set(entries)) != len(
            entries
        ):
            raise ValueError("适用范围须为明确、不重复且不超过1000字的条目")
        return entries

    @model_validator(mode="after")
    def unique_references(self) -> Self:
        unique_sources(self.sources)
        return self


class RebaseChoice(StrictModel):
    path: str = Field(
        min_length=3,
        max_length=100,
        pattern=r"^(title|purpose|use_cases|requirements|constraints|unknowns|exclusions|specs/[a-zA-Z0-9_-]+)$",
    )
    selection: Literal["parent", "child"]
    reason: str = Field(min_length=3, max_length=2000)


class VariantRebasePayload(StrictModel):
    variant_id: UUID
    expected_variant_revision: int = Field(ge=1)
    parent_definition_id: UUID
    expected_parent_revision: int = Field(ge=1)
    choices: list[RebaseChoice] = Field(default_factory=list)
    sources: list[DefinitionReference] = Field(min_length=1)
    reason: str = Field(min_length=3, max_length=2000)
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)

    @model_validator(mode="after")
    def unique_choices(self) -> Self:
        if len({choice.path for choice in self.choices}) != len(self.choices):
            raise ValueError("每个差异只能作一次选择")
        unique_sources(self.sources)
        return self


def unique_sources(sources):
    if len(
        {
            (source.artifact_id, source.expected_revision, source.line, source.quote)
            for source in sources
        }
    ) != len(sources):
        raise ValueError("派生引用不能重复")
