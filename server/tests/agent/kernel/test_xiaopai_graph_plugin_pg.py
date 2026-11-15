"""The 小Pai main graph on the Temporal LangGraph plugin (P100), end to end on PostgreSQL."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.core.models import Receipt
from tests.agent.kernel import xiaopai_graph_plugin_harness as harness
from tests.agent.kernel.xiaopai_graph_plugin_harness import final, prepare, serve, tool_turn

pytestmark = pytest.mark.skipif(
    not harness.BINARY.is_file(), reason="Inspected local Temporal binary required",
)


def test_completed_run_executes_node_by_node_with_one_request_per_turn(setup, monkeypatch):
    stack = prepare(setup, monkeypatch, [None, final()])
    stack.client.steps[0] = tool_turn(stack)

    async def body(context):
        run_id = await context.start()
        assert await context.result(run_id) == {"run_id": str(run_id), "status": "completed"}
        assert (await context.view(run_id))["status"] == "completed"
        description = await context.handle(run_id).describe()
        assert description.workflow_type == "XiaopaiGraphWork"
        history, = await context.histories(run_id)
        await context.replay(history)
        return run_id, history

    run_id, history = serve(stack, body)
    harness.record("xiaopai_completed_one_tool_round", [history])
    assert stack.client.calls == 2
    assert harness.scheduled(history) == [
        "open_xiaopai_graph_run", "xiaopai.prepare_context", "xiaopai.model",
        "xiaopai.tools", "xiaopai.model", "xiaopai.verify", "xiaopai.finalize",
    ]
    saved = harness.row(setup, run_id)
    assert saved.state == "completed" and saved.held_tokens == 0
    assert saved.versions["execution_engine"] == "temporal-langgraph/v1"
    assert ("evidence.claim.record", "completed") in saved.calls
    assert saved.calls.count(("model", "completed")) == 2
    with Session(setup.admin) as session:
        assert session.scalar(select(Receipt).where(
            Receipt.agent_run_id == run_id, Receipt.operation == "evidence.claim.record",
        )) is not None
    recorded = harness.payloads(history)
    assert "Synthetic actual source claim" in recorded  # run data may be in history
    assert harness.SECRET not in recorded


def test_partial_when_the_run_budget_cannot_cover_a_model_request(setup, monkeypatch):
    stack = prepare(setup, monkeypatch, [final()])

    async def body(context):
        run_id = await context.start()
        result = await context.result(run_id)
        history, = await context.histories(run_id)
        return run_id, result, history

    run_id, result, history = serve(stack, body, token_limit=100)
    assert result == {"run_id": str(run_id), "status": "partial"}
    assert stack.client.calls == 0  # refused before any request was sent
    assert harness.scheduled(history)[-2:] == ["xiaopai.verify", "xiaopai.finalize"]
    saved = harness.row(setup, run_id)
    assert saved.state == "partial" and saved.result["status"] == "partial"


def test_cancelled_while_the_model_is_answering_stops_without_another_request(
    setup, monkeypatch
):
    import threading

    from temporalio.client import WorkflowFailureError

    release = threading.Event()

    def slow(_client):
        assert release.wait(30)
        return final()

    stack = prepare(setup, monkeypatch, [slow, final()])

    async def body(context):
        import asyncio

        run_id = await context.start()
        while stack.client.calls < 1:
            await asyncio.sleep(0.05)
        cancelled = await context.http.post(
            f"{context.path}/{run_id}/cancel", headers=setup.headers,
        )
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
        release.set()
        try:
            outcome = await context.result(run_id)
        except WorkflowFailureError as error:
            outcome = type(error.cause).__name__
        history, = await context.histories(run_id)
        return run_id, outcome, history

    run_id, outcome, history = serve(stack, body)
    assert outcome == "CancelledError" or outcome["status"] == "cancelled"
    assert stack.client.calls == 1
    assert "xiaopai.finalize" not in harness.scheduled(history)
    saved = harness.row(setup, run_id)
    assert saved.state == "cancelled" and saved.result is None and saved.held_tokens == 0


def test_failed_when_the_provider_refuses_and_the_request_is_not_repeated(setup, monkeypatch):
    from pdos_next.providers.types import ProviderError

    def refuse(_client):
        raise ProviderError("SOURCE_UNAVAILABLE")

    stack = prepare(setup, monkeypatch, [refuse, final()])

    async def body(context):
        run_id = await context.start()
        result = await context.result(run_id)
        history, = await context.histories(run_id)
        await context.replay(history)
        return run_id, result, history

    run_id, result, history = serve(stack, body)
    assert result["status"] == "failed" and result["error_code"] == "SOURCE_UNAVAILABLE"
    assert stack.client.calls == 1
    assert harness.scheduled(history)[-2:] == ["xiaopai.model", "close_xiaopai_graph_run"]
    saved = harness.row(setup, run_id)
    assert (saved.state, saved.error_code) == ("failed", "SOURCE_UNAVAILABLE")
    assert saved.held_tokens == 0


def test_unknown_provider_outcome_goes_to_reconciliation_not_a_second_request(
    setup, monkeypatch
):
    from pdos_next.providers.types import ProviderError

    def lost(_client):
        raise ProviderError("TIMEOUT", unknown=True)

    stack = prepare(setup, monkeypatch, [lost, final()])

    async def body(context):
        run_id = await context.start()
        result = await context.result(run_id)
        history, = await context.histories(run_id)
        await context.replay(history)
        return run_id, result, history

    run_id, result, history = serve(stack, body)
    assert stack.client.calls == 1
    assert harness.scheduled(history)[-3:] == [
        "xiaopai.model", "close_xiaopai_graph_run", "reconcile_xiaopai_run",
    ]
    saved = harness.row(setup, run_id)
    assert "reconciliation_required" in saved.events
    assert ("model", "completed") not in saved.calls
    assert result["status"] == saved.state and saved.state in {"failed", "partial"}
    assert saved.held_tokens == 0


class WorkerDied(BaseException):
    """Leaves the attempt as a killed worker would: no settlement, no error handling."""


def test_worker_lost_after_the_request_was_sent_is_reconciled_not_resent(setup, monkeypatch):
    def die(_client):
        raise WorkerDied()

    stack = prepare(setup, monkeypatch, [die, final()])

    async def body(context):
        run_id = await context.start()
        result = await context.result(run_id)
        history, = await context.histories(run_id)
        return run_id, result, history

    run_id, result, history = serve(stack, body)
    # The first attempt sent the request and vanished with its ledger row still open.
    # The retried attempt found that row and stopped before the gateway.
    assert stack.client.calls == 1
    names = harness.scheduled(history)
    assert names.count("xiaopai.model") == 1 and names[-1] == "reconcile_xiaopai_run"
    attempts = [
        event.activity_task_started_event_attributes.attempt for event in history.events
        if event.HasField("activity_task_started_event_attributes")
    ]
    assert 2 in attempts
    saved = harness.row(setup, run_id)
    assert ("model", "completed") not in saved.calls and saved.held_tokens == 0
    assert "reconciliation_required" in saved.events
    assert result["status"] == saved.state and saved.state in {"failed", "partial"}


def test_completed_request_is_replayed_from_the_ledger_when_its_result_was_lost(
    setup, monkeypatch
):
    from sqlalchemy.exc import OperationalError

    from pdos_next.agent.kernel import plugin_graph

    stack = prepare(setup, monkeypatch, [final()])
    original, lost = plugin_graph.PluginHooks.dehydrate, []

    def lose_once(self, scope, messages):
        if not lost:
            lost.append(1)
            # After the gateway settled the call, before the node could return it.
            raise OperationalError("synthetic", {}, Exception("connection lost"))
        return original(self, scope, messages)

    monkeypatch.setattr(plugin_graph.PluginHooks, "dehydrate", lose_once)

    async def body(context):
        run_id = await context.start()
        return run_id, await context.result(run_id)

    run_id, result = serve(stack, body)
    assert result["status"] == "completed" and lost
    assert stack.client.calls == 1  # the retry restored the recorded answer
    assert harness.row(setup, run_id).calls.count(("model", "completed")) == 1


def test_question_waits_for_a_committed_answer_and_ignores_duplicates(setup, monkeypatch):
    from uuid import uuid4

    from pdos_next.workflows.xiaopai_graph import XiaopaiGraphWork

    stack = prepare(setup, monkeypatch, [
        harness.question("market"), harness.question("voltage"), final(),
    ])

    async def body(context):
        run_id = await context.start()
        handle = context.handle(run_id)
        first, = await context.waiting(run_id)
        assert first["questions"][0]["id"] == "market"
        assert (await context.view(run_id))["status"] == "waiting_input"
        assert harness.row(setup, run_id).state == "waiting_input"
        await handle.signal(XiaopaiGraphWork.resume, "approved")  # not a reference
        market = await context.answer(run_id, {"market": "US"})
        await handle.signal(XiaopaiGraphWork.resume, market)  # duplicate delivery
        while True:
            pending = await context.waiting(run_id)
            if pending[0]["questions"][0]["id"] == "voltage":
                break
        await handle.signal(XiaopaiGraphWork.resume, market)  # late duplicate
        assert stack.client.calls == 2
        await context.answer(run_id, {"voltage": "120V"})
        result = await context.result(run_id)
        history, = await context.histories(run_id)
        await context.replay(history)
        return run_id, result, history, str(uuid4())

    run_id, result, history, _ = serve(stack, body)
    harness.record("xiaopai_two_questions", [history])
    assert result["status"] == "completed" and stack.client.calls == 3
    # Each answer reached the model exactly once, in order.
    assert '"market": "US"' in stack.client.requests[1][-1]["content"]
    assert '"voltage": "120V"' in stack.client.requests[2][-1]["content"]
    assert sum('"market": "US"' in m["content"] for m in stack.client.requests[2]) == 1
    names = harness.scheduled(history)
    assert names.count("xiaopai.model") == 3 and names.count("xiaopai.route") == 4
    # Signals carried references only.
    signals = [
        event.workflow_execution_signaled_event_attributes for event in history.events
        if event.HasField("workflow_execution_signaled_event_attributes")
    ]
    assert len(signals) == 5 and "120V" not in str(signals)
    assert harness.row(setup, run_id).state == "completed"


def test_long_run_continues_as_new_without_rerunning_finished_nodes(setup, monkeypatch):
    from pdos_next.agent.kernel import plugin_graph

    stack = prepare(setup, monkeypatch, [None, None, final()])
    stack.client.steps[0] = tool_turn(stack, "first")
    stack.client.steps[1] = tool_turn(stack, "second")
    monkeypatch.setattr(plugin_graph, "ROLLOVER_MODEL_TURNS", 1)

    async def body(context):
        run_id = await context.start()
        result = await context.result(run_id)
        histories = await context.histories(run_id)
        for history in histories:
            await context.replay(history)
        return run_id, result, histories

    run_id, result, histories = serve(stack, body)
    harness.record("xiaopai_two_tool_rounds_rolled_over", histories)
    assert result == {"run_id": str(run_id), "status": "completed"}
    assert len(histories) == 3  # rolled over after each tool round
    for history in histories[:-1]:
        assert history.events[-1].HasField(
            "workflow_execution_continued_as_new_event_attributes"
        )
    names = [name for history in histories for name in harness.scheduled(history)]
    assert names == [
        "open_xiaopai_graph_run", "xiaopai.prepare_context", "xiaopai.model", "xiaopai.tools",
        "xiaopai.model", "xiaopai.tools", "xiaopai.model", "xiaopai.verify",
        "xiaopai.finalize",
    ]
    assert stack.client.calls == 3
    saved = harness.row(setup, run_id)
    assert saved.state == "completed" and saved.calls.count(("model", "completed")) == 3
    assert saved.events.count("skill_loaded") == 1


def _read_turn(stack):
    import json

    from pdos_next.agent.kernel.types import ModelTurn, ToolCall
    from pdos_next.providers.agent_wire import tool_name
    from pdos_next.providers.types import ProviderUsage

    arguments = {"artifact_ids": [stack.f.arguments["artifact_id"]]}
    return ModelTurn(
        calls=(ToolCall(id="read", name="assistant.materials.read", arguments=arguments),),
        usage=ProviderUsage(20, 10),
        # Provider-private protocol data for the next request of the same route, in the
        # exact shape the real wire layer validates before it re-sends it.
        continuation={
            "protocol": stack.f.route.protocol, "route_digest": stack.f.route.digest,
            "message": {
                "role": "assistant", "content": "",
                "reasoning_content": "PRIVATE-REASONING-MARK",
                "tool_calls": [{"id": "read", "type": "function", "function": {
                    "name": tool_name("assistant.materials.read"),
                    "arguments": json.dumps(arguments),
                }}],
            },
        },
    )


def test_read_results_and_provider_continuation_stay_in_the_ledger(setup, monkeypatch):
    stack = prepare(setup, monkeypatch, [None, final()])
    stack.client.steps[0] = _read_turn(stack)

    async def body(context):
        run_id = await context.start()
        result = await context.result(run_id)
        history, = await context.histories(run_id)
        return run_id, result, history

    run_id, result, history = serve(stack, body)
    harness.record("xiaopai_read_by_ledger_reference", [history])
    assert result["status"] == "completed", harness.row(setup, run_id).error_code
    recorded = harness.payloads(history)
    # Graph state carried references; the second request still got the real values.
    assert '"ledger_ref"' in recorded and '"result_digest"' in recorded
    assert '"provider_continuation_ref"' in recorded
    assert "PRIVATE-REASONING-MARK" not in recorded
    assistant, = [m for m in stack.client.requests[1] if m["role"] == "assistant"]
    assert assistant["provider_continuation"]["message"]["reasoning_content"] == (
        "PRIVATE-REASONING-MARK"
    )
    assert "provider_continuation_ref" not in assistant
    assert ("assistant.materials.read", "completed") in harness.row(setup, run_id).calls


def test_partial_result_lists_full_actions_restored_from_the_ledger(setup, monkeypatch):
    from pdos_next.agent.kernel import graph

    # Two turns: the read on the first runs; the last turn's call is not run (P122).
    stack = prepare(setup, monkeypatch, [None, None])
    stack.client.steps[0] = _read_turn(stack)
    stack.client.steps[1] = _read_turn(stack)
    budget = graph.Budget
    monkeypatch.setattr(graph, "Budget", lambda: budget(model_turns=2))

    async def body(context):
        run_id = await context.start()
        return run_id, await context.result(run_id)

    run_id, result = serve(stack, body)
    assert result["status"] == "partial" and stack.client.calls == 2
    action, = harness.row(setup, run_id).result["result"]["actions"]
    assert action["tool"] == "assistant.materials.read"
    assert "ledger_ref" not in action["value"] and "execution_ref" in action["value"]


def _blocking_read(monkeypatch, name="assistant.materials.read"):
    """Make one registered read wait inside the tools node until the test releases it."""
    import threading

    from pdos_next.agent.kernel.host import BoundHost

    entered, release = threading.Event(), threading.Event()
    original = BoundHost._registered_read

    def slow(self, scope, spec, *args, **kwargs):
        if spec.name == name:
            entered.set()
            assert release.wait(30)
        return original(self, scope, spec, *args, **kwargs)

    monkeypatch.setattr(BoundHost, "_registered_read", slow)
    return entered, release


def test_cancelled_while_a_tool_is_running_stops_before_the_next_model_request(
    setup, monkeypatch
):
    import asyncio

    from temporalio.client import WorkflowFailureError

    stack = prepare(setup, monkeypatch, [None, final()])
    stack.client.steps[0] = _read_turn(stack)
    entered, release = _blocking_read(monkeypatch)

    async def body(context):
        run_id = await context.start()
        assert await asyncio.to_thread(entered.wait, 30)
        cancelled = await context.http.post(
            f"{context.path}/{run_id}/cancel", headers=setup.headers,
        )
        assert cancelled.json()["status"] == "cancelled"
        release.set()
        try:
            outcome = await context.result(run_id)
        except WorkflowFailureError as error:
            outcome = type(error.cause).__name__
        history, = await context.histories(run_id)
        return run_id, outcome, history

    run_id, outcome, history = serve(stack, body)
    assert outcome == "CancelledError" or outcome["status"] == "cancelled"
    assert stack.client.calls == 1
    names = harness.scheduled(history)
    assert names.count("xiaopai.model") == 1 and "xiaopai.finalize" not in names
    saved = harness.row(setup, run_id)
    assert saved.state == "cancelled" and saved.result is None and saved.held_tokens == 0
    assert ("model", "started") not in saved.calls


async def _revert(context, run_id):
    """The real whole-run revert: the person's preview, then their T1 command."""
    setup = context.setup
    candidate = await context.http.post(
        f"{context.path}/{run_id}/revert-preview", headers=setup.headers,
    )
    if candidate.status_code != 200:
        return candidate
    return await context.http.post(
        f"/v1/categories/{setup.category}/commands", headers=setup.headers,
        json=candidate.json()["command"],
    )


def test_run_reverted_while_the_model_is_answering_stops_and_is_not_opened_again(
    setup, monkeypatch
):
    import asyncio
    import threading
    from uuid import uuid4

    from pdos_next.workflows.xiaopai_graph import XiaopaiGraphWork

    release = threading.Event()

    def slow(_client):
        assert release.wait(30)
        return final()

    stack = prepare(setup, monkeypatch, [None, slow, final()])
    stack.client.steps[0] = tool_turn(stack)

    async def body(context):
        run_id = await context.start()
        while stack.client.calls < 2:
            await asyncio.sleep(0.05)
        # The person reverts the whole run while its second model request is in flight.
        reverted = await _revert(context, run_id)
        assert reverted.status_code == 200, reverted.text
        release.set()
        result = await context.result(run_id)
        history, = await context.histories(run_id)
        # A later workflow for the reverted run stops at open and runs no node.
        again = await context.environment.client.start_workflow(
            XiaopaiGraphWork.run,
            {"tenant_id": str(setup.tenant), "category_id": str(setup.category),
             "actor_id": str(setup.human), "requester_id": str(setup.human),
             "subject_id": str(run_id)},
            id="reverted-" + str(uuid4()), task_queue=context.port.task_queue,
        )
        return run_id, result, history, await again.result(), await again.fetch_history()

    run_id, result, history, reopened, second = serve(stack, body)
    assert result["status"] == "cancelled", result
    assert stack.client.calls == 2  # the answer that arrived after the revert is unused
    names = harness.scheduled(history)
    assert "xiaopai.finalize" not in names and "xiaopai.verify" not in names
    assert reopened == {"run_id": str(run_id), "status": "cancelled", "reverted": True}
    assert harness.scheduled(second) == ["open_xiaopai_graph_run"]
    with Session(setup.admin) as session:
        from pdos_next.agent.kernel.models import AgentRun

        run = session.get(AgentRun, run_id)
        assert run.reverted_at and run.cancel_epoch == 1 and run.held_tokens == 0
        assert run.state != "completed" and run.result is None


def test_retried_node_repeats_its_progress_event_but_no_ledger_call(setup, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from pdos_next.agent.kernel import plugin_graph

    stack = prepare(setup, monkeypatch, [None, final()])
    stack.client.steps[0] = tool_turn(stack)
    original, lost = plugin_graph.PluginHooks.dehydrate, []

    def lose_once(self, scope, messages):
        if not lost:
            lost.append(1)
            raise OperationalError("synthetic", {}, Exception("connection lost"))
        return original(self, scope, messages)

    monkeypatch.setattr(plugin_graph.PluginHooks, "dehydrate", lose_once)

    async def body(context):
        run_id = await context.start()
        result = await context.result(run_id)
        process = await context.http.get(
            f"{context.path}/{run_id}/process", headers=setup.headers,
        )
        return run_id, result, process.json()

    run_id, result, process = serve(stack, body)
    assert result["status"] == "completed" and stack.client.calls == 2
    saved = harness.row(setup, run_id)
    # Known and cosmetic (P100 R7): the retried attempt announced its turn again.
    assert saved.events.count("model_started") == 3
    # Everything that is counted, charged or shown as a call comes from the ledger,
    # which has exactly the two model calls and the one tool call.
    assert saved.events.count("egress_checked") == 2
    assert saved.events.count("tool_started") == saved.events.count("tool_finished") == 1
    assert saved.calls.count(("model", "completed")) == 2 and len(saved.calls) == 3
    assert process["call_counts"] == {"total": 3, "completed": 3, "pending": 0, "failed": 0}
    assert [s["kind"] for s in process["steps"]].count("model_started") == 3


def test_rebuilding_scope_and_ports_for_each_node_is_cheap(setup, monkeypatch):
    import threading
    import time

    from pdos_next.agent.kernel import graph, plugin_graph

    stack = prepare(setup, monkeypatch, [None, final()])
    stack.client.steps[0] = tool_turn(stack)
    started, setups, lock = {}, [], threading.Lock()
    dependency, nodes = plugin_graph.dependency, graph.AgentKernel.nodes

    def begin(name):
        started[threading.get_ident()] = time.perf_counter()  # first thing a node does
        return dependency(name)

    def ready(self, scope, **kwargs):
        with lock:
            setups.append(time.perf_counter() - started[threading.get_ident()])
        return nodes(self, scope, **kwargs)

    monkeypatch.setattr(plugin_graph, "dependency", begin)
    monkeypatch.setattr(graph.AgentKernel, "nodes", ready)

    async def body(context):
        run_id = await context.start()
        return await context.result(run_id)

    assert serve(stack, body)["status"] == "completed"
    assert len(setups) == 6  # one per node Activity
    ordered = sorted(setups)
    harness.record_value("xiaopai_node_setup_seconds", {
        "nodes": len(setups), "median": round(ordered[len(ordered) // 2], 4),
        "max": round(ordered[-1], 4), "total": round(sum(setups), 4),
    })
    # Scope from the database, a host with its gateway, the kernel, the run lease and,
    # for the first node, the preload. Generous bound: this guards against a regression
    # to seconds per node, not a benchmark.
    assert ordered[len(ordered) // 2] < 0.5 and ordered[-1] < 2.0


def test_worker_process_killed_after_the_request_was_sent_is_reconciled_not_resent(
    setup, monkeypatch, tmp_path
):
    """G3: a real worker process, really killed, with the request already on the wire."""
    import asyncio
    import json
    import os
    import signal
    import subprocess
    import sys
    from pathlib import Path

    stack = prepare(setup, monkeypatch, [final()])
    journal = tmp_path / "journal.txt"
    hang = journal.with_suffix(".hang")
    hang.touch()
    binding = stack.runtime_ports.secrets.binding
    described = json.dumps([
        str(binding.tenant_id), str(binding.reference), str(binding.version),
        binding.protocol, binding.available,
    ])

    def lines():
        return journal.read_text().split() if journal.exists() else []

    async def body(context):
        target = context.environment.client.service_client.config.target_host
        command = [sys.executable, "-m", "tests.agent.kernel.xiaopai_graph_plugin_worker",
                   target, context.environment.client.namespace, context.port.task_queue,
                   described]

        def spawn():
            return subprocess.Popen(
                command, cwd=Path(__file__).resolve().parents[3],
                env={**os.environ, "PDOS_GRAPH_PILOT_JOURNAL": str(journal)},
            )

        async def until(line, count=1):
            while lines().count(line) < count:
                await asyncio.sleep(0.05)

        first, second = spawn(), None
        try:
            await until("worker:ready")
            run_id = await context.start()
            await until("request")
            first.send_signal(signal.SIGKILL)  # the request is out; nothing was settled
            first.wait()
            assert ("model", "started") in harness.row(setup, run_id).calls
            hang.unlink()
            second = spawn()
            # Temporal notices the dead attempt by its 45 s heartbeat timeout.
            result = await context.result(run_id, seconds=150)
            history, = await context.histories(run_id)
            return run_id, result, history
        finally:
            for process in (first, second):
                if process and process.poll() is None:
                    process.kill()
                    process.wait()

    run_id, result, history = serve(stack, body, timeout=200, in_process_worker=False)
    assert lines().count("request") == 1  # the new process never sent it again
    names = harness.scheduled(history)
    assert names.count("xiaopai.model") == 1 and names[-1] == "reconcile_xiaopai_run"
    assert names.count("xiaopai.prepare_context") == 1
    saved = harness.row(setup, run_id)
    assert ("model", "completed") not in saved.calls and saved.held_tokens == 0
    assert "reconciliation_required" in saved.events
    assert result["status"] == saved.state and saved.state in {"failed", "partial"}
