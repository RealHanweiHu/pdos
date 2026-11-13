"""Test support for the plugin-executed 小Pai graph (P100).

``advance`` drives one run in this process, without a Temporal server: the real open and
close bookkeeping, the real registered graphs and the real node shell, with an in-memory
checkpointer kept per run so a later call can deliver an answer reference. It returns
what the workflow would return, plus ``needs_input`` while the graph waits.

``graph_worker`` is the Temporal worker wiring for tests that do use a server.
"""

import asyncio

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from temporalio.exceptions import ApplicationError

from pdos_next.agent.kernel import plugin_graph
from pdos_next.agent.kernel.graph_activities import GraphRunActivities
from pdos_next.agent.kernel.persistence import KernelStore
from pdos_next.domain.my_work import summary_plugin_graph
from pdos_next.workflows import graph_nodes

_runs = {}


async def _no_rollover(_state):
    return {}


def _compiled(kind):
    graph = (
        summary_plugin_graph.build() if kind == "personal_summary"
        else plugin_graph.build(gate=_no_rollover)
    )
    return graph.compile(checkpointer=InMemorySaver())


def advance(engine, reference, *, technical_engine=None):
    reference = dict(reference)
    answer_ref = reference.pop("answer_ref", None)
    runs = GraphRunActivities(engine, technical_engine=technical_engine)
    opened = runs._open({**reference, "kind": "any"})  # raises DomainError, as a stop
    run_id = reference["subject_id"]
    if opened["status"] != "running":
        return opened
    graph_nodes.configure_graph_dependencies(kernel_store=KernelStore(engine))
    app = _runs.get(run_id)
    config = {"configurable": {"thread_id": run_id}, "recursion_limit": 200}
    if app is None:
        app = _runs[run_id] = _compiled(opened["kind"])
        payload = {key: opened[key] for key in ("run_id", "cancel_epoch", "goal")
                   if key in opened}
    else:
        waiting = asyncio.run(app.aget_state(config)).next
        if not waiting:
            return {"run_id": run_id, "status": "needs_input"}
        if answer_ref is None:
            return {"run_id": run_id, "status": "needs_input"}
        payload = Command(resume={"answer_ref": answer_ref})
    beat, graph_nodes.HEARTBEAT_SECONDS = graph_nodes.HEARTBEAT_SECONDS, 86_400
    try:
        result = asyncio.run(app.ainvoke(
            payload, config, context={**reference, "writer_id": opened["writer_id"]},
            version="v2",
        ))
    except ApplicationError as error:
        _runs.pop(run_id, None)
        return runs.close({**reference, "error_code": error.type})
    finally:
        graph_nodes.HEARTBEAT_SECONDS = beat
    if result.interrupts:
        return {"run_id": run_id, "status": "needs_input"}
    _runs.pop(run_id, None)
    return {"run_id": run_id, "status": result.value["output"]["status"]}


def graph_worker(client, task_queue, engine, executor, *, technical_engine=None,
                 activities=(), workflows=(), **options):
    """A worker with the plugin, the 小Pai workflow and its bookkeeping Activities."""
    from temporalio.worker import Worker

    from pdos_next.agent.kernel.activities import KernelActivities
    from pdos_next.workflows.worker import graph_plugin
    from pdos_next.workflows.xiaopai_graph import XiaopaiGraphWork

    plugin, run_activities = graph_plugin(engine, technical_engine=technical_engine)
    legacy = KernelActivities(engine, technical_engine=technical_engine)
    return Worker(
        client, task_queue=task_queue, workflows=[XiaopaiGraphWork, *workflows],
        activities=[*run_activities, legacy.reconcile, *activities], plugins=[plugin],
        activity_executor=executor, **options,
    )


class InlineRun:
    """``InlineRun(engine).advance(reference)``: one round of a run, in this process."""

    def __init__(self, engine, *, technical_engine=None):
        self.engine, self.technical_engine = engine, technical_engine

    def advance(self, reference):
        return advance(self.engine, reference, technical_engine=self.technical_engine)
