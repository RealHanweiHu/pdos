"""Synchronous host adapter; disconnecting a viewer never cancels durable work."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from time import monotonic, sleep

from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from pdos_agent_runtime.workflow import AgentWork


class RuntimeUnavailable(ValueError):
    code = "AGENT_RUNTIME_UNAVAILABLE"


class DurableRuntime:
    def __init__(self, store, *, address: str, namespace: str, task_queue: str):
        self.store = store
        self.address, self.namespace, self.task_queue = address, namespace, task_queue

    async def start(self, ref):
        client = await Client.connect(self.address, namespace=self.namespace)
        with suppress(WorkflowAlreadyStartedError):
            await client.start_workflow(
                AgentWork.run,
                ref,
                id=f"pdos-agent:{ref['realm']}:{ref['job_id']}",
                task_queue=self.task_queue,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )

    def submit(
        self, tenant_id, handler, payload, *, emit=None, verify=None, timeout=1800
    ):
        ref = self.store.put(str(tenant_id), handler, payload)
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(
                    lambda: asyncio.run(asyncio.wait_for(self.start(ref), 15))
                ).result()
        except Exception:
            raise RuntimeUnavailable(
                "持久执行服务不可用，原工作已保留，未改为本地执行。"
            ) from None
        after, deadline = 0, monotonic() + timeout
        while monotonic() < deadline:
            if verify:
                verify()
            if emit:
                for event in self.store.events(ref, after):
                    after = event["sequence"]
                    emit(event["body"])
            row = self.store.read(ref)
            if row["state"] == "completed":
                return row["result"]
            if row["state"] == "failed":
                raise RuntimeUnavailable(row["error_code"] or "AGENT_EXECUTION_FAILED")
            if row["error_code"] == "AGENT_RECONCILIATION_REQUIRED":
                raise RuntimeUnavailable(
                    "AGENT_RECONCILIATION_REQUIRED：原动作需要按业务回执对账。"
                )
            sleep(0.2)
        raise RuntimeUnavailable("原工作仍由持久执行服务管理，请查询原请求。")
