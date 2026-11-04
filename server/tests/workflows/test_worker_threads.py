"""D57/F45: the worker's Activity thread count is configurable and bounded."""

import pytest

from pdos_next.workflows.worker import activity_threads


def test_default_is_four(monkeypatch):
    monkeypatch.delenv("PDOS_WORKER_ACTIVITY_THREADS", raising=False)
    assert activity_threads() == 4


def test_configured_value_is_used(monkeypatch):
    monkeypatch.setenv("PDOS_WORKER_ACTIVITY_THREADS", "8")
    assert activity_threads() == 8


@pytest.mark.parametrize("value", ["0", "65", "-1", "four", "", "2.5"])
def test_invalid_values_stop_the_worker(monkeypatch, value):
    monkeypatch.setenv("PDOS_WORKER_ACTIVITY_THREADS", value)
    with pytest.raises(RuntimeError):
        activity_threads()
