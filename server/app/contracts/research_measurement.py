"""Participant-only measurement in actual market-space or product-line scope."""

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.contracts.common_objects import Contract, Digest, Key, Nonnegative, Text
from app.contracts.value_measurement import (
    Consent,
    SampleHistory,
    SampleRead,
    Segment,
    StudyProtocol,
    Summary,
)

SubjectKind = Literal["research_task", "scoped_work_item", "opportunity", "strategy", "definition"]


class StudyCreate(StudyProtocol):
    product_line_id: UUID | None = None
    request_id: UUID


class StudyHistory(Contract):
    product_line_id: UUID | None = None
    before_id: UUID | None = None


class Options(Contract):
    product_line_id: UUID | None = None
    subject_kind: SubjectKind
    query: str = Field(default="", max_length=128)
    before_id: UUID | None = None


class SampleDraft(Contract):
    study_id: UUID
    sample_id: UUID
    expected_version: Nonnegative
    subject_kind: SubjectKind
    subject_id: UUID
    source_locator: Text
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
        return self


class SampleSave(SampleDraft):
    request_id: UUID
    expected_digest: Digest
    reason: Text


__all__ = [
    "Consent",
    "Options",
    "SampleDraft",
    "SampleHistory",
    "SampleRead",
    "SampleSave",
    "StudyCreate",
    "StudyHistory",
    "Summary",
]
