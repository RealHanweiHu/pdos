"""Closed host data DTOs. Issuer, scope, source truth and nature are server bound."""

from datetime import UTC
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BeforeValidator,
    Field,
    field_validator,
    model_validator,
)

from pdos_next.contracts import SourceRead
from pdos_next.domain.professional_authority.schemas import DefinitionReference
from pdos_next.engines.planning.dto import CalendarSnapshot
from pdos_next.engines.supply_cost.common import FrozenDTO, bounded_decimal
from pdos_next.engines.supply_cost.dto import CoverageResult, PoolKey
from pdos_next.schemas.resource_readiness.contracts import (
    ExecutionWindow,
    ReadinessReport,
    ResourceRef,
    ResourceUse,
)
from pdos_next.schemas.supply_cost.dto import BoundDemand

from .execution_scope import OperationalScope


class DTO(FrozenDTO):
    pass


Key = Annotated[str, Field(min_length=1, max_length=160)]
Text = Annotated[str, Field(min_length=1, max_length=2000)]
Quantity = Annotated[
    Decimal, BeforeValidator(bounded_decimal), Field(ge=0, max_digits=24, decimal_places=8)
]
Positive = Annotated[
    Decimal, BeforeValidator(bounded_decimal), Field(gt=0, max_digits=24, decimal_places=8)
]
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Revision = Annotated[int, Field(ge=1, strict=True)]
Refs = Annotated[tuple[DefinitionReference, ...], Field(min_length=1)]


class ExternalMaterialHold(DTO):
    id: Key
    build_id: Key
    bom_item_id: Key | None = None
    quantity: Quantity | None
    unit: Key | None


class MaterialInput(DTO):
    key: PoolKey
    version: Revision
    observed_at: AwareDatetime
    stage: Literal["commitment", "in_transit", "on_hand", "received"]
    quantity: Quantity | None
    unit: Key | None
    availability: Literal["available", "unavailable", "unknown"]
    quality: Literal["released", "frozen", "unknown"]
    external_holds: tuple[ExternalMaterialHold, ...] = Field(default=())
    external_holds_complete: bool = Field(default=False, strict=True)
    sources: Refs

    @field_validator("observed_at")
    @classmethod
    def utc(cls, value):
        return value.astimezone(UTC)


class DecisionInput(DTO):
    kind: Literal["acceptance", "calibration", "qualification"]
    purpose: Key
    operation_id: Key
    status: Literal["accepted", "rejected", "revoked", "unknown"]
    valid_from: AwareDatetime | None = None
    valid_until: AwareDatetime | None = None
    named_decision_id: UUID | None = None
    actor_id: UUID | None = None
    conditions: tuple[Text, ...] = Field(default=())
    sources: Refs

    @field_validator("valid_from", "valid_until")
    @classmethod
    def utc(cls, value):
        return value.astimezone(UTC) if value else None

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.valid_from and self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("Decision interval must be positive")
        if self.status == "accepted" and (not self.named_decision_id or not self.actor_id):
            raise ValueError("Accepted facts require a named existing decision")
        return self


class MaintenanceInput(DTO):
    window: ExecutionWindow
    status: Literal["planned", "active", "completed", "cancelled", "unknown"]
    sources: Refs


class ExternalOccupancy(DTO):
    reservation_id: UUID
    window: ExecutionWindow
    units: Positive


class ResourceInput(DTO):
    resource: ResourceRef
    purposes: tuple[Key, ...] = Field(min_length=1)
    operation_ids: tuple[Key, ...] = Field(min_length=1)
    lifecycle: Literal["active", "withdrawn", "unknown"]
    facts: tuple[DecisionInput, ...] = Field(default=())
    maintenance: tuple[MaintenanceInput, ...] | None = Field(default=None)
    calendar: CalendarSnapshot | None = None
    calendar_sources: tuple[DefinitionReference, ...] = Field(default=())
    capacity: Positive | None = None
    external_occupancies: tuple[ExternalOccupancy, ...] = Field(default=())
    external_occupancies_complete: bool = Field(default=False, strict=True)
    sources: Refs

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len({(v.kind, v.purpose, v.operation_id) for v in self.facts}) != len(self.facts):
            raise ValueError("One current decision per fact kind/purpose/operation required")
        if (self.calendar is None) != (not self.calendar_sources):
            raise ValueError("Calendar and fixed original references are paired")
        if len({v.reservation_id for v in self.external_occupancies}) != len(
            self.external_occupancies
        ):
            raise ValueError("External resource occupancy identities must be unique")
        return self


class OperationRequirements(DTO):
    operation_key: Key
    uses: tuple[ResourceUse, ...] = Field(min_length=1)
    sources: Refs

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len({v.resource.id for v in self.uses}) != len(self.uses):
            raise ValueError("Resource units must be combined within one operation")
        return self


class FactInput(DTO):
    build_id: UUID
    expected_build_revision: Revision
    scope: OperationalScope
    external_id: Key
    expected_previous_id: UUID | None = None
    expected_previous_revision: int = Field(default=0, ge=0, strict=True)
    state: Literal["active", "withdrawn"] = "active"
    valid_from: AwareDatetime
    valid_until: AwareDatetime | None = None
    materials_scope_complete: bool = Field(default=False, strict=True)
    materials: tuple[MaterialInput, ...] = Field(default=())
    resources: tuple[ResourceInput, ...] = Field(default=())
    requirements: tuple[OperationRequirements, ...] = Field(default=())
    sources: Refs
    reason: Text

    @field_validator("valid_from", "valid_until")
    @classmethod
    def utc(cls, value):
        return value.astimezone(UTC) if value is not None else None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("Operational validity must be positive")
        if (self.expected_previous_id is None) != (self.expected_previous_revision == 0):
            raise ValueError("Current previous id/revision must be paired")
        for values, key in (
            (self.materials, lambda v: v.key),
            (self.resources, lambda v: v.resource.id),
            (self.requirements, lambda v: v.operation_key),
        ):
            if len({key(v) for v in values}) != len(values):
                raise ValueError("Material/resource/operation identity cannot repeat")
        return self


class OperationalCheck(DTO):
    dimension: Literal["binding", "materials", "resources", "authority"]
    code: Key
    status: Literal["UNKNOWN", "BLOCKED", "READY_WITH_CONDITIONS", "READY"]
    detail: Text


class FactRef(DTO):
    id: UUID
    revision: Revision
    epoch: Revision
    sha256: Hash
    nature: Literal["real", "synthetic"]


class DecisionProof(DTO):
    """Returned only by the host verifier of an existing named scoped decision."""

    current: bool = Field(strict=True)
    facts_revision: Hash
    valid_until: AwareDatetime | None = None


class OperationalBundle(DTO):
    state: Literal["UNKNOWN", "BLOCKED", "READY_WITH_CONDITIONS", "READY"]
    scope: OperationalScope
    build_revision: Revision
    engineering_configuration_id: UUID
    engineering_configuration_revision: Revision
    manufacturing_configuration_id: UUID
    manufacturing_configuration_revision: Revision
    binding: BoundDemand | None = None
    coverage: CoverageResult | None = None
    resources: ReadinessReport | None = None
    checks: tuple[OperationalCheck, ...]
    fact_refs: tuple[FactRef, ...] = ()
    required_source_read_set: tuple[SourceRead, ...] = ()
    facts_revision: Hash
    valid_until: AwareDatetime | None = None
    nature: Literal["unknown", "real", "synthetic"] = "unknown"
    decision_watermarks: tuple[dict, ...] = ()


class ReservationResult(DTO):
    owner_execution_id: UUID
    material_holds: tuple[UUID, ...]
    resource_reservations: tuple[UUID, ...]
    facts_revision: Hash
    disposition: Literal["staged_in_caller_uow"] = "staged_in_caller_uow"
