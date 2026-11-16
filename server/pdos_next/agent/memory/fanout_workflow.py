"""Deterministic orchestration for the memory side of business events; no source imports.

业务事件扇出 (memory design §14.9): one workflow per event hands it to four handlers.
Each handler is its own Activity, idempotent on (event, handler) through the
maintenance ledger, so one failing retries alone and never blocks the other three.
The daily pass (author hand-overs, procedural summary) is one workflow per tenant
and day. Neither calls a model.
"""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

HANDLERS = ("staleness", "distillation", "scope_recent", "index")
DAILY_TASKS = ("departure", "procedural")


@workflow.defn
class MemoryEventFanout:
    @workflow.run
    async def run(self, reference: dict):
        results = await asyncio.gather(*(
            workflow.execute_activity(
                "memory_fanout_handle",
                {**reference, "handler": handler},
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=5),
            )
            for handler in HANDLERS
        ), return_exceptions=True)
        return [value if isinstance(value, dict) else {"handler": handler, "failed": True}
                for handler, value in zip(HANDLERS, results, strict=True)]


@workflow.defn
class MemoryDailyMaintenance:
    @workflow.run
    async def run(self, reference: dict):
        results = []
        for task in DAILY_TASKS:
            results.append(await workflow.execute_activity(
                "memory_daily_task",
                {**reference, "task": task},
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=5),
            ))
        return results
