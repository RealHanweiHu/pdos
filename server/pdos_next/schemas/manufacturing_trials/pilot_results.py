"""Isolated mathematical DTOs. Parsing is never owner, qualification or release proof."""

from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from pdos_next.schemas.manufacturing_trials.contracts import (
    DTO,
    Count,
    Counts,
    Ref,
    ResultRecord,
    Revision,
    YieldScope,
)
from pdos_next.schemas.verification.contracts import Scope, SourceRef

Text = Annotated[str, Field(min_length=1, max_length=2000)]


class FixedCohort(DTO):
    """Actual owner-fixed input membership, not rework events or output denominator."""

    population_count: Count | None
    fixed_input_count: Count | None
    mode: Literal["entire_lot", "fixed_sampled_subset"]
    denominator_policy: Literal["all_fixed_input_units"] = "all_fixed_input_units"
    statistics_basis_key: Text
    unit_refs: tuple[Ref, ...] | None = Field()
    source: SourceRef

    @model_validator(mode="after")
    def membership(self) -> Self:
        if self.population_count is not None and self.fixed_input_count is not None:
            if self.fixed_input_count > self.population_count:
                raise ValueError("固定投入不得超过实际母批范围")
            if self.mode == "entire_lot" and self.fixed_input_count != self.population_count:
                raise ValueError("全批口径必须固定同一母批投入")
        if self.unit_refs is not None:
            if any(ref.kind != "sample" for ref in self.unit_refs):
                raise ValueError("单件成员必须是真实Sample引用")
            if len({ref.id for ref in self.unit_refs}) != len(self.unit_refs):
                raise ValueError("单件及其续版不能重复计入")
            if self.fixed_input_count is not None and len(self.unit_refs) != self.fixed_input_count:
                raise ValueError("实际成员全集必须等于固定投入分母")
        return self


class FixedPilotScope(DTO):
    schema_version: Literal["pdos-pilot-result-scope-v1"] = "pdos-pilot-result-scope-v1"
    scope: Scope
    pilot_id: UUID
    pilot_revision: Revision
    purpose: Text
    site: Text
    original_timezone: Text
    yield_scope: YieldScope
    cohort: FixedCohort

    @field_validator("original_timezone")
    @classmethod
    def timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError("统计窗口必须保留真实IANA时区") from error
        return value

    @model_validator(mode="after")
    def full_scope(self) -> Self:
        if self.yield_scope.manufacturing_baseline is None or self.yield_scope.line is None:
            raise ValueError("缺真实制造基线或产线的结果不能变成完整统计范围")
        if self.yield_scope.window_end <= self.yield_scope.window_start:
            raise ValueError("统计窗口须为正区间")
        return self


class RecordedBatch(DTO):
    fixed: FixedPilotScope
    record: ResultRecord

    @model_validator(mode="after")
    def scope_binding(self) -> Self:
        if self.record.scope != self.fixed.yield_scope:
            raise ValueError("原结果与服务器固定统计范围必须精确一致")
        if self.record.expected_pilot_revision != self.fixed.pilot_revision:
            raise ValueError("原结果CAS与固定Pilot版本不一致")
        if self.record.units:
            if self.fixed.cohort.unit_refs is None:
                raise ValueError("逐件口径须有实际固定成员全集")
            if {unit.sample for unit in self.record.units} != set(self.fixed.cohort.unit_refs):
                raise ValueError("逐件记录不得遗漏、替换或增加固定成员")
        return self


class Rate(DTO):
    numerator: Count | None
    denominator: Count | None
    value: Decimal | None
    recorded_fraction: Decimal | None
    partition_complete: bool
    state: Literal["known", "partial", "unknown", "undefined_zero_denominator"]


class Metrics(DTO):
    first_pass_yield: Rate
    final_good_yield: Rate
    warnings: tuple[str, ...]
    process_capability: Literal["NOT_ASSESSED"] = "NOT_ASSESSED"
    factory_qualification: Literal["NOT_ASSESSED"] = "NOT_ASSESSED"
    start_authorized: Literal[False] = False
    manufacturing_release: None = None
    external_delivery_authorized: Literal[False] = False


class PilotProjection(DTO):
    schema_version: Literal["pdos-pilot-result-projection-v1"] = "pdos-pilot-result-projection-v1"
    fixed: FixedPilotScope
    counts: Counts
    metrics: Metrics
    observation_id: UUID
    # Actual received_at remains a caller-host TimeFact, not a pure generated clock.
    received_at: None = None


class AggregateProjection(DTO):
    schema_version: Literal["pdos-pilot-result-aggregate-v1"] = "pdos-pilot-result-aggregate-v1"
    members: tuple[FixedPilotScope, ...]
    counts: Counts
    metrics: Metrics
    percentage_averaging_used: Literal[False] = False
