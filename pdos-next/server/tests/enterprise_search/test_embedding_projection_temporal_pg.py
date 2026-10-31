"""Actual HTTP T1 → Temporal → registered LangGraph → PG vector checkpoint recovery.

Never runs without explicit verified local DB/state/Temporal environment. Root
owns execution after numbering/applying the draft. No real provider is used.
"""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from temporalio.client import Client
from temporalio.worker import Worker

from pdos_next.dispatch.outbox import Envelope
from pdos_next.enterprise_search.embedding_activities import EmbeddingActivities
from pdos_next.enterprise_search.embedding_models import ChunkEmbedding, EmbeddingCall
from pdos_next.enterprise_search.embedding_workflow import (
    EnterpriseEmbedding,
    EnterpriseEmbeddingProjection,
)
from pdos_next.enterprise_search.events import ProjectionSender
from pdos_next.errors import DomainError
from tests.enterprise_search.embedding_harness import (
    command_for,
    ports_for,
    reference_for,
    save_profile,
)
from tests.enterprise_search.test_retrieval_pg import index, register

pytestmark = pytest.mark.skipif(
    not all(
        os.environ.get(name)
        for name in (
            "TEST_DATABASE_URL",
            "PDOS_CHECKPOINT_DATABASE_URL",
            "PDOS_TEMPORAL_ADDRESS",
            "PDOS_TEMPORAL_NAMESPACE",
        )
    ),
    reason="Explicit verified local PostgreSQL/checkpoint/Temporal environment required",
)


def test_confirmed_embedding_committed_batch_recovers_without_provider_reissue(setup, monkeypatch):
    identity = register(setup, "Synthetic projection", "SYNTHETIC_EMBEDDING_INPUT_NOT_IN_HISTORY")
    index(setup, identity)
    provider, ports = ports_for(setup)
    receipt, _ = save_profile(setup, ports, command_for(setup))
    assert not provider.calls
    reference = reference_for(setup, receipt)
    reference["event_type"] = "embedding.profile_saved"
    address, namespace = os.environ["PDOS_TEMPORAL_ADDRESS"], os.environ["PDOS_TEMPORAL_NAMESPACE"]
    endpoint = urlsplit("//" + address)
    assert endpoint.hostname in {"localhost", "127.0.0.1", "::1"} and endpoint.port
    import pdos_next.enterprise_search.embedding_activities as module

    original = module.execute_batch
    attempts = []

    def committed_ack_lost(*args, **kwargs):
        result = original(*args, **kwargs)
        attempts.append(result["batch_id"])
        if len(attempts) == 1:
            raise DomainError("SOURCE_UNAVAILABLE", "Synthetic committed acknowledgement loss")
        return result

    monkeypatch.setattr(module, "execute_batch", committed_ack_lost)

    async def actual():
        client = await Client.connect(address, namespace=namespace)
        queue = "embedding-recovery-" + str(uuid4())
        sender = ProjectionSender(client, task_queue=queue, embedding=True)
        event = Envelope(**reference)
        workflow_id = await sender.event(event)
        handle = client.get_workflow_handle(workflow_id)
        executor = ThreadPoolExecutor(max_workers=3)

        def worker():
            # Fresh Activity object and PostgresSaver on every worker instance.
            activities = EmbeddingActivities(
                setup.engine, ports, checkpoint_url=os.environ["PDOS_CHECKPOINT_DATABASE_URL"]
            )
            return Worker(
                client,
                task_queue=queue,
                workflows=[EnterpriseEmbedding, EnterpriseEmbeddingProjection],
                activities=[activities.plan, activities.embed],
                activity_executor=executor,
                graceful_shutdown_timeout=timedelta(0),
            )

        try:
            async with worker(), asyncio.timeout(60):
                while True:
                    description = await handle.describe()
                    if description.raw_description.pending_activities and provider.calls:
                        with Session(setup.admin) as session:
                            committed = session.scalar(
                                select(func.count())
                                .select_from(ChunkEmbedding)
                                .where(ChunkEmbedding.tenant_id == setup.tenant)
                            )
                        if committed:
                            break
                    await asyncio.sleep(0.05)
            assert len(provider.calls) == 1
            async with worker(), asyncio.timeout(120):
                result = await handle.result()
            assert result["status"] == "ready" and result["processed_batches"] == 1
            assert len(provider.calls) == 1 and len(attempts) == 2
            assert attempts[0] == attempts[1]
            with Session(setup.admin) as session:
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(EmbeddingCall)
                        .where(EmbeddingCall.tenant_id == setup.tenant)
                    )
                    == 1
                )
            assert await sender.event(replace(event, lease_id=str(uuid4()))) == workflow_id
            assert await client.get_workflow_handle(workflow_id).result() == result
            history = str((await handle.fetch_history()).events)
            assert "SYNTHETIC_EMBEDDING_INPUT_NOT_IN_HISTORY" not in history
            assert "synthetic-embedding-only" not in history
        finally:
            executor.shutdown(wait=True)

    asyncio.run(actual())
