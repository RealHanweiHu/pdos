"""Deterministic readiness with hard-block priority and half-open capacity sweeps."""

import hashlib
import json
from datetime import timedelta
from decimal import Decimal, localcontext

from pdos_next.engines.planning.calendar import CalendarError, WorkingTime
from pdos_next.schemas.resource_readiness.contracts import (
    Check,
    ExecutionWindow,
    Occupancy,
    ReadinessReport,
    ReservationRequest,
    ResourceContext,
    ResourceSnapshot,
    Status,
)

RULE_VERSION = "resource-readiness.v1"


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def semantic_digest(request: ReservationRequest) -> str:
    # Key aliases do not create a second semantic reservation.
    data = request.model_dump(mode="json", exclude={"intent_key"})
    with localcontext() as ctx:
        ctx.prec = 60
        for use in data["uses"]:
            use["units"] = format(Decimal(use["units"]).normalize(), "f")
    data["uses"] = sorted(data["uses"], key=lambda u: u["resource"]["id"])
    return digest(data)


def overlap(a: ExecutionWindow, b: ExecutionWindow) -> bool:
    return a.start < b.finish and b.start < a.finish


def aggregate(checks: tuple[Check, ...]) -> Status:
    for status in ("BLOCKED", "UNKNOWN", "READY_WITH_CONDITIONS"):
        if any(c.status == status for c in checks):
            return status
    return "READY"


def capacity_exceeded(
    window: ExecutionWindow, units: Decimal, capacity: Decimal, occupancies: tuple[Occupancy, ...]
) -> bool:
    # Integrate exact Decimal units. Boundary ties aggregate before comparison.
    with localcontext() as ctx:
        ctx.prec = 60
        points: dict = {window.start: units, window.finish: -units}
        for item in occupancies:
            if not overlap(window, item.window):
                continue
            left, right = (
                max(window.start, item.window.start),
                min(window.finish, item.window.finish),
            )
            points[left] = points.get(left, Decimal(0)) + item.units
            points[right] = points.get(right, Decimal(0)) - item.units
        total = Decimal(0)
        for at, delta in sorted(points.items()):
            total += delta
            if at < window.finish and total > capacity:
                return True
    return False


def evaluate(
    context: ResourceContext,
    request: ReservationRequest,
    snapshots: tuple[ResourceSnapshot, ...],
    occupancies: tuple[Occupancy, ...],
    source_checks: tuple[Check, ...] = (),
    *,
    exclude_reservation_id=None,
) -> ReadinessReport:
    checks = list(source_checks)
    conditions = []

    def add(code, status, detail, snapshot=None, source=None):
        checks.append(
            Check(
                resource=snapshot.ref if snapshot else None,
                code=code,
                status=status,
                detail=detail,
                source=source,
            )
        )

    if not context.authorized or context.cancelled:
        add("authority_denied", "BLOCKED", "Current permission revoked or owning run cancelled")
    if context.qualified is not True:
        add(
            "authority_qualification",
            "UNKNOWN" if context.qualified is None else "BLOCKED",
            "Current applicable qualification is missing or invalid",
        )
    if context.sources_current is not True:
        add(
            "current_sources",
            "UNKNOWN" if context.sources_current is None else "BLOCKED",
            "Owning run readset is missing, withdrawn or changed",
        )
    if not context.policy_registered:
        add(
            "policy_unregistered",
            "UNKNOWN",
            "Action policy is not registered; integration required",
        )
    if context.owner_run_id != request.owner_run_id:
        add("owner_mismatch", "BLOCKED", "Reservation owner differs from server-bound run")
    if request.window.finish <= context.now:
        add("execution_elapsed", "BLOCKED", "Execution interval has ended; no new valid execution")
    if (
        context.purpose != request.purpose
        or context.operation_id != request.operation_id
        or set(context.required_resources) != set(request.uses)
    ):
        add(
            "required_scope_mismatch",
            "BLOCKED",
            "Resources/purpose differ from server-required run set",
        )
    by_id = {s.ref.id: s for s in snapshots}
    if len(by_id) != len(snapshots) or set(by_id) - {u.resource.id for u in request.uses}:
        add(
            "invalid_snapshot_set",
            "BLOCKED",
            "Server resource snapshot is duplicate or out of scope",
        )
    if len({(o.reservation_id, o.resource_id) for o in occupancies}) != len(occupancies):
        add("invalid_occupancy_set", "UNKNOWN", "Occupancy projection duplicates a resource bundle")
    capacity_sources = {s.source for s in snapshots} | {
        s.calendar_source for s in snapshots if s.calendar_source is not None
    }
    capacity_status = (
        "unknown"
        if any(c.source in capacity_sources and c.status != "READY" for c in source_checks)
        else "checked"
    )
    for use in sorted(request.uses, key=lambda u: u.resource.id.bytes):
        snapshot = by_id.get(use.resource.id)
        if snapshot is None:
            add("resource_missing", "UNKNOWN", f"Resource {use.resource.id} facts are missing")
            capacity_status = "unknown" if capacity_status != "conflicted" else capacity_status
            continue
        if snapshot.scope != context.scope or snapshot.ref != use.resource:
            add(
                "resource_changed",
                "BLOCKED",
                "Fixed resource version/kind or applicability changed",
                snapshot,
            )
        if snapshot.lifecycle != "active":
            add(
                "lifecycle",
                "UNKNOWN" if snapshot.lifecycle == "unknown" else "BLOCKED",
                "Resource lifecycle is unknown or withdrawn",
                snapshot,
            )
        if (
            request.purpose not in snapshot.purposes
            or request.operation_id not in snapshot.operation_ids
        ):
            add(
                "inapplicable",
                "BLOCKED",
                "Resource does not cover this purpose/operation",
                snapshot,
            )
        assigned = set(context.assigned_person_ids) or {context.executor_id}
        if snapshot.ref.kind == "person" and snapshot.ref.id not in assigned:
            # Every crew member comes from the server's run/staffing assignment.
            add(
                "executor_mismatch",
                "BLOCKED",
                "Person differs from server-bound executor/crew",
                snapshot,
            )
        defaults = {
            "fixture": {"acceptance"},
            "equipment": {"acceptance", "calibration"},
            "person": {"qualification"},
            "line": {"acceptance"},
            "tooling": {"acceptance"},
        }
        required = defaults[snapshot.ref.kind] | set(snapshot.required_facts)
        for kind in sorted(required):
            fact = next(
                (
                    f
                    for f in snapshot.facts
                    if f.kind == kind
                    and f.purpose == request.purpose
                    and f.operation_id == request.operation_id
                ),
                None,
            )
            if fact is None or fact.status == "unknown":
                add(f"{kind}_missing", "UNKNOWN", f"Required {kind} evidence is missing", snapshot)
            elif fact.status != "accepted":
                add(
                    f"{kind}_invalid",
                    "BLOCKED",
                    f"Required {kind} is {fact.status}",
                    snapshot,
                    fact.source,
                )
            elif kind in {"calibration", "qualification"} and (
                fact.valid_from is None or fact.valid_until is None
            ):
                add(
                    f"{kind}_validity_unknown",
                    "UNKNOWN",
                    "Full validity interval is unknown",
                    snapshot,
                    fact.source,
                )
            elif (fact.valid_from is not None and fact.valid_from > request.window.start) or (
                fact.valid_until is not None and fact.valid_until < request.window.finish
            ):
                add(
                    f"{kind}_out_of_window",
                    "BLOCKED",
                    "Qualification does not cover full execution",
                    snapshot,
                    fact.source,
                )
            elif fact.conditions:
                missing = set(fact.conditions) - set(context.approved_conditions)
                add(
                    f"{kind}_conditions",
                    "BLOCKED" if missing else "READY_WITH_CONDITIONS",
                    "Unmet execution limits" if missing else "Named limits remain applicable",
                    snapshot,
                    fact.source,
                )
                conditions.extend(fact.conditions)
            else:
                add(
                    f"{kind}_valid",
                    "READY",
                    "Named fact covers full execution",
                    snapshot,
                    fact.source,
                )
        if snapshot.maintenance is None:
            add("maintenance_missing", "UNKNOWN", "Current maintenance facts are missing", snapshot)
        else:
            for maintenance in snapshot.maintenance:
                if overlap(maintenance.window, request.window):
                    if maintenance.status in ("planned", "active", "unknown"):
                        add(
                            "maintenance_overlap",
                            "UNKNOWN" if maintenance.status == "unknown" else "BLOCKED",
                            "Maintenance overlaps execution",
                            snapshot,
                            maintenance.source,
                        )
        if snapshot.calendar is None:
            add("calendar_missing", "UNKNOWN", "Current calendar is missing", snapshot)
            if capacity_status != "conflicted":
                capacity_status = "unknown"
        elif snapshot.calendar.timezone_rules_sha256 is None:
            add(
                "calendar_rules_unpinned",
                "UNKNOWN",
                "Current TZif rule digest is missing",
                snapshot,
            )
            if capacity_status != "conflicted":
                capacity_status = "unknown"
        else:
            try:
                # Use frozen calendar intervals directly, retaining exact subminute boundaries.
                clock = WorkingTime(snapshot.calendar, horizon_days=3660)
                first = request.window.start.astimezone(clock.zone).date()
                last = (
                    (request.window.finish - timedelta(microseconds=1))
                    .astimezone(clock.zone)
                    .date()
                )
                segments = tuple(
                    segment
                    for day in range((last - first).days + 1)
                    for segment in clock.intervals(first + timedelta(days=day))
                )
                cursor = request.window.start
                for left, right in segments:
                    if right <= cursor:
                        continue
                    if left > cursor:
                        break
                    cursor = max(cursor, right)
                if cursor < request.window.finish:
                    add(
                        "calendar_closed",
                        "BLOCKED",
                        "Calendar does not cover continuous execution",
                        snapshot,
                    )
                    capacity_status = "conflicted"
            except (CalendarError, ValueError, OverflowError) as exc:
                add("calendar_unusable", "UNKNOWN", f"Calendar cannot be verified: {exc}", snapshot)
                if capacity_status != "conflicted":
                    capacity_status = "unknown"
        if snapshot.capacity is None:
            add("capacity_missing", "UNKNOWN", "Current capacity is unknown", snapshot)
            if capacity_status != "conflicted":
                capacity_status = "unknown"
        elif capacity_exceeded(
            request.window,
            use.units,
            snapshot.capacity,
            tuple(
                o
                for o in occupancies
                if o.resource_id == use.resource.id and o.reservation_id != exclude_reservation_id
            ),
        ):
            add(
                "capacity_conflict",
                "BLOCKED",
                "Formal reservations exceed interval capacity",
                snapshot,
            )
            capacity_status = "conflicted"
        else:
            add(
                "capacity_available",
                "READY",
                "Capacity checked; this is not a reservation",
                snapshot,
            )
    frozen = tuple(sorted(snapshots, key=lambda s: s.ref.id.bytes))
    readset = {
        "rule": RULE_VERSION,
        "request": semantic_digest(request),
        "context": context.model_dump(mode="json", exclude={"now"}),
        "resources": [s.model_dump(mode="json") for s in frozen],
        "occupancies": sorted(
            [o.model_dump(mode="json") for o in occupancies],
            key=lambda o: (o["resource_id"], o["reservation_id"]),
        ),
        "source_checks": [c.model_dump(mode="json") for c in source_checks],
    }
    return ReadinessReport(
        status=aggregate(tuple(checks)),
        capacity_status=capacity_status,
        checks=tuple(checks),
        fixed_resources=frozen,
        input_digest=digest(readset),
        checked_at=context.now,
        conditions=tuple(sorted(set(conditions))),
    )
