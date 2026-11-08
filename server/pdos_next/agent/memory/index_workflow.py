"""Deterministic orchestration for the episode keyword index; no source imports."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn
class MemoryEpisodeIndex:
    @workflow.run
    async def run(self, reference: dict):
        return await workflow.execute_activity(
            "index_memory_episode",
            reference,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )
