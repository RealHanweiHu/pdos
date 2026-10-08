"""Deterministic snapshot/reconciliation rules; no queries, writes or stock allocation."""

from datetime import datetime, timedelta

from pdos_next.engines.supply_cost import expand_bom
from pdos_next.engines.supply_cost.common import calculation_context, digest, source_issues
from pdos_next.engines.supply_cost.dto import AlternateQualification
from pdos_next.engines.supply_cost.units import UNITS
from pdos_next.schemas.supply_cost.dto import (
    BasisBinding,
    BoundDemand,
    CostInputs,
    CostProjection,
    CoverageProjection,
    Delta,
    Freshness,
    Scope,
    SupplyReconciliation,
    SupplySnapshot,
)

from .errors import SupplyBusinessError


def require_scope(expected: Scope, actual: Scope) -> None:
    if expected != actual:
        raise SupplyBusinessError("FORBIDDEN_SCOPE", "Source is outside the server-bound scope")


def require_current(ref, as_of: datetime) -> None:
    if source_issues(ref, as_of, "source"):
        raise SupplyBusinessError("SOURCE_STALE", "Fixed source is not current at this time")


def basis_binding(bound: BoundDemand, as_of: datetime) -> BasisBinding:
    basis = bound.basis
    if not bound.source_read_set_complete:
        raise SupplyBusinessError(
            "SOURCE_READ_SET_UNCONNECTED",
            "Original configuration/Build evidence read set is pending",
        )
    if (
        bound.demand.basis_sha256 != digest(basis)
        or bound.demand.manufacturing_sha256 != bound.manufacturing_configuration.sha256
    ):
        raise SupplyBusinessError("DEMAND_BASIS_MISMATCH", "Demand does not bind this fixed basis")
    for ref in (
        basis.build.ref,
        basis.bom.ref,
        basis.bom.engineering_configuration,
        bound.manufacturing_configuration,
        bound.demand.ref,
        *bound.source_read_set,
    ):
        require_current(ref, as_of)
    expanded, _ = expand_bom(basis, as_of)
    # Canonical demand ordering is not coverage's greedy priority ordering.
    # Compare EVERY field (including unknowns, issues, ancestry and criticality).
    ids = [line.item_id for line in bound.demand.lines]
    if len(ids) != len(set(ids)) or sorted(expanded, key=lambda x: x.item_id) != sorted(
        bound.demand.lines, key=lambda x: x.item_id
    ):
        raise SupplyBusinessError(
            "DEMAND_EXPANSION_MISMATCH", "Engine expansion differs from authoritative Build demand"
        )
    return BasisBinding(
        build_id=basis.build.build_id,
        build=basis.build.ref,
        bom=basis.bom.ref,
        engineering_configuration=basis.bom.engineering_configuration,
        manufacturing_configuration=bound.manufacturing_configuration,
        demand=bound.demand.ref,
        basis_sha256=digest(basis),
        source_read_set=tuple(sorted(bound.source_read_set, key=digest)),
    )


def require_binding(expected: BasisBinding, actual: BasisBinding) -> None:
    if expected != actual:
        raise SupplyBusinessError(
            "FIXED_INPUT_MISMATCH",
            "Build, demand or engineering/manufacturing configuration changed",
        )


def _identity(pool) -> str:
    # JSON tuple identity is unambiguous even when IDs themselves contain colons.
    import json

    return json.dumps(
        [pool.source_system, pool.pool_id, pool.material_id],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _unique(rows, key):
    result = {}
    for row in rows:
        identity = key(row)
        if identity in result and row != result[identity]:
            raise SupplyBusinessError(
                "CONFLICTING_SNAPSHOT", "One stable identity has contradictory observations"
            )
        result[identity] = row
    return tuple(result[key] for key in sorted(result))


def canonical_supply(snapshot: SupplySnapshot) -> SupplySnapshot:
    """Deduplicate identical views only; never sum stages of one physical pool."""
    data = snapshot.model_dump(mode="python")
    for name in ("commitments", "in_transit", "receipts", "restrictions"):
        data[name] = _unique(getattr(snapshot, name), lambda row: row.record_id)
    data["pools"] = _unique(snapshot.pools, lambda row: _identity(row.key))
    data["reservations"] = _unique(snapshot.reservations, lambda row: row.reservation_id)
    pools = {row.key: row for row in data["pools"]}
    for restriction in data["restrictions"]:
        pool = pools.get(restriction.pool)
        if pool is None or (
            pool.quality != restriction.quality or pool.availability != restriction.availability
        ):
            raise SupplyBusinessError(
                "QUALITY_PROJECTION_CONFLICT",
                "Active restriction and current pool disagree; rebind quality partitions",
            )
        if restriction.affected_quantity is None or pool.quantity is None:
            if pool.quality == "released" and pool.availability == "available":
                raise SupplyBusinessError(
                    "QUALITY_PROJECTION_CONFLICT", "Released partition quantity is not established"
                )
        else:
            left, right = UNITS.get(restriction.unit or ""), UNITS.get(pool.unit or "")
            with calculation_context():
                if (
                    left is None
                    or right is None
                    or left[0] != right[0]
                    or restriction.affected_quantity * left[1] != pool.quantity * right[1]
                ):
                    raise SupplyBusinessError(
                        "QUALITY_PROJECTION_CONFLICT",
                        "Restriction does not cover exactly the authoritative pool partition",
                    )
    return SupplySnapshot.model_validate(data)


def _records(snapshot: SupplySnapshot) -> dict:
    rows = {}
    for name in ("commitments", "in_transit", "receipts", "restrictions", "pools", "reservations"):
        for row in getattr(snapshot, name):
            identity = (
                _identity(row.key)
                if name == "pools"
                else row.reservation_id
                if name == "reservations"
                else row.record_id
            )
            rows[(name, identity)] = row.model_dump(mode="json")
    rows[("snapshot", "basis")] = snapshot.binding.model_dump(mode="json")
    rows[("snapshot", "source")] = snapshot.ref.model_dump(mode="json")
    rows[("snapshot", "scope_complete")] = snapshot.supply_scope_complete
    rows[("snapshot", "note")] = snapshot.note
    return rows


def reconcile(previous: SupplySnapshot | None, current: SupplySnapshot) -> SupplyReconciliation:
    current = canonical_supply(current)
    before = canonical_supply(previous) if previous is not None else None
    if before:
        require_scope(before.scope, current.scope)
        if before.binding.build_id != current.binding.build_id:
            raise SupplyBusinessError(
                "FIXED_INPUT_MISMATCH", "Snapshots belong to different Builds"
            )
        if before.snapshot_id == current.snapshot_id:
            if before != current:
                raise SupplyBusinessError(
                    "SNAPSHOT_ID_CONFLICT", "Immutable snapshot ID was reused"
                )
            return SupplyReconciliation(
                previous=before,
                current=current,
                previous_sha256=digest(before),
                current_sha256=digest(current),
                duplicate=True,
                deltas=(),
            )
        if (
            current.previous_snapshot_id != before.snapshot_id
            or current.previous_revision != before.revision
            or current.revision != before.revision + 1
        ):
            raise SupplyBusinessError(
                "SNAPSHOT_VERSION_CONFLICT", "Previous snapshot pointer changed"
            )
        if current.ref.captured_at <= before.ref.captured_at:
            raise SupplyBusinessError(
                "SNAPSHOT_OUT_OF_ORDER", "New capture must be later than previous"
            )
    elif current.previous_snapshot_id is not None or current.revision != 1:
        raise SupplyBusinessError(
            "SNAPSHOT_VERSION_CONFLICT", "First snapshot must begin at revision 1"
        )
    old, new = _records(before) if before else {}, _records(current)
    deltas = []
    for entity, identity in sorted(old.keys() | new.keys()):
        key = entity, identity
        if key in old and key in new and old[key] == new[key]:
            continue
        deltas.append(
            Delta(
                entity=entity,
                identity=identity,
                kind="added" if key not in old else "removed" if key not in new else "changed",
                before=old.get(key),
                after=new.get(key),
            )
        )
    return SupplyReconciliation(
        previous=before,
        current=current,
        previous_sha256=digest(before) if before else None,
        current_sha256=digest(current),
        duplicate=False,
        deltas=tuple(deltas),
    )


def projection_freshness(
    projection: CoverageProjection | CostProjection,
    current: BoundDemand,
    as_of: datetime,
    *,
    supply: SupplySnapshot | None = None,
    cost: CostInputs | None = None,
    alternates: tuple[AlternateQualification, ...] | None = None,
    historical: bool = False,
) -> Freshness:
    """Read-side status only. Never mutate/rewrite old calculated results."""
    require_scope(projection.scope, current.scope)
    reasons = []
    try:
        binding = basis_binding(current, as_of)
        if binding != projection.binding:
            reasons.append("fixed_basis_changed")
    except SupplyBusinessError as error:
        reasons.append(error.code)
    if isinstance(projection, CoverageProjection):
        if supply is None:
            reasons.append("current_supply_unconnected")
        else:
            require_scope(projection.scope, supply.scope)
            if digest(canonical_supply(supply)) != projection.supply_sha256:
                reasons.append("supply_snapshot_changed")
            if source_issues(supply.ref, as_of, "source"):
                reasons.append("supply_source_unavailable")
        if alternates is not None:
            if sorted(alternates, key=digest) != sorted(projection.verified_alternates, key=digest):
                reasons.append("qualification_changed")
        elif projection.verified_alternates:
            reasons.append("qualification_recheck_unconnected")
        refs = (
            projection.result.input_snapshot.supply_snapshot,
            *(pool.ref for pool in projection.result.input_snapshot.pools),
            *(row.ref for row in projection.result.input_snapshot.reservations),
            *(row.ref for row in projection.verified_alternates),
            *projection.quality_sources,
        )
    else:
        if cost is None:
            reasons.append("current_cost_inputs_unconnected")
        else:
            require_scope(projection.scope, cost.scope)
            if digest(cost) != projection.cost_input_sha256:
                reasons.append("cost_inputs_changed")
            if source_issues(cost.ref, as_of, "source"):
                reasons.append("cost_source_unavailable")
        request = projection.result.input_snapshot
        refs = (
            *((request.process.ref,) if request.process else ()),
            *(price.ref for price in request.prices),
            *(rate.ref for rate in request.rates),
        )
        if any(
            (price.valid_from is not None and as_of < price.valid_from)
            or (price.valid_until is not None and as_of >= price.valid_until)
            for price in request.prices
        ):
            reasons.append("quote_validity_changed")
        if any(
            as_of - rate.ref.captured_at > timedelta(days=request.scope.max_rate_age_days)
            for rate in request.rates
        ):
            reasons.append("rate_age_limit_exceeded")
    if any(source_issues(ref, as_of, "source") for ref in refs):
        reasons.append("source_expired_or_unavailable")
    return Freshness(
        state="historical" if historical else "requires_recalculation" if reasons else "current",
        reasons=tuple(sorted(set(reasons))),
    )


def snapshot_freshness(
    snapshot: SupplySnapshot,
    current: BoundDemand,
    as_of: datetime,
    *,
    current_snapshot: SupplySnapshot | None,
    historical: bool = False,
) -> Freshness:
    """Label a saved input for review; never promote it to a live stock transaction."""
    require_scope(snapshot.scope, current.scope)
    snapshot = canonical_supply(snapshot)
    reasons = []
    try:
        if basis_binding(current, as_of) != snapshot.binding:
            reasons.append("fixed_basis_changed")
    except SupplyBusinessError as error:
        reasons.append(error.code)
    if current_snapshot is None:
        reasons.append("current_supply_unconnected")
    else:
        require_scope(snapshot.scope, current_snapshot.scope)
        if canonical_supply(current_snapshot) != snapshot:
            reasons.append("supply_snapshot_superseded")
    refs = (
        snapshot.ref,
        *(pool.ref for pool in snapshot.pools),
        *(row.ref for row in snapshot.reservations),
        *(row.ref for row in snapshot.restrictions),
    )
    if any(source_issues(ref, as_of, "source") for ref in refs):
        reasons.append("source_expired_or_unavailable")
    return Freshness(
        state="historical" if historical else "requires_recalculation" if reasons else "current",
        reasons=tuple(sorted(set(reasons))),
    )
