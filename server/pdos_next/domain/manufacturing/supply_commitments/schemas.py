"""Closed T0 supplier-commitment declarations (v1.1 §03.5, §04.10; F25).

A supplier commitment is a claim made by an external supplier about material it
will deliver. It is never inventory, an arrival, a purchase order or a supplier
entity. Scope, authorship, time basis and the check date stay server-owned.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from pdos_next.domain.manufacturing.supply_cost.engine.common import Quantity
from pdos_next.domain.projects.external_wait.schemas import Clock, Key
from pdos_next.domain.projects.work.schemas import DTO, Text, VersionRef
from pdos_next.schemas.verification.contracts import SourceRef

OPERATION = "supply.commitment.record"
EVENT = "supply.commitment_recorded"
SUBJECT = "supply_commitment"
ACTIONS = ("create", "revise", "close", "reopen")


class Promise(Clock):
    """What the supplier said: quantity, unit and promised date may each be unknown."""

    quantity: Quantity | None = None
    unit: Key | None = None
    promised_at: AwareDatetime | None
    text: Text

    @model_validator(mode="after")
    def unit_with_quantity(self):
        if self.quantity is not None and self.unit is None:
            raise ValueError("A known promised quantity needs its unit; keep unknown as null")
        return self


class Create(Promise):
    action: Literal["create"]
    build_id: UUID
    expected_build_revision: int = Field(ge=1, strict=True)
    material_id: UUID
    # The external supplier identifier as it appears in the source; no supplier entity.
    supplier_ref: Key


class Revise(Promise):
    action: Literal["revise"]


class Close(DTO):
    action: Literal["close"]
    result: Text


class Reopen(DTO):
    action: Literal["reopen"]


Record = Annotated[Create | Revise | Close | Reopen, Field(discriminator="action")]


class Payload(DTO):
    commitment: VersionRef | None = None
    # Exact original lines. A named person may instead (or also) state the basis
    # in their own words (F15, time_basis=human_recorded); 小Pai must cite originals.
    sources: tuple[SourceRef, ...] = ()
    statement: Text | None = None
    reason: Text | None = None
    record: Record

    @field_validator("sources")
    @classmethod
    def originals(cls, values):
        if any(ref.kind != "artifact" for ref in values):
            raise ValueError("Use exact original artifact references")
        if len({(ref.id, ref.revision, ref.position) for ref in values}) != len(values):
            raise ValueError("Exact source references cannot repeat")
        return values

    @model_validator(mode="after")
    def shape(self):
        if (self.record.action == "create") != (self.commitment is None):
            raise ValueError("Only creation may omit the exact current commitment reference")
        if not self.sources and self.statement is None:
            raise ValueError("Give exact original lines or your own statement as the basis")
        if self.record.action == "reopen" and self.reason is None:
            raise ValueError("Reopening a closed commitment needs its reason")
        return self


class Closure(DTO):
    result: Text
    actor_id: UUID
    requester_id: UUID
    recorded_at: AwareDatetime


class Snapshot(Clock):
    commitment_id: UUID
    revision: int = Field(ge=1)
    state: Literal["open", "closed"]
    build_id: UUID
    build_revision: int = Field(ge=1)
    project_id: UUID
    material_id: UUID
    supplier_ref: Key
    quantity: Quantity | None = None
    unit: Key | None = None
    promised_at: AwareDatetime | None
    # F25: the internal check is one day after the promised date; unknown date, no check.
    check_at: AwareDatetime | None
    text: Text
    responsible_id: UUID
    created_at: AwareDatetime
    recorded_at: AwareDatetime
    time_basis: Literal["human_recorded", "source_claim"]
    statement: Text | None = None
    sources: tuple[SourceRef, ...] = ()
    last_closure: Closure | None = None


PAYLOADS = {OPERATION: Payload}
