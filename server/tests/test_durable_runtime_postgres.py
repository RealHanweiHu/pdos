"""Real local Temporal + independent PostgreSQL recovery, never a business database."""

import asyncio
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from pdos_agent_runtime.activity import AgentActivities
from pdos_agent_runtime.bootstrap import install
from pdos_agent_runtime.client import DurableRuntime
from pdos_agent_runtime.followup import ProjectFollowup
from pdos_agent_runtime.graph import in_agent_graph
from pdos_agent_runtime.store import RuntimeStore
from pdos_agent_runtime.workflow import AgentWork
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker


def owned_store():
    # Explicit credentials for a dedicated runtime DB; no .env or business fallback.
    url, marker = (
        os.environ["PDOS_AGENT_TEST_DATABASE_URL"],
        os.environ["PDOS_AGENT_TEST_DB_MARKER"],
    )
    install(url, realm="pdos", marker=marker)
    return RuntimeStore(url, realm="pdos", marker=marker)


def test_private_reference_binding_and_immutable_input():
    store = owned_store()
    ref = store.put(str(uuid4()), "synthetic.receipt", {"source": "private synthetic source"})
    with pytest.raises(ValueError, match="realm"):
        store.read({**ref, "realm": "pdos-next"})
    with pytest.raises(ValueError, match="reference"):
        store.read({**ref, "tenant_id": str(uuid4())})
    with pytest.raises(ValueError, match="reference"):
        store.read({**ref, "input_digest": "forged"})
    with pytest.raises(Exception, match="immutable"), store.connection() as connection:
        connection.execute(
            "UPDATE agent_runtime_jobs SET payload='{}' WHERE id=%s", (ref["job_id"],)
        )


def test_real_workflow_checkpoints_and_history_are_private(tmp_path):
    async def scenario():
        store = owned_store()
        calls = []

        def execute(payload, emit):
            assert in_agent_graph()
            calls.append(payload)
            emit({"type": "progress", "text": "private synthetic progress"})
            return {"value": "private synthetic result"}

        activities = AgentActivities(
            store, {"synthetic.receipt": execute}, checkpoint_url=store.url
        )
        async with await WorkflowEnvironment.start_local(
            namespace="agent-convergence-test",
            dev_server_existing_path=os.environ["PDOS_TEMPORAL_TEST_BINARY"],
            dev_server_database_filename=str(tmp_path / "temporal.sqlite"),
        ) as env:
            with ThreadPoolExecutor(max_workers=2) as pool:
                async with Worker(
                    env.client,
                    task_queue="convergence-test",
                    workflows=[AgentWork],
                    activities=[activities.execute],
                    activity_executor=pool,
                ):
                    runtime = DurableRuntime(
                        store,
                        address=env.client.service_client.config.target_host,
                        namespace=env.client.namespace,
                        task_queue="convergence-test",
                    )
                    tenant = str(uuid4())
                    payload = {"source": "private synthetic source"}
                    events = []
                    result = await asyncio.wait_for(
                        asyncio.to_thread(
                            runtime.submit, tenant, "synthetic.receipt", payload, emit=events.append
                        ),
                        30,
                    )
                    assert result == {"value": "private synthetic result"}
                    assert (
                        await asyncio.to_thread(
                            runtime.submit, tenant, "synthetic.receipt", payload
                        )
                        == result
                    )
                    assert len(calls) == 1
                    assert events and events[0]["text"] == "private synthetic progress"
                    ref = store.put(tenant, "synthetic.receipt", payload)
                    handle = env.client.get_workflow_handle(f"pdos-agent:pdos:{ref['job_id']}")
                    assert (await handle.result())["state"] == "completed"
                    history = (await handle.fetch_history()).to_json()
                    assert "private synthetic" not in history
                    # Restarted Activity adapter reconciles the same finished work.
                    replacement = AgentActivities(
                        store, {"synthetic.receipt": execute}, checkpoint_url=store.url
                    )
                    assert store.read(ref)["state"] == "completed"
                    assert replacement is not activities

    asyncio.run(scenario())


def test_worker_process_death_after_checkpoint_recovers_without_second_effect(tmp_path):
    async def scenario():
        store = owned_store()
        with store.connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS convergence_effects(id uuid PRIMARY KEY)"
            )
        tenant = str(uuid4())
        payload = {"effect_id": str(uuid4()), "source": "private synthetic source"}
        ref = store.put(tenant, "synthetic.crash", payload)
        marker = tmp_path / "after-checkpoint"
        async with await WorkflowEnvironment.start_local(
            namespace="agent-convergence-crash",
            dev_server_existing_path=os.environ["PDOS_TEMPORAL_TEST_BINARY"],
            dev_server_database_filename=str(tmp_path / "temporal.sqlite"),
        ) as env:
            child_environment = {
                **os.environ,
                "CONVERGENCE_ADDRESS": env.client.service_client.config.target_host,
                "CONVERGENCE_NAMESPACE": env.client.namespace,
                "CONVERGENCE_MARKER": str(marker),
            }
            child = subprocess.Popen(
                [sys.executable, "-m", "tests.test_durable_runtime_postgres"],
                env=child_environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                runtime = DurableRuntime(
                    store,
                    address=env.client.service_client.config.target_host,
                    namespace=env.client.namespace,
                    task_queue="convergence-crash",
                )
                await runtime.start(ref)
                for _ in range(200):
                    if marker.exists():
                        break
                    if child.poll() is not None:
                        raise AssertionError("Worker failed before the checkpoint")
                    await asyncio.sleep(0.05)
                else:
                    raise AssertionError("Worker did not persist its result checkpoint")
                child.kill()
                await asyncio.to_thread(child.wait)
                assert store.read(ref)["state"] == "running"
                calls = []

                def forbidden_repeat(payload, emit):
                    calls.append(1)
                    raise AssertionError("Checkpoint recovery must not repeat the effect")

                replacement = AgentActivities(
                    store, {"synthetic.crash": forbidden_repeat}, checkpoint_url=store.url
                )
                # Keep the original workflow. Temporal's heartbeat timeout schedules
                # its Activity retry on a fresh worker using the original job/checkpoint.
                lost = env.client.get_workflow_handle(f"pdos-agent:pdos:{ref['job_id']}")
                with ThreadPoolExecutor(max_workers=2) as pool:
                    async with Worker(
                        env.client,
                        task_queue="convergence-crash",
                        workflows=[AgentWork],
                        activities=[replacement.execute],
                        activity_executor=pool,
                    ):
                        result = await asyncio.wait_for(lost.result(), 65)
                assert result["state"] == "completed"
                assert store.read(ref)["result"] == {"receipt": payload["effect_id"]}
                assert calls == []
                with store.connection() as connection:
                    assert (
                        connection.execute(
                            "SELECT count(*) FROM convergence_effects WHERE id=%s",
                            (payload["effect_id"],),
                        ).fetchone()["count"]
                        == 1
                    )
            finally:
                if child.poll() is None:
                    child.kill()
                    await asyncio.to_thread(child.wait)

    asyncio.run(scenario())


def test_uncheckpointed_crash_waits_for_receipts_and_never_reexecutes(tmp_path):
    async def scenario():
        store = owned_store()
        ref = store.put(str(uuid4()), "synthetic.uncertain", {"effect": "uncertain"})
        assert store.claim(ref)
        calls = []
        activities = AgentActivities(
            store, {"synthetic.uncertain": lambda *args: calls.append(1)}, checkpoint_url=store.url
        )
        async with await WorkflowEnvironment.start_local(
            namespace="agent-convergence-uncertain",
            dev_server_existing_path=os.environ["PDOS_TEMPORAL_TEST_BINARY"],
            dev_server_database_filename=str(tmp_path / "temporal.sqlite"),
        ) as env:
            with ThreadPoolExecutor(max_workers=2) as pool:
                async with Worker(
                    env.client,
                    task_queue="convergence-uncertain",
                    workflows=[AgentWork],
                    activities=[activities.execute],
                    activity_executor=pool,
                ):
                    handle = await env.client.start_workflow(
                        AgentWork.run,
                        ref,
                        id="uncertain:" + ref["job_id"],
                        task_queue="convergence-uncertain",
                    )
                    for _ in range(100):
                        if store.read(ref)["error_code"] == "AGENT_RECONCILIATION_REQUIRED":
                            break
                        await asyncio.sleep(0.05)
                    else:
                        raise AssertionError(
                            "An uncertain action must be visible for reconciliation"
                        )
                    await handle.signal(AgentWork.reconcile)
                    await asyncio.sleep(0.2)
                    assert calls == []
                    assert store.read(ref)["state"] == "running"
                    await handle.terminate("isolated uncertain-action check completed")

    asyncio.run(scenario())


def test_followup_wait_is_a_persisted_temporal_timer(tmp_path):
    @activity.defn(name="pdos_followup_graph")
    def scan(reference):
        from pdos_agent_runtime.graph import execute_graph

        def check(_):
            assert in_agent_graph()
            return {"active": True}

        return execute_graph(check, {}, thread_id="synthetic-followup")

    async def scenario():
        async with await WorkflowEnvironment.start_local(
            namespace="agent-convergence-followup",
            dev_server_existing_path=os.environ["PDOS_TEMPORAL_TEST_BINARY"],
            dev_server_database_filename=str(tmp_path / "temporal.sqlite"),
        ) as env:
            with ThreadPoolExecutor(max_workers=2) as pool:
                async with Worker(
                    env.client,
                    task_queue="convergence-followup",
                    workflows=[ProjectFollowup],
                    activities=[scan],
                    activity_executor=pool,
                ):
                    handle = await env.client.start_workflow(
                        ProjectFollowup.run,
                        {"tenant_id": str(uuid4()), "project_id": str(uuid4())},
                        id="followup:" + str(uuid4()),
                        task_queue="convergence-followup",
                    )
                    for _ in range(100):
                        history = await handle.fetch_history()
                        if any(
                            event.HasField("timer_started_event_attributes")
                            for event in history.events
                        ):
                            break
                        await asyncio.sleep(0.05)
                    else:
                        raise AssertionError("Follow-up timer must be stored in Temporal history")
                    await handle.terminate("isolated durable-timer check completed")

    asyncio.run(scenario())


async def crash_worker():
    from temporalio.client import Client

    store = owned_store()

    def execute(payload, emit):
        with store.connection() as connection:
            connection.execute(
                "INSERT INTO convergence_effects VALUES(%s)", (payload["effect_id"],)
            )
        return {"receipt": payload["effect_id"]}

    def stop_before_publication(ref, result):
        Path(os.environ["CONVERGENCE_MARKER"]).write_text(json.dumps({"checkpoint": True}))
        import time

        while True:
            time.sleep(0.05)

    store.finish = stop_before_publication
    activities = AgentActivities(store, {"synthetic.crash": execute}, checkpoint_url=store.url)
    client = await Client.connect(
        os.environ["CONVERGENCE_ADDRESS"], namespace=os.environ["CONVERGENCE_NAMESPACE"]
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        async with Worker(
            client,
            task_queue="convergence-crash",
            workflows=[AgentWork],
            activities=[activities.execute],
            activity_executor=pool,
        ):
            await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(crash_worker())
