"""Episode vectors on a real local Temporal server (D300; P85 第 3 项, design §14.9).

Two halves, one isolated ``pdos_test`` and one verified local Temporal/checkpoint store:

1. Background: the dispatch role finds the owner's episodes lacking a vector in
   the active “本人会话记录” profile, starts the registered ``MemoryEpisodeVectors``
   workflow, and the worker's ``embed_memory_episodes`` activity embeds them as
   the owner and writes the receipt. Only fixed UUID references and a small
   result travel through Temporal; no owner words, no vectors.
2. Query: an actual HTTP→Temporal Run whose model calls ``memory.search`` with
   words that match no keyword. The default ``Bootstrap`` wiring (no hand-made
   query port) embeds the query, fuses the vector ranking, and finds the episode.

The embedding provider is the in-process synthetic one: this proves the
registered integration, never retrieval quality, and nothing leaves the machine.
When ``PDOS_MEMORY_VECTORS_EVIDENCE`` names a file, measured facts are appended.
"""

import asyncio
import base64
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from temporalio.client import Client
from temporalio.worker import Worker

from pdos_next.agent.enterprise_search.embedding_activities import (
    EmbeddingActivities,
    EmbeddingPorts,
)
from pdos_next.agent.enterprise_search.embedding_query_binding import TOOL
from pdos_next.agent.kernel.activities import configure_agent_kernel
from pdos_next.agent.kernel.bootstrap import Bootstrap
from pdos_next.agent.kernel.models import AgentToolCall
from pdos_next.agent.kernel.temporal_port import TemporalPort
from pdos_next.agent.kernel.temporal_port import workflow_id as run_workflow_id
from pdos_next.agent.kernel.types import ModelTurn, ToolCall
from pdos_next.agent.memory.models import MemoryEmbeddingCall, MemoryEpisodeVector
from pdos_next.agent.memory.vector_workflow import MemoryEpisodeVectors
from pdos_next.agent.memory.vectors import dispatch_pending, workflow_id
from pdos_next.api import create_app
from pdos_next.providers.types import ProviderUsage
from tests.agent.enterprise_search.embedding_harness import (
    SyntheticEmbedding,
    command_for,
    save_profile,
)
from tests.agent.kernel.graph_inline import graph_worker
from tests.agent.kernel.test_cost_budget import rate, wallet
from tests.agent.kernel.test_model_configuration_transactions import configured, submit
from tests.agent.memory.support import episode, finish, start

pytestmark = pytest.mark.skipif(
    not all(os.environ.get(name) for name in (
        "TEST_DATABASE_URL", "PDOS_CHECKPOINT_DATABASE_URL", "PDOS_TEMPORAL_ADDRESS",
        "PDOS_TEMPORAL_NAMESPACE")),
    reason="Explicit verified local PostgreSQL/checkpoint/Temporal environment required",
)
GOAL = "比较三家气泵供应商的报价和交期"
QUERY = "上回那个对比"  # Shares no keyword with GOAL: only the vector can find it.


def record(value):
    target = os.environ.get("PDOS_MEMORY_VECTORS_EVIDENCE")
    if target:
        with Path(target).open("a") as handle:
            handle.write(json.dumps(value, ensure_ascii=False) + "\n")


def payloads(history):
    return b"\n".join(
        base64.b64decode(value) for value in re.findall(r'"data":\s*"([^"]*)"', history.to_json())
    ).decode(errors="replace")


class MemoryModel:
    """Offline synthetic model: one memory.search, then a completed answer."""

    def __init__(self):
        self.calls, self.results = 0, []

    def close(self):
        pass

    def turn(self, _route, **kwargs):
        from pdos_agent_runtime.graph import in_registered_agent_graph

        assert in_registered_agent_graph()
        self.calls += 1
        values = [json.loads(row["content"]) for row in kwargs["messages"]
                  if row["role"] == "tool"]
        if not values:
            return ModelTurn(calls=(ToolCall(id="synthetic-memory-search", name="memory.search",
                                             arguments={"query": QUERY}),),
                             usage=ProviderUsage(10, 2))
        self.results.append(values[-1])
        return ModelTurn(structured={
            "status": "completed", "summary": "合成回答：找到了以前的工作记录。",
            "result": {}, "questions": [], "unfinished": [],
        }, usage=ProviderUsage(10, 2))


def test_episode_vectors_are_built_through_temporal_and_used_by_an_actual_run(setup, monkeypatch):
    earlier, _ = start(setup, goal=GOAL)
    finish(setup, earlier)
    row = episode(setup, earlier)
    management, runtime, model_command = configured(setup)
    model_command["payload"]["metadata"]["context_window_tokens"] = 200_000
    saved_model, _ = submit(setup, management, model_command)
    assert saved_model.status_code == 200, saved_model.text
    independent = SyntheticEmbedding(setup.tenant)
    price = rate()

    def pricing(_tenant, meta):
        return replace(price, provider=meta.provider, model=meta.model,
                       configuration_version=meta.model_version)

    backend = EmbeddingPorts(independent, pricing, independent)
    command = command_for(setup)
    command["payload"]["metadata"]["data_categories"] = ["internal", "owner_session"]
    receipt, _ = save_profile(setup, backend, command)
    version = UUID(receipt["subject_id"])
    checkpoint = os.environ["PDOS_CHECKPOINT_DATABASE_URL"]
    background = EmbeddingActivities(setup.engine, backend, checkpoint_url=checkpoint)
    budget_id = wallet(setup)
    model = MemoryModel()
    # The default wiring: no hand-made query port, only the trusted embedding host.
    runtime = replace(runtime, provider_client=model, preload=lambda _: (),
                      memory_embedding=backend)
    bootstrap = Bootstrap(setup.engine, ports=runtime)
    adapters = replace(bootstrap.adapters(), cost_required=False,
                       provider_for=lambda *_: "synthetic-assistant-no-egress")
    monkeypatch.setattr(setup.engine, "_pdos_agent_kernel_adapters", None, raising=False)
    configure_agent_kernel(setup.engine, adapters)
    address = os.environ["PDOS_TEMPORAL_ADDRESS"]
    target = urlsplit("//" + address)
    assert target.hostname in {"127.0.0.1", "localhost", "::1"} and target.port
    queue = "memory-vectors-" + str(uuid4())

    async def actual():
        temporal = await Client.connect(address, namespace=os.environ["PDOS_TEMPORAL_NAMESPACE"])
        with ThreadPoolExecutor(max_workers=3) as executor:
            # 1. Background vectorization through the registered workflow.
            async with Worker(temporal, task_queue=queue, workflows=[MemoryEpisodeVectors],
                              activities=[background.embed_memory], activity_executor=executor):
                sent = await dispatch_pending(setup.dispatch, setup.tenant, temporal,
                                              task_queue=queue)
                value = {"tenant_id": str(setup.tenant), "owner_id": str(row.owner_id),
                         "profile_version_id": str(version), "episode_ids": [str(row.id)]}
                handle = temporal.get_workflow_handle(workflow_id(value))
                built = await asyncio.wait_for(handle.result(), 60)
                again = await dispatch_pending(setup.dispatch, setup.tenant, temporal,
                                               task_queue=queue)
                vector_history = await handle.fetch_history()
            # 2. An actual Run whose model calls memory.search.
            port = TemporalPort(temporal, task_queue=queue + "-run")
            native = bootstrap.api_ports(port)

            def binding(*args):
                value = bootstrap.binding_for(*args)
                value.token_limit = 2_000_000
                assert value.validation_budget_id == budget_id
                return value

            app = create_app(setup.engine, setup.auth, agent_runtime_ports=runtime,
                             agent_api_ports=replace(native, binding_for=binding))
            async with (
                graph_worker(temporal, port.task_queue, setup.engine, executor,
                             technical_engine=setup.dispatch),
                httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                  base_url="http://synthetic.local") as http,
            ):
                path = "/v1/personal/agent-runs"
                started = await http.post(path, headers=setup.headers, json={
                    "goal": "我以前做过类似的对比吗？", "idempotency_key": str(uuid4())})
                assert started.status_code == 202, started.text
                identity = UUID(started.json()["run_id"])
                run_handle = temporal.get_workflow_handle(run_workflow_id(setup.tenant, identity))
                outcome = await asyncio.wait_for(run_handle.result(), 90)
                run_history = await run_handle.fetch_history()
        return sent, built, again, vector_history, identity, outcome, run_history

    sent, built, again, vector_history, identity, outcome, run_history = asyncio.run(actual())
    assert sent == {"pending": 1, "delivered": 1, "unavailable": 0}
    assert built["status"] == "ready" and built["embedded"] == 1
    assert again == {"pending": 0, "delivered": 0, "unavailable": 0}
    with Session(setup.admin) as session:
        receipt_row = session.scalar(select(MemoryEmbeddingCall).where(
            MemoryEmbeddingCall.tenant_id == setup.tenant))
        stored = session.scalar(select(MemoryEpisodeVector).where(
            MemoryEpisodeVector.tenant_id == setup.tenant))
        calls = list(session.scalars(select(AgentToolCall).where(
            AgentToolCall.run_id == identity)))
    assert receipt_row.state == "completed" and receipt_row.data_categories == ["owner_session"]
    assert receipt_row.egress["provider"] == "embedding.invalid"
    assert receipt_row.input_tokens == 10 and receipt_row.charged_micro_usd > 0
    assert stored.episode_id == row.id and stored.profile_version_id == version
    background_history = payloads(vector_history)
    # Only fixed references and a small result went through Temporal.
    assert str(row.id) in background_history
    assert GOAL not in background_history and "气泵" not in background_history
    assert "vector" not in background_history and "synthetic-embedding-only" \
        not in background_history

    assert outcome["status"] == "completed", outcome
    found = model.results[0]
    assert [item["run_id"] for item in found["items"]] == [str(earlier)]
    assert found["retrieval"]["channels"] == ["keyword", "vector"]
    semantic = found["retrieval"]["semantic"]
    assert semantic["status"] == "queried" and semantic["profile_version_id"] == str(version)
    assert semantic["coverage"] == "complete" and semantic["switching"] is False
    derived = [call for call in calls if call.tool == TOOL]
    parent = [call for call in calls if call.tool == "memory.search"]
    assert len(derived) == 1 and derived[0].state == "completed"
    assert derived[0].execution_binding["parent_read_call_id"] == str(parent[0].id)
    assert derived[0].actual_input_tokens == 10
    assert len(independent.calls) == 2  # One background batch, one query.
    query_history = payloads(run_history)
    assert "synthetic-embedding-only" not in query_history
    assert "[1.0, 0.0]" not in query_history and "[1.0,0.0]" not in query_history
    record({"case": "memory_vectors_temporal",
            "background_history_events": len(vector_history.events),
            "background_history_bytes": len(vector_history.to_json().encode()),
            "owner_words_in_background_history": False, "vectors_in_history": False,
            "receipt": {"state": receipt_row.state, "provider": receipt_row.egress["provider"],
                        "data_categories": receipt_row.data_categories,
                        "input_tokens": receipt_row.input_tokens,
                        "charged_micro_usd": receipt_row.charged_micro_usd},
            "query": {"channels": found["retrieval"]["channels"], "semantic": semantic,
                      "derived_call_state": derived[0].state,
                      "derived_input_tokens": derived[0].actual_input_tokens},
            "run_history_events": len(run_history.events),
            "provider_calls": len(independent.calls)})
