"""All nine real source families resume a fixed rebuild after commit acknowledgement loss."""
# ruff: noqa: F401, F811 -- imported fixtures retain the real domain dependency tree

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.worker import Worker

from pdos_next.enterprise_search import recovery
from pdos_next.enterprise_search.events import ProjectionSender
from pdos_next.enterprise_search.recovery_workflow import EnterpriseRebuild
from pdos_next.enterprise_search.schemas import SOURCE_TYPES
from pdos_next.errors import DomainError
from pdos_next.service import digest
from pdos_next.workflows.worker import Activities
from tests.enterprise_search.test_recovery_pg import (
    accepted_work,
    all_sources,
    assert_statistics,
    authority,
    change_work,
    known_configuration,
    launch_work,
    operational_work,
    quality_work,
    ready_work,
    results_work,
)


@pytest.mark.skipif(
    not os.environ.get("PDOS_TEMPORAL_ADDRESS") or not os.environ.get("PDOS_TEMPORAL_NAMESPACE"),
    reason="Explicit verified local Temporal address and namespace required",
)
def test_nine_family_fixed_batches_survive_worker_restart_without_replanning(
    all_sources,
    monkeypatch,
    record_property,
):
    address, namespace = os.environ["PDOS_TEMPORAL_ADDRESS"], os.environ["PDOS_TEMPORAL_NAMESPACE"]
    endpoint = urlsplit("//" + address)
    assert endpoint.hostname in {"127.0.0.1", "localhost", "::1"} and endpoint.port
    person = all_sources.person
    before = digest(authority(person))
    planned, attempted = [], []
    original_plan, original_batch = recovery.plan_rebuild, recovery.rebuild_batch

    def plan(*args):
        value = original_plan(*args)
        planned.append(value["manifest_digest"])
        return value

    def committed_then_lost(*args):
        value = original_batch(*args)
        attempted.append((value["manifest_digest"], args[2]))
        if len(attempted) == 1:
            # The first batch committed. Losing this acknowledgement is safe:
            # the next worker must replay the same immutable target slice.
            raise DomainError("SOURCE_UNAVAILABLE", "Synthetic committed acknowledgement loss")
        return value

    monkeypatch.setattr(recovery, "plan_rebuild", plan)
    monkeypatch.setattr(recovery, "rebuild_batch", committed_then_lost)

    async def actual():
        client = await Client.connect(address, namespace=namespace)
        queue = "enterprise-recovery-" + str(uuid4())
        sender = ProjectionSender(client, task_queue=queue)
        ctx, request_id = replace(person.ctx, category_id=None), uuid4()
        identity = await sender.rebuild(ctx, request_id)
        handle = client.get_workflow_handle(identity)
        activities = Activities(person.engine, None, None)
        executor = ThreadPoolExecutor(max_workers=2)

        def worker():
            return Worker(
                client,
                task_queue=queue,
                workflows=[EnterpriseRebuild],
                activities=[
                    activities.enterprise_rebuild_plan,
                    activities.enterprise_rebuild_batch,
                ],
                activity_executor=executor,
                graceful_shutdown_timeout=timedelta(0),
            )

        try:
            async with worker(), asyncio.timeout(45):
                while True:
                    description = await handle.describe()
                    if any(
                        pending.last_failure.application_failure_info.type == "SOURCE_UNAVAILABLE"
                        for pending in description.raw_description.pending_activities
                    ):
                        break
                    await asyncio.sleep(0.05)
            async with worker(), asyncio.timeout(120):
                result = await handle.result()
            assert result["status"] == "current" and result["ready"] == result["total"]
            assert len(planned) == 1 and result["manifest_digest"] == planned[0]
            assert len(attempted) >= 2 and attempted[0] == attempted[1] == (planned[0], 0)
            assert set(SOURCE_TYPES) == {row["source_type"] for row in authority(person)}
            assert digest(authority(person)) == before
            assert_statistics(person)
            assert await sender.rebuild(ctx, request_id) == identity
            assert await client.get_workflow_handle(identity).result() == result
            history = await handle.fetch_history()
            assert "Synthetic recovery source evidence." not in str(history.events)
            record_property("rebuild_manifest_count", len(planned))
            record_property("rebuild_source_count", result["total"])
            record_property("rebuild_manifest_digest", result["manifest_digest"])
        finally:
            if (await handle.describe()).status == WorkflowExecutionStatus.RUNNING:
                await handle.terminate("End dedicated synthetic recovery workflow")
            executor.shutdown(wait=True)

    asyncio.run(actual())
