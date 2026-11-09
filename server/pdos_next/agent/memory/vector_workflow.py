"""Deterministic orchestration for optional episode vectors; no source imports."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn
class MemoryEpisodeVectors:
    @workflow.run
    async def run(self, reference: dict):
        return await workflow.execute_activity(
            "embed_memory_episodes",
            reference,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=1)),
        )
