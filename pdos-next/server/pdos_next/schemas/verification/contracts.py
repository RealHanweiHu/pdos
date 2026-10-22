"""Verification DTOs only; no ORM registration or authorization from payloads."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


Text = Annotated[str, Field(min_length=1, max_length=2000)]
Key = Annotated[str, Field(min_length=1, max_length=120)]
Revision = Annotated[int, Field(ge=1)]


class ConfigurationRef(DTO):
    id: UUID
    revision: Revision


class BuildRef(DTO):
    id: UUID
    revision: Revision
    product_id: UUID
    project_id: UUID
    engineering_configuration: ConfigurationRef
    manufacturing_configuration: ConfigurationRef


class SourceRef(DTO):
    id: UUID
    revision: Revision
    kind: Literal["artifact", "domain", "command"] = "artifact"
    position: Text


class SampleRef(DTO):
    id: UUID
    revision: Revision
    build_id: UUID
    actual_configuration: ConfigurationRef
    cavity: Key | None = None


class Scope(DTO):
    tenant_id: UUID
    product_id: UUID
    project_id: UUID


class EventTime(DTO):
    occurred_at: datetime
    original_timezone: Key
    source: SourceRef
    effective_at: datetime | None = None

    @field_validator("occurred_at", "effective_at")
    @classmethod
    def aware(cls, value):
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("时间必须含时区")
            return value.astimezone(UTC)
        return value

    @field_validator("original_timezone")
    @classmethod
    def timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("保留有效 IANA 时区") from exc
        return value


class TimeFact(EventTime):
    received_at: datetime
    actor_id: UUID

    @field_validator("received_at")
    @classmethod
    def received(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("接收时间必须含时区")
        return value.astimezone(UTC)


class Timeline(DTO):
    request_created: TimeFact
    sample_ready: TimeFact | None = None
    documents_complete: TimeFact | None = None
    offered: TimeFact | None = None
    accepted: TimeFact | None = None
    promised_start: TimeFact | None = None
    actual_start: TimeFact | None = None
    preliminary_result: TimeFact | None = None
    final_result: TimeFact | None = None
    disposed: TimeFact | None = None


class NumericCriterion(DTO):
    lower: Decimal | None = None
    upper: Decimal | None = None
    source: SourceRef

    @model_validator(mode="after")
    def bounds(self) -> Self:
        if self.lower is None and self.upper is None:
            raise ValueError("判据至少包含一个界限")
        if any(x is not None and not x.is_finite() for x in (self.lower, self.upper)):
            raise ValueError("判据必须为有限数值")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError("判据上限不得小于下限")
        return self


class TestItem(DTO):
    id: Key
    feature: Text
    drawing: SourceRef | None = None
    method: SourceRef | None = None
    criterion: NumericCriterion | None = None
    criterion_text: Text | None = None
    criterion_source: SourceRef | None = None
    unit: Key | None = None
    conditions: Text | None = None
    material: Text | None = None
    sample_count: int = Field(ge=1)
    cavities: tuple[Key, ...] = ()
    destructive: bool = False

    @field_validator("cavities")
    @classmethod
    def unique_cavities(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("模穴范围不能重复")
        return value


class DocumentRequirement(DTO):
    id: Key
    title: Text
    item_ids: tuple[Key, ...] = Field(min_length=1)
    source: SourceRef | None = None
    required: bool = True


class Coverage(DTO):
    sample_id: UUID
    item_id: Key


class Gap(DTO):
    code: Key
    detail: Text
    item_id: Key | None = None
    sample_id: UUID | None = None


class ReturnedScope(DTO):
    coverage: tuple[Coverage, ...]
    gaps: tuple[Gap, ...]
    reason: Text
    next_owner_id: UUID
    actor_id: UUID
    at: TimeFact


class Acceptance(DTO):
    coverage: tuple[Coverage, ...] = Field(min_length=1)
    actor_id: UUID
    at: TimeFact
    sample_ready: TimeFact | None = None


RequestState = Literal[
    "draft", "offered", "accepted", "scheduled", "executing", "reported", "disposed"
]
RunState = Literal["planned", "running", "results_pending", "reviewed", "disposed"]
Result = Literal["pending", "pass", "fail", "indeterminate", "invalid"]


class VerificationRequest(DTO):
    id: UUID
    revision: Revision
    scope: Scope
    build: BuildRef
    title: Text
    purpose: Text
    items: tuple[TestItem, ...] = Field(min_length=1)
    documents: tuple[DocumentRequirement, ...] = ()
    expected_at: datetime | None = None
    expected_timezone: Key | None = None
    return_form: Text
    status: RequestState = "draft"
    samples: tuple[SampleRef, ...] = ()
    offered_coverage: tuple[Coverage, ...] = ()
    acceptances: tuple[Acceptance, ...] = ()
    returns: tuple[ReturnedScope, ...] = ()
    timeline: Timeline
    tentative_start: EventTime | None = None

    @field_validator("expected_at")
    @classmethod
    def expected(cls, value):
        return EventTime.aware(value)

    @field_validator("expected_timezone")
    @classmethod
    def expected_zone(cls, value):
        return EventTime.timezone(value) if value is not None else None

    @model_validator(mode="after")
    def identity(self) -> Self:
        if self.expected_at is not None and self.expected_timezone is None:
            raise ValueError("预期时点必须保留原 IANA 时区")
        keys = {i.id for i in self.items}
        if len(keys) != len(self.items):
            raise ValueError("测试项 ID 不能重复")
        if len({d.id for d in self.documents}) != len(self.documents):
            raise ValueError("资料 ID 不能重复")
        if any(not set(d.item_ids) <= keys for d in self.documents):
            raise ValueError("资料适用范围必须在测试项内")
        return self


class ExecutionConditions(DTO):
    equipment: SourceRef
    calibration: SourceRef
    environment: Text
    conditions: Text
    executor_id: UUID


class Measurement(DTO):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)
    id: UUID
    coverage: Coverage
    raw_value: Annotated[str | None, Field(max_length=4000)] = None
    unit: Key | None = None
    conditions: Text | None = None
    equipment: SourceRef | None = None
    equipment_label: Text | None = None
    environment: Text | None = None
    method: SourceRef | None = None
    source: SourceRef | None = None
    missing: tuple[Text, ...] = ()
    note: Text | None = None
    observed_at: datetime | None = None
    observed_timezone: Key | None = None

    @field_validator("unit", "conditions", "environment")
    @classmethod
    def meaningful(cls, value):
        if value is not None and not value.strip():
            raise ValueError("缺项应保留为空，不可用空白冒充条件")
        return value

    @field_validator("observed_at")
    @classmethod
    def observed(cls, value):
        return EventTime.aware(value)

    @field_validator("observed_timezone")
    @classmethod
    def observation_timezone(cls, value):
        return EventTime.timezone(value) if value is not None else None


class ComputedResult(DTO):
    coverage: Coverage
    result: Result
    measurement_id: UUID | None = None
    reasons: tuple[Text, ...] = ()


class ProfessionalConclusion(DTO):
    text: Text
    actor_id: UUID
    source: SourceRef
    at: TimeFact


class PartialResultsReturn(DTO):
    returned_coverage: tuple[Coverage, ...]
    pending_coverage: tuple[Coverage, ...]
    reason: Text | None = None
    next_owner_id: UUID | None = None
    at: TimeFact


class TestRun(DTO):
    id: UUID
    revision: Revision
    scope: Scope
    request_id: UUID
    request_revision: Revision
    build: BuildRef
    items: tuple[TestItem, ...]
    samples: tuple[SampleRef, ...] = Field(min_length=1)
    coverage: tuple[Coverage, ...] = Field(min_length=1)
    status: RunState = "planned"
    result: Result = "pending"
    execution: ExecutionConditions | None = None
    actual_start: TimeFact | None = None
    actual_end: TimeFact | None = None
    preliminary_result: TimeFact | None = None
    final_result: TimeFact | None = None
    measurements: tuple[Measurement, ...] = ()
    computed_results: tuple[ComputedResult, ...] = ()
    partial_returns: tuple[PartialResultsReturn, ...] = ()
    professional_conclusion: ProfessionalConclusion | None = None
    disposition: ProfessionalConclusion | None = None


class RequestCreate(DTO):
    request_id: UUID
    build_id: UUID
    expected_build_revision: Revision
    title: Text
    purpose: Text
    items: tuple[TestItem, ...] = Field(min_length=1)
    documents: tuple[DocumentRequirement, ...] = ()
    expected_at: datetime | None = None
    expected_timezone: Key | None = None
    return_form: Text

    @field_validator("expected_at")
    @classmethod
    def expected(cls, value):
        return EventTime.aware(value)

    @field_validator("expected_timezone")
    @classmethod
    def expected_zone(cls, value):
        return EventTime.timezone(value) if value is not None else None

    @model_validator(mode="after")
    def expected_pair(self) -> Self:
        if self.expected_at is not None and self.expected_timezone is None:
            raise ValueError("预期时点必须保留原 IANA 时区")
        return self


class MethodPrepare(DTO):
    items: tuple[TestItem, ...] = Field(min_length=1)
    documents: tuple[DocumentRequirement, ...] = ()
    tentative_start: EventTime | None = None


class HandoffOffer(DTO):
    samples: tuple[SampleRef, ...] = Field(min_length=1)
    coverage: tuple[Coverage, ...] = Field(min_length=1)
    at: EventTime


class HandoffAccept(DTO):
    coverage: tuple[Coverage, ...] = Field(min_length=1)
    returned_coverage: tuple[Coverage, ...] = ()
    reason: Text | None = None
    next_owner_id: UUID | None = None
    at: EventTime


class HandoffReturn(DTO):
    coverage: tuple[Coverage, ...] = Field(min_length=1)
    reason: Text
    next_owner_id: UUID
    at: EventTime


class SchedulePromise(DTO):
    run_id: UUID
    expected_run_revision: int = Field(ge=1)
    at: EventTime


class ScheduleProposal(DTO):
    at: EventTime


class RunPlan(DTO):
    run_id: UUID
    coverage: tuple[Coverage, ...] = Field(min_length=1)


class RunStart(DTO):
    at: EventTime
    execution: ExecutionConditions


class ResultsSubmit(DTO):
    measurements: tuple[Measurement, ...] = Field()
    at: EventTime
    final: bool = False
    actual_end: EventTime | None = None
    incomplete_reason: Text | None = None
    next_owner_id: UUID | None = None

    @model_validator(mode="after")
    def nonempty_partial(self) -> Self:
        if not self.final and not self.measurements:
            raise ValueError("部分返回需要新增测量；最终返回可以仅确认既有完整范围")
        if (self.incomplete_reason is None) != (self.next_owner_id is None):
            raise ValueError("未完成原因与下一责任人须一起提供")
        if self.final and (self.incomplete_reason is not None or self.next_owner_id is not None):
            raise ValueError("最终返回不能暗中建立新的未完成责任")
        return self


class RunReview(DTO):
    text: Text
    at: EventTime


class RunDisposition(DTO):
    text: Text
    at: EventTime
