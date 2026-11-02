"""Embedding is xiaopai's registered derived-index work, not a second Agent."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


async def index_embeddings(reference):
    results = []
    for _window in range(20):
        plan = await workflow.execute_activity(
            "plan_enterprise_embeddings",
            reference,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        references = plan.get("batch_refs") or [
            {"context": plan["context"], "batch_id": identity} for identity in plan["batches"]
        ]
        for batch in references:
            results.append(
                await workflow.execute_activity(
                    "embed_enterprise_batch",
                    batch,
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(
                        maximum_attempts=3, initial_interval=timedelta(seconds=1)
                    ),
                )
            )
        if (
            not plan["truncated"]
            or not references
            or any(row["status"] != "ready" for row in results)
        ):
            break
    partial = (
        plan["uncovered_chunks"]
        or plan["truncated"]
        or any(result["status"] != "ready" for result in results)
    )
    return {
        "status": "partial" if partial else "ready",
        "processed_batches": len(results),
        "uncovered_chunks": plan["uncovered_chunks"],
        "truncated": plan["truncated"],
    }


@workflow.defn
class EnterpriseEmbedding:
    @workflow.run
    async def run(self, reference):
        return await index_embeddings(reference)


@workflow.defn
class EnterpriseEmbeddingProjection:
    @workflow.run
    async def run(self, reference):
        # Existing projection finishes first. New source events cannot race the
        # text/hash/scan projection and then be silently acknowledged as covered.
        keyword = await workflow.execute_activity(
            "project_enterprise_source",
            reference,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )
        semantic = await index_embeddings(reference)
        return {**keyword, "semantic_index": semantic}


@workflow.defn
class EnterpriseEmbeddingRebuild:
    @workflow.run
    async def run(self, reference):
        from .recovery_workflow import EnterpriseRebuild

        keyword = await workflow.execute_child_workflow(
            EnterpriseRebuild.run, reference["context"], id=workflow.info().workflow_id + ":keyword"
        )
        semantic = await index_embeddings(reference)
        return {**keyword, "semantic_index": semantic}
