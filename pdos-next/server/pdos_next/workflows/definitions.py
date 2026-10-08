from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn
class SourceWork:
    def __init__(self):
        self.pending: list[str] = []
        self.seen: set[str] = set()

    @workflow.signal
    def wake(self, event_id: str):
        if event_id not in self.seen:
            self.seen.add(event_id)
            self.pending.append(event_id)

    @workflow.run
    async def run(self, reference: dict) -> dict:
        first = True
        while True:
            if not first:
                await workflow.wait_condition(lambda: bool(self.pending))
            first = False
            self.pending.clear()
            result = await workflow.execute_activity(
                "advance_source_work",
                reference,
                start_to_close_timeout=timedelta(seconds=90),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            if result["status"] in {"completed", "cancelled"}:
                return result
            # No timer-driven model retries: an explicit domain event wakes a waiting goal.
            if len(self.seen) > 200:
                workflow.continue_as_new(reference)


@workflow.defn
class ParseOriginal:
    @workflow.run
    async def run(self, reference: dict) -> dict:
        return await workflow.execute_activity(
            "parse_uploaded_original",
            reference,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


@workflow.defn
class QueueOriginalSecurity:
    @workflow.run
    async def run(self, reference: dict) -> dict:
        return await workflow.execute_activity(
            "queue_original_security",
            reference,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


@workflow.defn
class SecureOriginal:
    @workflow.run
    async def run(self, reference: dict) -> dict:
        result = await workflow.execute_activity(
            "scan_original_request",
            reference,
            start_to_close_timeout=timedelta(seconds=90),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if result["status"] != "clean":
            return result
        return await workflow.execute_activity(
            "parse_uploaded_original",
            {**reference, "subject_id": result["original_id"]},
            start_to_close_timeout=timedelta(seconds=90),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


@workflow.defn
class OriginalLifecycle:
    @workflow.run
    async def run(self, reference: dict) -> dict:
        return await workflow.execute_activity(
            "advance_original_lifecycle",
            reference,
            start_to_close_timeout=timedelta(seconds=45),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


@workflow.defn
class UploadTerminal:
    @workflow.run
    async def run(self, reference: dict) -> dict:
        return await workflow.execute_activity(
            "reconcile_upload_terminal",
            reference,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
