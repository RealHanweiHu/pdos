"""One durable 小Pai workflow; questions and confirmations resume its same graph thread."""

from datetime import timedelta
from uuid import UUID

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError


@workflow.defn
class XiaopaiWork:
    def __init__(self):
        self.answer_refs = []
        self.seen_answer_refs = set()

    @workflow.signal
    def resume(self, answer_ref: str):
        # This is a committed answer reference, not model text or authorization in history.
        # Duplicate/out-of-order delivery is normal for the transactional Outbox.
        try:
            if not isinstance(answer_ref, str):
                return
            canonical = str(UUID(answer_ref))
        except ValueError:
            return
        if canonical not in self.seen_answer_refs:
            self.answer_refs.append(canonical)
            self.seen_answer_refs.add(canonical)

    @workflow.run
    async def run(self, reference: dict):
        required = {"tenant_id", "category_id", "actor_id", "requester_id", "subject_id"}
        if set(reference) != required or any(not isinstance(v, str) for v in reference.values()):
            raise ValueError("小Pai workflow requires its fixed server scope envelope")
        while True:
            payload = dict(reference)
            if self.answer_refs:
                payload["answer_ref"] = self.answer_refs.pop(0)
            try:
                result = await workflow.execute_activity(
                    "advance_xiaopai_run",
                    payload,
                    start_to_close_timeout=timedelta(minutes=10),
                    heartbeat_timeout=timedelta(seconds=45),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            except ActivityError:
                if not workflow.patched("xiaopai-reconciliation-v1"):
                    raise
                return await workflow.execute_activity(
                    "reconcile_xiaopai_run",
                    {**reference, "activity_exhausted": True},
                    start_to_close_timeout=timedelta(minutes=1),
                    # Technical cleanup must survive a database/service outage.
                    # It never repeats inference or an external/business action.
                    retry_policy=RetryPolicy(maximum_interval=timedelta(minutes=1)),
                )
            if result["status"] in {"completed", "partial", "cancelled", "failed"}:
                return result
            if result["status"] == "needs_reconciliation" and workflow.patched(
                "xiaopai-reconciliation-v1"
            ):
                await workflow.sleep(timedelta(minutes=5))
                return await workflow.execute_activity(
                    "reconcile_xiaopai_run",
                    reference,
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_interval=timedelta(minutes=1)),
                )
            await workflow.wait_condition(lambda: bool(self.answer_refs))
