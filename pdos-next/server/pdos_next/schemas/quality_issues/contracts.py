"""Closed Issue/CAPA DTOs. TestRun remains the sole measurement owner."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from pdos_next.schemas.verification.contracts import (
    DTO,
    BuildRef,
    Coverage,
    EventTime,
    Key,
    Revision,
    SampleRef,
    Scope,
    SourceRef,
    Text,
)

IssueState = Literal["open", "triaged", "actioning", "awaiting_verification", "closed"]
Risk = Literal["low", "medium", "high", "critical"]


class Ref(DTO):
    id: UUID
    revision: Revision


class FailureRef(DTO):
    identity: Key
    run: Ref
    measurement_id: UUID
    executor_id: UUID
    coverage: Coverage
    build: BuildRef
    sample: SampleRef
    criterion: SourceRef
    method: SourceRef
    source: SourceRef
    nature: Literal["real", "synthetic"]
    # Original values are read through RunPort, never copied into an Issue result store.


class History(DTO):
    command_id: UUID
    operation: Key
    actor_id: UUID
    actor_kind: Literal["human", "ai"]
    at: datetime
    note: Text

    @field_validator("at")
    @classmethod
    def aware(cls, value):
        return EventTime.aware(value)


class Containment(DTO):
    id: UUID
    text: Text
    executor_id: UUID
    evidence: tuple[SourceRef, ...] = Field(min_length=1)
    at: EventTime


class Hypothesis(DTO):
    text: Text
    sources: tuple[SourceRef, ...] = Field(min_length=1)


class NamedConclusion(DTO):
    text: Text
    actor_id: UUID
    sources: tuple[SourceRef, ...] = Field(min_length=1)
    at: datetime

    @field_validator("at")
    @classmethod
    def aware(cls, value):
        return EventTime.aware(value)


class CapaAction(DTO):
    id: UUID
    kind: Literal["corrective", "preventive"]
    text: Text
    executor_id: UUID
    completion: Containment | None = None


class EffectivenessRequirement(DTO):
    method: Text
    acceptance: Text
    observation_until: datetime
    required_failure_ids: tuple[Key, ...] = Field(min_length=1)

    @field_validator("observation_until")
    @classmethod
    def aware(cls, value):
        return EventTime.aware(value)

    @field_validator("required_failure_ids")
    @classmethod
    def unique(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("复核失败范围不可重复")
        return tuple(sorted(value))


class EffectivenessDecision(NamedConclusion):
    result: Literal["effective", "ineffective"]
    evidence_ids: tuple[UUID, ...]
    policy: Ref
    read_digest: Key


class Capa(DTO):
    id: UUID
    hypotheses: tuple[Hypothesis, ...] = Field(min_length=1)
    actions: tuple[CapaAction, ...] = Field(min_length=1)
    requirement: EffectivenessRequirement
    effectiveness: EffectivenessDecision | None = None
    effectiveness_history: tuple[EffectivenessDecision, ...] = ()

    @model_validator(mode="after")
    def unique_actions(self):
        if len({a.id for a in self.actions}) != len(self.actions):
            raise ValueError("措施身份不可重复")
        return self


class Issue(DTO):
    id: UUID
    revision: Revision
    scope: Scope
    audience: tuple[Key, ...] = Field(min_length=1)
    title: Text
    status: IssueState = "open"
    risk: Risk | None = None
    failures: tuple[FailureRef, ...] = Field(min_length=1)
    aliases: tuple[UUID, ...] = ()
    merged_into: UUID | None = None
    containment: tuple[Containment, ...] = ()
    root_cause: NamedConclusion | None = None
    capa: Capa | None = None
    needs_recheck: bool = False
    recheck_reasons: tuple[Text, ...] = ()
    history: tuple[History, ...] = ()
    closure: NamedConclusion | None = None

    @model_validator(mode="after")
    def fixed_identities(self):
        if len({f.identity for f in self.failures}) != len(self.failures):
            raise ValueError("稳定失败身份不可重复")
        if len(set(self.aliases)) != len(self.aliases) or self.id in self.aliases:
            raise ValueError("问题别名不可重复或自指")
        return self


class IssueCreate(DTO):
    run_id: UUID
    measurement_id: UUID
    event_id: UUID
    title: Text


class IssueMerge(DTO):
    sources: tuple[Ref, ...] = Field(min_length=1)
    reason: Text

    @field_validator("sources")
    @classmethod
    def unique(cls, value):
        if len({r.id for r in value}) != len(value):
            raise ValueError("原问题不可重复")
        return tuple(sorted(value, key=lambda r: str(r.id)))


class IssueTriage(DTO):
    reason: Text


class ContainmentRecord(DTO):
    action: Containment


class RootCauseDecide(DTO):
    text: Text
    sources: tuple[SourceRef, ...] = Field(min_length=1)


class CapaDraft(DTO):
    capa_id: UUID
    hypotheses: tuple[Hypothesis, ...] = Field(min_length=1)
    actions: tuple[CapaAction, ...] = Field(min_length=1)
    requirement: EffectivenessRequirement

    @model_validator(mode="after")
    def draft_only(self):
        if any(a.completion is not None for a in self.actions):
            raise ValueError("草稿不能声明措施已执行")
        return self


class ActionsComplete(DTO):
    completions: tuple[Containment, ...] = Field(min_length=1)

    @field_validator("completions")
    @classmethod
    def unique(cls, value):
        if len({a.id for a in value}) != len(value):
            raise ValueError("完成记录不可重复")
        return value


class EffectivenessDecide(DTO):
    result: Literal["effective", "ineffective"]
    text: Text
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)

    @field_validator("evidence_ids")
    @classmethod
    def unique(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("验证证据不可重复")
        return tuple(sorted(value, key=str))


class IssueClose(DTO):
    text: Text


class IssueRecheck(DTO):
    reason: Text
