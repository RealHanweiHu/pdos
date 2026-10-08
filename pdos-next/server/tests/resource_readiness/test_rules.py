from datetime import timedelta
from decimal import Decimal, localcontext
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.resource_readiness.rules import capacity_exceeded, evaluate, semantic_digest
from pdos_next.schemas.resource_readiness.contracts import (
    ExecutionWindow,
    MaintenanceFact,
    Occupancy,
    QualificationFact,
    ReservationRequest,
)

from .support import NOW, context, request, snapshot, source, window


def report(req=None, **updates):
    req = req or request()
    ctx = context(req)
    if updates.get("calendar", "unchanged") is None:
        updates["calendar_source"] = None
    snap = snapshot(req, ctx).model_copy(update=updates)
    return evaluate(ctx, req, (snap,), ())


@pytest.mark.parametrize("kind", ["equipment", "fixture", "person", "line", "tooling"])
def test_named_facts_ready_for_each_kind(kind):
    result = report(request(kind))
    assert result.status == "READY"
    assert result.capacity_status == "checked"


@pytest.mark.parametrize(
    "field,value",
    [
        ("facts", ()),
        ("maintenance", None),
        ("capacity", None),
        ("lifecycle", "unknown"),
        ("calendar", None),
    ],
)
def test_missing_facts_are_unknown(field, value):
    assert report(**{field: value}).status == "UNKNOWN"


@pytest.mark.parametrize("status", ["rejected", "revoked"])
def test_explicit_fixture_nonacceptance_blocks(status):
    req = request()
    snap = snapshot(req, context(req))
    fact = snap.facts[0].model_copy(update={"status": status})
    result = report(req, facts=(fact,), capacity=None)
    assert result.status == "BLOCKED"
    assert any(c.status == "UNKNOWN" for c in result.checks)


@pytest.mark.parametrize("kind", ["equipment", "person"])
@pytest.mark.parametrize("change", ["ends_before_finish", "starts_after_start", "missing_until"])
def test_qualification_full_window(kind, change):
    req = request(kind)
    snap = snapshot(req, context(req))
    facts = list(snap.facts)
    field = "valid_from" if change == "starts_after_start" else "valid_until"
    value = (
        req.window.start + timedelta(seconds=1)
        if field == "valid_from"
        else req.window.finish - timedelta(seconds=1)
    )
    if change == "missing_until":
        value = None
    facts[-1] = facts[-1].model_copy(update={field: value})
    assert report(req, facts=tuple(facts)).status == (
        "UNKNOWN" if change == "missing_until" else "BLOCKED"
    )


def test_validity_exclusive_finish_equality_covers_half_open_execution():
    req = request("person")
    fact = (
        snapshot(req, context(req))
        .facts[0]
        .model_copy(update={"valid_from": req.window.start, "valid_until": req.window.finish})
    )
    assert report(req, facts=(fact,)).status == "READY"


def test_conditions_require_current_host_allowance_and_do_not_waive_expiry():
    req = request()
    ctx = context(req, approved_conditions=("speed <= 10",))
    snap = snapshot(req, ctx)
    fact = snap.facts[0].model_copy(update={"conditions": ("speed <= 10",)})
    snap = snap.model_copy(update={"facts": (fact,)})
    assert evaluate(context(req), req, (snap,), ()).status == "BLOCKED"
    result = evaluate(ctx, req, (snap,), ())
    assert result.status == "READY_WITH_CONDITIONS" and result.conditions == ("speed <= 10",)
    fact = fact.model_copy(update={"valid_until": req.window.finish - timedelta(seconds=1)})
    assert evaluate(ctx, req, (snap.model_copy(update={"facts": (fact,)}),), ()).status == "BLOCKED"


@pytest.mark.parametrize(
    "status,expected",
    [
        ("planned", "BLOCKED"),
        ("active", "BLOCKED"),
        ("unknown", "UNKNOWN"),
        ("completed", "READY"),
        ("cancelled", "READY"),
    ],
)
def test_maintenance_statuses(status, expected):
    item = MaintenanceFact(window=window(), source=source(), status=status)
    assert report(maintenance=(item,)).status == expected


def test_maintenance_boundary_is_half_open():
    item = MaintenanceFact(window=window(10, 11), source=source(), status="active")
    assert report(maintenance=(item,)).status == "READY"


@pytest.mark.parametrize(
    "update,expected",
    [
        ({"authorized": False}, "BLOCKED"),
        ({"cancelled": True}, "BLOCKED"),
        ({"qualified": None}, "UNKNOWN"),
        ({"qualified": False}, "BLOCKED"),
        ({"sources_current": None}, "UNKNOWN"),
        ({"sources_current": False}, "BLOCKED"),
        ({"policy_registered": False}, "UNKNOWN"),
        ({"purpose": "wrong"}, "BLOCKED"),
        ({"owner_run_id": UUID(int=999)}, "BLOCKED"),
    ],
)
def test_server_authority_never_payload_fact(update, expected):
    req = request()
    ctx = context(req, **update)
    assert evaluate(ctx, req, (snapshot(req, ctx),), ()).status == expected


def test_required_units_cannot_be_understated_and_person_must_match_executor():
    req = request(units="0.5")
    ctx = context(req, required_resources=request(units="1").uses)
    assert evaluate(ctx, req, (snapshot(req, ctx),), ()).status == "BLOCKED"
    req = request("person")
    ctx = context(req, executor_id=uuid4())
    assert evaluate(ctx, req, (snapshot(req, ctx),), ()).status == "BLOCKED"


def test_fixed_resource_version_and_purpose_cannot_drift():
    req = request()
    snap = snapshot(req, context(req))
    for update in (
        {"ref": snap.ref.model_copy(update={"revision": 2})},
        {"purposes": ("other",)},
        {"operation_ids": ("other",)},
        {"lifecycle": "withdrawn"},
    ):
        assert (
            evaluate(context(req), req, (snap.model_copy(update=update),), ()).status == "BLOCKED"
        )


def test_capacity_checked_does_not_imply_qualification_or_reservation():
    result = report(facts=())
    assert result.capacity_status == "checked"
    assert result.status == "UNKNOWN"
    assert not hasattr(result, "reservation_id")


def test_missing_resource_preserves_unknown():
    req = request()
    assert evaluate(context(req), req, (), ()).status == "UNKNOWN"


def test_duplicate_resource_or_occupancy_projections_fail_closed():
    req = request()
    ctx = context(req)
    snap = snapshot(req, ctx)
    assert evaluate(ctx, req, (snap, snap), ()).status == "BLOCKED"
    req = req.model_copy(
        update={"uses": (req.uses[0].model_copy(update={"units": Decimal("0.5")}),)}
    )
    ctx = context(req)
    occ = Occupancy(reservation_id=uuid4(), resource_id=snap.ref.id, window=window(), units="0.1")
    assert evaluate(ctx, req, (snap,), (occ, occ)).status == "UNKNOWN"


@pytest.mark.parametrize(
    "start,finish,conflict",
    [(10, 11, False), (8, 9, False), (9, 10, True), (8, 10, True), (9, 11, True)],
)
def test_capacity_half_open_boundaries(start, finish, conflict):
    occ = Occupancy(
        reservation_id=uuid4(), resource_id=UUID(int=11), window=window(start, finish), units="1"
    )
    assert capacity_exceeded(window(), Decimal(1), Decimal(1), (occ,)) is conflict


def test_capacity_sweep_does_not_sum_nonoverlapping_occupants():
    start = window().start
    a = window().model_copy(update={"finish": start + timedelta(minutes=30)})
    b = window().model_copy(update={"start": start + timedelta(minutes=30)})
    occ = tuple(
        Occupancy(reservation_id=uuid4(), resource_id=UUID(int=11), window=w, units="0.5")
        for w in (a, b)
    )
    assert not capacity_exceeded(window(), Decimal("0.5"), Decimal(1), occ)
    with localcontext() as ctx:
        ctx.prec = 3
        assert capacity_exceeded(window(), Decimal("0.500000000001"), Decimal(1), occ)


def test_frozen_calendar_rules_and_full_interval():
    req = request()
    snap = snapshot(req, context(req))
    assert (
        report(
            req, calendar=snap.calendar.model_copy(update={"timezone_rules_sha256": "0" * 64})
        ).status
        == "UNKNOWN"
    )
    assert (
        report(
            req, calendar=snap.calendar.model_copy(update={"timezone_rules_sha256": None})
        ).status
        == "UNKNOWN"
    )
    assert report(req, calendar=snap.calendar.model_copy(update={"weekly": ()})).status == "BLOCKED"


def test_exact_subminute_execution_uses_raw_calendar_intervals():
    req = request()
    req = req.model_copy(
        update={
            "window": req.window.model_copy(
                update={
                    "start": req.window.start + timedelta(seconds=15),
                    "finish": req.window.finish - timedelta(seconds=15),
                }
            )
        }
    )
    assert report(req).status == "READY"


def test_digest_ignores_key_alias_and_resource_order_but_keeps_fixed_content():
    req = request()
    assert semantic_digest(req) == semantic_digest(
        req.model_copy(update={"intent_key": "other-key"})
    )
    assert semantic_digest(req) != semantic_digest(req.model_copy(update={"purpose": "other"}))


@pytest.mark.parametrize(
    "extra", ["tenant_id", "authorized", "qualified", "executor_id", "write_tier"]
)
def test_request_rejects_authority_fields(extra):
    values = request().model_dump()
    values[extra] = "invented"
    with pytest.raises(ValidationError):
        ReservationRequest.model_validate(values)


@pytest.mark.parametrize("start,finish", [(NOW, NOW), (NOW, NOW - timedelta(minutes=1))])
def test_nonpositive_execution_rejected(start, finish):
    with pytest.raises(ValidationError):
        ExecutionWindow(start=start, finish=finish, original_timezone="UTC")


def test_naive_invalid_timezone_and_unbounded_precision_rejected():
    with pytest.raises(ValidationError):
        ExecutionWindow(start=NOW.replace(tzinfo=None), finish=NOW, original_timezone="UTC")
    with pytest.raises(ValidationError):
        ExecutionWindow(
            start=NOW, finish=NOW + timedelta(hours=1), original_timezone="invalid/zone"
        )
    with pytest.raises(ValidationError):
        request(units="0.0000000000001")


def test_accepted_fact_requires_existing_named_identity():
    with pytest.raises(ValidationError):
        QualificationFact(
            kind="acceptance", source=source(), purpose="test", operation_id="op", status="accepted"
        )


def test_context_never_promotes_future_actual_to_fact():
    req = request()
    with pytest.raises(ValidationError):
        context(req, verified_actual_start=req.window.start)


def test_semantic_decimal_quantity_is_canonical_despite_text_and_global_precision():
    req = request(units="0.500000000000")
    equivalent = req.model_copy(
        update={"uses": (req.uses[0].model_copy(update={"units": Decimal("0.5")}),)}
    )
    with localcontext() as ctx:
        ctx.prec = 3
        assert semantic_digest(req) == semantic_digest(equivalent)


@pytest.mark.parametrize(
    "start,finish",
    [
        ("2026-03-08T08:00:00+00:00", "2026-03-09T07:00:00+00:00"),
        ("2026-11-01T07:00:00+00:00", "2026-11-02T08:00:00+00:00"),
    ],
)
def test_resource_continuous_calendar_across_la_dst_days(start, finish):
    from datetime import datetime

    from pdos_next.engines.planning.calendar import frozen_timezone

    req = request()
    interval = ExecutionWindow(start=start, finish=finish, original_timezone="America/Los_Angeles")
    req = req.model_copy(update={"window": interval})
    ctx = context(req, now=datetime.fromisoformat(start) - timedelta(hours=1))
    snap = snapshot(req, ctx)
    facts = tuple(
        f.model_copy(
            update={
                "valid_from": interval.start - timedelta(days=1),
                "valid_until": interval.finish + timedelta(days=1),
            }
        )
        for f in snap.facts
    )
    calendar = snap.calendar.model_copy(
        update={
            "timezone": "America/Los_Angeles",
            "timezone_rules_sha256": frozen_timezone("America/Los_Angeles")[1],
        }
    )
    snap = snap.model_copy(update={"facts": facts, "calendar": calendar})
    assert evaluate(ctx, req, (snap,), ()).status == "READY"


def test_server_bound_crew_checks_each_person_qualification():
    req = request("person")
    second = req.uses[0].model_copy(
        update={"resource": req.uses[0].resource.model_copy(update={"id": UUID(int=12)})}
    )
    req = req.model_copy(update={"uses": (*req.uses, second)})
    ctx = context(req, assigned_person_ids=(UUID(int=11), UUID(int=12)))
    one = snapshot(req, ctx)
    other_req = req.model_copy(update={"uses": (second,)})
    two = snapshot(other_req, ctx)
    assert evaluate(ctx, req, (one, two), ()).status == "READY"
    two = two.model_copy(update={"facts": (two.facts[0].model_copy(update={"status": "revoked"}),)})
    assert evaluate(ctx, req, (one, two), ()).status == "BLOCKED"
