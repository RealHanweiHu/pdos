"""Drive the main graph's node bodies in-process, for unit tests with a scripted host.

Same wiring as production (``plugin_graph.wire``) and the same node bodies
(``AgentKernel.nodes``); only the hooks differ: a resume carries the answer itself, and
an adoption witness is handed over directly, because there is no database to read them
from. Durable behaviour (waiting, references, recovery) is tested on the plugin path.
"""

import asyncio

from langgraph.graph import StateGraph
from langgraph.types import Command
from pdos_agent_runtime.graph import registered_graph_context

from pdos_next.agent.kernel import plugin_graph
from pdos_next.agent.kernel.graph import NodeHooks, VerifiedCategoryAdoption
from pdos_next.errors import DomainError

_MISSING = object()


class _Direct(NodeHooks):
    def __init__(self, trusted):
        self.trusted = trusted

    def adoption(self, scope, wait):
        return wait(), self.trusted


async def _gate(_state):
    return {}


def execute(kernel, scope, *, goal=None, answer=_MISSING, checkpointer=None, preload=()):
    trusted = answer if isinstance(answer, VerifiedCategoryAdoption) else None
    resume = trusted.envelope() if trusted else answer
    kernel.ports.current(scope)
    graph = StateGraph(plugin_graph.State)
    for name, node in kernel.nodes(scope, preload=preload, hooks=_Direct(trusted)).items():
        graph.add_node(name, node)
    graph.add_node("rollover_gate", _gate)
    app = plugin_graph.wire(graph).compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": str(scope.run_id)}, "recursion_limit": 200}
    saved = app.get_state(config) if checkpointer is not None else None
    if saved and saved.values:
        if not saved.next:
            return saved.values
        interruptions = [i for task in saved.tasks for i in task.interrupts]
        if answer is _MISSING:
            if interruptions:
                return {**saved.values, "__interrupt__": interruptions}
            payload = None
        else:
            payload = Command(resume=resume)
    else:
        if answer is not _MISSING:
            raise DomainError("SOURCE_UNAVAILABLE", "恢复输入缺少原运行的检查点。")
        payload = {"goal": goal, "run_id": str(scope.run_id)}
    with registered_graph_context("xiaopai"):
        return asyncio.run(app.ainvoke(payload, config))
