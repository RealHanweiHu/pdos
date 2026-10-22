"""Business adapters call the existing Decimal engine, without owning Build demand."""

from datetime import datetime

from pdos_next.engines.supply_cost import calculate_cost, calculate_coverage
from pdos_next.engines.supply_cost.common import digest
from pdos_next.engines.supply_cost.dto import AlternateQualification, CostRequest, CoverageRequest
from pdos_next.schemas.supply_cost.dto import (
    BoundDemand,
    CostInputs,
    CostProjection,
    CoverageProjection,
    SupplySnapshot,
)

from .errors import SupplyBusinessError
from .rules import basis_binding, canonical_supply, require_binding, require_current, require_scope


def coverage_candidate(
    bound: BoundDemand,
    supply: SupplySnapshot,
    verified_alternates: tuple[AlternateQualification, ...],
    as_of: datetime,
) -> CoverageProjection:
    """Only a server SupplySnapshotPort may provide verified_alternates.

    This adapter is not an authorization entry point; handler and mainline ports
    own provenance/ACL. Engine status alone cannot authenticate a qualification.
    """
    binding = basis_binding(bound, as_of)
    require_scope(bound.scope, supply.scope)
    require_binding(binding, supply.binding)
    require_current(supply.ref, as_of)
    supply = canonical_supply(supply)
    for restriction in supply.restrictions:
        require_current(restriction.ref, as_of)
    for qualification in verified_alternates:
        if (
            qualification.status != "externally_verified"
            or qualification.build_id != binding.build_id
            or qualification.bom_sha256 != binding.bom.sha256
            or qualification.configuration_sha256 != binding.engineering_configuration.sha256
        ):
            raise SupplyBusinessError(
                "QUALIFICATION_PORT_REJECTED", "Server qualification does not cover the fixed basis"
            )
        require_current(qualification.ref, as_of)
    result = calculate_coverage(
        CoverageRequest(
            as_of=as_of,
            basis=bound.basis,
            supply_snapshot=supply.ref,
            supply_scope_complete=supply.supply_scope_complete,
            pools=supply.pools,
            reservations=supply.reservations,
            alternates=verified_alternates,
        )
    )
    # The preflight compares the entire authoritative expansion; the result only
    # selects explicit supply levels and applies critical-first candidate order.
    canonical = {line.item_id: line for line in bound.demand.lines}
    for line in result.lines:
        expected = canonical.get(line.demand.item_id)
        # An uncovered path is deliberately turned unknown by the engine. It is
        # not a replacement demand fact and must retain the original identity.
        if expected is None or (
            line.demand != expected
            and not any(note.code == "uncovered_bom_path" for note in line.demand.issues)
        ):
            raise SupplyBusinessError("DEMAND_EXPANSION_MISMATCH", "Coverage changed Build demand")
    return CoverageProjection(
        as_of=as_of,
        scope=bound.scope,
        binding=binding,
        supply_snapshot_id=supply.snapshot_id,
        supply_revision=supply.revision,
        supply_sha256=digest(supply),
        verified_alternates=verified_alternates,
        quality_sources=tuple(row.ref for row in supply.restrictions),
        result=result,
    )


def cost_candidate(bound: BoundDemand, inputs: CostInputs, as_of: datetime) -> CostProjection:
    binding = basis_binding(bound, as_of)
    require_scope(bound.scope, inputs.scope)
    require_binding(binding, inputs.binding)
    require_current(inputs.ref, as_of)
    if inputs.process is not None:
        keys = bound.manufacturing_operation_ids
        if keys is None:
            raise SupplyBusinessError(
                "PROCESS_MAPPING_UNCONNECTED", "Fixed manufacturing operation mapping is pending"
            )
        actual = [row.operation_id for row in inputs.process.operations]
        if (
            len(keys) != len(set(keys))
            or len(actual) != len(set(actual))
            or sorted(keys) != sorted(actual)
        ):
            raise SupplyBusinessError(
                "PROCESS_MAPPING_MISMATCH",
                "Cost process differs from fixed manufacturing operations",
            )
    # CostInputPort authenticates mapping to the fixed manufacturing operation
    # keys and the quantity/unit/loss/quote evidence; never infer from cycle time.
    result = calculate_cost(
        CostRequest(
            as_of=as_of,
            basis=bound.basis,
            scope=inputs.cost_scope,
            process=inputs.process,
            material_prices=inputs.material_prices,
            prices=inputs.prices,
            rates=inputs.rates,
            nre_price_ids=inputs.nre_price_ids,
        )
    )
    return CostProjection(
        as_of=as_of,
        scope=bound.scope,
        binding=binding,
        cost_input_id=inputs.input_id,
        cost_input_revision=inputs.revision,
        cost_input_sha256=digest(inputs),
        result=result,
    )
