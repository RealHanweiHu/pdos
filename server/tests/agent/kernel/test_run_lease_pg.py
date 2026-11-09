"""D243/D358: the per-run lease keeps Activity attempts from overlapping."""

import threading
import time
from contextlib import ExitStack
from uuid import uuid4

import pytest
from sqlalchemy import text
from temporalio.exceptions import CancelledError

from pdos_next.agent.kernel import activities
from pdos_next.agent.kernel.run_lease import RunBusy, RunLease, check_attempt, run_lease
from tests.agent.kernel.test_run_attempts import RUN, Store, owned


def test_one_holder_per_run_and_other_runs_are_independent(engines):
    engine, run = engines[1], uuid4()
    with run_lease(engine, run):
        with pytest.raises(RunBusy):
            with run_lease(engine, run):
                pass
        with run_lease(engine, uuid4()):
            pass
    with run_lease(engine, run):
        pass


def test_a_later_attempt_waits_until_the_earlier_one_stops(engines):
    engine, run = engines[1], uuid4()
    held, release, order, waits = threading.Event(), threading.Event(), [], []

    def earlier():
        with run_lease(engine, run):
            held.set()
            release.wait(5)
            order.append("earlier stopped")

    thread = threading.Thread(target=earlier)
    thread.start()
    assert held.wait(5)
    threading.Timer(0.5, release.set).start()
    with run_lease(engine, run, waiting=lambda: waits.append(time.monotonic()), interval=0.1):
        order.append("later started")
    thread.join(5)
    assert order == ["earlier stopped", "later started"] and waits


def test_the_lease_is_released_whatever_interrupts_the_attempt(engines):
    engine, run = engines[1], uuid4()
    with pytest.raises(KeyboardInterrupt):
        with run_lease(engine, run):
            raise KeyboardInterrupt
    with run_lease(engine, run):
        pass


def test_concurrent_leases_leave_the_business_connection_pool_free(engines):
    engine = engines[1]
    with ExitStack() as stack:
        for _ in range(15):
            stack.enter_context(run_lease(engine, uuid4()))
        assert engine.pool.checkedout() == 0
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT 1")) == 1


# D358: the lease's connection can drop on its own, releasing the run to a next attempt.
_HOLDER = text(
    "SELECT l.pid FROM pg_locks l, (SELECT hashtextextended(:key, 0) AS k) h"
    " WHERE l.locktype = 'advisory' AND l.granted AND l.objsubid = 1"
    " AND l.classid::bigint = ((h.k >> 32) & 4294967295)"
    " AND l.objid::bigint = (h.k & 4294967295)"
)


def holder(admin, run):
    with admin.connect() as connection:
        return connection.scalar(_HOLDER, {"key": "xiaopai-run-attempt:" + str(run)})


def drop(admin, pid):
    with admin.connect() as connection:
        assert connection.scalar(text("SELECT pg_terminate_backend(:pid, 5000)"), {"pid": pid})


def runs_with_both_key_signs(engine):
    """Run ids whose lock keys have the high bit clear and set (pg_locks splits them)."""
    found = {}
    with engine.connect() as connection:
        while len(found) < 2:
            run = uuid4()
            key = {"key": "xiaopai-run-attempt:" + str(run)}
            negative = connection.scalar(text("SELECT hashtextextended(:key, 0) < 0"), key)
            found.setdefault(negative, run)
    return list(found.values())


def test_the_lease_knows_it_holds_the_run(engines):
    engine = engines[1]
    for run in runs_with_both_key_signs(engine):
        with run_lease(engine, run) as lease, run_lease(engine, uuid4()) as other:
            assert lease.held() and other.held()


def test_a_dropped_lease_connection_is_found_and_stays_lost(engines):
    admin, engine = engines[0], engines[1]
    for run in runs_with_both_key_signs(engine):
        with run_lease(engine, run) as lease:
            drop(admin, holder(admin, run))
            # The lock went with the session: a next attempt could take the run now.
            with run_lease(engine, run):
                pass
            assert not lease.held()
            assert holder(admin, run) is None  # Probing did not take the run back.
            with run_lease(engine, run) as later:
                assert later.held()
                assert not lease.held()  # Lost stays lost, though the run is held again.


def test_a_session_that_does_not_hold_the_lock_is_not_the_lease(engines):
    """A quiet reconnect lands on a fresh session; succeeding queries prove nothing."""
    engine, run = engines[1], uuid4()
    with run_lease(engine, run), engine.connect() as fresh:
        assert not RunLease(fresh, {"key": "xiaopai-run-attempt:" + str(run)}).held()


def test_a_dropped_lease_stops_the_attempt_at_its_next_safe_point(engines, monkeypatch):
    """The Activity's heartbeat finds the drop; the attempt stops as a superseded one."""
    admin, engine = engines[0], engines[1]
    monkeypatch.setattr(activities, "HEARTBEAT_SECONDS", 0.05)
    store = Store("queued")
    with run_lease(engine, RUN) as lease:

        def execute(host):
            drop(admin, holder(admin, RUN))
            assert host.superseded.wait(5)
            check_attempt(host.superseded)  # The next model or tool call.

        with pytest.raises(CancelledError):
            owned(monkeypatch, store, execute, lease=lease)
    assert store.row.state == "running" and "failed" not in store.states
