"""Deterministic, resumable summary nodes inside the registered 小Pai boundary."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from pdos_agent_runtime.graph import registered_graph_context

from pdos_next.errors import DomainError

from . import personal_summary_runtime as runtime


class State(TypedDict, total=False):
    run_id: str
    cancel_epoch: int
    snapshot: dict
    output: dict


def execute(store, scope, *, checkpointer):
    # Store revalidates the actual Run and cancellation before both graph entry
    # and final persistence; this graph never constructs a gateway or a model.
    store.current(scope)

    def snapshot(_state):
        return {"snapshot": runtime.generate(store, scope)}

    def finalize(state):
        return {"output": runtime.persist(store, scope, state["snapshot"])}

    graph = StateGraph(State)
    graph.add_node("read_personal_summary", snapshot)
    graph.add_node("persist_personal_summary", finalize)
    graph.add_edge(START, "read_personal_summary")
    graph.add_edge("read_personal_summary", "persist_personal_summary")
    graph.add_edge("persist_personal_summary", END)
    compiled = graph.compile(checkpointer=checkpointer, name="xiaopai")
    config = {"configurable": {
        "thread_id": (
            f"xiaopai:{scope.tenant_id}:{scope.run_id}:personal-summary:{scope.cancel_epoch}"
        ),
    }}
    saved = compiled.get_state(config) if checkpointer is not None else None
    if saved and saved.values:
        if (saved.values.get("run_id"), saved.values.get("cancel_epoch")) != (
            str(scope.run_id), scope.cancel_epoch,
        ):
            raise DomainError("FORBIDDEN_SCOPE", "摘要检查点不属于当前实际运行。", 403)
        if not saved.next:
            # Even a terminal checkpoint cannot bypass current owner/source READ.
            with registered_graph_context("xiaopai"):
                output = runtime.persist(store, scope, saved.values["snapshot"])
            return {**saved.values, "output": output}
        payload = None
    else:
        payload = {"run_id": str(scope.run_id), "cancel_epoch": scope.cancel_epoch}
    with registered_graph_context("xiaopai"):
        return compiled.invoke(payload, config)
