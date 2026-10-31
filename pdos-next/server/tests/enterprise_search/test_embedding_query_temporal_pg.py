"""Actual HTTP→Temporal→KernelStore/model READ→query cost→RRF→verified source.

Root executes only after both unnumbered drafts are migrated. Synthetic vectors
prove the registered integration, never a trustworthy retrieval quality result.
"""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import select
from sqlalchemy.orm import Session
from temporalio.client import Client
from temporalio.worker import Worker

from pdos_next.agent_kernel.activities import KernelActivities, configure_agent_kernel
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.host import BoundHost
from pdos_next.agent_kernel.models import AgentToolCall, ValidationBudget
from pdos_next.agent_kernel.temporal_port import TemporalPort, workflow_id
from pdos_next.api import create_app
from pdos_next.enterprise_search.assistant_graph import AssistantExtractGraph
from pdos_next.enterprise_search.embedding_activities import (
    EmbeddingActivities,
    EmbeddingPorts,
)
from pdos_next.enterprise_search.embedding_query import QueryPorts
from pdos_next.enterprise_search.embedding_query_binding import TOOL
from pdos_next.workflows.checkpoints import verified_checkpoint_url
from pdos_next.workflows.xiaopai import XiaopaiWork
from tests.agent_kernel.test_cost_budget import rate, wallet
from tests.agent_kernel.test_model_configuration_transactions import configured, submit
from tests.enterprise_search.embedding_harness import (
    SyntheticEmbedding,
    command_for,
    reference_for,
    save_profile,
)
from tests.enterprise_search.test_assistant_pg import SyntheticClient
from tests.enterprise_search.test_assistant_temporal_pg import fixed_quote
from tests.enterprise_search.test_retrieval_pg import index, query, register

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
QUERY = "靛蓝彗星南极"


class SemanticClient(SyntheticClient):
    def turn(self, route, **kwargs):
        assert "PRIVATE_EMBEDDING_VECTOR" not in str(kwargs)
        result = super().turn(route, **kwargs)
        if result.calls and result.calls[0].name == "assistant.search":
            return replace(
                result, calls=(result.calls[0].model_copy(update={"arguments": {"query": QUERY}}),)
            )
        return result


def test_actual_run_query_embedding_is_read_derived_accounted_once_and_not_page_triggered(
    setup, monkeypatch
):
    source_id = register(setup, "气密合成记录", "漏气。更换密封圈。RAW_ONLY_CHILD_MARKER")
    index(setup, source_id)
    assert query(setup, QUERY)["items"] == []
    management, runtime, model_command = configured(setup)
    model_command["payload"]["metadata"]["context_window_tokens"] = 200_000
    configured_model, _ = submit(setup, management, model_command)
    assert configured_model.status_code == 200, configured_model.text
    independent = SyntheticEmbedding(setup.tenant)
    price = rate()

    def pricing(_tenant, meta):
        return replace(
            price,
            provider=meta.provider,
            model=meta.model,
            configuration_version=meta.model_version,
        )

    backend = EmbeddingPorts(independent, pricing, independent)
    profile_receipt, _ = save_profile(setup, backend, command_for(setup))
    profile_id = UUID(profile_receipt["subject_id"])
    checkpoint_url = os.environ["PDOS_CHECKPOINT_DATABASE_URL"]
    checkpoint = verified_checkpoint_url(checkpoint_url)
    background = EmbeddingActivities(setup.engine, backend, checkpoint_url=checkpoint_url)
    plan = background.plan(reference_for(setup, profile_receipt))
    for identity in plan["batches"]:
        assert (
            background.embed({"context": plan["context"], "batch_id": identity})["status"]
            == "ready"
        )
    background_calls = len(independent.calls)
    assert background_calls > 0
    budget_id = wallet(setup)
    provider = SemanticClient()
    runtime = replace(
        runtime,
        provider_client=provider,
        preload=lambda _: (),
        embedding_query=QueryPorts(backend, lambda _: profile_id),
    )
    bootstrap = Bootstrap(setup.engine, ports=runtime)
    adapters = replace(
        bootstrap.adapters(),
        cost_required=False,
        provider_for=lambda *_: "synthetic-assistant-no-egress",
    )
    bootstrap._assistant_adapter.graph = AssistantExtractGraph(
        BoundHost(bootstrap.store, adapters),
        bootstrap._assistant_adapter,
        checkpointer_factory=lambda: PostgresSaver.from_conn_string(checkpoint),
    )
    monkeypatch.setattr(setup.engine, "_pdos_agent_kernel_adapters", None, raising=False)
    configure_agent_kernel(setup.engine, adapters)
    address = os.environ["PDOS_TEMPORAL_ADDRESS"]
    target = urlsplit("//" + address)
    assert target.hostname in {"127.0.0.1", "localhost", "::1"} and target.port

    async def actual():
        temporal = await Client.connect(address, namespace=os.environ["PDOS_TEMPORAL_NAMESPACE"])
        temporal_port = TemporalPort(temporal, task_queue="embedding-query-" + str(uuid4()))
        native_ports = bootstrap.api_ports(temporal_port)

        def binding(*args):
            value = bootstrap.binding_for(*args)
            value.token_limit = 2_000_000
            assert value.validation_budget_id == budget_id
            return value

        app = create_app(
            setup.engine,
            setup.auth,
            agent_runtime_ports=runtime,
            agent_api_ports=replace(native_ports, binding_for=binding),
        )
        activities = KernelActivities(
            setup.engine, checkpoint_url=checkpoint_url, technical_engine=setup.dispatch
        )
        with ThreadPoolExecutor(max_workers=3) as executor:
            async with (
                Worker(
                    temporal,
                    task_queue=temporal_port.task_queue,
                    workflows=[XiaopaiWork],
                    activities=[activities.advance, activities.reconcile],
                    activity_executor=executor,
                ),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://synthetic.local"
                ) as http,
            ):
                path = "/v1/personal/agent-runs"
                body = {"goal": "以前类似问题怎么处理？", "idempotency_key": str(uuid4())}
                started = await http.post(path, headers=setup.headers, json=body)
                assert started.status_code == 202, started.text
                identity = UUID(started.json()["run_id"])
                handle = temporal.get_workflow_handle(workflow_id(setup.tenant, identity))
                result = await asyncio.wait_for(handle.result(), 90)
                assert result["status"] == "completed", result
                record = await http.get(path + "/" + str(identity), headers=setup.headers)
                assert record.status_code == 200, record.text
                answer = record.json()["result"]["result"]["assistant"]
                assert answer["lookup"] == "cited" and answer["matched_count"] == 1
                assert answer["sources"][0]["source_id"] == str(source_id)
                assert len(independent.calls) == background_calls + 1
                await fixed_quote(http, setup.headers, answer["sources"][0])
                assert len(independent.calls) == background_calls + 1
                replay = await http.post(path, headers=setup.headers, json=body)
                assert replay.status_code == 202 and replay.json()["run_id"] == str(identity)
                assert provider.calls == 5 and len(independent.calls) == background_calls + 1
                with Session(setup.admin) as session:
                    calls = list(
                        session.scalars(
                            select(AgentToolCall).where(AgentToolCall.run_id == identity)
                        )
                    )
                    derived = [row for row in calls if row.tool == TOOL]
                    assert len(derived) == 1 and derived[0].state == "completed"
                    proof = derived[0].execution_binding
                    parent = next(
                        row for row in calls if str(row.id) == proof["parent_read_call_id"]
                    )
                    assert (
                        parent.tool == "assistant.search"
                        and parent.execution_binding["kind"] == "read"
                    )
                    assert proof["profile_version_id"] == str(profile_id)
                    assert (
                        derived[0].cost_state == "actual" and derived[0].actual_input_tokens == 10
                    )
                    assert derived[0].result["vector"] == [1.0, 0.0]
                    budget = session.get(ValidationBudget, budget_id)
                    assert (
                        budget.calls == 1
                        and budget.held_micro_usd == 0
                        and budget.spent_micro_usd > 0
                    )
                assert "vector" not in str(
                    provider.messages
                ) and "synthetic-embedding-only" not in str(provider.messages)
                history = str((await handle.fetch_history()).events)
                assert (
                    "RAW_ONLY_CHILD_MARKER" not in history
                    and "synthetic-embedding-only" not in history
                )

    asyncio.run(actual())
