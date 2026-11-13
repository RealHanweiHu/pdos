"""D243: a superseded node attempt stops cleanly and never fails the run."""

from contextlib import contextmanager
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from temporalio.testing import ActivityEnvironment

from pdos_next.agent.kernel.host import BoundHost
from pdos_next.agent.kernel.run_lease import AttemptSuperseded, attempt_scope, check_attempt

RUN = uuid4()
SCOPE = SimpleNamespace(run_id=RUN, trigger="chat")


def test_cancelled_attempt_tells_its_node_to_stop_and_does_not_fail_the_run():
    """Temporal gave the attempt up: the body sees the signal, nothing marks a failure."""
    import asyncio
    import threading

    from pdos_next.workflows import graph_nodes

    started, observed = threading.Event(), []

    def body(state, context, stop):
        started.set()
        observed.append(stop.wait(10))  # A long node reaches its next safe point.
        check_attempt(stop)

    node = graph_nodes.activity_node(body)
    environment = ActivityEnvironment()

    async def attempt():
        task = asyncio.ensure_future(
            environment.run(node, {}, SimpleNamespace(context={"subject_id": str(RUN)}))
        )
        await asyncio.to_thread(started.wait, 10)
        environment.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(attempt())
    assert observed == [True]


SAFE_POINTS = ["model_step", "read", "read_callback", "prepare", "write", "recover"]


def call_safe_point(host, method):
    args = (SCOPE,) if method == "model_step" else (SCOPE, None, {}, "intent")
    kwargs = {
        "model_step": {}, "read": {}, "prepare": {},
        "read_callback": {"source": None, "callback": None},
    }.get(method, {"source": None})
    return getattr(host, method)(*args, **kwargs)


@pytest.mark.parametrize("method", SAFE_POINTS)
def test_every_host_safe_point_stops_a_superseded_attempt_first(method):
    host = BoundHost.__new__(BoundHost)  # Nothing else is touched before the check.
    host.superseded = Event()
    host.superseded.set()
    with pytest.raises(AttemptSuperseded):
        call_safe_point(host, method)


@pytest.mark.parametrize("method", SAFE_POINTS)
def test_a_startup_host_stops_on_the_attempt_signal_of_its_scope(method):
    """D269: the isolated children's hosts are built once, with no signal of their own."""
    host = BoundHost.__new__(BoundHost)
    signal = Event()
    signal.set()
    with attempt_scope(signal), pytest.raises(AttemptSuperseded):
        call_safe_point(host, method)


def test_the_context_guard_is_not_a_stop_point_because_it_also_runs_after_a_claim():
    """D269: the gateway re-runs the guard after claiming; stopping there stranded the call."""
    run = SimpleNamespace(versions={})

    class Store:
        @contextmanager
        def transaction(self, *_args, **_kwargs):
            yield None, run

    host = BoundHost.__new__(BoundHost)
    host.store, host.adapters = Store(), SimpleNamespace(context_guard=None)
    host.superseded = Event()
    host.superseded.set()
    with attempt_scope(host.superseded):
        host.context_guard(SCOPE)  # No AttemptSuperseded: the claimed call goes on.


def test_isolated_extraction_threads_see_the_attempt_signal_and_stop():
    """D257: children run on hosts built at startup and on their own threads."""
    from pdos_next.agent.enterprise_search import assistant_fanout as fanout
    from pdos_next.agent.kernel.run_lease import current_attempt

    signal, seen = Event(), []

    def child():
        seen.append(current_attempt() is signal)
        signal.set()  # Temporal gives the attempt up mid-extraction.
        fanout.checkpoint()  # The child's next model or read call.
        pytest.fail("a superseded child must stop at its safe point")

    with attempt_scope(signal), pytest.raises(AttemptSuperseded):
        fanout.run([child, child], 2)
    assert seen and all(seen)
    assert current_attempt() is None  # The signal belongs to that attempt only.


def test_parallel_reads_carry_the_attempt_signal_into_their_threads():
    """D269: research.fanout and evidence.extract run on the kernel's read pool."""
    import threading

    from pdos_next.agent.kernel.graph import AgentKernel
    from pdos_next.agent.kernel.run_lease import current_attempt
    from pdos_next.agent.kernel.tools import default_registry
    from pdos_next.agent.kernel.types import ModelTurn, ToolCall
    from tests.agent.kernel.test_graph import Host, final, scope

    signal, main, seen = Event(), threading.current_thread(), []

    class Reader(Host):
        def read(self, _scope, spec, arguments, intent_key):
            seen.append((current_attempt() is signal, threading.current_thread() is not main))
            return {"actual": spec.name}

    host = Reader([ModelTurn(calls=(
        ToolCall(id="a", name="evidence.search", arguments={"query": "a"}),
        ToolCall(id="b", name="evidence.search", arguments={"query": "b"}),
    )), final()])
    with attempt_scope(signal):
        AgentKernel(host, default_registry()).execute(scope(), goal="synthetic")
    assert seen == [(True, True), (True, True)]
