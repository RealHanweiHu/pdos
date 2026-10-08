from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from pdos_next.contracts import StrictModel


class DefinitionReference(StrictModel):
    artifact_id: UUID
    expected_revision: int = Field(ge=1)
    line: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=4000)


Number = Decimal | None


class DefinitionSpec(StrictModel):
    key: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    parameter: str = Field(min_length=1, max_length=200)
    value_type: Literal["number", "range", "text"]
    availability: Literal["known", "unknown", "conflicted", "not_applicable"] = "unknown"
    value: Number = None
    lower: Number = None
    upper: Number = None
    text: str | None = Field(default=None, max_length=2000)
    unit: str | None = Field(default=None, min_length=1, max_length=80)
    tolerance: Number = None
    test_conditions: list[str] = Field(default_factory=list, max_length=30)
    method: str | None = Field(default=None, min_length=1, max_length=2000)
    acceptance_criterion: str | None = Field(default=None, min_length=1, max_length=2000)
    nature: Literal["observed", "extracted", "computed", "inferred", "decided"] = "extracted"
    state: Literal["proposed", "needs_confirmation"] = "needs_confirmation"
    owner_id: UUID | None = None
    reason: str = Field(min_length=1, max_length=2000)
    sources: list[DefinitionReference] = Field(min_length=1, max_length=20)

    @field_validator("value", "lower", "upper", "tolerance")
    @classmethod
    def supported_decimal(cls, number):
        if number is not None and (
            not number.is_finite()
            or abs(number) >= Decimal("1e26")
            or number.as_tuple().exponent < -12
        ):
            raise ValueError("数值须有限且最多12位小数、26位整数")
        return number

    @field_validator("test_conditions")
    @classmethod
    def valid_conditions(cls, conditions):
        if any(not item.strip() or len(item) > 1000 for item in conditions):
            raise ValueError("测试条件须为非空文字且不超过1000字")
        return [item.strip() for item in conditions]

    @model_validator(mode="after")
    def value_consistency(self) -> Self:
        populated = any(
            item is not None for item in (self.value, self.lower, self.upper, self.text)
        )
        if self.availability != "known" and populated:
            raise ValueError("未知、冲突或不适用规格不得补填数值或文字目标")
        if self.availability == "known":
            if self.value_type == "number":
                if self.value is None or any(
                    v is not None for v in (self.lower, self.upper, self.text)
                ):
                    raise ValueError("数值规格须有且仅有一个目标值")
            elif self.value_type == "range":
                if self.lower is None or self.upper is None or self.lower > self.upper:
                    raise ValueError("范围规格须有有序上下限")
                if self.value is not None or self.text is not None:
                    raise ValueError("范围规格不能另填单值或文字目标")
            elif (
                not self.text
                or not self.text.strip()
                or any(v is not None for v in (self.value, self.lower, self.upper))
            ):
                raise ValueError("文字规格须有且仅有文字目标")
            if self.value_type != "text" and not self.unit:
                raise ValueError("已知数值和范围规格须明确单位")
        if self.tolerance is not None and self.tolerance < 0:
            raise ValueError("允差不能为负")
        if self.tolerance is not None and (
            self.value_type == "text" or self.availability != "known"
        ):
            raise ValueError("未知或文字规格不能填写数值允差")
        if len(
            {(s.artifact_id, s.expected_revision, s.line, s.quote) for s in self.sources}
        ) != len(self.sources):
            raise ValueError("规格引用不能重复")
        return self


class DefinitionDraftPayload(StrictModel):
    title: str = Field(min_length=2, max_length=200)
    purpose: str = Field(min_length=3, max_length=2000)
    visibility: Literal["private", "product"] = "private"
    parent_definition_id: UUID | None = None
    expected_parent_revision: int | None = Field(default=None, ge=1)
    use_cases: list[str] = Field(min_length=1, max_length=50)
    requirements: list[str] = Field(default_factory=list, max_length=100)
    constraints: list[str] = Field(default_factory=list, max_length=100)
    unknowns: list[str] = Field(default_factory=list, max_length=100)
    exclusions: list[str] = Field(default_factory=list, max_length=100)
    sources: list[DefinitionReference] = Field(min_length=1, max_length=20)
    specs: list[DefinitionSpec] = Field(default_factory=list, max_length=100)
    change_reason: str = Field(min_length=3, max_length=2000)

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
    def consistent_definition(self) -> Self:
        if (self.parent_definition_id is None) != (self.expected_parent_revision is None):
            raise ValueError("固定父版ID和版本必须同时提供")
        if len({item.key for item in self.specs}) != len(self.specs):
            raise ValueError("规格标识不能重复")
        refs = {(s.artifact_id, s.expected_revision, s.line, s.quote) for s in self.sources}
        if len(refs) != len(self.sources):
            raise ValueError("定义引用不能重复")
        if set(self.requirements) & set(self.exclusions):
            raise ValueError("要求和排除范围不能重复")
        for spec in self.specs:
            if (
                not {(s.artifact_id, s.expected_revision, s.line, s.quote) for s in spec.sources}
                <= refs
            ):
                raise ValueError("规格引用必须包含在定义引用中")
        return self
