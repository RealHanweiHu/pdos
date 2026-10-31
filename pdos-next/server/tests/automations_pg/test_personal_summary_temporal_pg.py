"""Real local Temporal delivery loss/restart of the no-model summary Run.

Only root executes the opt-in guarded PG/Temporal case. Provider and outbound
adapters are absent, and each Temporal payload carries only the actual Run ref.
"""
# ruff: noqa: F401, F811 -- real fixture dependency tree

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.exceptions import ApplicationError
from temporalio.worker import Worker

from pdos_next.agent_kernel.temporal_port import TemporalPort
from pdos_next.workflows.xiaopai import XiaopaiWork
from tests.automations_pg.test_personal_summary_pg import (
    admit,
    checked,
    kernel,
    original_security_work,
    saved,
    summary_work,
    work_case,
)


@pytest.mark.skipif(
    not os.environ.get("PDOS_TEMPORAL_ADDRESS") or not os.environ.get("PDOS_TEMPORAL_NAMESPACE"),
    reason="Explicit verified local Temporal address and namespace required",
)
def test_actual_no_model_summary_acknowledgement_loss_and_worker_restart(summary_work, monkeypatch):
    address = os.environ["PDOS_TEMPORAL_ADDRESS"]
    endpoint = urlsplit("//" + address)
    assert endpoint.hostname in {"127.0.0.1", "localhost", "::1"} and endpoint.port
    _rule, envelope = admit(summary_work)
    worker_activity = kernel(summary_work, monkeypatch)
    attempts = []

    @activity.defn(name="advance_xiaopai_run")
    def advance(reference):
        assert reference == envelope
        result = worker_activity.advance(reference)
        attempts.append((activity.info().attempt, result))
        assert result["status"] == "completed"
        if len(attempts) == 1:
            # Terminal result and LangGraph checkpoint already committed; only
            # the Activity acknowledgement is lost. There is no provider retry.
            raise ApplicationError("Synthetic committed summary acknowledgement loss",
                                   type="SOURCE_UNAVAILABLE")
        return result

    async def actual():
        client = await Client.connect(address, namespace=os.environ["PDOS_TEMPORAL_NAMESPACE"])
        assert await client.service_client.check_health()
        queue = "personal-summary-restart-" + str(uuid4())
        port = TemporalPort(client, task_queue=queue)
        executor = ThreadPoolExecutor(max_workers=2)
        handle = None

        def worker():
            return Worker(
                client, task_queue=queue, workflows=[XiaopaiWork], activities=[advance],
                activity_executor=executor, graceful_shutdown_timeout=timedelta(0),
                sticky_queue_schedule_to_start_timeout=timedelta(seconds=1),
            )

        try:
            async with worker(), asyncio.timeout(90):
                handle = await port.start(envelope)
                while True:
                    state = await handle.describe()
                    if any(p.last_failure.application_failure_info.type == "SOURCE_UNAVAILABLE"
                           for p in state.raw_description.pending_activities):
                        break
                    await asyncio.sleep(0.02)
            committed = await asyncio.to_thread(saved, summary_work, envelope)
            assert len(attempts) == 1 and committed[0] is not None
            async with worker(), asyncio.timeout(90):
                output = await handle.result()
            assert output == attempts[0][1] == attempts[-1][1]
            assert attempts[-1][0] >= 2
            assert await asyncio.to_thread(saved, summary_work, envelope) == committed
            assert await asyncio.to_thread(checked, summary_work, envelope) == committed[0]
            assert await (await port.start(envelope)).result() == output
            history = await handle.fetch_history()
            assert "私有项目材料已核对" not in str(history.events)
            assert "fact_summary" not in str(history.events)
        finally:
            if handle and (await handle.describe()).status == WorkflowExecutionStatus.RUNNING:
                await handle.terminate("End dedicated synthetic personal summary workflow")
            executor.shutdown(wait=True)

    asyncio.run(actual())
