"""The original workflow is untouched by the plugin worker; routing is pure (P100).

Histories of ``XiaopaiWork`` are recorded on a worker configured as before the
migration (no plugin), then replayed against the worker's full registration list with
the plugin installed. Routing functions are checked as plain functions of state.
"""

import asyncio
import inspect
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

import pdos_next.workflows.worker as worker_module
from pdos_next.agent.kernel import plugin_graph
from pdos_next.workflows.xiaopai import XiaopaiWork
from tests.workflows.graph_pilot_fixtures import BINARY


def reference():
    return {key: str(uuid4()) for key in (
        "tenant_id", "category_id", "actor_id", "requester_id", "subject_id",
    )}


@pytest.mark.skipif(not BINARY.is_file(), reason="Inspected local Temporal binary required")
def test_original_workflow_histories_replay_on_the_plugin_worker():
    script = {}

    @activity.defn(name="advance_xiaopai_run")
    def advance(payload):
        steps = script[payload["subject_id"]]
        step = steps.pop(0) if len(steps) > 1 else steps[0]
        if step == "raise":
            raise ApplicationError("synthetic", non_retryable=True)
        return {"run_id": payload["subject_id"], "status": step,
                **({"answer": payload["answer_ref"]} if "answer_ref" in payload else {})}

    @activity.defn(name="reconcile_xiaopai_run")
    def reconcile(payload):
        return {"run_id": payload["subject_id"], "status": "failed"}

    async def actual():
        environment = await WorkflowEnvironment.start_local(dev_server_existing_path=str(BINARY))
        try:
            queue, histories = "original-" + str(uuid4()), []
            with ThreadPoolExecutor(max_workers=2) as executor:
                async with Worker(
                    environment.client, task_queue=queue, workflows=[XiaopaiWork],
                    activities=[advance, reconcile], activity_executor=executor,
                ), asyncio.timeout(90):
                    for steps, signals in (
                        (["completed"], []),
                        (["partial"], []),
                        (["cancelled"], []),
                        (["needs_input", "needs_input", "completed"],
                         [str(uuid4()), "not-a-reference", str(uuid4())]),
                        (["raise"], []),
                    ):
                        ref = reference()
                        script[ref["subject_id"]] = list(steps)
                        handle = await environment.client.start_workflow(
                            XiaopaiWork.run, ref, id="original-" + ref["subject_id"],
                            task_queue=queue,
                        )
                        for value in [*signals, *signals[:1]]:  # with a duplicate
                            await handle.signal(XiaopaiWork.resume, value)
                        await handle.result()
                        histories.append(await handle.fetch_history())
            return histories
        finally:
            await environment.shutdown()

    histories = asyncio.run(actual())
    assert len(histories) == 5
    # Never connected: the registration only needs an engine object to hold.
    plugin, _ = worker_module.graph_plugin(create_engine("postgresql+psycopg://unused/unused"))
    replayer = Replayer(workflows=worker_module.registered_workflows(), plugins=[plugin])
    for history in histories:
        asyncio.run(replayer.replay_workflow(history))  # raises on nondeterminism


BASE = {"calls": [], "output": {}, "pending_categories": []}
ROUTES = [
    (plugin_graph.choose, {**BASE, "calls": [{"id": "a"}]}, "tools"),
    (plugin_graph.choose, {**BASE, "calls": [{"id": "a"}], "output": {"status": "completed"}},
     "tools"),
    (plugin_graph.choose, BASE, "model"),
    (plugin_graph.choose, {**BASE, "output": {"status": "needs_input"}}, "route"),
    (plugin_graph.choose, {**BASE, "output": {"status": "completed"}}, "verify"),
    (plugin_graph.choose, {**BASE, "output": {"status": "partial"}}, "verify"),
    (plugin_graph.after_route, BASE, "model"),
    (plugin_graph.after_route, {**BASE, "output": {"status": "needs_input"}}, "verify"),
    (plugin_graph.after_tools, BASE, "rollover_gate"),
    (plugin_graph.after_tools, {"calls": [], "output": {}}, "rollover_gate"),
    (plugin_graph.after_tools, {**BASE, "pending_categories": [{"event_id": "x"}]},
     "await_category_adoption"),
    (plugin_graph.after_verify, BASE, "model"),
    (plugin_graph.after_verify, {**BASE, "output": {"status": "completed"}}, "finalize"),
]


@pytest.mark.parametrize(("route", "state", "expected"), ROUTES)
def test_routing_is_a_pure_function_of_state(route, state, expected):
    assert inspect.iscoroutinefunction(route)  # the workflow sandbox cannot run sync edges
    before = repr(state)
    assert [asyncio.run(route(state)) for _ in range(3)] == [expected] * 3
    assert repr(state) == before


def test_routing_reads_nothing_but_state():
    forbidden = {"dependency", "store", "engine", "session", "time", "datetime", "random",
                 "uuid4", "environ", "open", "requests", "httpx"}
    for route in (plugin_graph.choose, plugin_graph.after_route, plugin_graph.after_tools,
                  plugin_graph.after_verify):
        code = route.__code__
        assert not forbidden & set(code.co_names), route.__name__
        assert code.co_varnames[:code.co_argcount] == ("state",)
    # The gate also reads the workflow's own deterministic history counters, nothing else.
    gate = set(plugin_graph.rollover_gate.__code__.co_names)
    assert not forbidden & gate and "workflow" in gate


def test_every_graph_node_declares_where_it_runs_and_only_the_gate_is_in_the_workflow():
    from temporalio.langgraph import LangGraphPlugin

    graph = plugin_graph.build()
    placement = {name: node.metadata["execute_in"] for name, node in graph.nodes.items()}
    assert placement == {
        "prepare_context": "activity", "model": "activity", "route": "activity",
        "tools": "activity", "await_category_adoption": "activity", "verify": "activity",
        "finalize": "activity", "rollover_gate": "workflow",
    }
    for name, node in graph.nodes.items():
        if placement[name] == "activity":
            assert node.metadata["start_to_close_timeout"].total_seconds() > 0
            assert node.metadata["heartbeat_timeout"].total_seconds() == 45
    registered = LangGraphPlugin(graphs={plugin_graph.GRAPH: graph})
    assert sorted(a.__temporal_activity_definition.name for a in registered.activities) == [
        "xiaopai.await_category_adoption", "xiaopai.finalize", "xiaopai.model",
        "xiaopai.prepare_context", "xiaopai.route", "xiaopai.tools", "xiaopai.verify",
    ]
