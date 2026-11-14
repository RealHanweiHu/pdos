"""Episode keyword index on a real local Temporal server (M1 缺口 ⑤, D300 的索引部分; P121 B0).

The dispatch role finds episodes without an index row, starts the registered
``MemoryEpisodeIndex`` workflow, and the worker's own ``index_memory_episode``
activity writes the row as the episode owner. This uses the inspected local
Temporal binary, the real workflow and activity, and the isolated ``pdos_test``;
it is not the full production worker process and calls no provider.

When ``PDOS_MEMORY_B0_EVIDENCE`` names a file, the measured facts (history size,
the dev server's namespace retention) are appended to it as JSON lines.
"""

import asyncio
import base64
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from pdos_next.agent.kernel.persistence import KernelStore
from pdos_next.agent.memory.index import dispatch_pending, workflow_id
from pdos_next.agent.memory.index_workflow import MemoryEpisodeIndex
from pdos_next.agent.memory.models import MemoryIndexEntry
from pdos_next.agent.memory.tool import memory_search
from pdos_next.workflows.worker import Activities
from tests.agent.memory.support import episode, finish, scope, start

BINARY = Path(__file__).resolve().parents[4] / ".local/tools/temporal"
QUEUE = "pdos-memory-index-b0"
GOAL = "比较三家气泵供应商的报价和交期"

pytestmark = pytest.mark.skipif(
    not BINARY.is_file(), reason="Inspected local Temporal binary required",
)


def record(value):
    target = os.environ.get("PDOS_MEMORY_B0_EVIDENCE")
    if target:
        with Path(target).open("a") as handle:
            handle.write(json.dumps(value, ensure_ascii=False) + "\n")


def payloads(history):
    return b"\n".join(
        base64.b64decode(value) for value in re.findall(r'"data":\s*"([^"]*)"', history.to_json())
    ).decode()


def search(setup, run_id):
    return memory_search(KernelStore(setup.engine))(
        scope(setup, run_id), {"query": "气泵供应商报价"})


def test_pending_episode_is_indexed_through_temporal_and_only_references_enter_history(setup):
    first, _ = start(setup, goal=GOAL)
    finish(setup, first)
    row = episode(setup, first)
    reference = {"tenant_id": str(setup.tenant), "owner_id": str(row.owner_id),
                 "episode_id": str(row.id)}
    current, _ = start(setup, goal="上次那三家供应商后来定了哪家？")
    before = search(setup, current)
    assert [item["run_id"] for item in before["items"]] == [str(first)]
    assert before["retrieval"]["index_pending"] == 1  # Found by the lag scan, said so.

    async def actual():
        environment = await WorkflowEnvironment.start_local(dev_server_existing_path=str(BINARY))
        try:
            client = environment.client
            activities = Activities(setup.engine, KernelStore(setup.engine), None)
            with ThreadPoolExecutor(max_workers=2) as executor:
                async with Worker(client, task_queue=QUEUE, workflows=[MemoryEpisodeIndex],
                                  activities=[activities.memory_episode_index],
                                  activity_executor=executor):
                    sent = await dispatch_pending(setup.dispatch, setup.tenant, client,
                                                  task_queue=QUEUE)
                    handle = client.get_workflow_handle(workflow_id(reference))
                    result = await asyncio.wait_for(handle.result(), 60)
                    again = await dispatch_pending(setup.dispatch, setup.tenant, client,
                                                   task_queue=QUEUE)
                    history = await handle.fetch_history()
            namespace = await client.workflow_service.describe_namespace(
                DescribeNamespaceRequest(namespace=client.namespace))
            retention = namespace.config.workflow_execution_retention_ttl.ToTimedelta()
            return sent, result, again, history, retention
        finally:
            await environment.shutdown()

    sent, result, again, history, retention = asyncio.run(actual())
    assert sent == {"pending": 1, "delivered": 1, "unavailable": 0}
    assert result == {"episode_id": str(row.id), "indexed": True, "rows": ["episode", "answer"]}
    assert again == {"pending": 0, "delivered": 0, "unavailable": 0}
    with Session(setup.admin) as session:
        assert session.scalar(select(func.count()).select_from(MemoryIndexEntry).where(
            MemoryIndexEntry.episode_id == row.id)) == 2  # Own words, and the answer side.
    after = search(setup, current)
    assert [item["run_id"] for item in after["items"]] == [str(first)]
    assert after["retrieval"]["index_pending"] == 0
    recorded = payloads(history)
    # Only the fixed UUID reference and the small result travel through Temporal.
    assert str(row.id) in recorded and "气泵" not in recorded and GOAL not in recorded
    record({"case": "memory_index_temporal", "history_events": len(history.events),
            "history_json_bytes": len(history.to_json().encode()),
            "owner_words_in_history": False,
            "dev_server_namespace_retention_hours": retention.total_seconds() / 3600})
