"""Fixed pre-project team scope and source-version-bound independent reception."""

from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from app.contracts.common_objects import Contract, Digest, Key, Text
from app.contracts.research_measurement import SubjectKind


class Options(Contract):
    study_id: UUID
    subject_kind: SubjectKind
    workpack_id: UUID | None = None
    query: str = Field(default="", max_length=128)
    before_id: UUID | None = None
    user_before_id: UUID | None = None


class Participant(Contract):
    user_id: UUID
    role_id: Key
    first_use: bool


class WorkpackCreate(Contract):
    request_id: UUID
    study_id: UUID
    subject_kind: SubjectKind
    subject_id: UUID
    mode: Literal["baseline_without_ai", "assisted"]
    deliverer_user_id: UUID
    receiver_user_id: UUID
    members: tuple[Participant, ...] = Field(min_length=2, max_length=20)
    complexity_stratum: Key
    workflow_version: Key
    pair_key: Key | None = None
    matching_basis: Text | None = None
    scope: Text
    completion_criteria: Text
    full_roster_confirmed: Literal[True]

    @model_validator(mode="after")
    def roster(self) -> Self:
        people = {p.user_id for p in self.members}
        if len(people) != len(self.members):
            raise ValueError("每名实际参与者只能登记一次主职责，不可由多个职责虚增人数")
        if self.deliverer_user_id == self.receiver_user_id:
            raise ValueError("交付人和下游接收人须为不同实际成员")
        if not {self.deliverer_user_id, self.receiver_user_id} <= people:
            raise ValueError("完整参与者清单须包含交付人及接收人")
        if (self.pair_key is None) != (self.matching_basis is None):
            raise ValueError("任务对标识与匹配依据须同时填写")
        return self


class History(Contract):
    study_id: UUID
    before_id: UUID | None = None


class Read(Contract):
    workpack_id: UUID


class DeliveryPreview(Read):
    subject_id: UUID
    locator: Text
    description: Text


class DeliverySave(DeliveryPreview):
    request_id: UUID
    expected_digest: Digest


class ReceptionPreview(Read):
    delivery_id: UUID
    decision: Literal["accepted", "returned"]
    criteria_checked: Literal[True]
    reason: Text


class ReceptionSave(ReceptionPreview):
    request_id: UUID
    expected_digest: Digest


class ClosePreview(Read):
    outcome: Literal["failed", "cancelled"]
    reason: Text


class Close(ClosePreview):
    request_id: UUID
    expected_digest: Digest
