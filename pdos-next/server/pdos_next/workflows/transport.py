from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from pdos_next.dispatch.outbox import Envelope

from .definitions import (
    OriginalLifecycle,
    QueueOriginalSecurity,
    SecureOriginal,
    SourceWork,
    UploadTerminal,
)


class TemporalSender:
    def __init__(self, client, task_queue="pdos-next-domain-v1"):
        self.client, self.task_queue = client, task_queue

    async def __call__(self, event: Envelope):
        reference = {
            "tenant_id": event.tenant_id,
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
        if event.event_type in {"ai.work_started", "ai.work_resume_requested", "ai.run_cancelled"}:
            identity = f"pdos-source:{event.tenant_id}:{event.subject_id}"
            try:
                await self.client.start_workflow(
                    SourceWork.run,
                    reference,
                    id=identity,
                    task_queue=self.task_queue,
                    id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                    start_signal="wake",
                    start_signal_args=[event.event_id],
                )
            except WorkflowAlreadyStartedError:
                # A completed domain goal is never restarted after a lost acknowledgement.
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
