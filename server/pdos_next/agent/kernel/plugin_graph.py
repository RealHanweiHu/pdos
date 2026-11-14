"""The 小Pai graph for the Temporal LangGraph plugin (P100, stage 2).

Built once at worker start. Every node is an Activity that rebuilds the server scope and
its ports from the database and worker-level dependencies, then runs the same node body
as the checkpointed path (``AgentKernel.nodes``). Routing functions and the roll-over
gate run inside the workflow and only read state.

Graph state holds run data. It never holds credentials, and large read results and
provider-private continuation data stay in the run's ledger, referenced by call id.
"""

from datetime import timedelta
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from sqlalchemy import select
from temporalio import workflow
from temporalio.common import RetryPolicy

from pdos_next.core.service import digest
from pdos_next.errors import DomainError
from pdos_next.workflows.graph_nodes import activity_node, dependency

from .graph import AgentKernel, GraphState, NodeHooks, VerifiedCategoryAdoption
from .models import AgentToolCall
from .run_lease import attempt_scope, check_attempt, lease_watch, run_lease

GRAPH = "xiaopai"
CONTINUATION_REF = "provider_continuation_ref"
# Roll the workflow over to a fresh history before Temporal's limits (P100 §6.3).
ROLLOVER_HISTORY_BYTES = 8 * 1024 * 1024
ROLLOVER_MODEL_TURNS = 6


class State(GraphState, total=False):
    cancel_epoch: int
    rolled_at: int


class PluginHooks(NodeHooks):
    def __init__(self, store, engine):
        self.store, self.engine = store, engine
        self._continuations = {}

    def _state(self, scope, state):
        with self.store.transaction(scope, lock=True) as (session, row):
            if row.state != state:
                row.state = state
                from .process_view import record_state

                record_state(session, row)

    def _resolved(self, scope, wait):
        # The node starts again from its top when it is resumed, so this runs twice:
        # once to record the wait, once with the committed answer reference.
        self._state(scope, "waiting_input")
        resumed = wait()
        from .category_adoption import resolve

        if not isinstance(resumed, dict) or set(resumed) != {"answer_ref"}:
            raise DomainError("FORBIDDEN_SCOPE", "恢复输入须是服务器已提交的答复引用。")
        answer = resolve(self.engine, scope, resumed["answer_ref"])
        self._state(scope, "running")
        return answer

    def answer(self, scope, wait):
        answer = self._resolved(scope, wait)
        if isinstance(answer, VerifiedCategoryAdoption):
            raise DomainError("FORBIDDEN_SCOPE", "当前检查点没有该待采用候选。")
        return answer

    def adoption(self, scope, wait):
        trusted = self._resolved(scope, wait)
        if not isinstance(trusted, VerifiedCategoryAdoption):
            raise DomainError("FORBIDDEN_SCOPE", "普通答复不能释放品类采用等待。")
        return trusted.envelope(), trusted

    def _call(self, session, scope, call_id):
        call = session.get(AgentToolCall, UUID(str(call_id)))
        if (
            not call or call.tenant_id != scope.tenant_id or call.run_id != scope.run_id
            or call.state != "completed" or not isinstance(call.result, dict)
        ):
            raise DomainError("FORBIDDEN_SCOPE", "执行图引用的调用不在当前运行的账本中。")
        return call

    def hydrate(self, scope, messages):
        if not any(CONTINUATION_REF in message for message in messages):
            return messages
        restored = []
        with self.store.transaction(scope) as (session, _):
            for message in messages:
                reference = message.get(CONTINUATION_REF)
                if reference is None:
                    restored.append(message)
                    continue
                call = self._call(session, scope, reference)
                saved = call.result.get("continuation")
                if call.tool != "model" or saved is None:
                    raise DomainError("FORBIDDEN_SCOPE", "原模型调用没有可续接的协议数据。")
                self._continuations[digest(saved)] = str(call.id)
                value = {k: v for k, v in message.items() if k != CONTINUATION_REF}
                restored.append({**value, "provider_continuation": saved})
        return restored

    def dehydrate(self, scope, messages):
        if not any("provider_continuation" in message for message in messages):
            return messages
        packed = []
        with self.store.transaction(scope) as (session, _):
            for message in messages:
                saved = message.get("provider_continuation")
                if saved is None:
                    packed.append(message)
                    continue
                reference = self._continuations.get(digest(saved))
                if reference is None:
                    # The turn just returned: its completed row is in this run's ledger.
                    for call in session.scalars(
                        select(AgentToolCall).where(
                            AgentToolCall.run_id == scope.run_id,
                            AgentToolCall.tool == "model",
                            AgentToolCall.state == "completed",
                        ).order_by(AgentToolCall.created_at.desc()).limit(20)
                    ):
                        if isinstance(call.result, dict) and call.result.get(
                            "continuation"
                        ) == saved:
                            reference = str(call.id)
                            break
                if reference is None:
                    raise DomainError("SOURCE_UNAVAILABLE", "模型续接数据缺少账本记录。")
                value = {k: v for k, v in message.items() if k != "provider_continuation"}
                packed.append({**value, CONTINUATION_REF: reference})
        return packed

    def pack(self, scope, entry):
        value = entry["value"]
        reference = value.get("execution_ref") if isinstance(value, dict) else None
        if entry["tier"] != "READ" or not isinstance(reference, dict) \
                or not reference.get("call_id"):
            # Receipts, errors and skill bodies are small and have no read-ledger row.
            return entry
        raw = {key: child for key, child in value.items() if key != "execution_ref"}
        return {**entry, "value": {"ledger_ref": reference, "result_digest": digest(raw)}}

    def unpack(self, scope, entries):
        if not any(self._packed(entry) for entry in entries):
            return entries
        restored = []
        with self.store.transaction(scope) as (session, _):
            for entry in entries:
                if not self._packed(entry):
                    restored.append(entry)
                    continue
                packed = entry["value"]
                call = self._call(session, scope, packed["ledger_ref"]["call_id"])
                if call.tool != entry["tool"] or digest(call.result) != packed["result_digest"]:
                    raise DomainError("FORBIDDEN_SCOPE", "账本中的读取结果与执行图记录不一致。")
                restored.append({**entry, "value": {
                    **call.result, "execution_ref": packed["ledger_ref"],
                }})
        return restored

    @staticmethod
    def _packed(entry):
        value = entry.get("value") if isinstance(entry, dict) else None
        return isinstance(value, dict) and set(value) == {"ledger_ref", "result_digest"}

    def final(self, scope, output):
        actions = output.get("result", {}).get("actions")
        if not isinstance(actions, list):
            return output
        return {**output, "result": {**output["result"], "actions": self.unpack(scope, actions)}}


def _no_open_model_call(store, scope):
    """Never send a main-graph model request while an earlier one has no known outcome.

    The gateway already refuses to repeat the same request. This also covers a retry
    whose request no longer hashes the same (route or calibration changed meanwhile):
    the main graph has one model call in flight at a time, so any ``started`` or
    ``unknown`` row means a request may have been sent and must be reconciled.
    """
    with store.transaction(scope) as (session, _):
        open_call = session.scalar(
            select(AgentToolCall).where(
                AgentToolCall.run_id == scope.run_id, AgentToolCall.tool == "model",
                AgentToolCall.state.in_(("started", "unknown")),
                AgentToolCall.execution_binding["isolation"].astext == "main",
            ).limit(1)
        )
        found = (open_call.id, open_call.state) if open_call else None
    if found is None:
        return
    if found[1] == "started":
        store.release_call(scope, found[0], unknown=True, error="EXTERNAL_OUTCOME_UNKNOWN")
    raise DomainError(
        "EXTERNAL_OUTCOME_UNKNOWN", "原模型调用须按回执对账，不能盲目重发。",
        detail={"call_id": str(found[0])},
    )


def _node(name):
    def body(state, context, stop):
        from .activities import KernelActivities
        from .host import BoundHost
        from .tools import default_registry

        store = dependency("kernel_store")
        engine = store.engine
        adapters = getattr(engine, "_pdos_agent_kernel_adapters", None)
        if adapters is None:
            raise DomainError("SOURCE_UNAVAILABLE", "当前模型未配置，AI 暂不可用。")
        scope = store.scope(
            tenant_id=UUID(context["tenant_id"]),
            requester_id=UUID(context["requester_id"]),
            writer_id=UUID(context["writer_id"]),
            category_id=UUID(context["category_id"]) if context["category_id"] else None,
            run_id=UUID(context["subject_id"]),
        )
        if state.get("run_id", str(scope.run_id)) != str(scope.run_id) \
                or state.get("cancel_epoch") != scope.cancel_epoch:
            raise DomainError("CANCELLED_RUN", "运行已取消；已办理动作保留。")
        host = BoundHost(store, adapters)
        host.superseded = stop
        try:
            # One attempt works on a run at a time; an attempt Temporal gave up may
            # still be on its thread, and stops at its next safe point (D243). A lease
            # whose connection dropped stops the attempt the same way (D358).
            with run_lease(engine, scope.run_id, waiting=lambda: check_attempt(stop)) as lease, \
                    lease_watch(lease, stop), attempt_scope(stop):
                kernel = AgentKernel(
                    host, adapters.tool_registry or default_registry(), catalog=host.catalog,
                )
                preload = (
                    KernelActivities(engine).preload(scope, adapters)
                    if name == "prepare_context" else ()
                )
                if name == "model":
                    _no_open_model_call(store, scope)
                nodes = kernel.nodes(scope, preload=preload, hooks=PluginHooks(store, engine))
                return nodes[name](state)
        finally:
            host.gateway.close()

    body.__name__ = name
    body.__qualname__ = name
    return body


prepare_context = _node("prepare_context")
model = _node("model")
route = _node("route")
tools = _node("tools")
await_category_adoption = _node("await_category_adoption")
verify = _node("verify")
finalize = _node("finalize")


async def rollover_gate(state):
    """Workflow side. Ask the workflow to continue as new once its history is large."""
    turns = state.get("turns", 0)
    info = workflow.info()
    if turns > state.get("rolled_at", 0) and (
        info.is_continue_as_new_suggested()
        or info.get_current_history_size() >= ROLLOVER_HISTORY_BYTES
        or turns - state.get("rolled_at", 0) >= ROLLOVER_MODEL_TURNS
    ):
        interrupt({"type": "rollover"})
    return {}


async def choose(state):
    if state["calls"]:
        return "tools"
    if not state["output"]:
        return "model"
    return "route" if state["output"].get("status") == "needs_input" else "verify"


async def after_route(state):
    # An answered question clears the output; malformed questions go to verification.
    return "verify" if state["output"] else "model"


async def after_tools(state):
    return "await_category_adoption" if state.get("pending_categories") else "rollover_gate"


async def after_verify(state):
    return "finalize" if state["output"] else "model"


def _options(minutes, *, heartbeat=True, attempts=3):
    return {
        "execute_in": "activity",
        "start_to_close_timeout": timedelta(minutes=minutes),
        **({"heartbeat_timeout": timedelta(seconds=45)} if heartbeat else {}),
        "retry_policy": (
            RetryPolicy(maximum_attempts=attempts) if attempts
            else RetryPolicy(maximum_interval=timedelta(minutes=1))
        ),
    }


def build(*, gate=rollover_gate):
    """``gate`` is replaceable only so the graph can be driven outside a workflow."""
    graph = StateGraph(State)
    for name, body, options in (
        ("prepare_context", prepare_context, _options(5)),
        ("model", model, _options(20)),
        ("route", route, _options(1)),
        # W1 rounds with isolated children legitimately ran 10–30 minutes (D243).
        ("tools", tools, _options(60)),
        ("await_category_adoption", await_category_adoption, _options(1)),
        ("verify", verify, _options(5)),
        # Technical closure must survive a database outage; finish is idempotent.
        ("finalize", finalize, _options(1, attempts=None)),
    ):
        graph.add_node(name, activity_node(body), metadata=options)
    graph.add_node("rollover_gate", gate, metadata={"execute_in": "workflow"})
    return wire(graph)


def wire(graph):
    """The main graph's edges, for a graph that already has its eight nodes."""
    graph.add_edge(START, "prepare_context")
    graph.add_edge("prepare_context", "model")
    graph.add_conditional_edges("model", choose, ["tools", "model", "route", "verify"])
    graph.add_conditional_edges("route", after_route, ["model", "verify"])
    graph.add_conditional_edges("tools", after_tools, ["await_category_adoption", "rollover_gate"])
    graph.add_conditional_edges(
        "await_category_adoption", after_tools, ["await_category_adoption", "rollover_gate"]
    )
    graph.add_edge("rollover_gate", "model")
    graph.add_conditional_edges("verify", after_verify, ["finalize", "model"])
    graph.add_edge("finalize", END)
    return graph
