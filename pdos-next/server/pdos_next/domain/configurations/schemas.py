from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from pdos_next.engines.supply_cost.common import Loss, Positive


class StrictModel(BaseModel):
    # Local base keeps this public DTO independently importable from the command registry.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DefinitionReference(StrictModel):
    artifact_id: UUID
    expected_revision: int = Field(ge=1)
    line: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=4000)


class ExternalDesignReference(StrictModel):
    system: str = Field(min_length=1, max_length=100)
    external_id: str = Field(min_length=1, max_length=200)
    revision: str | None = Field(default=None, min_length=1, max_length=100)
    as_of: AwareDatetime | None = None
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    basis: DefinitionReference | None = None

    @model_validator(mode="after")
    def pinned_or_sourced(self) -> Self:
        if self.basis is None and any(
            value is None for value in (self.revision, self.as_of, self.content_sha256)
        ):
            raise ValueError("外部引用须固定版本、时点和hash，或提供可核验的精确原文依据")
        return self


class PartDraft(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    internal_number: str | None = Field(default=None, min_length=1, max_length=100)
    erp_number: str | None = Field(default=None, min_length=1, max_length=100)
    customer_number: str | None = Field(default=None, min_length=1, max_length=100)
    mapping_version: str | None = Field(default=None, min_length=1, max_length=100)
    external_design_refs: list[ExternalDesignReference] = Field(default_factory=list)


class BomLineInput(StrictModel):
    key: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    part_id: UUID | None = None
    expected_part_revision: int | None = Field(default=None, ge=1)
    part: PartDraft | None = None
    quantity: Positive | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=80)
    # Declared additional loss multiplier: demand = quantity * (1 + loss_rate).
    loss_rate: Loss | None = None
    critical: bool = Field(default=False, strict=True)
    notes: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def explicit_part_and_quantity(self) -> Self:
        if self.part_id is None:
            if self.part is None or self.expected_part_revision is not None:
                raise ValueError("新物料须提供身份资料，不能捏造固定物料版本")
        elif self.part is not None or self.expected_part_revision is None:
            raise ValueError("复用物料须固定ID与版本，不同时改写物料身份")
        if self.quantity is not None and self.unit is None:
            raise ValueError("已知BOM数量须明确单位，未知数量保持null")
        return self


class _RevisionPayload(StrictModel):
    name: str = Field(min_length=2, max_length=200)
    visibility: Literal["private", "category", "audience"] = "private"
    previous_id: UUID | None = None
    expected_previous_revision: int | None = Field(default=None, ge=1)
    reason: str = Field(min_length=3, max_length=2000)
    sources: list[DefinitionReference] = Field(min_length=1)
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)

    @model_validator(mode="after")
    def exact_previous_and_sources(self) -> Self:
        if (self.previous_id is None) != (self.expected_previous_revision is None):
            raise ValueError("固定旧版ID和版本须同时提供；初版均为null")
        if len(
            {(ref.artifact_id, ref.expected_revision, ref.line, ref.quote) for ref in self.sources}
        ) != len(self.sources):
            raise ValueError("精确原文依据不能重复")
        return self


class EngineeringBomRevisePayload(_RevisionPayload):
    lines: list[BomLineInput] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_lines(self) -> Self:
        if len({line.key for line in self.lines}) != len(self.lines):
            raise ValueError("BOM行标识不能重复")
        return self


class EngineeringConfigurationCreatePayload(_RevisionPayload):
    definition_id: UUID
    expected_definition_revision: int = Field(ge=1)
    bom_id: UUID
    expected_bom_revision: int = Field(ge=1)
    mechanical: ExternalDesignReference | None = None
    electronic: ExternalDesignReference | None = None
    firmware: ExternalDesignReference | None = None


class ResourceRequirement(StrictModel):
    kind: Literal["person", "equipment", "tooling", "station", "other"]
    name: str = Field(min_length=1, max_length=200)
    external_id: str | None = Field(default=None, min_length=1, max_length=200)
    qualification: str | None = Field(default=None, min_length=1, max_length=2000)


class ProcessOperation(StrictModel):
    key: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["assembly", "inspection", "test", "packaging", "other"]
    depends_on: list[str] = Field(default_factory=list)
    bom_line_keys: list[str] = Field(default_factory=list)
    sop: ExternalDesignReference | None = None
    resource_requirements: list[ResourceRequirement] = Field(default_factory=list)
    cycle_time_minutes: Positive | None = None
    acceptance_criterion: str | None = Field(default=None, min_length=1, max_length=2000)
    notes: str | None = Field(default=None, min_length=1, max_length=2000)


class NpiProcessRevisePayload(_RevisionPayload):
    engineering_configuration_id: UUID
    expected_engineering_revision: int = Field(ge=1)
    site: str | None = Field(default=None, min_length=1, max_length=200)
    line: str | None = Field(default=None, min_length=1, max_length=200)
    operations: list[ProcessOperation] = Field(min_length=1)

    @model_validator(mode="after")
    def coherent_operations(self) -> Self:
        keys = {operation.key for operation in self.operations}
        if len(keys) != len(self.operations):
            raise ValueError("工序标识不能重复")
        for operation in self.operations:
            if len(set(operation.depends_on)) != len(operation.depends_on):
                raise ValueError("工序依赖不能重复")
            if any(key not in keys for key in operation.depends_on):
                raise ValueError("工序依赖须引用本配置中的真实工序")
            if len(set(operation.bom_line_keys)) != len(operation.bom_line_keys):
                raise ValueError("工序关联的BOM行不能重复")
        remaining = set(keys)
        while remaining:
            next_keys = {
                operation.key
                for operation in self.operations
                if operation.key in remaining and not remaining.intersection(operation.depends_on)
            }
            if not next_keys:
                raise ValueError("工序依赖存在循环")
            remaining -= next_keys
        return self
