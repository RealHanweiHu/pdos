"""D257: bounded concurrency for the isolated children of one assistant.extract."""

import threading
import time
from contextvars import ContextVar
from threading import Barrier, Event, Lock
from uuid import UUID, uuid4

import pytest
from pdos_agent_runtime.graph import in_registered_agent_graph, registered_graph_context

from pdos_next.agent.enterprise_search import assistant_fanout as fanout
from pdos_next.agent.enterprise_search.assistant_adapter import AssistantReadAdapter
from pdos_next.agent.enterprise_search.assistant_graph import AssistantExtractGraph
from pdos_next.agent.kernel.run_lease import AttemptSuperseded, attempt_scope
from pdos_next.agent.kernel.types import RunScope
from pdos_next.errors import DomainError


class Peak:
    def __init__(self):
        self.lock, self.active, self.peak = Lock(), 0, 0

    def __enter__(self):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)

    def __exit__(self, *_):
        with self.lock:
            self.active -= 1


def no_child_threads():
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if not any(t.name.startswith("assistant-extract") for t in threading.enumerate()):
            return True
        time.sleep(0.01)
    return False


def test_outcomes_keep_task_order_and_never_exceed_the_limit():
    peak = Peak()

    def task(index, delay):
        def run():
            with peak:
                time.sleep(delay)
                return index
        return run

    # Later tasks finish first; the merge still follows task order.
    tasks = [task(i, 0.05 * (5 - i)) for i in range(5)]
    assert fanout.run(tasks, 2) == [(i, None) for i in range(5)]
    assert peak.peak == 2
    assert no_child_threads()


def test_limit_one_runs_serially_in_the_calling_thread():
    caller, seen, peak = threading.get_ident(), [], Peak()

    def task():
        with peak:
            seen.append(threading.get_ident())
            time.sleep(0.01)
            return True

    assert fanout.run([task, task, task], 1) == [(True, None)] * 3
    assert set(seen) == {caller} and peak.peak == 1


def test_a_domain_error_is_that_task_failure_and_the_others_still_finish():
    finished = []

    def ok(index):
        def run():
            time.sleep(0.02)
            finished.append(index)
            return index
        return run

    def fails():
        raise DomainError("SOURCE_UNAVAILABLE", "synthetic child failure")

    outcomes = fanout.run([ok(0), fails, ok(2), ok(3)], 3)
    assert [value for value, _error in outcomes] == [0, None, 2, 3]
    assert outcomes[1][1].code == "SOURCE_UNAVAILABLE"
    assert sorted(finished) == [0, 2, 3]


def test_an_unexpected_error_stops_running_and_unstarted_siblings_before_raising():
    started, model_calls_after_failure = [], []
    running, failed = Event(), Event()

    def slow_child():
        started.append("slow")
        running.set()
        for _step in range(200):  # Each step is a safe point, then a "model call".
            fanout.checkpoint()
            if failed.is_set():
                model_calls_after_failure.append("slow")
            time.sleep(0.01)
        return "slow finished"

    def broken_child():
        started.append("broken")
        running.wait(2)
        failed.set()
        raise RuntimeError("synthetic unexpected failure")

    def queued_child():
        started.append("queued")
        return "queued"

    with pytest.raises(RuntimeError, match="synthetic unexpected failure"):
        fanout.run([slow_child, broken_child, queued_child], 2)
    # The running sibling stopped at its next safe point; the queued one never ran,
    # and no child thread is left once run() has raised.
    assert len(model_calls_after_failure) <= 1
    assert "queued" not in started
    assert no_child_threads()


def test_a_superseded_attempt_stops_every_child_before_its_next_model_call():
    superseded, gate = Event(), Barrier(3, timeout=5)
    calls, after = [], []

    def child(index):
        def run():
            gate.wait()  # All three children are running at once.
            for _step in range(200):
                fanout.checkpoint()  # ReadOnlyHost.current, before model/read calls.
                (after if superseded.is_set() else calls).append(index)
                if index == 0 and len(calls) >= 3:
                    superseded.set()  # Temporal gave the attempt up mid-extraction.
                time.sleep(0.01)
            return index
        return run

    with attempt_scope(superseded), pytest.raises(AttemptSuperseded):
        fanout.run([child(0), child(1), child(2)], 3)
    # Child 0 records the call that set the flag; nobody makes a call after that.
    assert len(after) <= 1
    assert no_child_threads()


def test_a_superseded_attempt_starts_no_child():
    superseded, started = Event(), []
    superseded.set()
    with attempt_scope(superseded), pytest.raises(AttemptSuperseded):
        fanout.run([lambda: started.append(1), lambda: started.append(2)], 2)
    assert started == []


def test_an_attempt_handback_wins_over_an_ordinary_error():
    gate = Barrier(2, timeout=5)

    def ordinary():
        gate.wait()
        raise RuntimeError("ordinary")

    def handback():
        gate.wait()
        raise AttemptSuperseded()

    with pytest.raises(AttemptSuperseded):
        fanout.run([ordinary, handback], 2)


def test_children_inherit_the_parent_context_but_not_each_others():
    marker = ContextVar("fanout_test_marker", default="unset")
    superseded = Event()

    def child(index):
        def run():
            seen = (in_registered_agent_graph(), fanout.current_attempt(), marker.get())
            marker.set(f"child-{index}")
            return seen
        return run

    marker.set("parent")
    with registered_graph_context("xiaopai"), attempt_scope(superseded):
        outcomes = fanout.run([child(i) for i in range(3)], 3)
    assert [value for value, _ in outcomes] == [(True, superseded, "parent")] * 3
    assert marker.get() == "parent"


@pytest.mark.parametrize(("raw", "value"), [(None, 2), ("1", 1), ("2", 2), ("8", 8)])
def test_concurrency_setting(monkeypatch, raw, value):
    if raw is None:
        monkeypatch.delenv(fanout.ENV, raising=False)
    else:
        monkeypatch.setenv(fanout.ENV, raw)
    assert fanout.concurrency() == value


@pytest.mark.parametrize("raw", ["0", "9", "-1", " 2", "2.0", "two", ""])
def test_invalid_concurrency_setting_fails_at_startup(monkeypatch, raw):
    monkeypatch.setenv(fanout.ENV, raw)
    with pytest.raises(RuntimeError, match=fanout.ENV):
        fanout.concurrency()
    # The graph reads it when the worker composes its adapters, not mid-run.
    with pytest.raises(RuntimeError, match=fanout.ENV):
        AssistantExtractGraph(None, None)
    with pytest.raises(RuntimeError, match=fanout.ENV):
        AssistantExtractGraph(None, None, concurrency=True)


def scope():
    return RunScope(
        tenant_id=uuid4(), requester_id=uuid4(), writer_id=uuid4(), session_id=uuid4(),
        run_id=uuid4(), category_id=uuid4(),
    )


def adapter_with(graph, citations, missing=()):
    """The real extract() over in-memory issued citations and current sources."""
    adapter = AssistantReadAdapter(None, None, graph=graph)
    adapter._started = lambda *_args: uuid4()
    adapter._selected = lambda _scope, identities: {
        str(cid): {"citation_id": str(cid)} for cid in identities
    }
    adapter._current = lambda _scope, selected, **_kwargs: (
        {cid: citations[cid] for cid in selected if cid in citations},
        {cid: "source_revoked" for cid in selected if cid in missing},
    )
    return adapter


def structured(cid):
    from datetime import UTC, datetime

    return {"nature": "structured", "structured": {"title": f"T{cid[:4]}"},
            "body": f"T{cid[:4]} body", "as_of": datetime(2026, 11, 1, tzinfo=UTC),
            "read_basis_status": "current", "source_type": "knowledge"}


def test_extract_merges_children_in_citation_order_at_any_concurrency():
    ids = [str(uuid4()) for _ in range(6)]
    kinds = ["untrusted", "structured", "untrusted", "missing", "untrusted", "untrusted"]
    citations = {cid: structured(cid) if kind == "structured" else {"nature": "untrusted"}
                 for cid, kind in zip(ids, kinds, strict=True) if kind != "missing"}
    missing = {cid for cid, kind in zip(ids, kinds, strict=True) if kind == "missing"}

    class Graph:
        def __init__(self, limit):
            self.concurrency = limit

        def __call__(self, bound, citation, _source, _question, _parent):
            cid = citation["citation_id"]
            assert bound.isolation == "assistant_extract"
            assert bound.citation_ids == {UUID(cid)}
            index = ids.index(cid)
            time.sleep(0.01 * (6 - index))  # Later citations finish first.
            if index == 4:
                raise DomainError("SOURCE_STALE", "synthetic stale child")
            return {"rows": [{"citation_id": cid, "quote": f"q{index}"}],
                    "coverage": {"citation_id": cid, "complete": index != 2,
                                 "kind": "untrusted"},
                    "rejected": [{"index": index}] if index == 5 else []}

    arguments = {"citation_ids": ids, "question": "q"}
    results = [adapter_with(Graph(limit), citations, missing).extract(
        scope(), arguments, intent_key="k") for limit in (1, 2, 3, 8)]
    assert all(result == results[0] for result in results[1:])
    serial = results[0]
    assert [row["citation_id"] for row in serial["rows"]] == [ids[0], ids[1], ids[2], ids[5]]
    assert [row["citation_id"] for row in serial["coverage"]] == [ids[0], ids[1], ids[2], ids[5]]
    assert serial["failures"] == [{"citation_id": ids[3], "code": "source_revoked"},
                                  {"citation_id": ids[4], "code": "SOURCE_STALE"}]
    assert serial["rejected"] == [{"index": 5}] and serial["partial"] is True


def test_extract_without_a_graph_still_refuses_untrusted_sources():
    cid = str(uuid4())
    adapter = adapter_with(None, {cid: {"nature": "untrusted"}})
    with pytest.raises(DomainError) as failure:
        adapter.extract(scope(), {"citation_ids": [cid]}, intent_key="k")
    assert failure.value.code == "SOURCE_UNAVAILABLE"
    # A structured-only extraction needs no isolated graph at all.
    sid = str(uuid4())
    result = adapter_with(None, {sid: structured(sid)}).extract(
        scope(), {"citation_ids": [sid]}, intent_key="k")
    assert result["row_count"] == 1 and result["failures"] == []
