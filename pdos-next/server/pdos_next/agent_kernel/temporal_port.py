"""Durable reference-only transport for the one 小Pai workflow."""

from uuid import UUID

from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from pdos_next.workflows.xiaopai import XiaopaiWork


def workflow_id(tenant_id, run_id):
    return f"pdos-next:xiaopai:{UUID(str(tenant_id))}:{UUID(str(run_id))}"


class TemporalPort:
    def __init__(self, client, *, task_queue="pdos-next-domain-v1"):
        self.client, self.task_queue = client, task_queue

    async def start(self, reference):
        expected = {"tenant_id", "category_id", "actor_id", "requester_id", "subject_id"}
        if set(reference) != expected:
            raise ValueError("Temporal accepts only the fixed persisted Run reference")
        for key, value in reference.items():
            if key != "category_id" or value:
                UUID(value)
        try:
            return await self.client.start_workflow(
                XiaopaiWork.run,
                reference,
                id=workflow_id(reference["tenant_id"], reference["subject_id"]),
                task_queue=self.task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
        except WorkflowAlreadyStartedError:
            return self.client.get_workflow_handle(
                workflow_id(reference["tenant_id"], reference["subject_id"])
            )

    async def signal(self, tenant_id, run_id, answer_ref):
        await self.client.get_workflow_handle(workflow_id(tenant_id, run_id)).signal(
            XiaopaiWork.resume, str(UUID(str(answer_ref)))
        )

    async def cancel(self, tenant_id, run_id):
        await self.client.get_workflow_handle(workflow_id(tenant_id, run_id)).cancel()


class RuntimeTemporal:
    """The API holds a reference transport, never an inference fallback."""

    def __init__(self):
        self.port = None

    def current(self):
        if self.port is None:
            from pdos_next.errors import DomainError

            raise DomainError("SOURCE_UNAVAILABLE", "持久执行服务暂不可用。")
        return self.port

    async def start(self, reference):
        return await self.current().start(reference)

    async def signal(self, tenant_id, run_id, answer_ref):
        return await self.current().signal(tenant_id, run_id, answer_ref)

    async def cancel(self, tenant_id, run_id):
        return await self.current().cancel(tenant_id, run_id)


async def dispatch_pending_runs(engine, tenant_id, port):
    """Recover a crash after Run commit; dispatch role can read only UUID references."""
    from sqlalchemy import text

    from pdos_next.database import tenant_session

    with tenant_session(engine, tenant_id) as session:
        rows = (
            session.execute(
                text("SELECT * FROM kernel_pending_run_references(:tenant,100)"),
                {"tenant": tenant_id},
            )
            .mappings()
            .all()
        )
    delivered = unavailable = 0
    for row in rows:
        reference = {
            "tenant_id": str(row["tenant_id"]),
            "category_id": str(row["category_id"]) if row["category_id"] else "",
            "actor_id": str(row["actor_id"]),
            "requester_id": str(row["requester_id"]),
            "subject_id": str(row["run_id"]),
        }
        try:
            await port.start(reference)
        except Exception:
            unavailable += 1
        else:
            delivered += 1
    return {"delivered": delivered, "unavailable": unavailable}
