"""Actual staging protocol with SQL/READY ports substituted; no real qualification claim."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from pdos_next.domain.test_resources import service as resources

from .harness import v2


@pytest.fixture
def staging(h, monkeypatch):
    new = resources
    h.at = h.clock = h.binding.window.start + timedelta(minutes=1)
    raw, record = v2(h)
    ready = raw[0].model_copy(
        update={"report": raw[0].report.model_copy(update={"status": "READY"})}
    )
    context = raw[1].model_copy(update={"qualified": True})
    current = (ready, context, *raw[2:])
    sinks = []
    state = SimpleNamespace(
        new=new,
        h=h,
        record=record,
        current=current,
        sinks=sinks,
        added=[],
        flushes=0,
        flush_hook=None,
        after_load=None,
        load_count=0,
    )

    class UOW:
        def get_bind(self):
            return h.engine

        def scalar(self, stmt):
            return SimpleNamespace(visibility="private")

        def add(self, row):
            state.added.append(row)
            if hasattr(row, "fingerprint_version"):
                h.existing = row

        def flush(self):
            state.flushes += 1
            if state.flush_hook:
                state.flush_hook()

    state.session = UOW()
    event = new.EventTime(
        occurred_at=h.clock,
        original_timezone="UTC",
        source=new.SourceRef(id=UUID(int=1000), revision=1, position="Actual source statement"),
    )
    state.event = event
    from pdos_next.domain.resource_readiness.rules import semantic_digest
    from pdos_next.schemas.resource_readiness.contracts import ReservationEvent

    state.reservation = new.Reservation(
        id=h.binding.run_id,
        revision=1,
        scope=context.scope,
        request=current[2],
        semantic_digest=semantic_digest(current[2]),
        state="formal",
        fixed_resources=ready.resources,
        report=ready.report,
        events=(ReservationEvent(kind="formal", at=h.clock, actor_id=h.ctx.requester_id),),
    )

    def substituted_load(*args, **kwargs):
        assert kwargs["_fingerprint_version"] == new._FINGERPRINT_V2
        sink = kwargs["_fingerprint_collector"]
        assert type(sink) is list and sink == []
        sinks.append(sink)
        sink.append(deepcopy(state.record))
        state.load_count += 1
        if state.after_load:
            state.after_load()
        return state.current

    monkeypatch.setattr(new, "_load", substituted_load)
    monkeypatch.setattr(new, "TestResourceReservation", lambda **fields: SimpleNamespace(**fields))
    monkeypatch.setattr(new, "_start_guard", lambda *args: event)
    state.ports = lambda: new._Ports(
        state.session,
        h.ctx,
        h.pid,
        h.binding,
        h.fact.id,
        h.fact.revision,
        intent="a" * 64,
        accepted=True,
        verified_actual_start=event,
        fingerprint_version=new._FINGERPRINT_V2,
        expected_facts_revision=record["facts_revision"],
    )

    class StructuralHandler:
        def __init__(self, facts, store):
            self.ports = store

        def preview(self, *args, **kwargs):
            return object()

        def stage_formal(self, *args, **kwargs):
            self.ports.stage(
                context,
                state.reservation,
                0,
                tuple(((key, row.occupancy_epoch) for key, row in h.assets.items())),
            )
            return SimpleNamespace(reservation=state.reservation, replayed=False)

    monkeypatch.setattr(new, "ResourceReservationHandler", StructuralHandler)
    state.start = lambda sink: new.stage_start(
        state.session,
        h.ctx,
        h.pid,
        h.binding,
        h.fact.id,
        h.fact.revision,
        expected_facts_revision=record["facts_revision"],
        intent_digest="a" * 64,
        accepted_confirmation=True,
        verified_actual_start=event,
        _fingerprint_version=new._FINGERPRINT_V2,
        _fingerprint_collector=sink,
    )
    return state


def test_every_fresh_call_owns_its_empty_list_and_full_record(staging):
    state = staging
    ports = state.ports()
    ports.fresh()
    ports.fresh()
    assert len(state.sinks) == 2 and state.sinks[0] is not state.sinks[1]
    assert ports.latest_record == state.record
    assert ports.latest_record is not state.sinks[-1][0]


def test_held_scope_port_reuses_only_same_real_transaction_and_mutation_epoch(staging):
    from pdos_next.request_proof import request_proof

    state = staging
    # A real SQLAlchemy transaction without database IO. Full resource loading
    # is substituted by this fixture; this does not attest real qualification.
    with Session(bind=state.h.engine) as session, session.begin():
        state.session = session
        proof = request_proof(session)
        proof.scope_locks.add(state.h.pid)
        ports = state.ports()
        first = ports.fresh()
        assert ports.fresh() is first and state.load_count == 1
        proof.mutation_epoch += 1
        ports.fresh()
        assert state.load_count == 2
        with session.begin_nested():
            ports.fresh()
            assert state.load_count == 3
        ports.fresh()
        assert state.load_count == 4
        state.h.engine._pdos_test_resource_issuer_epochs["unrelated-other-scope"] += 1
        ports.fresh()
        assert state.load_count == 5


@pytest.mark.parametrize("boundary", ["qualification", "window"])
def test_held_scope_port_checks_actual_deadline_on_each_cache_hit(staging, boundary):
    from pdos_next.request_proof import request_proof

    state = staging
    if boundary == "qualification":
        state.current = (
            state.current[0].model_copy(
                update={"valid_until": state.h.clock + timedelta(seconds=1)}
            ),
            *state.current[1:],
        )
    with Session(bind=state.h.engine) as session, session.begin():
        state.session = session
        request_proof(session).scope_locks.add(state.h.pid)
        ports = state.ports()
        ports.fresh()
        state.h.clock = (
            state.current[0].valid_until
            if boundary == "qualification"
            else state.h.binding.window.finish
        )
        with pytest.raises(state.new.DomainError) as error:
            ports.fresh()
        assert error.value.reason == "SOURCE_STALE" and state.load_count == 1


def test_stage_writes_identical_full_record_to_owner_before_single_caller_result(staging):
    state = staging
    sink = []
    result = state.start(sink)
    row = state.h.existing
    assert state.flushes == 1 and len(state.added) == 4
    assert row.fingerprint_version == state.new._FINGERPRINT_V2
    assert row.dependency_proof == state.record == sink[0]
    assert row.dependency_proof is not sink[0]
    assert result.facts_revision == row.facts_revision == state.record["facts_revision"]
    assert result.owner_run_id == result.reservation_id == row.run_id
    assert len(result.occupancy_ids) == 2 and len(result.sample_usage_ids) == 1
    assert all(asset.occupancy_epoch == 6 for asset in state.h.assets.values())
    assert all(sentinel.epoch == 5 for sentinel in state.h.sentinels.values())
    assert result.replayed is False


@pytest.mark.parametrize("change", ["full-record", "facts-revision"])
def test_every_fresh_call_stays_bound_to_trusted_expected_facts(staging, change):
    state = staging
    if change == "full-record":
        state.record = deepcopy(state.record)
        state.record["material"]["assets"][0]["sha256"] = "e" * 64
        state.record = state.new._stored_fingerprint_v2(state.record["material"])
    else:
        state.current = (
            state.current[0].model_copy(update={"facts_revision": "e" * 64}),
            *state.current[1:],
        )
    sink = []
    with pytest.raises(state.new.DomainError):
        state.start(sink)
    assert sink == [] and state.added == [] and (state.flushes == 0)


def test_runtime_changes_during_fresh_owner_io_are_rejected(staging):
    state = staging
    state.after_load = lambda: state.h.engine._pdos_test_resource_issuer_epochs.update(
        {"unrelated-other-scope": 100}
    )
    with pytest.raises(state.new.DomainError) as error:
        state.ports().fresh()
    assert error.value.reason == "SOURCE_STALE" and state.added == []


def test_current_io_after_material_collection_still_guards_runtime_before_effects(
    staging, monkeypatch
):
    state = staging
    monkeypatch.setattr(
        state.new,
        "_sources",
        lambda *args: state.h.engine._pdos_test_resource_issuer_epochs.update(
            {"unrelated-other-scope": 100}
        ),
    )
    sink = []
    with pytest.raises(state.new.DomainError) as error:
        state.start(sink)
    assert error.value.reason == "SOURCE_STALE" and sink == [] and (state.added == [])


@pytest.mark.parametrize("change", ["runtime", "proof", "window", "qualification", "collector"])
def test_flush_and_final_owner_io_cannot_export_a_stale_or_changed_record(staging, change):
    state = staging
    sink = []
    if change == "runtime":
        state.flush_hook = lambda: state.h.engine._pdos_test_resource_issuer_epochs.update(
            {"unrelated-other-scope": 100}
        )
    elif change == "proof":
        state.flush_hook = lambda: state.h.existing.dependency_proof.update(
            {"facts_revision": "f" * 64}
        )
    elif change == "window":
        state.flush_hook = lambda: setattr(state.h, "clock", state.h.binding.window.finish)
    elif change == "qualification":
        state.current = (
            state.current[0].model_copy(
                update={"valid_until": state.h.clock + timedelta(seconds=1)}
            ),
            *state.current[1:],
        )
        state.flush_hook = lambda: setattr(state.h, "clock", state.h.clock + timedelta(seconds=1))
    else:
        state.flush_hook = lambda: sink.append({"external": "changed"})
    with pytest.raises((state.new.DomainError, TypeError)):
        state.start(sink)
    assert state.flushes == 1
    assert sink == ([{"external": "changed"}] if change == "collector" else [])


@pytest.mark.parametrize("sink", [None, {}, [{}]])
def test_invalid_v2_sink_fails_before_any_owner_io(staging, sink):
    state = staging
    with pytest.raises((state.new.DomainError, TypeError)):
        state.start(sink)
    assert state.load_count == state.flushes == 0 and state.added == []


def test_default_v1_stage_does_not_accept_or_infer_a_v2_collector(staging):
    state = staging
    with pytest.raises(state.new.DomainError):
        state.new.stage_start(
            state.session,
            state.h.ctx,
            state.h.pid,
            state.h.binding,
            state.h.fact.id,
            state.h.fact.revision,
            expected_facts_revision=state.record["facts_revision"],
            intent_digest="a" * 64,
            accepted_confirmation=True,
            verified_actual_start=state.event,
            _fingerprint_collector=[],
        )
    assert state.load_count == state.flushes == 0 and state.added == []
