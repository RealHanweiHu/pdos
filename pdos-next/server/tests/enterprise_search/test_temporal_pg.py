"""Actual local HTTP→Outbox→Temporal Activity→projection, with no model Activity."""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.worker import Worker

from pdos_next.agent_kernel.models import AgentRun, AgentToolCall
from pdos_next.dispatch.outbox import dispatch_once
from pdos_next.enterprise_search import indexing
from pdos_next.enterprise_search.events import ProjectionSender
from pdos_next.enterprise_search.models import SearchSource
from pdos_next.enterprise_search.workflow import EnterpriseProjection
from pdos_next.errors import DomainError
from pdos_next.models import Inbox, Outbox
from pdos_next.workflows.transport import TemporalSender
from pdos_next.workflows.worker import Activities
from tests.enterprise_search.test_retrieval_pg import query, register, session_for


@pytest.mark.skipif(
    not os.environ.get("PDOS_TEMPORAL_ADDRESS") or not os.environ.get("PDOS_TEMPORAL_NAMESPACE"),
    reason="Explicit local Temporal address and namespace required",
)
def test_projection_retries_after_worker_restart_without_model_or_raw_temporal_payload(
    setup, monkeypatch
):
    address, namespace = os.environ["PDOS_TEMPORAL_ADDRESS"], os.environ["PDOS_TEMPORAL_NAMESPACE"]
    endpoint = urlsplit("//" + address)
    assert endpoint.hostname in {"127.0.0.1", "localhost", "::1"} and endpoint.port
    assert namespace.strip()
    identity = register(setup, "D16-01 气密恢复", "漏气复验，NO_RAW_TEMPORAL_BODY。")

    async def actual():
        client = await Client.connect(address, namespace=namespace)
        assert await client.service_client.check_health()
        queue, references = "enterprise-projection-" + str(uuid4()), []
        projection = ProjectionSender(client, task_queue=queue)

        class RecordingSender:
            async def event(self, event):
                references.append(event)
                return await projection.event(event)

        sender = TemporalSender(client, projection_sender=RecordingSender())
        result = await dispatch_once(setup.dispatch, setup.tenant, sender)
        assert result == {"delivered": 1, "unknown": 0}
        reference = references[0]
        workflow_id = f"pdos-enterprise-projection:{setup.tenant}:{reference.event_id}"
        handle = client.get_workflow_handle(workflow_id)
        with Session(setup.admin) as session:
            delivery = session.scalar(
                select(Inbox).where(Inbox.event_id == UUID(reference.event_id))
            )
            assert delivery.workflow_id == workflow_id and delivery.status == "received"
            assert session.get(Outbox, UUID(reference.event_id)).delivered_at
        activities = Activities(setup.engine, None, None)
        executor = ThreadPoolExecutor(max_workers=2)

        def worker():
            return Worker(
                client,
                task_queue=queue,
                workflows=[EnterpriseProjection],
                activities=[activities.enterprise_projection],
                activity_executor=executor,
                graceful_shutdown_timeout=timedelta(0),
            )

        def unavailable(*_args, **_kwargs):
            raise DomainError("SOURCE_UNAVAILABLE", "Synthetic retry only")

        try:
            with monkeypatch.context() as patch:
                patch.setattr(indexing, "chunks", unavailable)
                async with worker(), asyncio.timeout(15):
                    while True:
                        description = await handle.describe()
                        if any(
                            pending.last_failure.application_failure_info.type
                            == "SOURCE_UNAVAILABLE"
                            for pending in description.raw_description.pending_activities
                        ):
                            break
                        await asyncio.sleep(0.05)
            with session_for(setup) as session:
                state = session.scalar(
                    select(SearchSource).where(SearchSource.source_id == identity)
                )
                assert state.status == "failed" and state.last_error == "SOURCE_UNAVAILABLE"
            async with worker(), asyncio.timeout(25):
                assert await handle.result() == {"processed": 1, "changed": 1}
            assert await sender(reference) == workflow_id
            assert await client.get_workflow_handle(workflow_id).result() == {
                "processed": 1,
                "changed": 1,
            }
            assert query(setup, "D16-01漏气")["returned"] == 1
            history = await handle.fetch_history()
            assert "NO_RAW_TEMPORAL_BODY" not in str(history.events)
            assert "text" not in asdict(reference)
            with Session(setup.admin) as session:
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(AgentRun)
                        .where(AgentRun.tenant_id == setup.tenant)
                    )
                    == 0
                )
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(AgentToolCall)
                        .where(AgentToolCall.tenant_id == setup.tenant)
                    )
                    == 0
                )
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(SearchSource)
                        .where(SearchSource.tenant_id == setup.tenant)
                    )
                    == 1
                )
        finally:
            if (await handle.describe()).status == WorkflowExecutionStatus.RUNNING:
                await handle.terminate("End this dedicated synthetic projection test")
            executor.shutdown(wait=True)

    asyncio.run(actual())
