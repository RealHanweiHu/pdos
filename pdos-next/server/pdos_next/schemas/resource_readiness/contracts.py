"""Closed resource subprotocol; facts come from scoped server ports, never a model."""

from datetime import UTC
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from pdos_next.engines.planning.dto import CalendarSnapshot
from pdos_next.schemas.verification.contracts import Scope, SourceRef

Key = Annotated[str, Field(min_length=1, max_length=160)]
Text = Annotated[str, Field(min_length=1, max_length=2000)]
Revision = Annotated[int, Field(ge=1, strict=True)]
Units = Annotated[Decimal, Field(gt=0, allow_inf_nan=False, max_digits=24, decimal_places=12)]
Instant = Annotated[AwareDatetime, AfterValidator(lambda v: v.astimezone(UTC))]
Status = Literal["UNKNOWN", "BLOCKED", "READY_WITH_CONDITIONS", "READY"]
FactKind = Literal["acceptance", "calibration", "qualification"]


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ResourceRef(DTO):
    id: UUID
    revision: Revision
    kind: Literal["equipment", "fixture", "person", "line", "tooling"]


class ExecutionWindow(DTO):
    """UTC [start, finish); never an Actual fact or forecast promise."""

    start: Instant
    finish: Instant
    original_timezone: Key

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.finish <= self.start:
            raise ValueError("Execution interval must be positive")
        try:
            ZoneInfo(self.original_timezone)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("Valid IANA timezone required") from exc
        return self


class ResourceUse(DTO):
    resource: ResourceRef
    units: Units


class ReservationRequest(DTO):
    """No scope, permission, qualification, source status or Actual input fields."""

    reservation_id: UUID
    owner_run_id: UUID
    intent_key: Key
    purpose: Key
    operation_id: Key
    window: ExecutionWindow
    uses: tuple[ResourceUse, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique(self) -> Self:
        ids = [use.resource.id for use in self.uses]
        if len(ids) != len(set(ids)):
            raise ValueError("A resource must appear exactly once, with summed units")
        return self


class QualificationFact(DTO):
    kind: FactKind
    source: SourceRef
    purpose: Key
    operation_id: Key
    status: Literal["accepted", "rejected", "revoked", "unknown"]
    valid_from: Instant | None = None
    valid_until: Instant | None = None
    conditions: tuple[Text, ...] = Field(default=())
    named_decision_id: UUID | None = None
    actor_id: UUID | None = None

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until <= self.valid_from
        ):
            raise ValueError("Fact validity must be positive")
        if self.status == "accepted" and (self.named_decision_id is None or self.actor_id is None):
            raise ValueError("Accepted qualification must have an existing named decision")
        return self


class MaintenanceFact(DTO):
    window: ExecutionWindow
    source: SourceRef
    status: Literal["planned", "active", "completed", "cancelled", "unknown"]


class ResourceSnapshot(DTO):
    ref: ResourceRef
    scope: Scope
    source: SourceRef
    purposes: tuple[Key, ...] = Field()
    operation_ids: tuple[Key, ...] = Field()
    lifecycle: Literal["active", "withdrawn", "unknown"]
    required_facts: tuple[FactKind, ...] = ()
    facts: tuple[QualificationFact, ...] = Field(default=())
    # None means missing maintenance evidence; () means server verified no maintenance.
    maintenance: tuple[MaintenanceFact, ...] | None = None
    calendar: CalendarSnapshot | None = None
    calendar_source: SourceRef | None = None
    capacity: Units | None = None
    occupancy_revision: Revision

    @model_validator(mode="after")
    def complete(self) -> Self:
        keys = [(f.kind, f.purpose, f.operation_id) for f in self.facts]
        if len(keys) != len(set(keys)):
            raise ValueError("Snapshot supplies one current fact per kind/purpose/operation")
        if len(set(self.required_facts)) != len(self.required_facts):
            raise ValueError("Required fact kinds cannot repeat")
        if (self.calendar is None) != (self.calendar_source is None):
            raise ValueError("Calendar and its fixed source must be supplied together")
        return self


class Check(DTO):
    resource: ResourceRef | None = None
    code: Key
    status: Status
    detail: Text
    source: SourceRef | None = None


class ReadinessReport(DTO):
    status: Status
    capacity_status: Literal["checked", "unknown", "conflicted"]
    checks: tuple[Check, ...]
    fixed_resources: tuple[ResourceSnapshot, ...]
    input_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    checked_at: Instant
    # Every condition remains explicit and must be complied with at execution.
    conditions: tuple[Text, ...] = ()


class ReservationEvent(DTO):
    kind: Literal["tentative", "formal", "released", "cancelled"]
    at: Instant
    actor_id: UUID
    reason: Text | None = None


class Reservation(DTO):
    id: UUID
    revision: Revision
    scope: Scope
    request: ReservationRequest
    semantic_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    state: Literal["tentative", "formal", "released", "cancelled"]
    fixed_resources: tuple[ResourceSnapshot, ...]
    report: ReadinessReport
    events: tuple[ReservationEvent, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.id != self.request.reservation_id or self.events[-1].kind != self.state:
            raise ValueError("Reservation identity/state must match retained history")
        ids = [s.ref.id for s in self.fixed_resources]
        required_ids = {u.resource.id for u in self.request.uses}
        if (
            len(ids) != len(set(ids))
            or not set(ids) <= required_ids
            or (self.state == "formal" and set(ids) != required_ids)
        ):
            raise ValueError("Formal reservation must retain all fixed resource facts")
        return self


class ResourceContext(DTO):
    """Only returned by a current host authority port, never deserialized from a request."""

    scope: Scope
    actor_id: UUID
    owner_run_id: UUID
    executor_id: UUID
    assigned_person_ids: tuple[UUID, ...] = Field(default=())
    now: Instant
    authorized: bool
    qualified: bool | None
    cancelled: bool
    sources_current: bool | None
    policy_registered: bool
    facts_revision: Key  # Include permission, qualification and cancellation epochs.
    purpose: Key
    operation_id: Key
    required_resources: tuple[ResourceUse, ...] = Field(min_length=1)
    approved_conditions: tuple[Text, ...] = ()
    # Host-verified real RunStart source only; never fill from reservation/Forecast.
    verified_actual_start: Instant | None = None

    @model_validator(mode="after")
    def current_actual(self) -> Self:
        if self.verified_actual_start is not None and self.verified_actual_start > self.now:
            raise ValueError("Verified actual start cannot be in the future")
        ids = [use.resource.id for use in self.required_resources]
        if len(ids) != len(set(ids)):
            raise ValueError("Server-required resources cannot repeat")
        return self


class ReservationPreview(DTO):
    request: ReservationRequest
    report: ReadinessReport
    context_revision: Key
    expected_revision: int = Field(ge=0, strict=True)
    target_state: Literal["tentative", "formal", "released", "cancelled"]
    reason: Text | None = None
    digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    allowed: bool
    effect: Text


class StagedReservation(DTO):
    reservation: Reservation
    replayed: bool = False
    disposition: Literal["staged_in_caller_uow"] = "staged_in_caller_uow"


class Occupancy(DTO):
    """Sanitized capacity projection across projects, not another SampleUnit ledger."""

    reservation_id: UUID
    resource_id: UUID
    window: ExecutionWindow
    units: Units
