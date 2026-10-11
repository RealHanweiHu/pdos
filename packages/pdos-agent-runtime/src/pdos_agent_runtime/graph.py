"""An actual LangGraph boundary around a complete capability, not its provider call."""

from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

_active = ContextVar("pdos_agent_graph", default=False)


def in_agent_graph() -> bool:
    return bool(_active.get())


def in_registered_agent_graph(name: str = "xiaopai") -> bool:
    return name == "xiaopai" and _active.get() == name


class State(TypedDict, total=False):
    input: dict
    result: dict


def execute_graph(
    handler: Callable[[dict], dict],
    payload: dict,
    *,
    thread_id: str,
    checkpointer=None,
    verify: Callable[[dict], None] | None = None,
) -> dict:
    def execute(state):
        token = _active.set(True)
        try:
            return {"result": handler(state["input"])}
        finally:
            _active.reset(token)

    def validate(state):
        if not isinstance(state["result"], dict):
            raise TypeError("A capability must return a typed result envelope")
        if verify:
            verify(state["result"])
        return {}

    graph = StateGraph(State)
    graph.add_node("execute_capability", execute)
    graph.add_node("verify_result", validate)
    graph.add_edge(START, "execute_capability")
    graph.add_edge("execute_capability", "verify_result")
    graph.add_edge("verify_result", END)
    compiled = graph.compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": thread_id}}
    saved = compiled.get_state(config) if checkpointer else None
    if saved and saved.values.get("result") is not None and not saved.next:
        validate(saved.values)
        return saved.values["result"]
    return compiled.invoke(
        None if saved and saved.values else {"input": payload}, config
    )["result"]


@contextmanager
def registered_graph_context(name: str):
    """Fixed graph entry for the next host; no arbitrary model bypass or retired realm."""
    if name != "xiaopai":
        raise ValueError("Unregistered agent graph")
    token = _active.set(name)
    try:
        yield
    finally:
        _active.reset(token)
