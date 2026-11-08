"""D243: a superseded Activity attempt stops cleanly and never fails the run."""

from contextlib import contextmanager, nullcontext
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from temporalio.exceptions import CancelledError
from temporalio.testing import ActivityEnvironment

from pdos_next.agent.kernel import activities
from pdos_next.agent.kernel.host import BoundHost
from pdos_next.agent.kernel.run_lease import AttemptSuperseded, check_attempt
from pdos_next.errors import DomainError

RUN = uuid4()
SCOPE = SimpleNamespace(run_id=RUN, trigger="chat")


class Store:
    def __init__(self, state="running", error_code=None):
        self.row = SimpleNamespace(id=RUN, state=state, error_code=error_code,
                                   reverted_at=None, result=None)
        self.states = []

    @contextmanager
    def transaction(self, scope, *, lock=False):
        yield None, self.row
        self.states.append(self.row.state)

    def emit(self, *_):
        pass


def owned(monkeypatch, store, execute, reference=None):
    """Run the lease-owned part of advance with the kernel replaced by ``execute``."""
    acts = activities.KernelActivities.__new__(activities.KernelActivities)
    acts.engine = SimpleNamespace(_pdos_agent_kernel_adapters=SimpleNamespace(tool_registry=None))
    acts.store, acts.checkpoint_url, acts.technical_engine = store, "postgresql://checkpoints", None
    gateway = SimpleNamespace(close=lambda: None)
    host = SimpleNamespace(catalog=None, superseded=None, gateway=gateway)
    monkeypatch.setattr(activities, "BoundHost", lambda *_: host)
    monkeypatch.setattr(activities, "AgentKernel",
                        lambda *_, **__: SimpleNamespace(execute=lambda *a, **k: execute(host)))
    monkeypatch.setattr(activities, "verified_checkpoint_url", lambda url: url)
    monkeypatch.setattr(activities.PostgresSaver, "from_conn_string", lambda _: nullcontext())
    monkeypatch.setattr(acts, "preload", lambda *_: ())
    monkeypatch.setattr("pdos_next.agent.kernel.process_view.record_state", lambda *_: None)
    monkeypatch.setattr("pdos_next.agent.kernel.work_state.record_finish", lambda *_: None)
    reference = reference or {"subject_id": str(RUN)}
    return ActivityEnvironment().run(
        acts._advance_owned, None, RUN, SCOPE, reference, uuid4(), "goal", False
    )


@pytest.mark.parametrize("stop", ["safe_point", "sdk_cancel"])
def test_superseded_attempt_raises_cancelled_and_leaves_the_run_running(monkeypatch, stop):
    store = Store("queued")

    def execute(host):
        if stop == "sdk_cancel":  # W1: the SDK's own cancellation used to fail the run.
            raise CancelledError("synthetic timeout")
        host.superseded.set()  # Temporal gave this attempt up during the round.
        check_attempt(host.superseded)  # The next model or tool call is a safe point.

    with pytest.raises(CancelledError):
        owned(monkeypatch, store, execute)
    assert store.row.state == "running" and "failed" not in store.states


def test_ordinary_domain_failure_still_fails_the_run(monkeypatch):
    store = Store("queued")

    def execute(_host):
        raise DomainError("SOURCE_UNAVAILABLE", "synthetic")

    result = owned(monkeypatch, store, execute)
    assert result["status"] == "failed" and store.row.state == "failed"


def test_attempt_after_a_question_returns_needs_input_without_rerunning(monkeypatch):
    store = Store("waiting_input")
    result = owned(monkeypatch, store, lambda _: pytest.fail("the round must not run again"))
    assert result == {"run_id": str(RUN), "status": "needs_input"}


@pytest.mark.parametrize("state", ["completed", "partial", "failed", "cancelled"])
def test_attempt_after_a_finished_round_returns_its_state(monkeypatch, state):
    result = owned(monkeypatch, Store(state), lambda _: pytest.fail("the round must not run again"))
    assert result == {"run_id": str(RUN), "status": state}


@pytest.mark.parametrize("method", ["context_guard", "read", "prepare", "write", "recover"])
def test_every_host_safe_point_stops_a_superseded_attempt_first(method):
    host = BoundHost.__new__(BoundHost)  # Nothing else is touched before the check.
    host.superseded = Event()
    host.superseded.set()
    args = (SCOPE,) if method == "context_guard" else (SCOPE, None, {}, "intent")
    kwargs = {} if method in {"context_guard", "read", "prepare"} else {"source": None}
    with pytest.raises(AttemptSuperseded):
        getattr(host, method)(*args, **kwargs)


def test_isolated_extraction_threads_see_the_attempt_signal_and_stop(monkeypatch):
    """D257: children run on hosts built at startup and on their own threads."""
    from pdos_next.agent.enterprise_search import assistant_fanout as fanout
    from pdos_next.agent.kernel.run_lease import current_attempt

    store, seen = Store("queued"), []

    def execute(host):
        seen.append(current_attempt() is host.superseded is not None)

        def child():
            seen.append(current_attempt() is host.superseded)
            host.superseded.set()  # Temporal gives the attempt up mid-extraction.
            fanout.checkpoint()  # The child's next model or read call.
            pytest.fail("a superseded child must stop at its safe point")

        fanout.run([child, child], 2)

    with pytest.raises(CancelledError):
        owned(monkeypatch, store, execute)
    assert seen and all(seen)
    assert store.row.state == "running" and "failed" not in store.states
    assert current_attempt() is None  # The signal belongs to that attempt only.
