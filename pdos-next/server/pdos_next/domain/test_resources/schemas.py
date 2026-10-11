"""Controlled imports and fixed host bindings; none of these fields grant authority."""

from datetime import UTC
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from pdos_next.contracts import SourceRead
from pdos_next.domain.build_operational_facts.schemas import (
    DTO,
    FactRef,
    Hash,
    Key,
    Refs,
    ResourceInput,
    Revision,
    Text,
)
from pdos_next.domain.professional_authority.schemas import DefinitionReference
from pdos_next.engines.supply_cost.common import bounded_decimal
from pdos_next.schemas.resource_readiness.contracts import (
    ExecutionWindow,
    ReadinessReport,
    ResourceSnapshot,
    ResourceUse,
)
from pdos_next.schemas.verification.contracts import SampleRef


class TestPairBinding(DTO):
    sample: SampleRef
    item_id: Key
    method_id: UUID
    method_revision: Revision
    method_sha256: Hash
    destructive: bool = Field(strict=True)


class TestPlanBinding(DTO):
    """Constructed by the locked host from accepted scope and actual method facts."""

    run_id: UUID
    request_id: UUID
    accepted_request_id: UUID
    accepted_request_revision: Revision
    build_id: UUID
    project_id: UUID
    purpose: Text
    executor_id: UUID
    window: ExecutionWindow
    environment: Text
    conditions: Text
    equipment: DefinitionReference
    calibration: DefinitionReference
    pairs: tuple[TestPairBinding, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def pairs_unique(self) -> Self:
        if len({(v.sample.id, v.item_id) for v in self.pairs}) != len(self.pairs):
            raise ValueError("Fixed sample/item coverage cannot repeat")
        if any(v.sample.build_id != self.build_id for v in self.pairs):
            raise ValueError("Every actual sample must belong to the fixed Build")
        for identity in {v.sample.id for v in self.pairs}:
            values = [v for v in self.pairs if v.sample.id == identity]
            if any(v.sample != values[0].sample for v in values):
                raise ValueError("One physical sample cannot have inconsistent fixed versions")
            if sum(v.destructive for v in values) > 1:
                raise ValueError("One physical sample cannot serve multiple destructive tests")
        return self


class TestResourceFactInput(DTO):
    """Only a server-held trusted issuer may import this whole-version declaration."""

    binding: TestPlanBinding
    external_id: Key
    expected_previous_id: UUID | None = None
    expected_previous_revision: int = Field(default=0, ge=0, strict=True)
    state: Literal["active", "withdrawn"] = "active"
    valid_from: AwareDatetime
    valid_until: AwareDatetime | None = None
    resources: tuple[ResourceInput, ...] = Field(min_length=1)
    required_uses: tuple[ResourceUse, ...] = Field(min_length=1)
    # A trusted approved-method declaration, never a client waiver checkbox.
    requirements_sources: Refs
    approved_conditions: tuple[Text, ...] = Field(default=())
    sources: Refs
    reason: Text

    @field_validator("valid_from", "valid_until")
    @classmethod
    def utc(cls, value):
        return value.astimezone(UTC) if value is not None else None

    @field_validator("required_uses", mode="before")
    @classmethod
    def exact_units(cls, values):
        for value in values:
            raw = value.get("units") if isinstance(value, dict) else value.units
            bounded_decimal(raw)  # Refuse binary floats, bool and non-finite decimals.
        return values

    @model_validator(mode="after")
    def complete(self) -> Self:
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("Test facts require a positive validity interval")
        if (self.expected_previous_id is None) != (self.expected_previous_revision == 0):
            raise ValueError("Previous fact id and revision must be paired")
        if len({v.resource.id for v in self.resources}) != len(self.resources):
            raise ValueError("Physical resources cannot repeat")
        if len({v.resource.id for v in self.required_uses}) != len(self.required_uses):
            raise ValueError("Resource units must be combined once per physical identity")
        if {v.resource for v in self.required_uses} != {v.resource for v in self.resources}:
            raise ValueError("Trusted requirements and exact resource revisions must match")
        if not any(
            v.resource.kind == "person" and v.resource.id == self.binding.executor_id
            for v in self.required_uses
        ):
            raise ValueError("A named executor qualification resource is mandatory")
        return self


class SampleUsageView(DTO):
    sample_id: UUID
    state: Literal["available", "reserved", "consumed", "unknown"]
    owner_run_id: UUID | None = None
    revision: Revision | None = None
    reason: Text | None = None


class BoundTestResources(DTO):
    binding: TestPlanBinding
    report: ReadinessReport
    fact_ref: FactRef | None = None
    facts_revision: Hash
    resources: tuple[ResourceSnapshot, ...] = ()
    uses: tuple[ResourceUse, ...] = ()
    required_source_read_set: tuple[SourceRead, ...] = ()
    valid_until: AwareDatetime | None = None
    expiry_boundaries: tuple[AwareDatetime, ...] = Field(default=(), exclude=True)
    authority_basis: dict | None = Field(default=None, exclude=True)
    nature: Literal["unknown", "real", "synthetic"] = "unknown"
    sample_usage: tuple[SampleUsageView, ...] = ()


class TestReservationResult(DTO):
    owner_run_id: UUID
    reservation_id: UUID
    occupancy_ids: tuple[UUID, ...]
    sample_usage_ids: tuple[UUID, ...]
    facts_revision: Hash
    replayed: bool = Field(default=False, strict=True)
    disposition: Literal["staged_in_caller_uow"] = "staged_in_caller_uow"
