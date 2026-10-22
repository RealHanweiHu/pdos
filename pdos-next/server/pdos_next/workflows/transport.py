from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from pdos_next.dispatch.outbox import Envelope

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
        automation_sender=None,
    ):
        self.client, self.task_queue = client, task_queue
        self.dispatch_engine = dispatch_engine
        self.automation_sender = automation_sender

    async def __call__(self, event: Envelope):
        if self.automation_sender is not None:
            # Persist every eligible rule source before this single shared consumer
            # acknowledges delivery, even when the original event has no workflow.
            await self.automation_sender.event(event)
        if event.event_type == "category.created":
            if self.dispatch_engine is None:
                raise RuntimeError("Category continuation requires the metadata dispatcher")
            from pdos_next.agent_kernel.category_adoption import dispatch_reference
            from pdos_next.agent_kernel.temporal_port import TemporalPort, workflow_id

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
        return None
