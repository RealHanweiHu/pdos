"""One durable 小Pai workflow; questions and confirmations resume its same graph thread."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn
class XiaopaiWork:
    def __init__(self):
        self.answer_ref = None

    @workflow.signal
    def resume(self, answer_ref: str):
        # This is a committed answer reference, not model text or authorization in history.
        self.answer_ref = answer_ref

    @workflow.run
    async def run(self, reference: dict):
        required = {"tenant_id", "category_id", "actor_id", "requester_id", "subject_id"}
        if set(reference) != required or any(not isinstance(v, str) for v in reference.values()):
            raise ValueError("小Pai workflow requires its fixed server scope envelope")
        while True:
            payload = dict(reference)
            if self.answer_ref:
                payload["answer_ref"] = self.answer_ref
                self.answer_ref = None
            result = await workflow.execute_activity(
                "advance_xiaopai_run",
                payload,
                start_to_close_timeout=timedelta(minutes=10),
                heartbeat_timeout=timedelta(seconds=45),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            if result["status"] in {"completed", "partial", "cancelled", "failed"}:
                return result
            await workflow.wait_condition(lambda: self.answer_ref is not None)
