"""Plugin-path waits (P100): a resume carries a committed reference, never the answer.

The node bodies and the plugin graph's own routing are driven in-process with an
in-memory checkpointer, exactly as the workflow drives them, without a Temporal server.
Only the database behind the hooks is replaced.
"""

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from pdos_agent_runtime.graph import registered_graph_context

from pdos_next.agent.kernel import category_adoption, plugin_graph, process_view
from pdos_next.errors import DomainError
from tests.agent.kernel.test_category_wait import fixture, proof


class Store:
    def __init__(self):
        self.row, self.states = SimpleNamespace(state="running"), []

    @contextmanager
    def transaction(self, scope, *, lock=False):
        before = self.row.state
        yield None, self.row
        if self.row.state != before:
            self.states.append(self.row.state)


def drive(monkeypatch, *, count=1, question=False):
    scope, host, kernel, _ = fixture(count=count, question=question)
    store, answers = Store(), {}
    monkeypatch.setattr(process_view, "record_state", lambda *_: None)
    monkeypatch.setattr(
        category_adoption, "resolve", lambda _engine, bound, ref: answers[(bound.run_id, ref)],
    )
    nodes = kernel.nodes(
        scope, preload=("category_framing",), hooks=plugin_graph.PluginHooks(store, None),
    )
    graph = StateGraph(plugin_graph.State)
    for name, node in nodes.items():
        graph.add_node(name, node)

    async def gate(_state):
        return {}

    graph.add_node("rollover_gate", gate)
    graph.add_edge(START, "prepare_context")
    graph.add_edge("prepare_context", "model")
    graph.add_conditional_edges("model", plugin_graph.choose,
                                ["tools", "model", "route", "verify"])
    graph.add_conditional_edges("route", plugin_graph.after_route, ["model", "verify"])
    graph.add_conditional_edges("tools", plugin_graph.after_tools,
                                ["await_category_adoption", "rollover_gate"])
    graph.add_conditional_edges("await_category_adoption", plugin_graph.after_tools,
                                ["await_category_adoption", "rollover_gate"])
    graph.add_edge("rollover_gate", "model")
    graph.add_conditional_edges("verify", plugin_graph.after_verify, ["finalize", "model"])
    graph.add_edge("finalize", END)
    app = graph.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": str(scope.run_id)}, "recursion_limit": 50}

    def invoke(payload):
        # The Activity shell enters the registered graph before a node body runs.
        with registered_graph_context("xiaopai"):
            return asyncio.run(app.ainvoke(payload, config, version="v2"))

    def commit(value):
        ref = str(uuid4())
        answers[(scope.run_id, ref)] = value
        return Command(resume={"answer_ref": ref})

    first = invoke({"goal": "Synthetic category", "run_id": str(scope.run_id)})
    return SimpleNamespace(scope=scope, host=host, store=store, invoke=invoke, commit=commit,
                           first=first)


def test_candidates_are_adopted_by_reference_in_any_order(monkeypatch):
    run = drive(monkeypatch, count=2)
    assert run.first.interrupts[0].value["type"] == "category_adoption"
    assert run.store.row.state == "waiting_input"
    second, first = proof(run.scope, run.host, 1), proof(run.scope, run.host, 0)
    paused = run.invoke(run.commit(second))  # the later candidate is confirmed first
    assert paused.interrupts[0].value["event_id"] == run.host.candidates[0]["event_id"]
    assert paused.value["consumed_input_refs"] == [second.input_ref]
    done = run.invoke(run.commit(first))
    assert not done.interrupts and done.value["output"]["status"] == "completed"
    assert done.value["consumed_input_refs"] == [second.input_ref, first.input_ref]
    assert done.value["pending_categories"] == []
    # Tools ran once; each wait was recorded and lifted.
    assert len(run.host.prepared) == 2 and len(run.host.prefixes) == 2
    assert run.store.states == ["waiting_input", "running", "waiting_input", "running"]
    assert run.store.row.state == "running"


@pytest.mark.parametrize("value", [{}, {"approved": True}, {"market": "US"}])
def test_an_ordinary_answer_cannot_release_an_adoption_wait(monkeypatch, value):
    run = drive(monkeypatch)
    with pytest.raises(DomainError, match="普通答复不能释放品类采用等待"):
        run.invoke(run.commit(value))
    assert len(run.host.prefixes) == 1


def test_the_same_adoption_cannot_be_consumed_twice(monkeypatch):
    run = drive(monkeypatch, count=2)
    adopted = proof(run.scope, run.host, 0)
    run.invoke(run.commit(adopted))
    with pytest.raises(DomainError):
        run.invoke(run.commit(adopted))


def test_an_adoption_cannot_answer_a_question(monkeypatch):
    run = drive(monkeypatch, question=True)
    asked = run.invoke(run.commit(proof(run.scope, run.host)))
    assert "questions" in asked.interrupts[0].value
    with pytest.raises(DomainError, match="当前检查点没有该待采用候选"):
        run.invoke(run.commit(proof(run.scope, run.host)))


def test_a_question_is_answered_by_reference_and_reaches_the_model_once(monkeypatch):
    run = drive(monkeypatch, question=True)
    run.invoke(run.commit(proof(run.scope, run.host)))
    done = run.invoke(run.commit({"next": "yes"}))
    assert not done.interrupts and done.value["output"]["status"] == "completed"
    answered = [m for m in done.value["messages"] if '"answers"' in m.get("content", "")]
    assert len(answered) == 1 and '"next": "yes"' in answered[0]["content"]


@pytest.mark.parametrize("payload", [
    {"market": "US"}, "approved", {"answer_ref": "x", "answers": {"market": "US"}},
])
def test_resume_must_be_exactly_one_committed_reference(monkeypatch, payload):
    run = drive(monkeypatch)
    with pytest.raises(DomainError, match="恢复输入须是服务器已提交的答复引用"):
        run.invoke(Command(resume=payload))
