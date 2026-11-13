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

from pdos_next.core.database import configured_engines, tenant_session
from pdos_next.core.dispatch.outbox import dispatch_once
from pdos_next.errors import DomainError
from pdos_next.originals.access import parse_uploaded
from pdos_next.originals.security import configure, queue_uploaded, scan_requested
from pdos_next.originals.store import OriginalStore
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
        from pdos_next.agent.enterprise_search.events import process_event

        try:
            return process_event(self.engine, reference)
        except DomainError as error:
            raise ApplicationError(
                "Enterprise projection unavailable",
                type=error.code,
                non_retryable=error.code == "FORBIDDEN_SCOPE",
            ) from None

    @activity.defn(name="index_memory_episode")
    def memory_episode_index(self, reference: dict):
        from pdos_next.agent.memory.index import index_episode

        try:
            return index_episode(self.engine, reference)
        except DomainError as error:
            raise ApplicationError(
                "Memory index unavailable",
                type=error.code,
                non_retryable=error.code == "FORBIDDEN_SCOPE",
            ) from None

    @activity.defn(name="plan_enterprise_rebuild")
    def enterprise_rebuild_plan(self, reference: dict):
        from pdos_next.agent.enterprise_search.recovery import _context, plan_rebuild

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
        from pdos_next.agent.enterprise_search.recovery import rebuild_batch

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
        from pdos_next.originals.lifecycle.types import LifecycleFailure
        from pdos_next.originals.lifecycle.worker import process

        try:
            return process(self.engine, reference)
        except (DomainError, LifecycleFailure) as exc:
            raise ApplicationError(
                "Lifecycle requires current reconciliation", type=exc.code, non_retryable=True
            ) from None

    @activity.defn(name="reconcile_upload_terminal")
    def terminal_upload(self, reference: dict):
        from pdos_next.core.dispatch.context import event_context
        from pdos_next.core.models import UploadAttempt
        from pdos_next.originals.object_storage import StorageFailure
        from pdos_next.originals.upload_lifecycle import reconcile_terminal

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


def activity_threads():
    """Activity thread count (D57, F45), from PDOS_WORKER_ACTIVITY_THREADS; default 4.

    Temporal is given the same limit, so it never starts an Activity that would wait
    for a free thread while its execution timeout is already running.
    """
    raw = os.environ.get("PDOS_WORKER_ACTIVITY_THREADS", "4")
    value = int(raw) if raw.isdigit() else 0
    if not 1 <= value <= 64:
        raise RuntimeError("PDOS_WORKER_ACTIVITY_THREADS must be a whole number from 1 to 64")
    return value


def graph_plugin(engine, *, technical_engine=None):
    """The Temporal LangGraph plugin with every graph this worker runs node by node (P100).

    Graphs are built once here, at worker start. Their nodes reach the database through
    the dependencies configured below, never through graph state or runtime context.
    Returns the plugin and the plain Activities that open and close a graph's run.
    """
    from temporalio.langgraph import LangGraphPlugin

    from pdos_next.agent.kernel.graph_activities import GraphRunActivities
    from pdos_next.agent.kernel.persistence import KernelStore
    from pdos_next.domain.my_work import summary_plugin_graph
    from pdos_next.workflows.graph_nodes import configure_graph_dependencies

    configure_graph_dependencies(kernel_store=KernelStore(engine))
    runs = GraphRunActivities(engine, technical_engine=technical_engine)
    from pdos_next.agent.kernel import plugin_graph

    plugin = LangGraphPlugin(graphs={
        summary_plugin_graph.GRAPH: summary_plugin_graph.build(),
        plugin_graph.GRAPH: plugin_graph.build(),
    })
    return plugin, [runs.open, runs.close]


def registered_workflows():
    """Every workflow class the worker registers, in registration order.

    The release replay check (tools/workflow_replay_check.py, D212) replays open
    histories against exactly this list before a worker with new code is started.
    """
    from pdos_next.agent.enterprise_search.embedding_workflow import (
        EnterpriseEmbedding,
        EnterpriseEmbeddingProjection,
        EnterpriseEmbeddingRebuild,
    )
    from pdos_next.agent.enterprise_search.events import EnterpriseProjection
    from pdos_next.agent.enterprise_search.recovery_workflow import EnterpriseRebuild
    from pdos_next.agent.memory.index_workflow import MemoryEpisodeIndex
    from pdos_next.agent.memory.vector_workflow import MemoryEpisodeVectors
    from pdos_next.integrations.dingtalk.summary_workflow import DingTalkSummaryDelivery
    from pdos_next.integrations.dingtalk.workflow import DingTalkCompletion
    from pdos_next.workflows.automation import AutomationRuleWork
    from pdos_next.workflows.maintenance import TenantMaintenance
    from pdos_next.workflows.personal_summary_graph import PersonalSummaryGraphWork
    from pdos_next.workflows.xiaopai import XiaopaiWork
    from pdos_next.workflows.xiaopai_graph import XiaopaiGraphWork

    return [
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
        MemoryEpisodeIndex,
        MemoryEpisodeVectors,
        TenantMaintenance,
        PersonalSummaryGraphWork,
        XiaopaiGraphWork,
    ]


async def main(
    *, agent_runtime_ports=None, agent_kernel_adapters=None, embedding_ports=None,
    dingtalk_runtime=None,
):
    engine, auth = configured_engines()
    from pdos_next.core.database import engine_for

    dispatch_engine = engine_for(os.environ["DISPATCH_DATABASE_URL"])
    from pdos_next.agent.kernel.activities import KernelActivities, configure_agent_kernel
    from pdos_next.domain.automations.transport import ServiceAutomationSender

    if agent_kernel_adapters is not None:
        configure_agent_kernel(engine, agent_kernel_adapters)
    else:
        from pdos_next.agent.kernel.bootstrap import Bootstrap

        configure_agent_kernel(engine, Bootstrap(engine, ports=agent_runtime_ports).adapters())
    kernel_activities = KernelActivities(
        engine,
        checkpoint_url=os.environ["PDOS_CHECKPOINT_DATABASE_URL"],
        technical_engine=dispatch_engine,
    )
    store = OriginalStore(os.environ["PDOS_OBJECT_ROOT"])
    from pdos_next.originals.lifecycle.worker import configure_lifecycle

    configure_lifecycle(engine, store, allow_local_profile=True)
    from pdos_next.bootstrap.security import local_runtime

    configure(engine, await local_runtime(store))
    tenants = [UUID(value) for value in os.environ["PDOS_WORKFLOW_TENANTS"].split(",")]
    client = await Client.connect(
        os.environ["PDOS_TEMPORAL_ADDRESS"], namespace=os.environ["PDOS_TEMPORAL_NAMESPACE"]
    )
    activities = Activities(engine, store, os.environ["PDOS_CHECKPOINT_DATABASE_URL"])
    from pdos_next.agent.enterprise_search.embedding_activities import EmbeddingActivities
    from pdos_next.agent.enterprise_search.embedding_composition import configured_ports

    if embedding_ports is None:
        from pdos_next.agent.model_configuration.host import runtime_ports

        embedding_ports = configured_ports(
            agent_runtime_ports if agent_runtime_ports is not None else runtime_ports(engine),
            provider_io=True,
        )
    embedding_activities = EmbeddingActivities(
        engine, embedding_ports, checkpoint_url=os.environ["PDOS_CHECKPOINT_DATABASE_URL"],
    )
    automation_sender = ServiceAutomationSender(client, engine, dispatch_engine)
    from pdos_next.agent.enterprise_search.events import ProjectionSender
    from pdos_next.agent.memory.index import dispatch_pending as dispatch_memory_index
    from pdos_next.agent.memory.vectors import dispatch_pending as dispatch_memory_vectors

    sender = TemporalSender(
        client,
        dispatch_engine=dispatch_engine,
        automation_sender=automation_sender,
        projection_sender=ProjectionSender(client, embedding=True),
    )
    from pdos_next.agent.kernel.temporal_port import TemporalPort, dispatch_pending_runs
    from pdos_next.workflows.checkpoint_retention import CheckpointRetention
    from pdos_next.workflows.maintenance import MaintenanceSender

    maintenance = MaintenanceSender(client, task_queue=sender.task_queue)
    retention = CheckpointRetention(
        dispatch_engine, os.environ["PDOS_CHECKPOINT_DATABASE_URL"],
    )
    from pdos_next.originals.rescan import OriginalRescan

    rescans = OriginalRescan(engine, dispatch_engine)

    kernel_sender = TemporalPort(client, task_queue=sender.task_queue)
    from pdos_next.integrations.dingtalk.runtime import configure as configure_dingtalk
    from pdos_next.integrations.dingtalk.summary_workflow import (
        SummaryActivities,
    )
    from pdos_next.integrations.dingtalk.workflow import (
        ChannelActivities,
        ChannelSender,
    )

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
                try:
                    await maintenance.discover(tenant)
                except Exception as error:
                    logging.getLogger(__name__).warning(
                        "Maintenance discovery unavailable: %s", type(error).__name__
                    )
                await dispatch_once(dispatch_engine, tenant, sender)
                await dispatch_pending_runs(dispatch_engine, tenant, kernel_sender)
                try:
                    await dispatch_memory_index(
                        dispatch_engine, tenant, client, task_queue=sender.task_queue,
                    )
                except Exception as error:
                    logging.getLogger(__name__).warning(
                        "Memory index discovery unavailable: %s", type(error).__name__
                    )
                try:
                    # P85 第 3 项: only when the profile selects “本人会话记录”.
                    await dispatch_memory_vectors(
                        dispatch_engine, tenant, client, task_queue=sender.task_queue,
                    )
                except Exception as error:
                    logging.getLogger(__name__).warning(
                        "Memory vector discovery unavailable: %s", type(error).__name__
                    )
                if dingtalk_runtime is not None:
                    await channel_sender.discover(tenant)
            try:
                await asyncio.wait_for(stop.wait(), 1)
            except TimeoutError:
                pass

    threads = activity_threads()
    plugin, graph_run_activities = graph_plugin(engine, technical_engine=dispatch_engine)
    with ThreadPoolExecutor(max_workers=threads) as executor:
        async with Worker(
            client,
            task_queue=sender.task_queue,
            workflows=registered_workflows(),
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
                embedding_activities.embed_memory,
                activities.enterprise_rebuild_plan,
                activities.enterprise_rebuild_batch,
                activities.memory_episode_index,
                retention.purge,
                rescans.rescan,
                *graph_run_activities,
            ],
            plugins=[plugin],
            activity_executor=executor,
            max_concurrent_activities=threads,
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
