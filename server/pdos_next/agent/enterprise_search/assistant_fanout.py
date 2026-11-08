"""Bounded concurrency for the isolated children of one assistant.extract (D257).

Each citation in an extraction runs its own registered child graph. They used to run
one after another, so an extraction of three citations took three children's time. Now
at most ``limit`` run at once and their outcomes come back in citation order, so the
merged result is the same as the serial loop's.

Nothing else about a child changes. Its model calls, read receipts, budget and fee
reservations, checkpoint and idempotency keys are its own, and every claim or release
locks the run row (then the call, then the budget), so children side by side reserve
and record exactly what they would one after another.

Rules kept by ``run``:
- Every child has stopped before ``run`` returns or raises. No child thread outlives the
  Activity attempt, so a later attempt can never overlap one (D243).
- A superseded attempt stops each child at its next safe point (``checkpoint``), before
  its next model or read call.
- A DomainError is that citation's failure; the other children carry on, as before.
- Any other error stops the children that have not started and asks the running ones to
  stop at their next safe point. The first such error in citation order is raised; an
  attempt hand-back (a BaseException such as AttemptSuperseded) wins over ordinary ones.
"""

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import ContextVar, copy_context
from threading import Event

from pdos_next.agent.kernel.run_lease import check_attempt, current_attempt
from pdos_next.errors import DomainError

ENV = "PDOS_ASSISTANT_EXTRACT_CONCURRENCY"
# Conservative default; the reasons are in tasks/ai-native-integrated-todo.md D257.
DEFAULT = 2
MAXIMUM = 8  # ExtractInput accepts at most 8 citations.

_STOP = ContextVar("assistant_extract_sibling_stop", default=None)


class SiblingStopped(BaseException):
    """Another child failed unexpectedly; this one stopped at a safe point."""


def validated(value):
    if type(value) is not int or not 1 <= value <= MAXIMUM:
        raise RuntimeError(f"{ENV} must be a whole number from 1 to {MAXIMUM}")
    return value


def concurrency():
    """How many children of one extraction may run at once (default 2, 1 = serial)."""
    raw = os.environ.get(ENV, str(DEFAULT))
    return validated(int(raw) if raw.isdigit() else 0)


def checkpoint():
    """A child's safe point: called before each of its model and read calls."""
    check_attempt(current_attempt())
    stop = _STOP.get()
    if stop is not None and stop.is_set():
        raise SiblingStopped()


def run(tasks, limit):
    """Run zero-argument tasks; return ``(value, None)`` or ``(None, DomainError)`` in order."""
    validated(limit)
    if limit == 1 or len(tasks) <= 1:
        outcomes = []
        for task in tasks:
            try:
                outcomes.append((task(), None))
            except DomainError as error:
                outcomes.append((None, error))
        return outcomes

    stop = Event()
    outcomes = [None] * len(tasks)

    def child(index, task):
        _STOP.set(stop)
        if stop.is_set():
            return  # Never started: a sibling has already failed.
        check_attempt(current_attempt())
        try:
            outcomes[index] = (task(), None)
        except DomainError as error:
            outcomes[index] = (None, error)

    errors = {}
    executor = ThreadPoolExecutor(
        max_workers=min(limit, len(tasks)), thread_name_prefix="assistant-extract"
    )
    try:
        # Each child runs in a copy of this context: the registered-graph marker and
        # the attempt's stop signal reach it, and its own settings stay its own.
        futures = {
            executor.submit(copy_context().run, child, index, task): index
            for index, task in enumerate(tasks)
        }
        for future in as_completed(futures):
            error = future.exception()
            if error is not None:
                errors[futures[future]] = error
                stop.set()
    except BaseException:
        stop.set()
        raise
    finally:
        executor.shutdown(wait=True)
    if errors:
        raised = [errors[index] for index in sorted(errors)
                  if not isinstance(errors[index], SiblingStopped)]
        handback = [error for error in raised if not isinstance(error, Exception)]
        raise (handback or raised)[0]
    return outcomes
