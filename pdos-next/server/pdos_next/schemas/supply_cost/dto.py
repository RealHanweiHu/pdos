"""Supply business DTO v1. Ports, never client fields, establish source authority.

DemandSnapshot is a read-only transport of Build's authoritative demand, not a
second demand entity. All persistence is owned by the common command transaction.
"""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, JsonValue, field_validator, model_validator

from pdos_next.engines.supply_cost.common import FrozenDTO, Quantity, SnapshotRef, Text
from pdos_next.engines.supply_cost.dto import (
    AlternateQualification,
    CostResult,
    CostScope,
    CoverageResult,
    DemandLine,
    ExchangeRate,
    FixedBasis,
    MaterialPrice,
    PoolKey,
    PriceSnapshot,
    ProcessSnapshot,
    ReservationSnapshot,
    SupplyPool,
)

Revision = Annotated[int, Field(ge=1, strict=True)]
Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Operation = Literal["supply.snapshot.record", "supply.coverage.calculate", "supply.cost.estimate"]


class Scope(FrozenDTO):
    tenant_id: Text
    category_id: Text
    product_id: Text
    project_id: Text
    audience: Text


class Timed(FrozenDTO):
    as_of: datetime

    @field_validator("as_of")
    @classmethod
    def aware_time(cls, value):
        return SnapshotRef.aware_time(value)


class DemandSnapshot(FrozenDTO):
    ref: SnapshotRef
    basis_sha256: Sha256
    manufacturing_sha256: Sha256
    lines: Annotated[tuple[DemandLine, ...], Field()]


class BoundDemand(FrozenDTO):
    scope: Scope
    basis: FixedBasis
    manufacturing_configuration: SnapshotRef
    demand: DemandSnapshot
    # Exact operation keys from the fixed manufacturing configuration. None is
    # a missing mapping, not an empty/zero-cost manufacturing process.
    manufacturing_operation_ids: tuple[Text, ...] | None = None
    source_read_set: tuple[SnapshotRef, ...] = ()
    source_read_set_complete: bool = Field(default=False, strict=True)


class BasisBinding(FrozenDTO):
    build_id: Text
    build: SnapshotRef
    bom: SnapshotRef
    engineering_configuration: SnapshotRef
    manufacturing_configuration: SnapshotRef
    demand: SnapshotRef
    basis_sha256: Sha256
    source_read_set: tuple[SnapshotRef, ...] = ()


class SupplyCommitment(FrozenDTO):
    record_id: Text
    ref: SnapshotRef
    supplier_id: Text
    material_id: Text
    quantity: Quantity | None
    unit: Text | None
    expected_at: datetime | None = None
    note: Text

    @field_validator("expected_at")
    @classmethod
    def aware_time(cls, value):
        return SnapshotRef.aware_time(value)


class TransitObservation(FrozenDTO):
    record_id: Text
    ref: SnapshotRef
    commitment_id: Text | None = None
    pool: PoolKey
    quantity: Quantity | None
    unit: Text | None
    note: Text


class ReceiptObservation(TransitObservation):
    # Incremental delivery observations are preserved as evidence; current pool
    # balance comes from the server snapshot and is never summed from history.
    received_at: datetime

    @field_validator("received_at")
    @classmethod
    def aware_time(cls, value):
        return SnapshotRef.aware_time(value)


class QualityRestriction(FrozenDTO):
    record_id: Text
    ref: SnapshotRef
    pool: PoolKey
    quality: Literal["released", "frozen", "unknown"]
    availability: Literal["available", "unavailable", "unknown"]
    affected_quantity: Quantity | None
    unit: Text | None
    note: Text


class SupplySnapshot(FrozenDTO):
    schema_version: Literal["supply-business-snapshot.v1"] = "supply-business-snapshot.v1"
    snapshot_id: Text
    revision: Revision
    scope: Scope
    binding: BasisBinding
    ref: SnapshotRef
    previous_snapshot_id: Text | None = None
    previous_revision: Revision | None = None
    commitments: Annotated[tuple[SupplyCommitment, ...], Field()] = ()
    in_transit: Annotated[tuple[TransitObservation, ...], Field()] = ()
    receipts: Annotated[tuple[ReceiptObservation, ...], Field()] = ()
    restrictions: Annotated[tuple[QualityRestriction, ...], Field()] = ()
    # Only these authoritative current pools enter the engine. The other records
    # never add capacity, nor does a commitment become stock when its date passes.
    pools: Annotated[tuple[SupplyPool, ...], Field()]
    reservations: Annotated[tuple[ReservationSnapshot, ...], Field()] = ()
    supply_scope_complete: bool = Field(strict=True)
    note: Text

    @model_validator(mode="after")
    def previous_pair(self) -> Self:
        if (self.previous_snapshot_id is None) != (self.previous_revision is None):
            raise ValueError("Previous snapshot ID and revision must be provided together")
        if self.previous_snapshot_id == self.snapshot_id:
            raise ValueError("A new snapshot has a new immutable identity")
        return self


class CostInputs(FrozenDTO):
    schema_version: Literal["cost-business-input.v1"] = "cost-business-input.v1"
    input_id: Text
    revision: Revision
    scope: Scope
    binding: BasisBinding
    ref: SnapshotRef
    cost_scope: CostScope
    process: ProcessSnapshot | None = None
    material_prices: Annotated[tuple[MaterialPrice, ...], Field()]
    prices: Annotated[tuple[PriceSnapshot, ...], Field()]
    rates: Annotated[tuple[ExchangeRate, ...], Field()] = ()
    nre_price_ids: Annotated[tuple[Text, ...], Field()] = ()


class Delta(FrozenDTO):
    entity: Text
    identity: Text
    kind: Literal["added", "removed", "changed"]
    before: JsonValue | None
    after: JsonValue | None


class SupplyReconciliation(FrozenDTO):
    previous: SupplySnapshot | None
    current: SupplySnapshot
    previous_sha256: Sha256 | None
    current_sha256: Sha256
    duplicate: bool
    deltas: tuple[Delta, ...]
    notice: str = "Source or balance changes require recalculation; old results remain unchanged"


class CoverageProjection(Timed):
    schema_version: Literal["supply-business-coverage.v1"] = "supply-business-coverage.v1"
    scope: Scope
    binding: BasisBinding
    supply_snapshot_id: Text
    supply_revision: Revision
    supply_sha256: Sha256
    verified_alternates: tuple[AlternateQualification, ...]
    # Quality evidence is outside the engine DTO; retain it for same-transaction
    # source rechecks and passage-of-time invalidation of saved candidates.
    quality_sources: tuple[SnapshotRef, ...] = ()
    result: CoverageResult


class CostProjection(Timed):
    schema_version: Literal["supply-business-cost.v1"] = "supply-business-cost.v1"
    scope: Scope
    binding: BasisBinding
    cost_input_id: Text
    cost_input_revision: Revision
    cost_input_sha256: Sha256
    result: CostResult


class Freshness(FrozenDTO):
    state: Literal["current", "requires_recalculation", "historical"]
    reasons: tuple[Text, ...]


class BuildPayload(FrozenDTO):
    build_id: Text
    expected_build_revision: Revision


class RecordSupplyPayload(BuildPayload):
    # capture_id points to the server-validated import/manual-evidence draft.
    # It is not a caller-controlled claim of stock, permission or qualification.
    capture_id: Text
    expected_previous_snapshot_id: Text | None = None
    expected_previous_revision: Revision | None = None
    reason: Text

    @model_validator(mode="after")
    def previous_pair(self) -> Self:
        if (self.expected_previous_snapshot_id is None) != (
            self.expected_previous_revision is None
        ):
            raise ValueError("Expected previous ID and revision must be provided together")
        return self


class CalculateCoveragePayload(BuildPayload):
    supply_snapshot_id: Text
    expected_supply_revision: Revision


class EstimateCostPayload(BuildPayload):
    cost_input_id: Text
    expected_cost_input_revision: Revision


class Intent(FrozenDTO):
    command_id: Text
    idempotency_key: Annotated[str, Field(min_length=8, max_length=160)]
    operation: Operation
    payload: RecordSupplyPayload | CalculateCoveragePayload | EstimateCostPayload

    @model_validator(mode="after")
    def operation_payload(self) -> Self:
        expected = {
            "supply.snapshot.record": RecordSupplyPayload,
            "supply.coverage.calculate": CalculateCoveragePayload,
            "supply.cost.estimate": EstimateCostPayload,
        }
        if not isinstance(self.payload, expected[self.operation]):
            raise ValueError("Operation and payload type do not match")
        return self


class Confirmation(FrozenDTO):
    review_id: Text
    token: Annotated[str, Field(min_length=20, max_length=500)]
    plan_sha256: Sha256


class CommandBinding(Timed):
    scope: Scope
    current_time: datetime

    @field_validator("current_time")
    @classmethod
    def aware_time(cls, value):
        return SnapshotRef.aware_time(value)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.as_of > self.current_time:
            raise ValueError("Fixed calculation time cannot be in the future")
        return self


class PreparedPlan(Timed):
    scope: Scope
    operation: Operation
    intent_sha256: Sha256
    sources: tuple[SnapshotRef, ...]
    value: SupplyReconciliation | CoverageProjection | CostProjection
    effect: Text
    write_tier: Literal["T1"] = "T1"


class Preview(Timed):
    review_id: Text
    confirmation_token: Annotated[str, Field(min_length=20, max_length=500)]
    plan_sha256: Sha256
    expires_at: datetime
    review: PreparedPlan

    @field_validator("expires_at")
    @classmethod
    def aware_time(cls, value):
        return SnapshotRef.aware_time(value)


class CommandReceipt(FrozenDTO):
    receipt_id: Text
    subject_id: Text
    subject_type: Literal["supply_snapshot", "supply_coverage", "cost_estimate"]
    revision: Revision
    plan_sha256: Sha256
    replayed: bool = False
