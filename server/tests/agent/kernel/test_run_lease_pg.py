"""D243: the per-run lease keeps Activity attempts from overlapping."""

import threading
import time
from uuid import uuid4

import pytest

from pdos_next.agent.kernel.run_lease import RunBusy, run_lease


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
