"""Typed, source-bound preparation payloads, not qualifications or occurrence facts."""

from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Kind = Literal["work_instruction", "control_plan", "manufacturing_baseline"]
Revision = Annotated[int, Field(strict=True, ge=1)]
Key = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")]
Text = Annotated[str, Field(min_length=1, max_length=2000)]


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="after")
    def exact_reference_collection(self):
        sources = getattr(self, "sources", ())
        if len(set(sources)) != len(sources):
            raise ValueError("同一字段的精确出处不能重复")
        return self


class Source(Closed):
    artifact_id: UUID
    expected_revision: Revision
    line: Revision
    quote: Annotated[str, Field(min_length=1, max_length=4000)]

    @field_validator("quote")
    @classmethod
    def whole_utf8_quote(cls, value):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError("原文须为UTF-8") from error
        if "\x00" in value or "\n" in value or "\r" in value:
            raise ValueError("原文须精确一整行，不含NUL或跨行")
        return value


class ObjectRef(Closed):
    kind: Kind
    id: UUID
    revision: Revision


class ProcessRef(Closed):
    id: UUID
    revision: Revision


class Parameter(Closed):
    key: Key
    nominal: Decimal | None = None
    lower: Decimal | None = None
    upper: Decimal | None = None
    unit: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    sources: tuple[Source, ...] = Field(default=())

    @field_validator("nominal", "lower", "upper", mode="before")
    @classmethod
    def finite_decimal(cls, value):
        if value is None:
            return value
        if isinstance(value, bool) or not isinstance(value, (str, Decimal, int)):
            raise ValueError("参数必须为明确有限Decimal，不接受bool或二进制float")
        try:
            parsed = Decimal(value)
        except InvalidOperation as error:
            raise ValueError("参数不是Decimal") from error
        if (
            not parsed.is_finite()
            or len(parsed.as_tuple().digits) > 32
            or parsed.as_tuple().exponent < -12
            or parsed.adjusted() > 19
        ):
            raise ValueError("参数必须有限且不超过32位及12位小数")
        return parsed

    @model_validator(mode="after")
    def sourced_bounds(self):
        if any(v is not None for v in (self.nominal, self.lower, self.upper)):
            if self.unit is None or not self.sources:
                raise ValueError("已知声明参数必须有单位与精确出处")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError("参数上下界不能颠倒")
        return self


class InstructionStep(Closed):
    key: Key
    text: Text
    parameters: tuple[Parameter, ...] = Field(default=())
    safety_notes: Text | None = None
    sources: tuple[Source, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_parameters(self):
        if len({p.key for p in self.parameters}) != len(self.parameters):
            raise ValueError("本步骤参数key不能重复")
        return self


class ControlCheck(Closed):
    key: Key
    feature: Text
    method: Text | None = None
    criterion: Parameter | None = None
    frequency: Text | None = None
    sampling_method: Text | None = None
    reaction_plan: Text | None = None
    responsible_role: Text | None = None
    sources: tuple[Source, ...] = Field(min_length=1)


class BasePayload(Closed):
    project_id: UUID
    process: ProcessRef
    title: Annotated[str, Field(min_length=2, max_length=200)]
    previous_id: UUID | None = None
    expected_previous_revision: Revision | None = None
    visibility: Literal["private", "category", "audience"] = "private"
    reason: Text
    sources: tuple[Source, ...] = Field(min_length=1)
    confirmation_token: Annotated[str, Field(min_length=20, max_length=128)] | None = None

    @model_validator(mode="after")
    def previous_pair(self):
        if (self.previous_id is None) != (self.expected_previous_revision is None):
            raise ValueError("旧版id/revision须成对，初版均为null")
        for name, values in (("sources", self.sources),):
            if len(set(values)) != len(values):
                raise ValueError(f"{name}精确原文引用不能重复")
        return self


class InstructionPayload(BasePayload):
    operation_key: Key
    conditions: Text | None = None
    steps: tuple[InstructionStep, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_steps(self):
        if len({step.key for step in self.steps}) != len(self.steps):
            raise ValueError("步骤key不能重复")
        return self


class ControlPlanPayload(BasePayload):
    operation_key: Key
    checks: tuple[ControlCheck, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_checks(self):
        if len({check.key for check in self.checks}) != len(self.checks):
            raise ValueError("控制项key不能重复")
        return self


class OperationDocuments(Closed):
    operation_key: Key
    work_instruction: ObjectRef | None = None
    control_plan: ObjectRef | None = None

    @model_validator(mode="after")
    def exact_kinds(self):
        for key in ("work_instruction", "control_plan"):
            ref = getattr(self, key)
            if ref is not None and ref.kind != key:
                raise ValueError("工序资料引用类型须精确匹配")
        return self


class BaselinePayload(BasePayload):
    operations: tuple[OperationDocuments, ...] = Field(min_length=1)
    risk_notes: Text | None = None
    packaging_label_basis: Text | None = None

    @model_validator(mode="after")
    def unique_operations(self):
        if len({v.operation_key for v in self.operations}) != len(self.operations):
            raise ValueError("固定工序不能重复")
        return self


PAYLOADS = {
    "npi.work_instruction.record": InstructionPayload,
    "npi.control_plan.record": ControlPlanPayload,
    "npi.manufacturing_baseline.record": BaselinePayload,
}
KINDS = dict(
    zip(PAYLOADS, ("work_instruction", "control_plan", "manufacturing_baseline"), strict=True)
)


def sources_of(value):
    values = []
    if isinstance(value, Source):
        values.append(value)
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            values.extend(sources_of(getattr(value, name)))
    elif isinstance(value, tuple):
        for item in value:
            values.extend(sources_of(item))
    return tuple(dict.fromkeys(values))


class RequiredRead(Closed):
    artifact_id: UUID
    expected_revision: Revision


class PreparationView(Closed):
    schema_version: Literal["pdos-manufacturing-preparation-v1"]
    id: UUID
    kind: Kind
    revision: Revision
    series_id: UUID
    project_id: UUID
    owner_id: UUID
    visibility: Literal["private", "category", "audience"]
    title: str
    status: Literal["draft"]
    purpose: str
    process: ProcessRef
    operation_key: Key | None
    previous_id: UUID | None
    previous_revision: Revision | None
    created_at: str
    is_current: Annotated[bool, Field(strict=True)]
    source_status: Literal["current", "needs_recheck"]
    required_source_read_set: Annotated[list[RequiredRead], Field()]
    body: dict
    sources: list[Source]
    receipt_id: UUID
    manufacturing_release: None
    qualification: Literal["unknown"]
    negative_enumeration_complete: Literal[False]


class PreparationReading(Closed):
    schema_version: Literal["pdos-manufacturing-preparation-v1"]
    versions: list[PreparationView]
    history_page: dict[str, str | None] = {"next_cursor": None}
    has_more: Annotated[bool, Field(strict=True)]
    unavailable_count: Annotated[int, Field(ge=0, strict=True)]
    qualification: Literal["unknown"]
    manufacturing_release: None
    negative_enumeration_complete: Literal[False]
