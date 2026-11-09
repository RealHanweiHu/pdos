"""One Activity attempt works on a 小Pai run at a time (D243).

When Temporal gives an attempt up (execution timeout) it starts the next one while the
old thread may still be inside a model or tool call. Two attempts then advanced the same
run, which broke its ledgers and failed the run. Now each attempt holds a per-run lease
for its whole duration, a later attempt waits for it, and a superseded attempt stops at
the next safe point: before its next model call or tool call.
"""

import time
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

_KEY = "xiaopai-run-attempt:"
_TRY = text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))")
_ATTEMPT = ContextVar("xiaopai_attempt_superseded", default=None)


class AttemptSuperseded(BaseException):
    """Raised at a safe point once Temporal has given this attempt up.

    A BaseException, so ordinary error handling never turns it into a run failure.
    """


class RunBusy(Exception):
    """Another attempt still holds the run, and this caller does not wait."""


@contextmanager
def run_lease(engine, run_id, *, waiting=None, interval=2.0):
    """Hold the run's session advisory lock while this attempt works on it.

    With ``waiting`` given, a busy lease is retried every ``interval`` seconds and
    ``waiting()`` runs between tries (the Activity heartbeats there). Without it, a busy
    lease raises RunBusy at once. The lock lives on its own autocommit connection, so no
    transaction stays open, and the connection is discarded afterwards: session locks
    outlive a pooled connection, and closing the session releases the lock whatever
    interrupted the attempt, including the worker process dying.
    """
    # A long-running lease must not reserve a slot in the business transaction pool.
    lease_engine = create_engine(
        engine.url, poolclass=NullPool, isolation_level="AUTOCOMMIT", hide_parameters=True,
    )
    with lease_engine.connect() as connection:
        key = {"key": _KEY + str(run_id)}
        while not connection.scalar(_TRY, key):
            if waiting is None:
                raise RunBusy(str(run_id))
            waiting()
            time.sleep(interval)
        yield


def check_attempt(superseded):
    """Stop at a safe point when this attempt has been superseded."""
    if superseded is not None and superseded.is_set():
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
