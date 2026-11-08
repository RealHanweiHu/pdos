"""Per-tenant system upkeep on durable timers.

Each job is one long-lived workflow per tenant with a fixed id, started by the
worker's discovery loop (the same pattern as automation supervision). It runs the
job's Activity, then waits on a durable timer. A pass that still fails after
Temporal's retries is logged and left to the next period, so one bad pass never
stops the schedule. History is bounded with continue-as-new. No job calls a model.
"""

from datetime import timedelta
from uuid import UUID

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

# job -> (Activity name, period). D58: checkpoints are purged daily (P78 item 3).
JOBS = {
    "checkpoint_retention": ("purge_checkpoint_retention", timedelta(days=1)),
}
PASSES_PER_HISTORY = 24
ACTIVITY_TIMEOUT = timedelta(minutes=10)
RETRY = RetryPolicy(maximum_attempts=3, maximum_interval=timedelta(minutes=5))


def _reference(value):
    try:
        if not isinstance(value, dict) or set(value) != {"tenant_id", "job"}:
            raise ValueError
        if value["job"] not in JOBS or not isinstance(value["tenant_id"], str):
            raise ValueError
        return {"job": value["job"], "tenant_id": str(UUID(value["tenant_id"]))}
    except (ValueError, TypeError, AttributeError):
        raise ApplicationError(
            "Maintenance requires a tenant UUID and a known job",
            type="MAINTENANCE_REFERENCE_INVALID",
            non_retryable=True,
        ) from None


def workflow_id(job, tenant_id):
    return f"pdos-next:maintenance:{job}:{UUID(str(tenant_id))}"


@workflow.defn
class TenantMaintenance:
    @workflow.run
    async def run(self, reference: dict) -> dict:
        fixed = _reference(reference)
        activity_name, period = JOBS[fixed["job"]]
        for _ in range(PASSES_PER_HISTORY):
            try:
                await workflow.execute_activity(
                    activity_name,
                    {"tenant_id": fixed["tenant_id"]},
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    heartbeat_timeout=timedelta(minutes=2),
                    retry_policy=RETRY,
                )
            except ActivityError as error:
                workflow.logger.warning(
                    "Maintenance pass %s unavailable: %s",
                    fixed["job"],
                    type(error.cause).__name__ if error.cause else "ActivityError",
                )
            await workflow.sleep(period)
        workflow.continue_as_new(fixed)


class MaintenanceSender:
    """Start each tenant's maintenance workflows once; later calls are local no-ops."""

    def __init__(self, client, task_queue="pdos-next-domain-v1", jobs=None):
        self.client, self.task_queue = client, task_queue
        self.jobs = tuple(JOBS if jobs is None else jobs)
        self._started = set()

    async def discover(self, tenant):
        from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
        from temporalio.exceptions import WorkflowAlreadyStartedError

        tenant = UUID(str(tenant))
        for job in self.jobs:
            identity = workflow_id(job, tenant)
            if identity in self._started:
                continue
            try:
                await self.client.start_workflow(
                    TenantMaintenance.run,
                    {"tenant_id": str(tenant), "job": job},
                    id=identity,
                    task_queue=self.task_queue,
                    id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                )
            except WorkflowAlreadyStartedError:
                pass
            self._started.add(identity)
        return {"ensured": len(self.jobs)}
