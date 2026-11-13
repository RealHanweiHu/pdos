"""An isolated child task inside the plugin path's ``tools`` node (P100, gap G2).

Authenticated HTTP → Temporal → plugin-executed main graph → ``assistant.extract``, which
runs its own child graph (own model calls, own PostgreSQL checkpoints) inside the tools
Activity, exactly as on the original path. Only the provider is synthetic.
"""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import UUID, uuid4

import httpx
import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import select
from sqlalchemy.orm import Session
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from pdos_next.agent.enterprise_search.assistant_graph import AssistantExtractGraph
from pdos_next.agent.kernel.activities import KernelActivities, configure_agent_kernel
from pdos_next.agent.kernel.bootstrap import Bootstrap
from pdos_next.agent.kernel.host import BoundHost
from pdos_next.agent.kernel.models import AgentToolCall
from pdos_next.agent.kernel.temporal_port import SWITCH, TemporalPort, workflow_id
from pdos_next.api import create_app
from pdos_next.workflows.checkpoints import verified_checkpoint_url
from pdos_next.workflows.worker import graph_plugin
from pdos_next.workflows.xiaopai import XiaopaiWork
from pdos_next.workflows.xiaopai_graph import XiaopaiGraphWork
from tests.agent.enterprise_search.test_assistant_pg import SyntheticClient
from tests.agent.enterprise_search.test_assistant_temporal_pg import fixed_quote
from tests.agent.enterprise_search.test_retrieval_pg import index, register
from tests.agent.kernel.test_model_configuration_transactions import configured, submit
from tests.agent.kernel.xiaopai_graph_plugin_harness import BINARY, payloads, scheduled


@pytest.mark.skipif(
    not BINARY.is_file() or not os.environ.get("PDOS_CHECKPOINT_DATABASE_URL"),
    reason="Local Temporal binary and the verified checkpoint store (children) required",
)
def test_isolated_extract_child_runs_inside_the_tools_node(setup, monkeypatch):
    index(setup, register(setup, "D16 气密记录", "漏气。更换密封圈。RAW_ONLY_CHILD_MARKER"))
    provider = SyntheticClient()
    checkpoint = verified_checkpoint_url(os.environ["PDOS_CHECKPOINT_DATABASE_URL"])
    management, runtime, command = configured(setup)
    command["payload"]["metadata"]["context_window_tokens"] = 200_000
    saved, _command = submit(setup, management, command)
    assert saved.status_code == 200, saved.text
    runtime = replace(runtime, provider_client=provider, preload=lambda _: ())
    bootstrap = Bootstrap(setup.engine, ports=runtime)
    adapters = replace(
        bootstrap.adapters(), cost_required=False,
        provider_for=lambda *_args: "synthetic-assistant-no-egress",
    )
    bootstrap._assistant_adapter.graph = AssistantExtractGraph(
        BoundHost(bootstrap.store, adapters), bootstrap._assistant_adapter,
        checkpointer_factory=lambda: PostgresSaver.from_conn_string(checkpoint),
    )
    monkeypatch.setattr(setup.engine, "_pdos_agent_kernel_adapters", None, raising=False)
    configure_agent_kernel(setup.engine, adapters)
    monkeypatch.setenv(SWITCH, str(setup.tenant))

    async def actual():
        environment = await WorkflowEnvironment.start_local(dev_server_existing_path=str(BINARY))
        try:
            port = TemporalPort(environment.client, task_queue="assistant-graph-" + str(uuid4()))

            def binding(*args):
                value = bootstrap.binding_for(*args)
                value.token_limit = 2_000_000
                return value

            app = create_app(
                setup.engine, setup.auth, agent_runtime_ports=runtime,
                agent_api_ports=replace(bootstrap.api_ports(port), binding_for=binding),
            )
            plugin, run_activities = graph_plugin(setup.engine, technical_engine=setup.dispatch)
            legacy = KernelActivities(setup.engine, technical_engine=setup.dispatch)
            with ThreadPoolExecutor(max_workers=4) as executor:
                async with Worker(
                    environment.client, task_queue=port.task_queue,
                    workflows=[XiaopaiWork, XiaopaiGraphWork],
                    activities=[*run_activities, legacy.reconcile],
                    plugins=[plugin], activity_executor=executor,
                ), httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://synthetic.local",
                ) as http, asyncio.timeout(90):
                    path = "/v1/personal/agent-runs"
                    payload = {"goal": "以前漏气怎么处理？", "idempotency_key": str(uuid4())}
                    started = await http.post(path, headers=setup.headers, json=payload)
                    assert started.status_code == 202, started.text
                    identity = UUID(started.json()["run_id"])
                    handle = environment.client.get_workflow_handle(
                        workflow_id(setup.tenant, identity)
                    )
                    outcome = await asyncio.wait_for(handle.result(), 60)
                    assert outcome["status"] == "completed", outcome
                    assert (await handle.describe()).workflow_type == "XiaopaiGraphWork"
                    record = await http.get(f"{path}/{identity}", headers=setup.headers)
                    answer = record.json()["result"]["result"]["assistant"]
                    assert answer["lookup"] == "cited" and answer["matched_count"] == 1
                    await fixed_quote(http, setup.headers, answer["sources"][0])
                    repeat = await http.post(path, headers=setup.headers, json=payload)
                    assert repeat.json()["run_id"] == str(identity)
                    history = await handle.fetch_history()
                    replay_plugin, _ = graph_plugin(setup.engine, technical_engine=setup.dispatch)
                    await Replayer(
                        workflows=[XiaopaiGraphWork], plugins=[replay_plugin],
                    ).replay_workflow(history)
                    return identity, history
        finally:
            await environment.shutdown()

    identity, history = asyncio.run(actual())
    # Same request counts as on the original path: three main turns, two child turns.
    assert provider.calls == 5 and provider.child_calls == 2
    names = scheduled(history)
    assert names.count("xiaopai.tools") == 2 and names.count("xiaopai.model") == 3
    with Session(setup.admin) as session:
        calls = session.scalars(
            select(AgentToolCall).where(AgentToolCall.run_id == identity)
        ).all()
    isolations = [
        call.execution_binding.get("isolation") for call in calls if call.tool == "model"
    ]
    assert isolations.count("main") == 3 and isolations.count("assistant_extract") == 2
    assert all(call.state == "completed" for call in calls)
    # The child's raw passage never enters the main graph's state or the workflow history.
    assert "RAW_ONLY_CHILD_MARKER" not in payloads(history)
