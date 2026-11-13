"""Stage 1 pilot of the Temporal LangGraph plugin (P100) against a real local Temporal.

Covers: normal completion and replay; a worker killed inside a node, after which the
finished node is not run again; duplicate, invalid and out-of-order signals; a node
attempt that times out and is retried; how a stopped node closes the run; and that no
credential-shaped value reaches workflow history. The journal counts node executions
(the summary has no model call to count; see the decision record §2.2).
"""

import asyncio
import base64
import json
import os
import re
import signal
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from temporalio.langgraph import LangGraphPlugin
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from pdos_next.domain.my_work import summary_plugin_graph
from pdos_next.workflows.xiaopai_graph import XiaopaiGraphWork
from tests.workflows import graph_pilot_fixtures as fixtures
from tests.workflows.graph_pilot_workflow import AskWork

pytestmark = pytest.mark.skipif(
    not fixtures.BINARY.is_file(), reason="Inspected local Temporal binary required",
)
SERVER = Path(__file__).resolve().parents[2]


def reference():
    return {key: str(uuid4()) for key in (
        "tenant_id", "category_id", "actor_id", "requester_id", "subject_id",
    )}


@pytest.fixture
def pilot(tmp_path, monkeypatch):
    monkeypatch.setenv("PDOS_GRAPH_PILOT_JOURNAL", str(tmp_path / "journal.txt"))
    fixtures.patch_summary(monkeypatch)
    return tmp_path


def plugin():
    return LangGraphPlugin(graphs={
        summary_plugin_graph.GRAPH: summary_plugin_graph.build(), "ask": fixtures.build_ask(),
    })


def worker(client, queue, executor):
    return Worker(
        client, task_queue=queue, workflows=[XiaopaiGraphWork, AskWork],
        activities=fixtures.RUN_ACTIVITIES, plugins=[plugin()], activity_executor=executor,
    )


def local(test):
    async def actual():
        environment = await WorkflowEnvironment.start_local(
            dev_server_existing_path=str(fixtures.BINARY),
        )
        try:
            with ThreadPoolExecutor(max_workers=4) as executor:
                await asyncio.wait_for(test(environment, executor), 180)
        finally:
            await environment.shutdown()

    asyncio.run(actual())


async def measured(handle):
    history = await handle.fetch_history()
    activities = [
        event.activity_task_scheduled_event_attributes.activity_type.name
        for event in history.events
        if event.HasField("activity_task_scheduled_event_attributes")
    ]
    return history, activities, len(history.events), len(history.to_json().encode())


def payloads(history):
    """Every payload recorded in a history, decoded (they are base64 in its JSON)."""
    return b"\n".join(
        base64.b64decode(value) for value in re.findall(r'"data":\s*"([^"]*)"', history.to_json())
    ).decode().encode().decode("unicode_escape")


def record(name, events, size, activities):
    target = os.environ.get("PDOS_GRAPH_PILOT_EVIDENCE")
    if target:
        with Path(target).open("a") as handle:
            handle.write(json.dumps({
                "case": name, "history_events": events, "history_json_bytes": size,
                "activities": activities,
            }, ensure_ascii=False) + "\n")


def test_summary_completes_node_by_node_and_replays(pilot):
    async def test(environment, executor):
        queue, ref = "pilot-" + str(uuid4()), reference()
        async with worker(environment.client, queue, executor):
            handle = await environment.client.start_workflow(
                XiaopaiGraphWork.run, ref, id="pilot-" + ref["subject_id"],
                task_queue=queue,
            )
            assert await handle.result() == {"run_id": ref["subject_id"], "status": "completed"}
        assert fixtures.notes() == ["open", "generate", "persist:start", "persist:done"]
        history, activities, events, size = await measured(handle)
        assert activities == [
            "open_xiaopai_graph_run",
            "personal-summary.read_personal_summary",
            "personal-summary.persist_personal_summary",
        ]
        record("summary_normal", events, size, activities)
        # Run data is allowed in history (P100); the fixed reference still carries no more.
        recorded = payloads(history)
        assert "合成摘要条目" in recorded and ref["subject_id"] in recorded
        assert fixtures.SECRET not in recorded
        # Nondeterminism check: the recorded history replays against the same code.
        await Replayer(
            workflows=[XiaopaiGraphWork], plugins=[plugin()],
        ).replay_workflow(history)
        assert fixtures.notes().count("generate") == 1

    local(test)


def test_worker_killed_inside_a_node_does_not_rerun_the_finished_node(pilot):
    async def test(environment, _executor):
        queue, ref = "pilot-" + str(uuid4()), reference()
        target = environment.client.service_client.config.target_host
        command = [sys.executable, "-m", "tests.workflows.graph_pilot_worker",
                   target, environment.client.namespace, queue]

        def spawn():
            return subprocess.Popen(command, cwd=SERVER, env=dict(os.environ))

        async def until(line, count=1):
            while fixtures.notes().count(line) < count:
                await asyncio.sleep(0.05)

        fixtures.flag("block-persist").touch()
        first = spawn()
        second = None
        try:
            await until("worker:ready")
            handle = await environment.client.start_workflow(
                XiaopaiGraphWork.run, ref, id="pilot-" + ref["subject_id"],
                task_queue=queue,
            )
            await until("persist:start")
            first.send_signal(signal.SIGKILL)  # no shutdown hook, no acknowledgement
            first.wait()
            assert fixtures.notes().count("generate") == 1
            assert "persist:done" not in fixtures.notes()
            fixtures.flag("block-persist").unlink()
            second = spawn()
            # Temporal notices the dead attempt by its 45 s heartbeat timeout.
            assert await handle.result() == {"run_id": ref["subject_id"], "status": "completed"}
        finally:
            for process in (first, second):
                if process and process.poll() is None:
                    process.kill()
                    process.wait()
        lines = fixtures.notes()
        assert lines.count("open") == 1 and lines.count("generate") == 1
        assert lines.count("persist:start") == 2 and lines.count("persist:done") == 1
        _, activities, events, size = await measured(handle)
        assert activities.count("personal-summary.read_personal_summary") == 1
        record("summary_worker_killed", events, size, activities)

    local(test)


def test_signals_are_deduplicated_and_consumed_in_arrival_order(pilot):
    async def test(environment, executor):
        queue, ref = "pilot-" + str(uuid4()), reference()
        early, late = str(uuid4()), str(uuid4())
        async with worker(environment.client, queue, executor):
            # The summary never asks: stray signals of any shape leave it untouched.
            summary = await environment.client.start_workflow(
                XiaopaiGraphWork.run, reference(), id="pilot-" + str(uuid4()),
                task_queue=queue,
            )
            for value in (late, "not-a-reference", late, early):
                await summary.signal(XiaopaiGraphWork.resume, value)
            assert (await summary.result())["status"] == "completed"

            handle = await environment.client.start_workflow(
                AskWork.run, args=[ref, False], id="ask-" + ref["subject_id"],
                task_queue=queue,
            )
            # Both answers, a duplicate and garbage arrive before the first question
            # exists, the later answer first.
            for value in (late, "approved", early, late, early.upper()):
                await handle.signal(AskWork.resume, value)
            result = await handle.result()
        assert result["answers"] == [late, early] and result["done"] is True
        lines = fixtures.notes()
        assert lines.count("prepare") == 1
        # An interrupted node starts again from its top when it is resumed.
        assert lines.count("ask:enter") == 4 and lines.count("ask:answered") == 2
        history, activities, events, size = await measured(handle)
        assert "approved" not in payloads(history).replace('"approved"', "", 1)
        record("ask_two_interrupts", events, size, activities)
        await Replayer(workflows=[AskWork], plugins=[plugin()]).replay_workflow(history)

    local(test)


def test_pending_question_is_queryable_until_answered(pilot):
    async def test(environment, executor):
        queue, ref = "pilot-" + str(uuid4()), reference()
        async with worker(environment.client, queue, executor):
            handle = await environment.client.start_workflow(
                AskWork.run, args=[ref, False], id="ask-" + ref["subject_id"],
                task_queue=queue,
            )
            for asked in (0, 1):
                while await handle.query(AskWork.pending_input) != [
                    {"type": "question", "asked": asked}
                ]:
                    await asyncio.sleep(0.05)
                await handle.signal(AskWork.resume, str(uuid4()))
            assert (await handle.result())["done"] is True
            assert await handle.query(AskWork.pending_input) is None

    local(test)


def test_timed_out_attempt_is_retried_without_rerunning_earlier_nodes(pilot):
    async def test(environment, executor):
        queue, ref = "pilot-" + str(uuid4()), reference()
        async with worker(environment.client, queue, executor):
            handle = await environment.client.start_workflow(
                AskWork.run, args=[ref, True], id="ask-" + ref["subject_id"],
                task_queue=queue,
            )
            for _ in range(2):
                await handle.signal(AskWork.resume, str(uuid4()))
            result = await handle.result()
            await asyncio.sleep(3)  # let the abandoned first attempt's thread end
        assert result["done"] is True
        lines = fixtures.notes()
        assert lines.count("finish:attempt1") == 1 and lines.count("finish:attempt2") == 1
        assert lines.count("prepare") == 1 and lines.count("ask:answered") == 2

    local(test)


def test_stopped_node_closes_the_run_with_its_code_and_is_not_retried(pilot):
    async def test(environment, executor):
        queue, ref = "pilot-" + str(uuid4()), reference()
        fixtures.flag("fail-generate").touch()
        async with worker(environment.client, queue, executor):
            handle = await environment.client.start_workflow(
                XiaopaiGraphWork.run, ref, id="pilot-" + ref["subject_id"],
                task_queue=queue,
            )
            result = await handle.result()
        assert result == {"run_id": ref["subject_id"], "status": "failed",
                          "error_code": "FORBIDDEN_SCOPE"}
        assert fixtures.notes() == ["open", "generate", "close:FORBIDDEN_SCOPE"]

    local(test)


def test_workflow_rejects_anything_but_the_fixed_reference(pilot):
    async def test(environment, executor):
        from temporalio.client import WorkflowFailureError

        queue = "pilot-" + str(uuid4())
        async with worker(environment.client, queue, executor):
            handle = await environment.client.start_workflow(
                XiaopaiGraphWork.run, {**reference(), "api_key": fixtures.SECRET},
                id="pilot-" + str(uuid4()), task_queue=queue,
            )
            with pytest.raises(WorkflowFailureError):
                await handle.result()
        assert fixtures.notes() == []

    local(test)
