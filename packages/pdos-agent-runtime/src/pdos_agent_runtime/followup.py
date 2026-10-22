"""Durable timer for a server-owned project delegation; references only in history."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn
class ProjectFollowup:
    @workflow.run
    async def run(self, reference: dict) -> dict:
        if set(reference) != {"tenant_id", "project_id"}:
            raise ValueError("Follow-up accepts fixed domain references only")
        for _ in range(1000):
            result = await workflow.execute_activity(
                "pdos_followup_graph",
                reference,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            if not result["active"]:
                return {"status": "completed"}
            await workflow.sleep(timedelta(minutes=1))
        workflow.continue_as_new(reference)
