"""Durable fixed-manifest rebuild: source bodies never enter workflow history."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


def finish_rebuild(plan, batches):
    """Watermarks describe actual acknowledged slices, not an inferred tenant total."""
    actual = [row for batch in batches for row in batch["rows"]]
    failed = sum(row["code"] is not None for row in actual)
    processed = len(actual)
    return {
        "processed": processed,
        "changed": sum(batch["changed"] for batch in batches),
        "failed": failed,
        "total": len(plan["targets"]),
        "status": "current" if processed == len(plan["targets"]) and not failed else "partial",
        "source_as_of": plan["source_as_of"],
        "indexed_as_of": min((batch["indexed_as_of"] for batch in batches), default=None),
        "manifest_digest": plan["manifest_digest"],
        "ready": processed - failed,
        "unavailable": [row for row in actual if row["code"] is not None],
        "scope": "调用者当时可读的固定来源集合；不代表全租户不可读来源已重建。",
    }


@workflow.defn
class EnterpriseRebuild:
    @workflow.run
    async def run(self, reference: dict):
        policy = RetryPolicy(maximum_attempts=5)
        plan = await workflow.execute_activity(
            "plan_enterprise_rebuild",
            reference,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=policy,
        )
        cursor, batches = 0, []
        while True:
            for attempt in range(3):
                result = await workflow.execute_activity(
                    "rebuild_enterprise_batch",
                    {"plan": plan, "cursor": cursor},
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=policy,
                )
                if not result["failed"] or attempt == 2:
                    break
                await workflow.sleep(timedelta(seconds=1))
            batches.append(result)
            if result["next_cursor"] is None:
                return finish_rebuild(plan, batches)
            cursor = result["next_cursor"]
