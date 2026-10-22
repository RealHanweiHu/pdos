"""DTO v1. Callers bind and validate scope/authority before supplying these snapshots."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, field_validator

from .common import Currency, FrozenDTO, Issue, Loss, Positive, Quantity, SnapshotRef, Text


class TimedRequest(FrozenDTO):
    as_of: datetime

    @field_validator("as_of")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Calculation time must include an explicit timezone")
        return value.astimezone(UTC)


class BuildSnapshot(FrozenDTO):
    build_id: Text
    ref: SnapshotRef
    quantity: Positive | None
    product_unit: Text | None


class BomItem(FrozenDTO):
    item_id: Text
    parent_item_id: Text | None = None
    material_id: Text | None
    quantity_per_parent: Positive | None
    unit: Text | None
    loss_rate: Loss | None
    supply_required: bool
    critical: bool = False


class BomSnapshot(FrozenDTO):
    ref: SnapshotRef
    engineering_configuration: SnapshotRef
    items: Annotated[tuple[BomItem, ...], Field()]


class FixedBasis(FrozenDTO):
    schema_version: Literal["supply-cost-input.v1"] = "supply-cost-input.v1"
    build: BuildSnapshot
    bom: BomSnapshot


class PoolKey(FrozenDTO):
    source_system: Text
    pool_id: Text
    material_id: Text


class SupplyPool(FrozenDTO):
    key: PoolKey
    ref: SnapshotRef
    stage: Literal["commitment", "in_transit", "on_hand", "received"]
    quantity: Quantity | None
    unit: Text | None
    availability: Literal["available", "unavailable", "unknown"]
    quality: Literal["released", "frozen", "unknown"]
    expected_at: datetime | None = None

    @field_validator("expected_at")
    @classmethod
    def aware_time(cls, value: datetime | None) -> datetime | None:
        return SnapshotRef.aware_time(value)


class ReservationSnapshot(FrozenDTO):
    reservation_id: Text
    ref: SnapshotRef
    pool: PoolKey
    build_id: Text
    bom_item_id: Text | None
    quantity: Quantity | None
    unit: Text | None


class AlternateQualification(FrozenDTO):
    qualification_id: Text
    ref: SnapshotRef
    status: Literal["externally_verified", "unverified"]
    target_material_id: Text
    alternate_material_id: Text
    target_unit: Text
    alternate_unit: Text
    alternate_quantity_per_target: Positive | None
    build_id: Text
    bom_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    configuration_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class CoverageRequest(TimedRequest):
    basis: FixedBasis
    supply_snapshot: SnapshotRef
    # True only if the service has supplied every relevant pool and active reservation.
    supply_scope_complete: bool
    pools: Annotated[tuple[SupplyPool, ...], Field()]
    reservations: Annotated[tuple[ReservationSnapshot, ...], Field()] = ()
    alternates: Annotated[tuple[AlternateQualification, ...], Field()] = ()


class DemandLine(FrozenDTO):
    item_id: Text
    material_id: Text | None
    unit: Text | None
    critical: bool
    ancestry: tuple[str, ...]
    quantity_per_product: Decimal | None
    required_quantity: Decimal | None
    issues: tuple[Issue, ...]


class PoolObservation(FrozenDTO):
    key: PoolKey
    stage: str
    unit: Text | None
    quantity: Decimal | None
    reserved_quantity: Decimal | None
    unreserved_usable_quantity: Decimal | None
    own_secured_quantity: Decimal | None
    source: SnapshotRef
    issues: tuple[Issue, ...]


class SupplyUse(FrozenDTO):
    pool: PoolKey
    quantity_in_pool_unit: Decimal
    quantity_in_demand_unit: Decimal
    kind: Literal["secured", "unreserved_candidate"]
    reservation_id: Text | None = None
    qualification_id: Text | None = None


class DemandCoverage(FrozenDTO):
    demand: DemandLine
    known_secured_quantity: Decimal
    known_potential_quantity: Decimal
    secured_gap: Decimal | None
    potential_gap: Decimal | None
    secured_ready: bool | None
    potential_ready: bool | None
    uses: tuple[SupplyUse, ...]
    issues: tuple[Issue, ...]


class CoverageResult(FrozenDTO):
    schema_version: Literal["supply-coverage-result.v1"] = "supply-coverage-result.v1"
    algorithm: Literal["fixed-bom-shared-pool.v1"] = "fixed-bom-shared-pool.v1"
    input_sha256: str
    input_snapshot: CoverageRequest
    secured_ready: bool | None
    potential_ready: bool | None
    critical_secured_ready: bool | None
    candidate_policy: Literal["critical-then-item-primary-then-alternate.v1"] = (
        "critical-then-item-primary-then-alternate.v1"
    )
    potential_is_feasibility_proof: Literal[False] = False
    lines: tuple[DemandCoverage, ...]
    pools: tuple[PoolObservation, ...]
    issues: tuple[Issue, ...]
    notice: str = (
        "Snapshot calculation only; candidates do not reserve stock or approve a Build. "
        "Potential readiness/gaps describe this greedy candidate, "
        "not optimal substitution feasibility"
    )


class PriceSnapshot(FrozenDTO):
    price_id: Text
    subject_kind: Literal["material", "process", "nre"]
    subject_id: Text
    ref: SnapshotRef
    stage: Literal["estimate", "quote"]
    basis: Literal["unit", "nre"]
    amount: Quantity | None
    price_quantity: Positive | None
    unit: Text | None
    currency: Currency | None
    tax_basis: Literal["exclusive", "inclusive", "unknown"]
    tax_rate: Loss | None = None
    freight_basis: Literal["included", "excluded", "unknown"]
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    minimum_quantity: Quantity | None = None
    maximum_quantity: Positive | None = None
    scope_assumption: Text

    @field_validator("valid_from", "valid_until")
    @classmethod
    def aware_time(cls, value: datetime | None) -> datetime | None:
        return SnapshotRef.aware_time(value)


class MaterialPrice(FrozenDTO):
    bom_item_id: Text
    price_id: Text


class ProcessOperation(FrozenDTO):
    operation_id: Text
    quantity_per_product: Quantity | None
    unit: Text | None
    loss_rate: Loss | None
    price_id: Text | None


class ProcessSnapshot(FrozenDTO):
    ref: SnapshotRef
    operations: Annotated[tuple[ProcessOperation, ...], Field()]
    assumption: Text


class ExchangeRate(FrozenDTO):
    rate_id: Text
    ref: SnapshotRef
    from_currency: Currency
    to_currency: Currency
    rate: Positive | None
    purpose: Literal["spot", "budget"]


class CostScope(FrozenDTO):
    currency: Currency
    tax_basis: Literal["exclusive", "inclusive"]
    freight_basis: Literal["included", "excluded"]
    coverage: Literal["materials_only", "materials_and_process"]
    rate_purpose: Literal["spot", "budget"]
    max_rate_age_days: Annotated[int, Field(ge=0, le=3650)]
    nre_policy: Literal["excluded", "separate", "amortize"]
    nre_volume: Positive | None = None
    assumptions: Annotated[tuple[Text, ...], Field(min_length=1)]


class CostRequest(TimedRequest):
    basis: FixedBasis
    scope: CostScope
    process: ProcessSnapshot | None = None
    material_prices: Annotated[tuple[MaterialPrice, ...], Field()]
    prices: Annotated[tuple[PriceSnapshot, ...], Field()]
    rates: Annotated[tuple[ExchangeRate, ...], Field()] = ()
    nre_price_ids: Annotated[tuple[Text, ...], Field()] = ()


class CostLine(FrozenDTO):
    line_id: Text
    category: Literal["material", "process", "nre"]
    price_id: Text | None
    quantity_per_product: Decimal | None
    quantity_for_build: Decimal | None
    demand_unit: Text | None
    quantity_in_price_unit: Decimal | None
    original_currency: str | None
    original_build_amount: Decimal | None
    rate_id: Text | None
    per_product_candidate: Decimal | None
    build_candidate: Decimal | None
    issues: tuple[Issue, ...]


class CostResult(FrozenDTO):
    schema_version: Literal["cost-estimate-result.v1"] = "cost-estimate-result.v1"
    algorithm: Literal["fixed-bom-process-decimal.v1"] = "fixed-bom-process-decimal.v1"
    input_sha256: str
    input_snapshot: CostRequest
    complete_in_selected_scope: bool
    currency: Currency
    known_build_subtotal: Decimal
    known_nre_subtotal: Decimal
    per_product_candidate: Decimal | None
    build_candidate: Decimal | None
    nre_candidate: Decimal | None
    including_amortized_nre: Decimal | None
    lines: tuple[CostLine, ...]
    issues: tuple[Issue, ...]
    sensitive_items: tuple[Issue, ...]
    decimal_precision: Literal[38] = 38
    rounding: str = "ROUND_HALF_EVEN at precision 38; no currency display quantization"
    notice: str = (
        "Selected-scope estimate candidate; not ERP actual cost, approval or proven saving"
    )
