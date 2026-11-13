"""Routing and node placement of the plugin graph are pure and declared (P100)."""

import asyncio
import inspect

import pytest

from pdos_next.agent.kernel import plugin_graph

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
