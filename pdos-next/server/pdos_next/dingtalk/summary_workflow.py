"""Summary delivery uses the existing Temporal worker and one registered Xiaopai graph."""

from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    from .summary_delivery import SummaryReference


@workflow.defn
class DingTalkSummaryDelivery:
    @workflow.run
    async def run(self, reference: dict):
        SummaryReference.model_validate(reference)
        return await workflow.execute_activity(
            "deliver_dingtalk_summary",
            reference,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_interval=timedelta(minutes=1)),
        )


class SummaryActivities:
    def __init__(self, engine, metadata_engine, *, runtime=None):
        self.engine, self.metadata_engine, self.runtime = engine, metadata_engine, runtime

    @activity.defn(name="deliver_dingtalk_summary")
    def deliver(self, reference):
        from langgraph.graph import END, START, StateGraph
        from pdos_agent_runtime.graph import registered_graph_context

        from pdos_next.errors import DomainError

        from .summary_delivery import SummaryDeliveryService

        ref = SummaryReference.model_validate(reference)
        service = SummaryDeliveryService(self.engine, self.metadata_engine, runtime=self.runtime)
        graph = StateGraph(dict)
        graph.add_node("deliver_fixed_summary", lambda _state: service.deliver(ref.model_dump()))
        graph.add_edge(START, "deliver_fixed_summary")
        graph.add_edge("deliver_fixed_summary", END)
        try:
            with registered_graph_context("xiaopai"):
                return graph.compile(name="xiaopai").invoke({})
        except DomainError as error:
            return {"state": "blocked", "error_code": error.reason}


class SummarySender:
    def __init__(self, client, metadata_engine, *, task_queue="pdos-next-domain-v1"):
        self.client, self.metadata_engine, self.task_queue = client, metadata_engine, task_queue

    async def discover(self, tenant_id):
        from sqlalchemy import text

        from pdos_next.database import tenant_session

        with tenant_session(self.metadata_engine, tenant_id) as session:
            rows = (
                session.execute(
                    text("SELECT * FROM dingtalk_pending_summaries(:tenant,100)"),
                    {"tenant": tenant_id},
                )
                .mappings()
                .all()
            )
        for row in rows:
            reference = {"tenant_id": str(tenant_id), "run_id": str(row["run_id"])}
            try:
                await self.client.start_workflow(
                    DingTalkSummaryDelivery.run,
                    reference,
                    id=f"pdos-next:dingtalk-summary:{tenant_id}:{row['run_id']}",
                    task_queue=self.task_queue,
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                )
            except WorkflowAlreadyStartedError:
                pass
        return {"summary_discovered": len(rows)}
