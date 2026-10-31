"""Deterministic projection orchestration; no source or provider imports."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn
class EnterpriseProjection:
    @workflow.run
    async def run(self, reference: dict):
        return await workflow.execute_activity(
            "project_enterprise_source",
            reference,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )
