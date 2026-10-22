"""Synthetic server-port records, never live business data or authority."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256

from pdos_next.domain.supply_cost.rules import basis_binding
from pdos_next.engines.supply_cost import expand_bom
from pdos_next.engines.supply_cost.common import SnapshotRef, digest
from pdos_next.engines.supply_cost.dto import (
    AlternateQualification,
    BomItem,
    BomSnapshot,
    BuildSnapshot,
    CostScope,
    FixedBasis,
    MaterialPrice,
    PoolKey,
    PriceSnapshot,
    ReservationSnapshot,
    SupplyPool,
)
from pdos_next.schemas.supply_cost.dto import (
    BoundDemand,
    CostInputs,
    DemandSnapshot,
    Scope,
    SupplySnapshot,
)

AS_OF = datetime(2026, 10, 2, 12, tzinfo=UTC)
SCOPE = Scope(
    tenant_id="tenant",
    category_id="category",
    product_id="product",
    project_id="project",
    audience="internal",
)


def ref(source_id, *, version="1", captured_at=None, valid_until=None, state="current"):
    return SnapshotRef(
        source_id=source_id,
        version=version,
        sha256=sha256(f"{source_id}/{version}".encode()).hexdigest(),
        captured_at=captured_at or AS_OF - timedelta(hours=1),
        valid_until=valid_until,
        state=state,
    )


def bound_demand(*, scope=SCOPE, quantity="5", items=None, build_ref=None):
    basis = FixedBasis(
        build=BuildSnapshot(
            build_id="build", ref=build_ref or ref("build"), quantity=quantity, product_unit="ea"
        ),
        bom=BomSnapshot(
            ref=ref("bom"),
            engineering_configuration=ref("engineering"),
            items=items
            or (
                BomItem(
                    item_id="a",
                    material_id="material",
                    quantity_per_parent="2",
                    unit="ea",
                    loss_rate="0",
                    supply_required=True,
                    critical=True,
                ),
            ),
        ),
    )
    manufacturing = ref("manufacturing")
    lines, _ = expand_bom(basis, AS_OF)
    return BoundDemand(
        scope=scope,
        basis=basis,
        manufacturing_configuration=manufacturing,
        source_read_set=(ref("original-evidence"),),
        source_read_set_complete=True,
        demand=DemandSnapshot(
            ref=ref("demand"),
            basis_sha256=digest(basis),
            manufacturing_sha256=manufacturing.sha256,
            lines=lines,
        ),
    )


def pool(*, quantity="10", pool_id="lot", material_id="material", **updates):
    return SupplyPool(
        key=PoolKey(source_system="erp", pool_id=pool_id, material_id=material_id),
        ref=ref(f"pool:{pool_id}"),
        stage="received",
        quantity=quantity,
        unit="ea",
        availability="available",
        quality="released",
    ).model_copy(update=updates)


def reservation(key, *, identity="own", build_id="build", quantity="4"):
    return ReservationSnapshot(
        reservation_id=identity,
        ref=ref(f"reservation:{identity}"),
        pool=key,
        build_id=build_id,
        bom_item_id="a" if build_id == "build" else "other-item",
        quantity=quantity,
        unit="ea",
    )


def supply(bound=None, **updates):
    bound = bound or bound_demand()
    return SupplySnapshot(
        snapshot_id="supply-1",
        revision=1,
        scope=bound.scope,
        binding=basis_binding(bound, AS_OF),
        ref=ref("supply-1"),
        pools=(pool(),),
        supply_scope_complete=True,
        note="Synthetic authorized snapshot",
    ).model_copy(update=updates)


def price(*, amount="0.10", **updates):
    return PriceSnapshot(
        price_id="quote",
        subject_kind="material",
        subject_id="material",
        ref=ref("quote"),
        stage="quote",
        basis="unit",
        amount=amount,
        price_quantity="1",
        unit="ea",
        currency="USD",
        tax_basis="exclusive",
        freight_basis="included",
        valid_from=AS_OF - timedelta(days=1),
        valid_until=AS_OF + timedelta(days=1),
        minimum_quantity="0",
        maximum_quantity="100",
        scope_assumption="One selected quote tier for this Build quantity",
    ).model_copy(update=updates)


def cost_inputs(bound=None, **updates):
    bound = bound or bound_demand()
    return CostInputs(
        input_id="cost-1",
        revision=1,
        scope=bound.scope,
        binding=basis_binding(bound, AS_OF),
        ref=ref("cost-1"),
        cost_scope=CostScope(
            currency="USD",
            tax_basis="exclusive",
            freight_basis="included",
            coverage="materials_only",
            rate_purpose="budget",
            max_rate_age_days=7,
            nre_policy="excluded",
            assumptions=("Explicit materials-only candidate",),
        ),
        material_prices=(MaterialPrice(bom_item_id="a", price_id="quote"),),
        prices=(price(),),
    ).model_copy(update=updates)


def alternate(bound=None, **updates):
    bound = bound or bound_demand()
    return AlternateQualification(
        qualification_id="qualified",
        ref=ref("qualification"),
        status="externally_verified",
        target_material_id="material",
        alternate_material_id="alternate",
        target_unit="ea",
        alternate_unit="ea",
        alternate_quantity_per_target="1",
        build_id="build",
        bom_sha256=bound.basis.bom.ref.sha256,
        configuration_sha256=bound.basis.bom.engineering_configuration.sha256,
    ).model_copy(update=updates)
