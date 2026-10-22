"""Closed manufacturing DTOs. Payloads carry references, never authority or inventory."""

from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from pdos_next.schemas.verification.contracts import (
    DTO,
    EventTime,
    RequestCreate,
    Scope,
    SourceRef,
    TimeFact,
)

Key = Annotated[str, Field(min_length=1, max_length=120)]
Text = Annotated[str, Field(min_length=1, max_length=2000)]
Count = Annotated[int, Field(strict=True, ge=0, le=10**12)]
Revision = Annotated[int, Field(strict=True, ge=1)]
Kind = Literal[
    "build",
    "build_lot",
    "actual_configuration",
    "engineering_configuration",
    "process_revision",
    "manufacturing_baseline",
    "tooling",
    "fixture",
    "equipment",
    "line",
    "person",
    "material_lot",
    "work_instruction",
    "control_plan",
    "risk",
    "first_article",
    "issue",
    "corrective_action",
    "named_acceptance",
    "sample",
    "criterion",
    "reservation",
    "qualification",
]


class Ref(DTO):
    kind: Kind
    id: UUID
    revision: Revision


class Parameter(DTO):
    key: Key
    value: Decimal | None
    unit: Key | None
    source: SourceRef | None

    @model_validator(mode="after")
    def sourced_value(self) -> Self:
        if self.value is not None and (
            not self.value.is_finite() or not self.source or not self.unit
        ):
            raise ValueError("参数值必须有限且有单位和来源")
        return self


class Gap(DTO):
    code: Key
    detail: Text
    state: Literal["blocked", "unknown", "conflicted"]
    owner_role: Key


class Readiness(DTO):
    state: Literal["BLOCKED", "UNKNOWN", "READY"]
    gaps: tuple[Gap, ...]
    # Even READY is only preparation, never a named manufacturing/start decision.
    start_authorized: Literal[False] = False


class LotBasis(DTO):
    build: Ref
    lot: Ref
    actual_configuration: Ref
    engineering_configuration: Ref
    process_revision: Ref
    unit: Key

    @model_validator(mode="after")
    def kinds(self) -> Self:
        for field, kind in (
            ("build", "build"),
            ("lot", "build_lot"),
            ("actual_configuration", "actual_configuration"),
            ("engineering_configuration", "engineering_configuration"),
            ("process_revision", "process_revision"),
        ):
            if getattr(self, field).kind != kind:
                raise ValueError(f"{field}引用类型不相容")
        return self


class PilotCreate(DTO):
    pilot_id: UUID
    basis: LotBasis
    purpose: Text
    manufacturing_baseline: Ref | None = None
    line: Ref | None = None
    people: tuple[Ref, ...] = ()
    material_lots: tuple[Ref, ...] = ()
    fixtures: tuple[Ref, ...] = ()
    equipment: tuple[Ref, ...] = ()
    instructions: tuple[Ref, ...] = ()
    control_plan: Ref | None = None
    risk: Ref | None = None
    reservation: Ref | None = None
    first_article: Ref | None = None
    parameters: tuple[Parameter, ...] = ()
    source: SourceRef

    @model_validator(mode="after")
    def references(self) -> Self:
        fields = {
            "manufacturing_baseline": "manufacturing_baseline",
            "line": "line",
            "people": "person",
            "material_lots": "material_lot",
            "fixtures": "fixture",
            "equipment": "equipment",
            "instructions": "work_instruction",
            "control_plan": "control_plan",
            "risk": "risk",
            "reservation": "reservation",
            "first_article": "first_article",
        }
        for field, kind in fields.items():
            value = getattr(self, field)
            values = value if isinstance(value, tuple) else (() if value is None else (value,))
            if any(v.kind != kind for v in values) or len(set(values)) != len(values):
                raise ValueError(f"{field}引用类型不相容或重复")
        if len({p.key for p in self.parameters}) != len(self.parameters):
            raise ValueError("参数key重复")
        return self


class ToolTrialCreate(DTO):
    trial_id: UUID
    build: Ref
    tooling: Ref
    trial_round: Count
    purpose: Text
    cavities: tuple[Key, ...] = Field(min_length=1)
    material_lots: tuple[Ref, ...] = ()
    parameters: tuple[Parameter, ...] = ()
    issues: tuple[Ref, ...] = ()
    corrective_actions: tuple[Ref, ...] = ()
    named_acceptances: tuple[Ref, ...] = ()
    verification: RequestCreate
    source: SourceRef

    @model_validator(mode="after")
    def references(self) -> Self:
        if self.build.kind != "build" or self.tooling.kind != "tooling":
            raise ValueError("试模必须固定Build/Tooling引用")
        for values, kind in (
            (self.material_lots, "material_lot"),
            (self.issues, "issue"),
            (self.corrective_actions, "corrective_action"),
            (self.named_acceptances, "named_acceptance"),
        ):
            if any(v.kind != kind for v in values) or len(set(values)) != len(values):
                raise ValueError("引用类型不相容或重复")
        if len(set(self.cavities)) != len(self.cavities):
            raise ValueError("模穴不能重复")
        if len({p.key for p in self.parameters}) != len(self.parameters):
            raise ValueError("参数key重复")
        if (
            self.verification.build_id != self.build.id
            or self.verification.expected_build_revision != self.build.revision
        ):
            raise ValueError("品质请求必须固定相同Build")
        return self


class YieldScope(DTO):
    basis: LotBasis
    manufacturing_baseline: Ref | None
    line: Ref | None
    cohort_key: Key
    window_start: AwareDatetime
    window_end: AwareDatetime
    criterion: Ref
    nature: Literal["real", "synthetic"]
    minimum_sample: Revision

    @model_validator(mode="after")
    def bounds(self) -> Self:
        if self.window_end < self.window_start or self.criterion.kind != "criterion":
            raise ValueError("窗口或判据引用不有效")
        if (
            self.manufacturing_baseline
            and self.manufacturing_baseline.kind != "manufacturing_baseline"
        ):
            raise ValueError("不能将工艺草稿冒充制造基线")
        if self.line and self.line.kind != "line":
            raise ValueError("线体引用不有效")
        return self


class Counts(DTO):
    """Cumulative unique units, not events. Output excludes unprocessed inputs only."""

    input_count: Count | None
    output_count: Count | None
    first_pass: Count | None
    first_failed: Count | None
    first_unknown: Count | None
    final_good: Count | None
    reworked_good: Count | None
    scrap: Count | None
    rework_pending: Count | None
    undecided: Count | None
    unprocessed: Count | None
    rework_cycles: Count | None  # informational; NEVER an additional input


class UnitOutcome(DTO):
    sample: Ref
    first_result: Literal["pass", "fail", "unknown", "unprocessed"]
    final_state: Literal["good", "scrap", "rework_pending", "undecided", "unprocessed"]
    rework_cycles: Count
    source: SourceRef

    @model_validator(mode="after")
    def sample_kind(self) -> Self:
        if self.sample.kind != "sample":
            raise ValueError("必须引用已有SampleUnit")
        if (self.first_result == "unprocessed") != (self.final_state == "unprocessed"):
            raise ValueError("未加工必须在两种口径一致")
        if self.final_state == "unprocessed" and self.rework_cycles:
            raise ValueError("未加工不能有返工次数")
        if self.first_result == "pass" and (self.final_state != "good" or self.rework_cycles):
            raise ValueError("首遍通过不得重复返工统计")
        if self.first_result == "fail" and self.final_state == "good" and not self.rework_cycles:
            raise ValueError("首遍失败后合格须有返工来源")
        return self


class ExceptionFact(DTO):
    key: Key
    description: Text
    source: SourceRef
    issue: Ref | None = None
    disposition: SourceRef | None = None

    @model_validator(mode="after")
    def issue_kind(self) -> Self:
        if self.issue and self.issue.kind != "issue":
            raise ValueError("异常必须引用Issue")
        return self


class ResultRecord(DTO):
    observation_id: UUID
    expected_pilot_revision: Revision
    previous_observation_id: UUID | None = None
    correction_reason: Text | None = None
    scope: YieldScope
    counts: Counts | None = None
    units: tuple[UnitOutcome, ...] = Field(default=())
    exceptions: tuple[ExceptionFact, ...] = Field(default=())
    observed: EventTime
    source: SourceRef

    @model_validator(mode="after")
    def representation(self) -> Self:
        if (self.counts is None) == (not self.units):
            raise ValueError("逐件与批次口径须且仅须选择一种")
        if bool(self.previous_observation_id) != bool(self.correction_reason):
            raise ValueError("修正续版须含前版与原因")
        if len({u.sample.id for u in self.units}) != len(self.units):
            raise ValueError("同一实际单件不能重复计入")
        if len({e.key for e in self.exceptions}) != len(self.exceptions):
            raise ValueError("异常key不能重复")
        if not self.scope.window_start <= self.observed.occurred_at <= self.scope.window_end:
            raise ValueError("观察发生时间须在固定统计窗口内")
        return self


class YieldResult(DTO):
    counts: Counts
    first_pass_yield: Decimal | None
    final_good_yield: Decimal | None
    warnings: tuple[Key, ...]
    process_capability: Literal["NOT_ASSESSED"] = "NOT_ASSESSED"
    factory_qualification: Literal["NOT_ASSESSED"] = "NOT_ASSESSED"


class ToolTrial(DTO):
    id: UUID
    revision: Revision = 1
    scope: Scope
    details: ToolTrialCreate
    readiness: Readiness
    writer_id: UUID
    received_at: AwareDatetime
    write_tier: Literal["T1"] = "T1"


class PilotRun(DTO):
    id: UUID
    revision: Revision = 1
    scope: Scope
    details: PilotCreate
    readiness: Readiness
    latest_observation_id: UUID | None = None
    writer_id: UUID
    received_at: AwareDatetime
    write_tier: Literal["T1"] = "T1"


class Observation(DTO):
    id: UUID
    pilot_id: UUID
    revision: Revision
    details: ResultRecord
    time: TimeFact
    result: YieldResult
