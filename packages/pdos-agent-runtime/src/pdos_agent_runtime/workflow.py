"""Temporal owns scheduling and durable waiting; its history contains references only."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn
class AgentWork:
    def __init__(self):
        self.reconcile_requested = False

    @workflow.signal
    def reconcile(self):
        # A signal requests a receipt check, never permission to repeat side effects.
        self.reconcile_requested = True

    @workflow.run
    async def run(self, reference: dict) -> dict:
        allowed = {"realm", "tenant_id", "job_id", "handler", "input_digest"}
        if set(reference) != allowed or any(
            not isinstance(v, str) for v in reference.values()
        ):
            raise ValueError(
                "Agent workflow accepts only a fixed private-work reference"
            )
        while True:
            self.reconcile_requested = False
            result = await workflow.execute_activity(
                "pdos_execute_agent_graph",
                reference,
                start_to_close_timeout=timedelta(minutes=30),
                heartbeat_timeout=timedelta(seconds=45),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            if result.get("state") != "needs_reconciliation":
                return result
            await workflow.wait_condition(lambda: self.reconcile_requested)
