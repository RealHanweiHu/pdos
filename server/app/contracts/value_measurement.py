"""Explicit study registration and participant-owned observations; no passive tracking."""

from typing import Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, model_validator

from app.contracts.common_objects import Contract, Digest, Key, Nonnegative, Text


class ExclusionRule(Contract):
    rule_id: Key
    description: Text


class StudyProtocol(Contract):
    title: str = Field(min_length=1, max_length=256)
    protocol_version: Key
    window_start: AwareDatetime
    window_end: AwareDatetime
    timezone: str = Field(min_length=1, max_length=128)
    scenario_id: Key
    role_ids: tuple[Key, ...] = Field(min_length=1, max_length=20)
    complexity_strata: tuple[Key, ...] = Field(min_length=1, max_length=20)
    inclusion_rule: Text
    exclusion_rules: tuple[ExclusionRule, ...] = Field(default=(), max_length=20)
    matching_rule: Text
    evidence_kind: Literal["real_business", "controlled_replay", "synthetic"]
    purpose: Text

    @model_validator(mode="after")
    def protocol_shape(self) -> Self:
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError("需要实际 IANA 时区") from error
        if self.window_end <= self.window_start:
            raise ValueError("观察窗口结束须晚于开始，采用左闭右开区间")
        for values in (
            self.role_ids,
            self.complexity_strata,
            tuple(r.rule_id for r in self.exclusion_rules),
        ):
            if len(set(values)) != len(values):
                raise ValueError("职责、复杂度和排除规则标识不能重复")
        return self


class StudyCreate(StudyProtocol):
    request_id: UUID


class StudyHistory(Contract):
    before_id: UUID | None = None


class Options(Contract):
    query: str = Field(default="", max_length=128)
    task_before_id: UUID | None = None
    document_before_id: UUID | None = None


class Consent(Contract):
    study_id: UUID
    request_id: UUID
    expected_version: Nonnegative
    status: Literal["consented", "withdrawn"]
    activity_and_aggregate_use_confirmed: bool
    reason: Text

    @model_validator(mode="after")
    def explicit(self) -> Self:
        if self.status == "consented" and not self.activity_and_aggregate_use_confirmed:
            raise ValueError("同意前须本人明确核对活动登记、项目内披露及汇总用途")
        return self


class Segment(Contract):
    segment_id: UUID
    phase: Literal[
        "prepare",
        "learn",
        "input",
        "review",
        "correct",
        "clarify",
        "execute",
        "handoff",
        "receive",
        "passive_wait",
    ]
    start_at: AwareDatetime
    end_at: AwareDatetime | None = None
    capture_method: Literal[
        "participant_timer", "participant_recollection", "authorized_event_reference"
    ]
    participant_verified: bool
    related_object_ref: Text | None = None

    @model_validator(mode="after")
    def interval(self) -> Self:
        if self.end_at is not None and self.end_at < self.start_at:
            raise ValueError("活动结束不能早于开始")
        if self.capture_method == "authorized_event_reference" and not self.related_object_ref:
            raise ValueError("引用系统事件须填写实际事件位置；事件间隔不自动等于主动时间")
        return self


class SampleDraft(Contract):
    study_id: UUID
    sample_id: UUID
    expected_version: Nonnegative
    task_id: UUID
    evidence_document_id: UUID | None = None
    evidence_locator: Text | None = None
    role_id: Key
    complexity_stratum: Key
    mode: Literal["baseline_without_ai", "assisted"]
    pair_key: Key | None = None
    matching_basis: Text | None = None
    first_use: bool
    workflow_version: Key
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    as_of: AwareDatetime
    terminal_state: Literal["completed", "failed", "cancelled", "incomplete"]
    segments: tuple[Segment, ...] = Field(default=(), max_length=100)
    review_confirmed: bool = False
    correction_confirmed: bool = False
    all_activity_confirmed: bool = False
    duplicate_entry_count: Nonnegative | None = None
    clarification_round_count: Nonnegative | None = None
    omission_rework_count: Nonnegative | None = None
    false_block_count: Nonnegative | None = None
    excluded_rule_id: Key | None = None
    exclusion_reason: Text | None = None

    @model_validator(mode="after")
    def sample_shape(self) -> Self:
        if (
            self.as_of < self.started_at
            or self.ended_at is not None
            and not self.started_at <= self.ended_at <= self.as_of
        ):
            raise ValueError("开始、终止和观察截点顺序不符")
        if (self.terminal_state == "incomplete") != (self.ended_at is None):
            raise ValueError("未完成须保留无终止时刻，已终止须填写实际结束时间")
        if len({s.segment_id for s in self.segments}) != len(self.segments):
            raise ValueError("活动编号不能重复")
        for segment in self.segments:
            if not self.started_at <= segment.start_at <= (self.ended_at or self.as_of):
                raise ValueError("活动开始须位于本次观察范围")
            if segment.end_at is not None and segment.end_at > (self.ended_at or self.as_of):
                raise ValueError("活动结束须位于本次观察范围")
            if self.ended_at is not None and segment.end_at is None:
                raise ValueError("已终止样本不能保留未结束活动段")
        if (self.pair_key is None) != (self.matching_basis is None):
            raise ValueError("配对标识和配对依据须同时填写")
        if (self.excluded_rule_id is None) != (self.exclusion_reason is None):
            raise ValueError("排除须对应预先登记规则并填写本项理由")
        if (self.evidence_document_id is None) != (self.evidence_locator is None):
            raise ValueError("证据文件和原文位置须同时填写")
        return self


class SampleSave(SampleDraft):
    request_id: UUID
    expected_digest: Digest
    reason: Text


class SampleHistory(Contract):
    study_id: UUID
    before_id: UUID | None = None


class SampleRead(Contract):
    sample_id: UUID
    before_version: int | None = Field(default=None, ge=1)


class Summary(Contract):
    study_id: UUID
