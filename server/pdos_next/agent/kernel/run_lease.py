"""One Activity attempt works on a 小Pai run at a time (D243).

When Temporal gives an attempt up (execution timeout) it starts the next one while the
old thread may still be inside a model or tool call. Two attempts then advanced the same
run, which broke its ledgers and failed the run. Now each attempt holds a per-run lease
for its whole duration, a later attempt waits for it, and a superseded attempt stops at
the next safe point: before its next model call or tool call.

The lease's connection can drop on its own; its lock is then released and the next
attempt could start while this one runs on. The Activity probes the lease on every
heartbeat and stops the attempt the same way once it is lost (D358); on the plugin path
each node's lease is probed by ``lease_watch``.
"""

import time
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Event, Lock, Thread

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

_KEY = "xiaopai-run-attempt:"
_TRY = text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))")
# A bigint advisory key shows in pg_locks as its high (classid) and low (objid) halves.
_HELD = text(
    "SELECT EXISTS (SELECT 1 FROM pg_locks l, (SELECT hashtextextended(:key, 0) AS k) h"
    " WHERE l.locktype = 'advisory' AND l.pid = pg_backend_pid() AND l.granted"
    " AND l.objsubid = 1 AND l.classid::bigint = ((h.k >> 32) & 4294967295)"
    " AND l.objid::bigint = (h.k & 4294967295))"
)
# A dead peer surfaces within about half a minute instead of hanging the probe.
_KEEPALIVE = {
    "keepalives": 1,
    "keepalives_idle": 10,
    "keepalives_interval": 5,
    "keepalives_count": 3,
    "tcp_user_timeout": 30000,
}
_ATTEMPT = ContextVar("xiaopai_attempt_superseded", default=None)


class AttemptSuperseded(BaseException):
    """Raised at a safe point once Temporal has given this attempt up.

    A BaseException, so ordinary error handling never turns it into a run failure.
    """


class RunBusy(Exception):
    """Another attempt still holds the run, and this caller does not wait."""


class RunLease:
    """The lease an attempt holds; ``held()`` finds out whether it still does (D358)."""

    def __init__(self, connection, key):
        self._connection, self._key = connection, key
        self._probe = Lock()
        self._lost = False

    def held(self):
        """Ask the lease's own session whether it still holds the run's lock.

        The driver may reconnect quietly after a drop, so a query that merely succeeds
        proves nothing: the probe looks for the lock among this backend's own locks.
        Once lost, the lease stays lost.
        """
        with self._probe:
            if not self._lost:
                try:
                    self._lost = not self._connection.scalar(_HELD, self._key)
                except SQLAlchemyError:
                    self._lost = True
            return not self._lost


@contextmanager
def run_lease(engine, run_id, *, waiting=None, interval=2.0):
    """Hold the run's session advisory lock while this attempt works on it.

    With ``waiting`` given, a busy lease is retried every ``interval`` seconds and
    ``waiting()`` runs between tries (the Activity heartbeats there). Without it, a busy
    lease raises RunBusy at once. The lock lives on its own autocommit connection, so no
    transaction stays open, and the connection is discarded afterwards: session locks
    outlive a pooled connection, and closing the session releases the lock whatever
    interrupted the attempt, including the worker process dying.

    Yields the RunLease, whose ``held()`` the attempt probes while it works.
    """
    # A long-running lease must not reserve a slot in the business transaction pool.
    lease_engine = create_engine(
        engine.url,
        poolclass=NullPool,
        isolation_level="AUTOCOMMIT",
        hide_parameters=True,
        connect_args=_KEEPALIVE,
    )
    with lease_engine.connect() as connection:
        key = {"key": _KEY + str(run_id)}
        while not connection.scalar(_TRY, key):
            if waiting is None:
                raise RunBusy(str(run_id))
            waiting()
            time.sleep(interval)
        yield RunLease(connection, key)


@contextmanager
def lease_watch(lease, stop, *, interval=10.0):
    """Probe ``lease`` every ``interval`` seconds and set ``stop`` once it is lost (D358).

    The attempt then stops at its next safe point, as a superseded one does, and leaves
    the run to the next attempt. The probe uses the lease's own idle connection.
    """
    done = Event()

    def watch():
        while not done.wait(interval):
            if not lease.held():
                stop.set()
                return

    thread = Thread(target=watch, name="run-lease-watch", daemon=True)
    thread.start()
    try:
        yield
    finally:
        done.set()
        thread.join(timeout=1)


def check_attempt(superseded=None):
    """Stop at a safe point when this attempt has been superseded.

    Safe points come before a model or tool call is claimed. Hosts built at startup
    (the isolated children's) have no signal of their own, so the attempt's signal
    from ``attempt_scope`` is checked as well (D269).
    """
    for signal in (superseded, _ATTEMPT.get()):
        if signal is not None and signal.is_set():
            raise AttemptSuperseded()


@contextmanager
def attempt_scope(superseded):
    """Expose this attempt's stop signal to code that has no handle on its host.

    The isolated children of a tool call run on hosts built once at startup, so the
    Activity cannot hand them the signal directly (D257). They read it from here, and
    threads they start copy it with their context.
    """
    token = _ATTEMPT.set(superseded)
    try:
        yield
    finally:
        _ATTEMPT.reset(token)


def current_attempt():
    return _ATTEMPT.get()
