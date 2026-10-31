"""Closed public declarations and server-bound work snapshots."""

from datetime import UTC
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
    model_validator,
)

from pdos_next.schemas.verification.contracts import SourceRef

from .constants import ACCEPT, ASSIGN, COMMIT, CREATE, REVIEW, START, STATUS, SUBMIT

Text = Annotated[str, Field(min_length=1, max_length=4000)]
Key = Annotated[str, Field(min_length=1, max_length=120)]
State = Literal["proposed", "assigned", "accepted", "in_progress", "submitted", "completed"]


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class VersionRef(DTO):
    id: UUID
    revision: int = Field(ge=1, strict=True)


class G0OpenItemRef(DTO):
    id: UUID
    decision_id: UUID


class Outcome(DTO):
    key: Key
    text: Text
    required: bool = Field(strict=True)


def unique_keys(values):
    return len({value.key for value in values}) == len(values)


class Payload(DTO):
    project_id: UUID
    sources: tuple[SourceRef, ...]
    reason: Text

    @field_validator("sources")
    @classmethod
    def original_artifacts(cls, values):
        if any(value.kind != "artifact" for value in values):
            raise ValueError("Work commands require exact original artifact references")
        return values


class ConfirmedPayload(Payload):
    confirmation_token: Annotated[str, Field(min_length=20, max_length=128)] | None = None


class NpiTemplateRef(DTO):
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    project_type: Key
    phase_id: Key
    task_id: Key
    phase_code: Key
    phase_name: Key


class TaskCreatePayload(Payload):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    goal: Text
    outcomes: tuple[Outcome, ...] = Field(min_length=1)
    plan_task: VersionRef | None = None
    npi_template: NpiTemplateRef | None = None
    g0_open_item: G0OpenItemRef | None = None

    @model_serializer(mode="wrap")
    def serialize(self, handler):
        value = handler(self)
        if self.npi_template is None:
            value.pop("npi_template", None)
        return value

    @model_validator(mode="after")
    def has_direct_source(self):
        if not self.sources and self.g0_open_item is None:
            raise ValueError("A task requires original artifacts or an exact G0 open item")
        return self

    @field_validator("outcomes")
    @classmethod
    def distinct(cls, values):
        if not unique_keys(values):
            raise ValueError("Task outcomes cannot repeat a key")
        return values


class TaskAssignPayload(ConfirmedPayload):
    task: VersionRef
    assignee_id: UUID
    recipient_id: UUID


class TaskAcceptPayload(ConfirmedPayload):
    task: VersionRef


class ClockFields(DTO):
    original_timezone: Key
    calendar_id: UUID | None = None

    @field_validator("original_timezone")
    @classmethod
    def timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("Use an actual IANA timezone") from exc
        return value

    @field_validator("*", mode="after")
    @classmethod
    def utc(cls, value):
        if hasattr(value, "astimezone"):
            return value.astimezone(UTC)
        return value


class CommitmentAcceptPayload(ConfirmedPayload, ClockFields):
    sources: tuple[SourceRef, ...] = Field(min_length=1)
    task: VersionRef
    recipient_id: UUID
    outcome_keys: tuple[Key, ...] = Field(min_length=1)
    promised_at: AwareDatetime | None
    replaces: VersionRef | None = None

    @field_validator("outcome_keys")
    @classmethod
    def distinct(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("Commitment outcome identities cannot repeat")
        return values


class TaskStartPayload(ConfirmedPayload, ClockFields):
    task: VersionRef
    actual_at: AwareDatetime


class Result(DTO):
    key: Key
    text: Text
    status: Literal["present", "partial", "missing"]
    sources: tuple[SourceRef, ...]

    @field_validator("sources")
    @classmethod
    def original_artifacts(cls, values):
        return Payload.original_artifacts(values)

    @model_validator(mode="after")
    def present_has_own_sources(self):
        if self.status == "present" and not self.sources:
            raise ValueError("A present result requires its own original sources")
        return self


class TaskSubmitPayload(TaskStartPayload):
    results: tuple[Result, ...] = Field(min_length=1)

    @field_validator("results")
    @classmethod
    def distinct(cls, values):
        if not unique_keys(values):
            raise ValueError("Submitted outcome identities cannot repeat")
        return values


class ReviewCheck(DTO):
    key: Key
    decision: Literal["accepted", "rejected", "unknown"]
    reason: Text


class TaskReviewPayload(TaskStartPayload):
    decision: Literal["accepted", "returned"]
    checks: tuple[ReviewCheck, ...] = Field(min_length=1)

    @field_validator("checks")
    @classmethod
    def distinct(cls, values):
        if not unique_keys(values):
            raise ValueError("Reviewed outcome identities cannot repeat")
        return values


class StatusUpdatePayload(ConfirmedPayload):
    sources: tuple[SourceRef, ...] = Field(min_length=1)
    fact_summary: Text
    next_steps: Text
    task_refs: tuple[VersionRef, ...] = ()

    @field_validator("task_refs")
    @classmethod
    def distinct(cls, values):
        if len({value.id for value in values}) != len(values):
            raise ValueError("Status updates cannot repeat a task identity")
        return values


PAYLOADS = {
    CREATE: TaskCreatePayload,
    ASSIGN: TaskAssignPayload,
    ACCEPT: TaskAcceptPayload,
    COMMIT: CommitmentAcceptPayload,
    START: TaskStartPayload,
    SUBMIT: TaskSubmitPayload,
    REVIEW: TaskReviewPayload,
    STATUS: StatusUpdatePayload,
}


class TimeFact(ClockFields):
    actual_at: AwareDatetime
    actor_id: UUID
    recorded_at: AwareDatetime


class Submission(DTO):
    time: TimeFact
    results: tuple[Result, ...]


class Review(DTO):
    time: TimeFact
    decision: Literal["accepted", "returned"]
    checks: tuple[ReviewCheck, ...]


class TaskSnapshot(DTO):
    task_id: UUID
    revision: int = Field(ge=1)
    state: State
    title: Text
    goal: Text
    outcomes: tuple[Outcome, ...]
    plan_task: VersionRef | None = None
    npi_template: NpiTemplateRef | None = None
    g0_open_item: G0OpenItemRef | None = None
    assignee_id: UUID | None = None
    recipient_id: UUID | None = None
    actual_start: TimeFact | None = None
    submission: Submission | None = None
    review: Review | None = None

    @model_validator(mode="after")
    def shape(self):
        if not self.outcomes or not unique_keys(self.outcomes):
            raise ValueError("The actual task needs distinct outcomes")
        if self.state != "proposed" and (self.assignee_id is None or self.recipient_id is None):
            raise ValueError("Assigned work must retain the actual assignee and recipient")
        return self


class CommitmentSnapshot(ClockFields):
    revision: int = Field(ge=1)
    task_id: UUID
    task_revision: int = Field(ge=1)
    promisor_id: UUID
    recipient_id: UUID
    outcome_keys: tuple[Key, ...]
    promised_at: AwareDatetime | None
    replaces: VersionRef | None = None
    recorded_at: AwareDatetime


class StatusPlan(DTO):
    fact_summary: Text
    next_steps: Text
    task_refs: tuple[VersionRef, ...]
    actor_id: UUID
    recorded_at: AwareDatetime
