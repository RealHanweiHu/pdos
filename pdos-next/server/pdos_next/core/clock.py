"""Server-owned clock injection for deterministic deadlines; never a command parameter."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

_clock = ContextVar("pdos_clock", default=lambda: datetime.now(UTC))


def now():
    return _clock.get()()


def earliest_deadline(*values):
    """Optional grants have no deadline; genuine bounded facts keep theirs."""
    return min((value for value in values if value is not None), default=None)


def deadline_current(value, at=None):
    """A declared temporary deadline is enforced; ordinary facts have no TTL."""
    return value is None or (now() if at is None else at) < value


def proof_deadline_current(tier, value, at):
    """T1 confirmation expires; a named T2 decision has no mandatory time window."""
    if value is None:
        return tier == "T2"
    return isinstance(value, datetime) and value.utcoffset() is not None and at < value


@contextmanager
def using_clock(clock):
    instant = clock()
    if instant.tzinfo is None:
        raise ValueError("The server clock must return a timezone-aware datetime")
    token = _clock.set(clock)
    try:
        yield
    finally:
        _clock.reset(token)
