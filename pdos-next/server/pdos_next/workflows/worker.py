"""Local durable activities; domain truth is reread on every activity attempt."""

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

from temporalio import activity
from temporalio.client import Client
from temporalio.exceptions import ApplicationError
from temporalio.worker import Worker

from pdos_next.database import configured_engines, tenant_session
from pdos_next.dispatch.outbox import dispatch_once
from pdos_next.errors import DomainError
from pdos_next.original_security import configure, queue_uploaded, scan_requested
from pdos_next.original_store import OriginalStore
from pdos_next.originals import parse_uploaded
from pdos_next.workflows.definitions import (
    OriginalLifecycle,
    ParseOriginal,
    QueueOriginalSecurity,
    SecureOriginal,
    UploadTerminal,
)
from pdos_next.workflows.transport import TemporalSender


class Activities:
    def __init__(self, engine, store, checkpoint_url):
        self.engine, self.store, self.checkpoint_url = engine, store, checkpoint_url

    @activity.defn(name="project_enterprise_source")
    def enterprise_projection(self, reference: dict):
        from pdos_next.enterprise_search.events import process_event

        try:
            return process_event(self.engine, reference)
        except DomainError as error:
            raise ApplicationError(
                "Enterprise projection unavailable",
                type=error.code,
                non_retryable=error.code == "FORBIDDEN_SCOPE",
            ) from None

    @activity.defn(name="plan_enterprise_rebuild")
    def enterprise_rebuild_plan(self, reference: dict):
        from pdos_next.enterprise_search.recovery import _context, plan_rebuild

        try:
            return plan_rebuild(self.engine, _context(reference))
        except DomainError as error:
            raise ApplicationError(
                "Enterprise rebuild planning unavailable",
                type=error.code,
                non_retryable=error.code == "FORBIDDEN_SCOPE",
            ) from None

    @activity.defn(name="rebuild_enterprise_batch")
    def enterprise_rebuild_batch(self, reference: dict):
        from pdos_next.enterprise_search.recovery import rebuild_batch

        try:
            return rebuild_batch(self.engine, reference["plan"], reference["cursor"])
        except DomainError as error:
            raise ApplicationError(
                "Enterprise rebuild batch unavailable",
                type=error.code,
                non_retryable=error.code == "FORBIDDEN_SCOPE",
            ) from None

    @activity.defn(name="automation_rule_tick")
    def automation_rule_tick(self, reference: dict):
        from pdos_next.domain.automations.service_runtime import tick

        return tick(self.engine, reference)

    @activity.defn(name="parse_uploaded_original")
    def parse(self, reference: dict):
        try:
            return parse_uploaded(self.engine, reference, self.store)
        except DomainError as exc:
            raise ApplicationError(exc.message, type=exc.code, non_retryable=True) from None

    @activity.defn(name="queue_original_security")
    def queue(self, reference: dict):
        try:
            return queue_uploaded(self.engine, reference)
        except DomainError as exc:
            raise ApplicationError(exc.message, type=exc.code, non_retryable=True) from None

    @activity.defn(name="scan_original_request")
    def scan(self, reference: dict):
        try:
            return scan_requested(self.engine, reference)
        except DomainError as exc:
            raise ApplicationError(exc.message, type=exc.code, non_retryable=True) from None

    @activity.defn(name="advance_original_lifecycle")
    def lifecycle(self, reference: dict):
        from pdos_next.lifecycle_worker import process
        from pdos_next.original_lifecycle.types import LifecycleFailure

        try:
            return process(self.engine, reference)
        except (DomainError, LifecycleFailure) as exc:
            raise ApplicationError(
                "Lifecycle requires current reconciliation", type=exc.code, non_retryable=True
            ) from None

    @activity.defn(name="reconcile_upload_terminal")
    def terminal_upload(self, reference: dict):
        from pdos_next.dispatch.context import event_context
        from pdos_next.models import UploadAttempt
        from pdos_next.object_storage import StorageFailure
        from pdos_next.upload_lifecycle import reconcile_terminal

        tenant, pid, oid = (UUID(reference[k]) for k in ("tenant_id", "product_id", "subject_id"))
        ctx = event_context(reference)
        try:
            with tenant_session(
                self.engine,
                tenant,
                actor_id=ctx.actor_id,
                requester_id=ctx.requester_id,
                category_id=ctx.category_id,
            ) as s:
                row = s.get(UploadAttempt, oid)
                if not row or row.product_id != pid:
                    raise DomainError("SOURCE_UNAVAILABLE", "上传登记不可用。", 403)
                if row.owner_id != ctx.requester_id:
                    raise DomainError("FORBIDDEN_SCOPE", "上传信封与具名登记不符。", 403)
                reconcile_terminal(s, ctx, pid, oid, self.store)
                return {"status": row.status}
        except (DomainError, StorageFailure) as exc:
            raise ApplicationError(
                "Upload journal requires reconciliation", type=exc.code, non_retryable=True
            ) from None


async def main(
    *, agent_runtime_ports=None, agent_kernel_adapters=None, embedding_ports=None,
    dingtalk_runtime=None,
):
    engine, auth = configured_engines()
    from pdos_next.database import engine_for

    dispatch_engine = engine_for(os.environ["DISPATCH_DATABASE_URL"])
    from pdos_next.agent_kernel.activities import KernelActivities, configure_agent_kernel
    from pdos_next.domain.automations.transport import ServiceAutomationSender
    from pdos_next.workflows.automation import AutomationRuleWork
    from pdos_next.workflows.xiaopai import XiaopaiWork

    if agent_kernel_adapters is not None:
        configure_agent_kernel(engine, agent_kernel_adapters)
    else:
        from pdos_next.agent_kernel.bootstrap import Bootstrap

        configure_agent_kernel(engine, Bootstrap(engine, ports=agent_runtime_ports).adapters())
    kernel_activities = KernelActivities(
        engine,
        checkpoint_url=os.environ["PDOS_CHECKPOINT_DATABASE_URL"],
        technical_engine=dispatch_engine,
    )
    store = OriginalStore(os.environ["PDOS_OBJECT_ROOT"])
    from pdos_next.lifecycle_worker import configure_lifecycle

    configure_lifecycle(engine, store, allow_local_profile=True)
    from pdos_next.security_bootstrap import local_runtime

    configure(engine, await local_runtime(store))
    tenants = [UUID(value) for value in os.environ["PDOS_WORKFLOW_TENANTS"].split(",")]
    client = await Client.connect(
        os.environ["PDOS_TEMPORAL_ADDRESS"], namespace=os.environ["PDOS_TEMPORAL_NAMESPACE"]
    )
    activities = Activities(engine, store, os.environ["PDOS_CHECKPOINT_DATABASE_URL"])
    from pdos_next.enterprise_search.embedding_activities import EmbeddingActivities
    from pdos_next.enterprise_search.embedding_composition import configured_ports
    from pdos_next.enterprise_search.embedding_workflow import (
        EnterpriseEmbedding,
        EnterpriseEmbeddingProjection,
        EnterpriseEmbeddingRebuild,
    )

    if embedding_ports is None:
        from pdos_next.model_configuration.host import runtime_ports

        embedding_ports = configured_ports(
            agent_runtime_ports if agent_runtime_ports is not None else runtime_ports(engine),
            provider_io=True,
        )
    embedding_activities = EmbeddingActivities(
        engine, embedding_ports, checkpoint_url=os.environ["PDOS_CHECKPOINT_DATABASE_URL"],
    )
    automation_sender = ServiceAutomationSender(client, engine, dispatch_engine)
    from pdos_next.enterprise_search.events import EnterpriseProjection, ProjectionSender
    from pdos_next.enterprise_search.recovery_workflow import EnterpriseRebuild

    sender = TemporalSender(
        client,
        dispatch_engine=dispatch_engine,
        automation_sender=automation_sender,
        projection_sender=ProjectionSender(client, embedding=True),
    )
    from pdos_next.agent_kernel.temporal_port import TemporalPort, dispatch_pending_runs

    kernel_sender = TemporalPort(client, task_queue=sender.task_queue)
    from pdos_next.dingtalk.runtime import configure as configure_dingtalk
    from pdos_next.dingtalk.summary_workflow import DingTalkSummaryDelivery, SummaryActivities
    from pdos_next.dingtalk.workflow import ChannelActivities, ChannelSender, DingTalkCompletion

    summary_channel_activities = SummaryActivities(
        engine, dispatch_engine, runtime=dingtalk_runtime,
    )
    channel_activities = ChannelActivities(
        engine, dispatch_engine, kernel_sender, runtime=dingtalk_runtime,
    )
    channel_sender = ChannelSender(
        client, dispatch_engine, kernel_sender, task_queue=sender.task_queue,
    )
    if dingtalk_runtime is not None:
        configure_dingtalk(engine, dingtalk_runtime)
    stop = asyncio.Event()

    async def deliver():
        while not stop.is_set():
            for tenant in tenants:
                try:
                    await automation_sender.discover(tenant)
                except Exception as error:
                    logging.getLogger(__name__).warning(
                        "Automation discovery unavailable: %s", type(error).__name__
                    )
                await dispatch_once(dispatch_engine, tenant, sender)
                await dispatch_pending_runs(dispatch_engine, tenant, kernel_sender)
                if dingtalk_runtime is not None:
                    await channel_sender.discover(tenant)
            try:
                await asyncio.wait_for(stop.wait(), 1)
            except TimeoutError:
                pass

    with ThreadPoolExecutor(max_workers=4) as executor:
        async with Worker(
            client,
            task_queue=sender.task_queue,
            workflows=[
                XiaopaiWork,
                DingTalkCompletion,
                DingTalkSummaryDelivery,
                AutomationRuleWork,
                ParseOriginal,
                QueueOriginalSecurity,
                SecureOriginal,
                OriginalLifecycle,
                UploadTerminal,
                EnterpriseProjection,
                EnterpriseEmbedding,
                EnterpriseEmbeddingProjection,
                EnterpriseEmbeddingRebuild,
                EnterpriseRebuild,
            ],
            activities=[
                kernel_activities.advance,
                channel_activities.deliver,
                channel_activities.cancel,
                summary_channel_activities.deliver,
                activities.automation_rule_tick,
                kernel_activities.reconcile,
                activities.parse,
                activities.queue,
                activities.scan,
                activities.lifecycle,
                activities.terminal_upload,
                activities.enterprise_projection,
                embedding_activities.plan,
                embedding_activities.embed,
                activities.enterprise_rebuild_plan,
                activities.enterprise_rebuild_batch,
            ],
            activity_executor=executor,
        ):
            task = asyncio.create_task(deliver())
            try:
                await asyncio.Event().wait()
            finally:
                stop.set()
                await task
                runtime = getattr(engine, "_pdos_security_runtime", None)
                if runtime and hasattr(runtime.scanner, "close"):
                    await runtime.scanner.close()
                if callable(getattr(embedding_ports.client, "close", None)):
                    embedding_ports.client.close()
                engine.dispose()
                auth.dispose()


if __name__ == "__main__":
    asyncio.run(main())
