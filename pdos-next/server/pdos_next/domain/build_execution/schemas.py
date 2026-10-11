from datetime import UTC
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from pdos_next.domain.configurations.schemas import DefinitionReference

DISCRETE_UNITS = frozenset({"台", "件", "个", "只", "套", "ea", "piece", "unit"})


class _DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Fact(_DTO):
    reason: str = Field(min_length=3, max_length=2000)
    sources: list[DefinitionReference] = Field(min_length=1)
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)

    @model_validator(mode="after")
    def unique_sources(self) -> Self:
        if len(
            {(ref.artifact_id, ref.expected_revision, ref.line, ref.quote) for ref in self.sources}
        ) != len(self.sources):
            raise ValueError("事实来源不能重复")
        return self


class ConfigurationDifference(_DTO):
    path: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=3, max_length=2000)
    sources: list[DefinitionReference] = Field(min_length=1)


class ActualConfigurationPayload(_Fact):
    build_id: UUID
    expected_build_revision: int = Field(ge=1)
    actual_engineering_configuration_id: UUID
    expected_actual_engineering_revision: int = Field(ge=1)
    actual_manufacturing_configuration_id: UUID
    expected_actual_manufacturing_revision: int = Field(ge=1)
    observed_at: AwareDatetime
    differences: list[ConfigurationDifference] = Field(default_factory=list)

    @field_validator("observed_at")
    @classmethod
    def utc_time(cls, value):
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def unique_paths(self) -> Self:
        if len({difference.path for difference in self.differences}) != len(self.differences):
            raise ValueError("每个配置差异须有且仅有一条原因与来源")
        return self


class ExternalObservation(_DTO):
    system: str = Field(min_length=1, max_length=100)
    external_id: str = Field(min_length=1, max_length=200)
    nature: Literal["real", "synthetic"]
    occurred_at: AwareDatetime

    @field_validator("occurred_at")
    @classmethod
    def utc_time(cls, value):
        return value.astimezone(UTC)


class OutputPayload(_Fact):
    build_id: UUID
    expected_build_revision: int = Field(ge=1)
    actual_configuration_id: UUID
    expected_actual_configuration_revision: int = Field(ge=1)
    lot_label: str = Field(min_length=1, max_length=100)
    observed_unit_count: int = Field(ge=1, strict=True)
    unit: str = Field(min_length=1, max_length=80)
    observation: ExternalObservation

    @field_validator("unit")
    @classmethod
    def discrete_unit(cls, value):
        if value not in DISCRETE_UNITS:
            raise ValueError("本轮只记录明确离散单件产出，不把重量或体积转换为样件个数")
        return value


class SampleIdentity(_DTO):
    label: str = Field(min_length=1, max_length=100)
    operation_key: str | None = Field(default=None, min_length=1, max_length=80)
    cavity: str | None = Field(default=None, min_length=1, max_length=100)
    custodian_id: UUID | None = None
    custodian_label: str | None = Field(default=None, min_length=1, max_length=200)
    location: str | None = Field(default=None, min_length=1, max_length=500)
    destination: str | None = Field(default=None, min_length=1, max_length=500)
    availability: Literal["unknown", "hold"] = "unknown"


class SampleAllocatePayload(_Fact):
    lot_id: UUID
    expected_lot_revision: int = Field(ge=1)
    samples: list[SampleIdentity] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_labels(self) -> Self:
        if len({sample.label for sample in self.samples}) != len(self.samples):
            raise ValueError("同一次分配不能重复标识相同样件标签")
        return self
