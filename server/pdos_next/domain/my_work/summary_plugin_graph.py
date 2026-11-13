"""Personal summary graph for the Temporal LangGraph plugin (P100, stage 1 pilot).

Same two deterministic steps as ``summary_graph``; each is its own Activity and the
workflow history, not a checkpoint database, records which step has finished. The graph
is built once at worker start. A node receives only the fixed run reference and the
state below, and rebuilds the server scope from the database on every execution.
"""

from datetime import timedelta
from typing import TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from temporalio.common import RetryPolicy

from pdos_next.domain.my_work import summary_runtime as runtime
from pdos_next.errors import DomainError
from pdos_next.workflows.graph_nodes import activity_node, dependency

GRAPH = "personal-summary"


class State(TypedDict, total=False):
    run_id: str
    cancel_epoch: int
    snapshot: dict
    output: dict


def _bound(state, context):
    store = dependency("kernel_store")
    scope = store.scope(
        tenant_id=UUID(context["tenant_id"]),
        requester_id=UUID(context["requester_id"]),
        writer_id=UUID(context["writer_id"]),
        category_id=UUID(context["category_id"]) if context["category_id"] else None,
        run_id=UUID(context["subject_id"]),
    )
    if (state.get("run_id"), state.get("cancel_epoch")) != (
        str(scope.run_id), scope.cancel_epoch,
    ):
        raise DomainError("CANCELLED_RUN", "摘要运行已取消或不属于当前实际运行。")
    store.current(scope)
    return store, scope


def read_personal_summary(state, context, _stop):
    store, scope = _bound(state, context)
    return {"snapshot": runtime.generate(store, scope)}


def persist_personal_summary(state, context, _stop):
    # Rechecks the snapshot's source ACLs under the owner's current reading scope.
    store, scope = _bound(state, context)
    return {"output": runtime.persist(store, scope, state["snapshot"])}


def build():
    graph = StateGraph(State)
    graph.add_node(
        "read_personal_summary", activity_node(read_personal_summary),
        metadata={
            "execute_in": "activity",
            "start_to_close_timeout": timedelta(minutes=2),
            "heartbeat_timeout": timedelta(seconds=45),
            "retry_policy": RetryPolicy(maximum_attempts=3),
        },
    )
    graph.add_node(
        "persist_personal_summary", activity_node(persist_personal_summary),
        metadata={
            "execute_in": "activity",
            "start_to_close_timeout": timedelta(minutes=1),
            "heartbeat_timeout": timedelta(seconds=45),
            # Technical persistence must survive a database outage; it is idempotent.
            "retry_policy": RetryPolicy(maximum_interval=timedelta(minutes=1)),
        },
    )
    graph.add_edge(START, "read_personal_summary")
    graph.add_edge("read_personal_summary", "persist_personal_summary")
    graph.add_edge("persist_personal_summary", END)
    return graph
