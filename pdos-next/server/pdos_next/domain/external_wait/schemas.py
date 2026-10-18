"""Closed T0 declarations; actual scope, authorship and evidence stay server-owned."""

from datetime import UTC
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, field_validator, model_validator

from pdos_next.domain.work_management.schemas import DTO, Text, VersionRef
from pdos_next.schemas.verification.contracts import SourceRef

OPERATION = "work.external_wait.record"
Key = Annotated[str, Field(min_length=1, max_length=200)]


class CalendarRef(DTO):
    kind: Literal["project_plan", "build_resource"]
    id: UUID
    revision: int = Field(ge=1, strict=True)
    calendar_key: Key
    calendar_version: Key
    resource_id: str | None = None


class Clock(DTO):
    original_timezone: Key

    @field_validator("original_timezone")
    @classmethod
    def zone(cls, value):
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError("Use an actual IANA timezone") from error
        return value

    @field_validator("*", mode="after")
    @classmethod
    def utc(cls, value):
        return value.astimezone(UTC) if hasattr(value, "astimezone") else value


class Schedule(Clock):
    next_check_at: AwareDatetime | None
    calendar: CalendarRef | None = None


class Create(Schedule):
    action: Literal["create"]
    title: Key
    target: Text
    request_content: Text
    closure_condition: Text
    blocking: bool = Field(strict=True)
    milestone: VersionRef | None = None
    build: VersionRef | None = None
    replaces: VersionRef | None = None


class Details(Schedule):
    action: Literal["details"]
    title: Key
    closure_condition: Text
    blocking: bool = Field(strict=True)


class EventInput(Clock):
    at: AwareDatetime | None
    text: Text


class Initiate(EventInput):
    action: Literal["initiate"]


class Delivery(EventInput):
    action: Literal["delivery"]
    status: Literal["effective", "unverified", "conflict"]

    @model_validator(mode="after")
    def actual_time(self):
        if self.status == "effective" and self.at is None:
            raise ValueError("Effective delivery needs its actual event time")
        return self


class CounterpartyCommitment(Clock):
    action: Literal["commitment"]
    promised_at: AwareDatetime | None
    text: Text


class Reply(EventInput):
    action: Literal["reply"]
    status: Literal["partial", "received", "conflict", "unknown"]


class Close(DTO):
    action: Literal["close"]
    result: Text


class Reopen(DTO):
    action: Literal["reopen"]


class TransferRequest(DTO):
    action: Literal["transfer_request"]
    to_id: UUID


class TransferAccept(DTO):
    action: Literal["transfer_accept"]
    request_id: UUID


class TransferCancel(DTO):
    action: Literal["transfer_cancel"]
    request_id: UUID


Record = Annotated[
    Create
    | Details
    | Initiate
    | Delivery
    | CounterpartyCommitment
    | Reply
    | Close
    | Reopen
    | TransferRequest
    | TransferAccept
    | TransferCancel,
    Field(discriminator="action"),
]


class Payload(DTO):
    project_id: UUID
    wait: VersionRef | None = None
    sources: tuple[SourceRef, ...] = Field(min_length=1)
    reason: Text
    record: Record

    @field_validator("sources")
    @classmethod
    def originals(cls, values):
        if any(ref.kind != "artifact" for ref in values):
            raise ValueError("Use exact original artifact references")
        return values

    @model_validator(mode="after")
    def target(self):
        if (self.record.action == "create") != (self.wait is None):
            raise ValueError("Only creation may omit the exact current waiting reference")
        return self


class Entry(Clock):
    at: AwareDatetime | None
    text: Text
    time_basis: Literal["human_recorded", "source_claim"]
    actor_id: UUID
    requester_id: UUID
    recorded_at: AwareDatetime
    sources: tuple[SourceRef, ...] = Field(min_length=1)


class DeliveryEntry(Entry):
    status: Literal["effective", "unverified", "conflict"]


class CommitmentEntry(Clock):
    promised_at: AwareDatetime | None
    text: Text
    actor_id: UUID
    requester_id: UUID
    recorded_at: AwareDatetime
    sources: tuple[SourceRef, ...] = Field(min_length=1)


class ReplyEntry(Entry):
    status: Literal["partial", "received", "conflict", "unknown"]


class Closure(DTO):
    result: Text
    actor_id: UUID
    requester_id: UUID
    recorded_at: AwareDatetime
    sources: tuple[SourceRef, ...] = Field(min_length=1)


class Transfer(DTO):
    request_id: UUID
    from_id: UUID
    to_id: UUID
    actor_id: UUID
    requested_at: AwareDatetime
    sources: tuple[SourceRef, ...] = Field(min_length=1)


class Snapshot(Schedule):
    wait_id: UUID
    revision: int = Field(ge=1)
    state: Literal["open", "closed"]
    responsible_id: UUID
    title: Key
    target: Text
    request_content: Text
    closure_condition: Text
    blocking: bool
    milestone: VersionRef | None = None
    build: VersionRef | None = None
    replaces: VersionRef | None = None
    created_at: AwareDatetime
    initiation: Entry | None = None
    delivery: DeliveryEntry | None = None
    counterparty_commitment: CommitmentEntry | None = None
    reply: ReplyEntry | None = None
    last_closure: Closure | None = None
    transfer: Transfer | None = None


PAYLOADS = {OPERATION: Payload}
