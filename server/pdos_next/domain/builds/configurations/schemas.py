from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from pdos_next.domain.manufacturing.supply_cost.engine.common import Loss, Positive


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


# A reference designator such as R12, C3, U1A or J2.1; separators are never part of one.
DESIGNATOR_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.+/#-]*$"
Designator = Annotated[str, Field(min_length=1, max_length=40, pattern=DESIGNATOR_PATTERN)]


class BomAlternateInput(StrictModel):
    """A declared alternate: an existing part of this product at a fixed version.

    The declaration grants nothing; only a Build-level `supply.alternate.approve`
    lets the kit count it (P113, P96, AT-21).
    """

    part_id: UUID
    expected_part_revision: int = Field(ge=1)


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
    # Source order is kept; repeated designators are reported by the rule card, not refused.
    reference_designators: list[Designator] = Field(default_factory=list, max_length=2000)
    # Declared alternates in priority order (P113); not a qualification.
    alternates: list[BomAlternateInput] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def explicit_part_and_quantity(self) -> Self:
        if self.part_id is None:
            if self.part is None or self.expected_part_revision is not None:
                raise ValueError("新物料须提供身份资料，不能捏造固定物料版本")
        elif self.part is not None or self.expected_part_revision is None:
            raise ValueError("复用物料须固定ID与版本，不同时改写物料身份")
        if self.quantity is not None and self.unit is None:
            raise ValueError("已知BOM数量须明确单位，未知数量保持null")
        alternates = [alternate.part_id for alternate in self.alternates]
        if len(set(alternates)) != len(alternates) or self.part_id in alternates:
            raise ValueError("替代料不能重复，也不能是本行物料自己")
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


BomImportField = Literal[
    "key",
    "internal_number",
    "name",
    "erp_number",
    "customer_number",
    "quantity",
    "unit",
    "loss_rate",
    "critical",
    "notes",
    "reference_designators",
    "alternates",
]


class BomImportColumn(StrictModel):
    field: BomImportField
    column: int = Field(ge=1, le=1000)


class BomImportDisposition(StrictModel):
    """A named decision for one original row the conversion could not take as is."""

    row: int = Field(ge=1, le=100_000)
    # accept: take the row as converted; new_part/reuse: settle its part identity.
    action: Literal["skip", "accept", "new_part", "reuse"]
    part_id: UUID | None = None
    expected_part_revision: int | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, min_length=1, max_length=500)
    # Import the row without the alternates that match no usable existing part.
    drop_unresolved_alternates: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def reuse_names_part(self) -> Self:
        if (self.action == "reuse") != (self.part_id is not None):
            raise ValueError("关联已有物料须固定物料ID与版本；其他处置不带物料")
        if (self.part_id is None) != (self.expected_part_revision is None):
            raise ValueError("关联已有物料须同时固定ID与版本")
        return self


class BomImportBasis(StrictModel):
    """Which parsed original, sheet, header row and column mapping produce the lines.

    The server converts again from this basis and refuses lines that differ, so
    the conversion is the code's, not the caller's (P79 D98).
    """

    artifact_id: UUID
    expected_revision: int = Field(ge=1)
    format: Literal["xlsx", "csv"]
    sheet: str | None = Field(default=None, min_length=1, max_length=200)
    header_row: int = Field(ge=1, le=100_000)
    columns: list[BomImportColumn] = Field(min_length=1, max_length=12)
    dispositions: list[BomImportDisposition] = Field(default_factory=list, max_length=10_000)

    @model_validator(mode="after")
    def coherent_basis(self) -> Self:
        if (self.format == "xlsx") != (self.sheet is not None):
            raise ValueError("XLSX 导入须指定工作表；CSV 没有工作表")
        if len({c.field for c in self.columns}) != len(self.columns):
            raise ValueError("同一 BOM 字段只能映射一列")
        if len({c.column for c in self.columns}) != len(self.columns):
            raise ValueError("同一列只能映射一个 BOM 字段")
        if not {c.field for c in self.columns} & {"internal_number", "name", "erp_number"}:
            raise ValueError("须至少映射物料编号或名称中的一列")
        rows = [d.row for d in self.dispositions]
        if len(set(rows)) != len(rows):
            raise ValueError("每个原件行只能有一个处置")
        if any(row <= self.header_row for row in rows):
            raise ValueError("处置只针对表头之后的数据行")
        return self


class EngineeringBomRevisePayload(_RevisionPayload):
    lines: list[BomLineInput] = Field(min_length=1)
    import_basis: BomImportBasis | None = None

    @model_validator(mode="after")
    def unique_lines(self) -> Self:
        if len({line.key for line in self.lines}) != len(self.lines):
            raise ValueError("BOM行标识不能重复")
        return self


class BomImportRequest(StrictModel):
    """READ request: convert one parsed original for review (not a command)."""

    artifact_id: UUID
    expected_revision: int = Field(ge=1)
    sheet: str | None = Field(default=None, min_length=1, max_length=200)
    header_row: int | None = Field(default=None, ge=1, le=100_000)
    # None asks for the deterministic header suggestion.
    columns: list[BomImportColumn] | None = Field(default=None, max_length=12)
    dispositions: list[BomImportDisposition] = Field(default_factory=list, max_length=10_000)
    previous_id: UUID | None = None
    expected_previous_revision: int | None = Field(default=None, ge=1)
    visibility: Literal["private", "category", "audience"] = "private"

    @model_validator(mode="after")
    def exact_previous(self) -> Self:
        if (self.previous_id is None) != (self.expected_previous_revision is None):
            raise ValueError("固定旧版ID和版本须同时提供；初版均为null")
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
