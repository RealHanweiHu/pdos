"""Closed, immutable inputs. Identity, authority and source verdicts are server ports."""

from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator, model_validator

from pdos_next.schema_base import StrictModel
from pdos_next.schemas.products.definitions import DefinitionDraftPayload


class DTO(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)


class Location(DTO):
    kind: Literal["line", "page", "cell"]
    line: int | None = Field(default=None, ge=1)
    page: int | None = Field(default=None, ge=1)
    sheet: str | None = Field(default=None, min_length=1, max_length=200)
    cell: str | None = Field(default=None, pattern=r"^[A-Z]+[1-9][0-9]*$")

    @model_validator(mode="after")
    def precise(self) -> Self:
        fields = {k for k in ("line", "page", "sheet", "cell") if getattr(self, k) is not None}
        if fields != {"line": {"line"}, "page": {"page"}, "cell": {"sheet", "cell"}}[self.kind]:
            raise ValueError("位置必须为一种完整的行、页或单元格")
        return self


class Citation(DTO):
    artifact_id: UUID
    expected_revision: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    derived_line: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=4000)
    original_id: UUID | None = None
    original_version: str | None = Field(default=None, min_length=1, max_length=200)
    original_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    location: Location

    @model_validator(mode="after")
    def original(self) -> Self:
        original = (self.original_id, self.original_version, self.original_hash)
        if any(v is not None for v in original) and not all(v is not None for v in original):
            raise ValueError("原件身份、版本和摘要须一起固定")
        if self.original_id is None and (
            self.location.kind != "line" or self.location.line != self.derived_line
        ):
            raise ValueError("非行位置必须有不可变原件及映射")
        return self


class SpecValue(DTO):
    parameter: str = Field(min_length=1, max_length=200)
    value_type: Literal["number", "range", "text"]
    value: Decimal | None = None
    lower: Decimal | None = None
    upper: Decimal | None = None
    text: str | None = Field(default=None, min_length=1, max_length=2000)
    unit: str | None = Field(default=None, min_length=1, max_length=80)
    tolerance: Decimal | None = None
    method: str | None = Field(default=None, min_length=1, max_length=2000)
    test_conditions: tuple[str, ...] = Field(default=(), max_length=30)
    applicability: str | None = Field(default=None, min_length=1, max_length=2000)
    acceptance_criterion: str | None = Field(default=None, min_length=1, max_length=2000)

    @field_validator("value", "lower", "upper", "tolerance")
    @classmethod
    def finite(cls, value):
        if value is not None and (
            not value.is_finite()
            or abs(value) >= Decimal("1e26")
            or value.as_tuple().exponent < -12
        ):
            raise ValueError("数值须有限且在定义支持的精度内")
        return value

    @field_validator("test_conditions")
    @classmethod
    def conditions(cls, values):
        if any(not v.strip() or len(v) > 1000 for v in values) or len(set(values)) != len(values):
            raise ValueError("条件须非空且不重复")
        return values

    @model_validator(mode="after")
    def values(self) -> Self:
        allowed = {"number": {"value"}, "range": {"lower", "upper"}, "text": {"text"}}
        if any(
            getattr(self, k) is not None
            for k in {"value", "lower", "upper", "text"} - allowed[self.value_type]
        ):
            raise ValueError("值类型与值字段不一致")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError("上下限无序")
        if self.tolerance is not None and (self.tolerance < 0 or self.value_type == "text"):
            raise ValueError("允差须非负且只适用于数值")
        return self


class Observation(DTO):
    id: UUID
    key: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    kind: Literal["spec", "requirement", "constraint", "note"]
    origin: Literal["human_observation", "ai_extraction", "translation", "customer_input"]
    raw_text: str = Field(min_length=1, max_length=4000)
    statement: str = Field(min_length=1, max_length=2000)
    spec: SpecValue | None = None
    sources: tuple[Citation, ...] = Field(min_length=1, max_length=20)
    accepted_requirement_id: UUID | None = None

    @model_validator(mode="after")
    def shape(self) -> Self:
        if (self.kind == "spec") != (self.spec is not None):
            raise ValueError("规格观察必须有专用值，其他观察不能携带规格")
        if self.accepted_requirement_id is not None and self.kind != "requirement":
            raise ValueError("已接受需求引用仅适用于需求")
        if len({c.model_dump_json() for c in self.sources}) != len(self.sources):
            raise ValueError("观察引用重复")
        return self


class PackageItem(DTO):
    category: str = Field(min_length=1, max_length=80)
    source: Citation


class ResearchStart(DTO):
    title: str = Field(min_length=2, max_length=200)
    mode: Literal["research", "oem"]
    questions: tuple[str, ...] = Field(min_length=1, max_length=30)
    use_cases: tuple[str, ...] = Field(min_length=1, max_length=50)


class ImportBatch(DTO):
    items: tuple[PackageItem, ...] = Field(min_length=1, max_length=20)
    observations: tuple[Observation, ...] = Field(default=(), max_length=100)


class Selection(DTO):
    key: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    observation_id: UUID | None = None
    reason: str = Field(min_length=3, max_length=2000)


class CandidateRequest(DTO):
    title: str = Field(min_length=2, max_length=200)
    selections: tuple[Selection, ...] = Field(min_length=1, max_length=100)
    partial_reason: str | None = Field(default=None, min_length=3, max_length=2000)
    parent_definition_id: UUID | None = None
    expected_parent_revision: int | None = Field(default=None, ge=1)
    change_reason: str = Field(min_length=3, max_length=2000)


class Verification(DTO):
    status: Literal["verified", "pending"]
    reason: str = Field(min_length=1, max_length=2000)
    accepted_requirement: bool = False


class StoredObservation(DTO):
    observation: Observation
    verification: Verification


class Research(DTO):
    id: UUID
    tenant_id: UUID
    owner_id: UUID
    audience: Literal["private", "category", "audience"]
    scope_id: UUID
    revision: int = Field(ge=1)
    title: str
    mode: Literal["research", "oem"]
    questions: tuple[str, ...]
    use_cases: tuple[str, ...]
    items: tuple[PackageItem, ...] = ()
    observations: tuple[StoredObservation, ...] = ()


class Conflict(DTO):
    key: str
    observation_ids: tuple[UUID, ...]
    reasons: tuple[str, ...]


class Provenance(DTO):
    key: str
    observations: tuple[StoredObservation, ...]
    selected_id: UUID | None
    actor_id: UUID
    reason: str
    maturity: Literal["candidate", "accepted_requirement"]


class DefinitionCandidate(DTO):
    research_id: UUID
    research_revision: int
    product_id: UUID
    expected_product_revision: int
    payload: DefinitionDraftPayload
    provenance: tuple[Provenance, ...]
    conflicts: tuple[Conflict, ...]
    missing_categories: tuple[str, ...]
    omitted_keys: tuple[str, ...]
    digest: str
    effect: str = "仅形成内部定义草稿；不发布规格、不创建项目、不表示客户批准"
