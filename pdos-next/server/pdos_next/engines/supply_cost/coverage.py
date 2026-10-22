"""Shared-pool observation and deterministic candidates; never allocate or authorize."""

from collections import defaultdict
from decimal import Decimal

from .bom import expand_bom
from .common import calculation_context, digest, issue, sorted_issues, source_issues
from .dto import (
    CoverageRequest,
    CoverageResult,
    DemandCoverage,
    DemandLine,
    PoolObservation,
    SupplyUse,
)
from .units import conversion

ZERO = Decimal(0)


def _gap(known: Decimal, required: Decimal | None, uncertain: bool) -> Decimal | None:
    if required is None:
        return None
    if known >= required:
        return ZERO
    return None if uncertain else required - known


def _unique(rows, key, path):
    """An identical view is one observation; conflicting versions contribute no capacity."""
    groups = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)
    unique, conflicts, problems = {}, set(), []
    for identity, group in groups.items():
        ordered = sorted(group, key=digest)
        unique[identity] = ordered[0]
        if any(row != ordered[0] for row in ordered[1:]):
            conflicts.add(identity)
            problems.append(
                issue(
                    "conflicting_snapshot",
                    path,
                    "One identity has conflicting observations; excluded",
                    "conflict",
                )
            )
    return unique, conflicts, problems


def calculate_coverage(request: CoverageRequest) -> CoverageResult:
    with calculation_context():
        return _calculate(request)


def _calculate(request: CoverageRequest) -> CoverageResult:
    expanded, base_issues = expand_bom(request.basis, request.as_of)
    demand_ids = {item.item_id for item in request.basis.bom.items if item.supply_required}
    demands = [line for line in expanded if line.item_id in demand_ids]
    parents = {item.parent_item_id for item in request.basis.bom.items}
    scope_issues = [note for line in expanded for note in line.issues if note.kind == "conflict"]
    for line in expanded:
        if line.item_id not in parents and not ({line.item_id, *line.ancestry} & demand_ids):
            note = issue(
                "uncovered_bom_path",
                line.item_id,
                "Each leaf path needs one explicit supply level; none was selected",
            )
            scope_issues.append(note)
            demands.append(
                DemandLine(
                    **line.model_dump(
                        exclude={"quantity_per_product", "required_quantity", "issues"}
                    ),
                    quantity_per_product=None,
                    required_quantity=None,
                    issues=sorted_issues([*line.issues, note]),
                )
            )
    # Sorting is an explicit candidate priority, not a write to a reservation service.
    demands.sort(key=lambda line: (not line.critical, line.item_id))
    problems = list(base_issues) + scope_issues
    supply_issues = source_issues(request.supply_snapshot, request.as_of, "supply_snapshot")
    problems.extend(supply_issues)
    if not request.supply_scope_complete:
        problems.append(
            issue(
                "incomplete_supply_scope",
                "supply_snapshot",
                "Relevant pools or active reservations may be missing",
            )
        )
    if not demands:
        problems.append(issue("empty_demand", "bom", "No demand items; kit readiness is unknown"))

    pools, pool_conflicts, notes = _unique(request.pools, lambda row: row.key, "pools")
    problems.extend(notes)
    reservations, reservation_conflicts, notes = _unique(
        request.reservations, lambda row: row.reservation_id, "reservations"
    )
    problems.extend(notes)
    held = defaultdict(list)
    ambiguous_reservation_pools = set()
    for reservation in request.reservations:
        if reservation.reservation_id in reservation_conflicts:
            ambiguous_reservation_pools.add(reservation.pool)
    for reservation in reservations.values():
        held[reservation.pool].append(reservation)
        if reservation.pool not in pools:
            problems.append(
                issue(
                    "reservation_pool_missing",
                    reservation.reservation_id,
                    "Reservation refers to an absent pool",
                )
            )

    alternates, alternate_conflicts, notes = _unique(
        request.alternates, lambda row: row.qualification_id, "alternates"
    )
    problems.extend(notes)
    accepted = []
    for identity, alternate in sorted(alternates.items()):
        notes = source_issues(alternate.ref, request.as_of, f"alternate:{identity}")
        if identity in alternate_conflicts:
            notes.append(
                issue(
                    "qualification_conflict",
                    identity,
                    "Conflicting qualification inputs",
                    "conflict",
                )
            )
        if alternate.status != "externally_verified":
            notes.append(
                issue(
                    "alternate_unverified",
                    identity,
                    "External verified qualification is required",
                    "restriction",
                )
            )
        if (
            alternate.build_id != request.basis.build.build_id
            or alternate.bom_sha256 != request.basis.bom.ref.sha256
            or alternate.configuration_sha256 != request.basis.bom.engineering_configuration.sha256
        ):
            notes.append(
                issue(
                    "alternate_scope_mismatch",
                    identity,
                    "Qualification does not cover this Build/BOM/configuration",
                    "restriction",
                )
            )
        if alternate.alternate_quantity_per_target is None:
            notes.append(issue("alternate_ratio_unknown", identity, "Qualified ratio is unknown"))
        if (
            conversion(alternate.target_unit, alternate.target_unit) is None
            or conversion(alternate.alternate_unit, alternate.alternate_unit) is None
        ):
            notes.append(
                issue(
                    "alternate_unit_unsupported",
                    identity,
                    "Qualification units are outside the v1 conversion range",
                )
            )
        problems.extend(notes)
        if not notes:
            accepted.append(alternate)

    def ratio(demand, pool):
        # Returns physical pool units consumed per demand unit.
        if pool.key.material_id == demand.material_id:
            return conversion(demand.unit, pool.unit), None
        choices = []
        for alternate in accepted:
            if (
                alternate.target_material_id == demand.material_id
                and alternate.alternate_material_id == pool.key.material_id
            ):
                left = conversion(demand.unit, alternate.target_unit)
                right = conversion(alternate.alternate_unit, pool.unit)
                if left is not None and right is not None:
                    choices.append(
                        (
                            left * alternate.alternate_quantity_per_target * right,
                            alternate.qualification_id,
                        )
                    )
        if not choices:
            return None, None
        if len({value for value, _ in choices}) > 1:
            return None, "conflicting_qualified_ratios"
        return sorted(choices, key=lambda row: row[1])[0]

    observations = []
    free = {}
    valid_held = {}
    pool_unknown = {}
    pool_notes = {}
    for key, pool in sorted(
        pools.items(), key=lambda row: (row[0].source_system, row[0].pool_id, row[0].material_id)
    ):
        notes = source_issues(pool.ref, request.as_of, f"pool:{key.pool_id}") + supply_issues
        if not request.supply_scope_complete:
            notes.append(
                issue(
                    "incomplete_supply_scope",
                    key.pool_id,
                    "Missing reservations may reduce this pool's capacity",
                )
            )
        if key in pool_conflicts:
            notes.append(
                issue(
                    "pool_conflict",
                    key.pool_id,
                    "Conflicting views of one physical pool",
                    "conflict",
                )
            )
        if key in ambiguous_reservation_pools:
            notes.append(
                issue(
                    "reservation_conflict",
                    key.pool_id,
                    "Conflicting reservations make capacity unknown",
                    "conflict",
                )
            )
        if pool.quantity is None:
            notes.append(issue("pool_quantity_unknown", key.pool_id, "Pool quantity is unknown"))
        if conversion(pool.unit, pool.unit) is None:
            notes.append(issue("pool_unit_unsupported", key.pool_id, "Missing or unsupported unit"))
        reserved = ZERO
        own = ZERO
        normalized = []
        for reservation in sorted(held[key], key=lambda row: row.reservation_id):
            reservation_notes = source_issues(
                reservation.ref, request.as_of, reservation.reservation_id
            )
            factor = conversion(reservation.unit, pool.unit)
            if reservation.quantity is None or factor is None:
                reservation_notes.append(
                    issue(
                        "reservation_quantity_incomparable",
                        reservation.reservation_id,
                        "Unknown quantity or incomparable reservation unit",
                    )
                )
            if reservation_notes:
                notes.extend(reservation_notes)
                continue
            value = reservation.quantity * factor
            reserved += value
            normalized.append((reservation, value))
            if reservation.build_id == request.basis.build.build_id:
                own += value
                if reservation.bom_item_id not in demand_ids:
                    notes.append(
                        issue(
                            "reservation_demand_missing",
                            reservation.reservation_id,
                            "Own reservation has no matching demand item",
                        )
                    )
        if pool.quantity is not None and reserved > pool.quantity:
            notes.append(
                issue(
                    "pool_overreserved",
                    key.pool_id,
                    "Active reservations exceed the physical pool balance",
                    "conflict",
                )
            )
        uncertain = bool(notes)
        actual = pool.stage in {"on_hand", "received"}
        if pool.availability == "unknown":
            notes.append(issue("availability_unknown", key.pool_id, "Usability is unknown"))
            uncertain = True
        if pool.quality == "unknown":
            notes.append(issue("quality_unknown", key.pool_id, "Quality release is unknown"))
            uncertain = True
        if pool.quality == "frozen":
            notes.append(
                issue("quality_frozen", key.pool_id, "Quality frozen stock excluded", "restriction")
            )
        if pool.availability == "unavailable":
            notes.append(
                issue("unavailable", key.pool_id, "Stock is explicitly unusable", "restriction")
            )
        if not actual:
            notes.append(
                issue(
                    "not_actual_stock",
                    key.pool_id,
                    f"{pool.stage} is not receipt or usable stock",
                    "restriction",
                )
            )
        permitted = (
            actual
            and not uncertain
            and pool.availability == "available"
            and pool.quality == "released"
        )
        pool_unknown[key] = actual and uncertain
        free[key] = max(pool.quantity - reserved, ZERO) if permitted else ZERO
        valid_held[key] = normalized if permitted else []
        observations.append(
            PoolObservation(
                key=key,
                stage=pool.stage,
                unit=pool.unit,
                quantity=pool.quantity,
                reserved_quantity=None if uncertain else reserved,
                unreserved_usable_quantity=None if pool_unknown[key] else free[key],
                own_secured_quantity=own if permitted else None if pool_unknown[key] else ZERO,
                source=pool.ref,
                issues=sorted_issues(notes),
            )
        )
        pool_notes[key] = notes
        problems.extend(notes)

    lines = []
    for demand in demands:
        notes = list(demand.issues)
        if demand.material_id is None:
            notes.append(
                issue("material_mapping_unknown", demand.item_id, "Material ID is unknown")
            )
        unknown = not request.supply_scope_complete or bool(supply_issues) or bool(notes)
        for key in held:
            if key not in pools and (
                key.material_id == demand.material_id
                or any(
                    a.target_material_id == demand.material_id
                    and a.alternate_material_id == key.material_id
                    for a in accepted
                )
            ):
                unknown = True
                notes.append(
                    issue(
                        "reservation_pool_missing",
                        demand.item_id,
                        "Demand has an active reservation in an absent pool",
                    )
                )
        secured = ZERO
        uses = []
        options = []
        for key, pool in pools.items():
            relevant = key.material_id == demand.material_id or any(
                a.target_material_id == demand.material_id
                and a.alternate_material_id == key.material_id
                for a in accepted
            )
            if not relevant:
                continue
            notes.extend(pool_notes[key])
            factor, qualification_id = ratio(demand, pool)
            if factor is None:
                unknown = True
                notes.append(
                    issue(
                        "supply_unit_or_qualification_conflict",
                        demand.item_id,
                        "Matching supply has incomparable units or qualified ratios",
                    )
                )
                continue
            unknown |= pool_unknown[key]
            options.append(
                (
                    qualification_id is not None,
                    key.source_system,
                    key.pool_id,
                    key.material_id,
                    key,
                    factor,
                    qualification_id,
                )
            )
        options.sort(key=lambda row: row[:4])
        for _, _, _, _, key, factor, qualification_id in options:
            for reservation, quantity in valid_held[key]:
                if (
                    reservation.build_id == request.basis.build.build_id
                    and reservation.bom_item_id == demand.item_id
                ):
                    secured += quantity / factor
                    uses.append(
                        SupplyUse(
                            pool=key,
                            quantity_in_pool_unit=quantity,
                            quantity_in_demand_unit=quantity / factor,
                            kind="secured",
                            reservation_id=reservation.reservation_id,
                            qualification_id=qualification_id,
                        )
                    )
        potential = secured
        required = demand.required_quantity
        if required is not None and demand.material_id is not None:
            for _, _, _, _, key, factor, qualification_id in options:
                if potential >= required:
                    break
                consumed = min(free[key], (required - potential) * factor)
                if consumed > 0:
                    free[key] -= consumed
                    potential += consumed / factor
                    uses.append(
                        SupplyUse(
                            pool=key,
                            quantity_in_pool_unit=consumed,
                            quantity_in_demand_unit=consumed / factor,
                            kind="unreserved_candidate",
                            qualification_id=qualification_id,
                        )
                    )

        secured_gap = _gap(secured, required, unknown)
        potential_gap = _gap(potential, required, unknown)
        lines.append(
            DemandCoverage(
                demand=demand,
                known_secured_quantity=secured,
                known_potential_quantity=potential,
                secured_gap=secured_gap,
                potential_gap=potential_gap,
                secured_ready=None if secured_gap is None else secured_gap == 0,
                potential_ready=None if potential_gap is None else potential_gap == 0,
                uses=tuple(uses),
                issues=sorted_issues(notes),
            )
        )
        problems.extend(notes)

    def readiness(rows, field):
        values = [getattr(row, field) for row in rows]
        if not values:
            return None
        if False in values:
            return False
        if scope_issues:
            return None
        return None if None in values else True

    return CoverageResult(
        input_sha256=digest(request),
        input_snapshot=request,
        secured_ready=readiness(lines, "secured_ready"),
        potential_ready=readiness(lines, "potential_ready"),
        critical_secured_ready=readiness(
            [row for row in lines if row.demand.critical], "secured_ready"
        ),
        lines=tuple(lines),
        pools=tuple(observations),
        issues=sorted_issues(problems),
    )
