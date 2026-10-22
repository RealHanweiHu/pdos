"""Explicit synthetic caller UOW; no database, shared services or SampleUnit implementation."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import RLock
from uuid import UUID, uuid4

from pdos_next.domain.resource_readiness.handlers import ResourceError, ResourceReservationHandler
from pdos_next.engines.planning.calendar import frozen_timezone
from pdos_next.engines.planning.dto import CalendarSnapshot, WeekdaySchedule, WorkInterval
from pdos_next.schemas.resource_readiness.contracts import (
    ExecutionWindow,
    Occupancy,
    QualificationFact,
    ReservationRequest,
    ResourceContext,
    ResourceRef,
    ResourceSnapshot,
    ResourceUse,
)
from pdos_next.schemas.verification.contracts import Scope, SourceRef

NOW = datetime(2026, 10, 2, 8, tzinfo=UTC)


def source(i=1):
    return SourceRef(id=UUID(int=i), revision=1, kind="domain", position="synthetic fixed fact")


def window(start=9, finish=10):
    return ExecutionWindow(
        start=NOW.replace(hour=start), finish=NOW.replace(hour=finish), original_timezone="UTC"
    )


def request(kind="fixture", *, owner=None, resource_id=None, units="1"):
    ref = ResourceRef(id=resource_id or UUID(int=11), revision=1, kind=kind)
    return ReservationRequest(
        reservation_id=uuid4(),
        owner_run_id=owner or uuid4(),
        intent_key="reservation-intent",
        purpose="quality-test",
        operation_id="operation-1",
        window=window(),
        uses=(ResourceUse(resource=ref, units=Decimal(units)),),
    )


def context(req, **updates):
    values = dict(
        scope=Scope(tenant_id=UUID(int=100), product_id=UUID(int=101), project_id=UUID(int=102)),
        actor_id=UUID(int=103),
        owner_run_id=req.owner_run_id,
        executor_id=req.uses[0].resource.id,
        now=NOW,
        authorized=True,
        qualified=True,
        cancelled=False,
        sources_current=True,
        policy_registered=True,
        facts_revision="authority-1",
        purpose=req.purpose,
        operation_id=req.operation_id,
        required_resources=req.uses,
    )
    values.update(updates)
    return ResourceContext(**values)


def snapshot(req, ctx):
    ref = req.uses[0].resource
    kinds = {
        "fixture": ("acceptance",),
        "equipment": ("acceptance", "calibration"),
        "person": ("qualification",),
        "line": ("acceptance",),
        "tooling": ("acceptance",),
    }
    facts = tuple(
        QualificationFact(
            kind=kind,
            source=source(20 + n),
            purpose=req.purpose,
            operation_id=req.operation_id,
            status="accepted",
            valid_from=NOW - timedelta(days=30),
            valid_until=NOW + timedelta(days=30),
            named_decision_id=UUID(int=200 + n),
            actor_id=UUID(int=103),
        )
        for n, kind in enumerate(kinds[ref.kind])
    )
    calendar = CalendarSnapshot(
        calendar_id="synthetic-calendar",
        version="1",
        timezone="UTC",
        timezone_rules_sha256=frozen_timezone("UTC")[1],
        weekly=tuple(
            WeekdaySchedule(weekday=i, intervals=(WorkInterval(start_minute=0, end_minute=1440),))
            for i in range(7)
        ),
    )
    return ResourceSnapshot(
        ref=ref,
        scope=ctx.scope,
        source=source(30),
        purposes=(req.purpose,),
        operation_ids=(req.operation_id,),
        lifecycle="active",
        facts=facts,
        maintenance=(),
        calendar=calendar,
        calendar_source=source(31),
        capacity=Decimal(1),
        occupancy_revision=1,
    )


class SyntheticHost:
    def __init__(self, req):
        self.contexts = {req.owner_run_id: context(req)}
        self.snapshots = {req.uses[0].resource.id: snapshot(req, self.contexts[req.owner_run_id])}
        self.records = {}
        self.consumed = set()  # Test-only stand-in for a separate caller sample mutation.
        self.confirmed = set()
        self.receipts = []
        self.fail_stage = False
        self.fail_cas = False
        self.sources = {}
        self.lock_orders = []
        self.mutex = RLock()
        self.in_uow = False
        self.handler = ResourceReservationHandler(self, self)

    @contextmanager
    def uow(self):
        # Emulates abort-whole-UOW; serializes transactions, not a DB concurrency proof.
        with self.mutex:
            before = deepcopy(
                (self.records, self.snapshots, self.confirmed, self.consumed, self.receipts)
            )
            self.in_uow = True
            try:
                yield self
            except Exception:
                (self.records, self.snapshots, self.confirmed, self.consumed, self.receipts) = (
                    before
                )
                raise
            finally:
                self.in_uow = False

    def context(self, owner_run_id, purpose, operation_id):
        return self.contexts[owner_run_id]

    def resources(self, ctx, ids):
        return tuple(
            self.snapshots[i].model_copy(update={"scope": ctx.scope})
            for i in ids
            if i in self.snapshots
        )

    def source_status(self, ctx, ref):
        return self.sources.get(ref.id, "current")

    def lock(self, ctx, req):
        assert self.in_uow, "host mutation requires caller UOW"
        self.lock_orders.append(
            tuple(sorted((u.resource.id for u in req.uses), key=lambda i: i.bytes))
        )

    def find(self, ctx, req):
        for record in self.records.values():
            if record.scope != ctx.scope:
                if record.id == req.reservation_id:
                    raise ResourceError("identity_conflict", "ID belongs to different scope")
                continue
            if (
                record.request.owner_run_id == req.owner_run_id
                or record.id == req.reservation_id
                or record.request.intent_key == req.intent_key
            ):
                if record.request.owner_run_id != req.owner_run_id:
                    raise ResourceError(
                        "identity_conflict", "Key/ID already attached to another run"
                    )
                return record
        return None

    def occupancies(self, ctx, ids):
        return tuple(
            Occupancy(
                reservation_id=r.id,
                resource_id=u.resource.id,
                window=r.request.window,
                units=u.units,
            )
            for r in self.records.values()
            if r.state == "formal"
            for u in r.request.uses
            if u.resource.id in ids
        )

    def confirm(self, ctx, preview):
        assert self.in_uow
        if preview.digest in self.confirmed:
            raise ResourceError("proof_consumed", "Proof has already been consumed")
        self.confirmed.add(preview.digest)

    def stage(self, ctx, record, expected_revision, expected_occupancy_revisions):
        assert self.in_uow
        for rid, revision in expected_occupancy_revisions:
            if self.fail_cas or self.snapshots[rid].occupancy_revision != revision:
                raise ResourceError("occupancy_cas", "Occupancy changed")
        old = self.records.get(record.id)
        if (old.revision if old else 0) != expected_revision:
            raise ResourceError("reservation_cas", "Reservation changed")
        self.records[record.id] = record
        for rid, revision in expected_occupancy_revisions:
            self.snapshots[rid] = self.snapshots[rid].model_copy(
                update={"occupancy_revision": revision + 1}
            )
        if self.fail_stage:
            raise RuntimeError("synthetic failure after resource staging")


def staged(host, req):
    preview = host.handler.preview(req)
    with host.uow():
        return host.handler.stage_formal(req, preview)
