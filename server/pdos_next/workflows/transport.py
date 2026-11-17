import asyncio

from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from pdos_next.core.dispatch.outbox import Envelope

from .definitions import (
    OriginalLifecycle,
    QueueOriginalSecurity,
    SecureOriginal,
    UploadTerminal,
)


class TemporalSender:
    def __init__(
        self,
        client,
        task_queue="pdos-next-domain-v1",
        *,
        dispatch_engine=None,
        business_engine=None,
        automation_sender=None,
        projection_sender=None,
        memory_fanout=False,
    ):
        self.client, self.task_queue = client, task_queue
        self.dispatch_engine = dispatch_engine
        self.business_engine = business_engine
        self.automation_sender = automation_sender
        self.projection_sender = projection_sender
        self.memory_fanout = memory_fanout

    async def __call__(self, event: Envelope):
        projection_id = None
        if self.projection_sender is not None:
            projection_id = await self.projection_sender.event(event)
        if self.automation_sender is not None:
            # Persist every eligible rule source before this single shared consumer
            # acknowledges delivery, even when the original event has no workflow.
            await self.automation_sender.event(event)
        if self.memory_fanout:
            # 记忆 M3 业务事件扇出 (§14.9): started before this consumer acknowledges.
            from pdos_next.agent.memory.fanout import start as start_memory_fanout

            await start_memory_fanout(self.client, self.task_queue, event)
        if event.event_type == "project.created" and self.business_engine is not None:
            from pdos_next.agent.kernel.temporal_port import TemporalPort, workflow_id
            from pdos_next.domain.projects.npi.continuation import queue

            run_ref = await asyncio.to_thread(queue, self.business_engine, event)
            if run_ref is not None:
                await TemporalPort(self.client, task_queue=self.task_queue).start(run_ref)
                return workflow_id(event.tenant_id, run_ref["subject_id"])
        if event.event_type == "category.created":
            if self.dispatch_engine is None:
                raise RuntimeError("Category continuation requires the metadata dispatcher")
            from pdos_next.agent.kernel.category_adoption import dispatch_reference
            from pdos_next.agent.kernel.temporal_port import TemporalPort, workflow_id

            adoption = dispatch_reference(self.dispatch_engine, event)
            if adoption is None:
                return None
            await TemporalPort(self.client, task_queue=self.task_queue).signal(
                adoption["tenant_id"],
                adoption["run_id"],
                adoption["input_ref"],
            )
            return workflow_id(adoption["tenant_id"], adoption["run_id"])
        reference = {
            "tenant_id": event.tenant_id,
            "category_id": event.category_id,
            "actor_id": event.actor_id,
            "requester_id": event.requester_id,
            "product_id": event.product_id,
            "subject_id": event.subject_id,
        }
        if event.event_type in {"original.lifecycle_requested", "original.upload_abandoned"}:
            lifecycle = event.event_type == "original.lifecycle_requested"
            prefix = "pdos-original-lifecycle" if lifecycle else "pdos-upload-terminal"
            identity = f"{prefix}:{event.tenant_id}:{event.subject_id}"
            try:
                await self.client.start_workflow(
                    OriginalLifecycle.run if lifecycle else UploadTerminal.run,
                    reference,
                    id=identity,
                    task_queue=self.task_queue,
                    id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                )
            except WorkflowAlreadyStartedError:
                pass
            return identity
        if event.event_type in {"original.uploaded", "original.scan_requested"}:
            uploaded = event.event_type == "original.uploaded"
            prefix = "pdos-security-queue" if uploaded else "pdos-security-scan"
            identity = f"{prefix}:{event.tenant_id}:{event.subject_id}"
            try:
                await self.client.start_workflow(
                    QueueOriginalSecurity.run if uploaded else SecureOriginal.run,
                    reference,
                    id=identity,
                    task_queue=self.task_queue,
                    id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                )
            except WorkflowAlreadyStartedError:
                pass
            return identity
        return projection_id
