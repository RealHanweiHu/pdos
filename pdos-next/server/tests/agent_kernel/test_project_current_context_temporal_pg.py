"""Actual native HTTP→Temporal→registered main graph, offline provider only.

Root runs this draft against its verified isolated PG/checkpoint/local Temporal.
Native project commands create every business fact; no fixture inserts status facts.
"""

# ruff: noqa: F401, F811 -- pytest needs the explicit native fixture tree

import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
from pdos_next.agent_kernel.activities import KernelActivities, configure_agent_kernel
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.models import AgentEvent, AgentRun, AgentToolCall
from pdos_next.agent_kernel.project_current_context import KEY
from pdos_next.agent_kernel.temporal_port import TemporalPort, workflow_id
from pdos_next.agent_kernel.types import ModelTurn
from pdos_next.api import create_app
from pdos_next.database import tenant_session
from pdos_next.domain.work_management.constants import STATUS
from pdos_next.models import Grant, now
from pdos_next.providers.types import ProviderUsage
from pdos_next.workflows.checkpoints import verified_checkpoint_url
from pdos_next.workflows.xiaopai import XiaopaiWork
from sqlalchemy import select
from sqlalchemy.orm import Session
from temporalio.client import Client
from temporalio.worker import Worker
from tests.agent_kernel.test_model_configuration_transactions import configured, submit
from tests.agent_kernel.test_project_current_context_pg import (
    original_security_work,
    prepare,
    project_work,
)
from tests.work_management_pg import test_workflow as flow

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL")
    or not os.environ.get("PDOS_TEMPORAL_ADDRESS")
    or not os.environ.get("PDOS_CHECKPOINT_DATABASE_URL"),
    reason="Root-owned verified isolated PG/checkpoint/local Temporal required",
)


class ProjectFactsClient:
    """Reads real context in the one registered main graph; no network adapter."""

    def __init__(self, receipt_id):
        self.receipt_id, self.calls, self.current = receipt_id, 0, None

    def close(self):
        pass

    def turn(self, _route, **request):
        from pdos_agent_runtime.graph import in_registered_agent_graph

        assert in_registered_agent_graph()
        self.calls += 1
        assert self.calls == 1
        contexts = [json.loads(row["content"]).get("context") for row in request["messages"]
                    if row.get("role") == "user" and row.get("content", "").startswith("{")]
        context = next(value for value in contexts if value and value.get("project"))
        current = self.current = deepcopy(context["project"]["current_facts"])
        assert current["named_status"]["reference"]["receipt_id"] == self.receipt_id
        assert current["governance"]["current_stage"]["key"] == "planning"
        gate = current["governance"]["gate"]
        assert gate["state"] == "UNKNOWN"
        assert gate["checks"][0]["detail"] == "当前计划尚无适用的批准基线"
        assert flow.SOURCE_LINE not in str(request)
        return ModelTurn(structured={
            "status": "completed",
            "summary": f"截至{current['as_of']}，当前在计划阶段；{gate['checks'][0]['detail']}。"
                       "门禁未知，不能推断已经进入DVT。",
            "result": {}, "questions": [], "unfinished": [],
        }, usage=ProviderUsage(10, 2))


def test_actual_project_native_context_runs_main_graph_and_retains_history_after_update(
    project_work, monkeypatch,
):
    work, setup = project_work, project_work.setup
    receipt = prepare(work)
    provider = ProjectFactsClient(receipt["id"])
    address = os.environ["PDOS_TEMPORAL_ADDRESS"]
    endpoint = urlsplit("//" + address)
    assert endpoint.hostname in {"127.0.0.1", "localhost", "::1"} and endpoint.port
    checkpoint_url = os.environ["PDOS_CHECKPOINT_DATABASE_URL"]
    verified_checkpoint_url(checkpoint_url)
    management, runtime, command = configured(setup)
    command["payload"]["metadata"]["context_window_tokens"] = 200_000
    saved, _ = submit(setup, management, command)
    assert saved.status_code == 200, saved.text
    runtime = replace(runtime, provider_client=provider, preload=lambda _: ())
    bootstrap = Bootstrap(setup.engine, ports=runtime)
    adapters = replace(bootstrap.adapters(), cost_required=False,
                       provider_for=lambda *_args: "synthetic-project-native-no-egress")
    monkeypatch.setattr(setup.engine, "_pdos_agent_kernel_adapters", None, raising=False)
    configure_agent_kernel(setup.engine, adapters)

    async def actual():
        temporal = await Client.connect(address, namespace=os.environ["PDOS_TEMPORAL_NAMESPACE"])
        assert await temporal.service_client.check_health()
        port = TemporalPort(temporal, task_queue="project-native-offline-" + str(uuid4()))

        def binding(*args):
            value = bootstrap.binding_for(*args)
            value.token_limit = 2_000_000
            return value

        app = create_app(setup.engine, setup.auth, agent_runtime_ports=runtime,
                         agent_api_ports=replace(bootstrap.api_ports(port), binding_for=binding))
        activities = KernelActivities(setup.engine, checkpoint_url=checkpoint_url,
                                      technical_engine=setup.dispatch)
        path = f"/v1/categories/{setup.category}/agent-runs"
        payload = {"goal": "这个项目为什么还没进入DVT？请保留未知与截至时间。",
                   "product_id": str(setup.product), "project_id": str(work.project_id),
                   "idempotency_key": str(uuid4())}
        with ThreadPoolExecutor(max_workers=2) as executor:
            async with (
                Worker(temporal, task_queue=port.task_queue, workflows=[XiaopaiWork],
                       activities=[activities.advance, activities.reconcile],
                       activity_executor=executor),
                httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                  base_url="http://synthetic.local") as http,
            ):
                started = await http.post(path, headers=setup.headers, json=payload)
                assert started.status_code == 202, started.text
                identity = UUID(started.json()["run_id"])
                handle = temporal.get_workflow_handle(workflow_id(setup.tenant, identity))
                outcome = await asyncio.wait_for(handle.result(), 55)
                assert outcome["status"] == "completed", outcome
                response = await http.get(path + "/" + str(identity), headers=setup.headers)
                assert response.status_code == 200, response.text
                result = response.json()["result"]
                answer = result["result"]["assistant"]
                basis = answer["project_basis"]
                assert basis["as_of"] == provider.current["as_of"]
                assert basis["currentness"] == "current"
                assert any(ref["receipt_id"] == receipt["id"] for ref in basis["references"])
                assert "lookup" not in answer and "sources" not in answer
                assert "citation_ids" not in answer and provider.calls == 1
                repeated = await http.post(path, headers=setup.headers, json=payload)
                assert repeated.status_code == 202 and repeated.json()["run_id"] == str(identity)
                assert provider.calls == 1
                history = str(await handle.fetch_history())
                assert flow.SOURCE_LINE not in history
                assert "具名登记：品质结果仍待补录。" not in history
                with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                                    requester_id=setup.human,
                                    category_id=setup.category) as session:
                    run = session.get(AgentRun, identity)
                    assert "customer_original" in run.data_categories
                    assert run.read_sources == []
                    assert any(ref["artifact_id"] == work.source["id"]
                               for ref in run.versions[KEY]["source_proof"])
                    model = list(session.scalars(select(AgentToolCall).where(
                        AgentToolCall.run_id == identity, AgentToolCall.tool == "model",
                    )))
                    assert len(model) == 1 and model[0].state == "completed"
                    events = list(session.scalars(select(AgentEvent).where(
                        AgentEvent.run_id == identity,
                    )))
                    egress = [event.body for event in events
                              if event.body.get("type") == "egress_checked"]
                    assert len(egress) == 1
                    assert egress[0]["provider"] == "synthetic-project-native-no-egress"
                    assert "customer_original" in egress[0]["data_categories"]
                flow.execute(work, STATUS, flow.payload(
                    work, fact_summary="新具名事实：准备核对新增条件。",
                    next_steps="原回答不能自动替换为新事实。", task_refs=[],
                ))
                updated = await http.get(path + "/" + str(identity), headers=setup.headers)
                assert updated.status_code == 200, updated.text
                old = updated.json()["result"]
                assert old["summary"] == result["summary"]
                assert old["result"]["assistant"]["project_basis"]["as_of"] == basis["as_of"]
                assert old["result"]["assistant"]["project_basis"]["currentness"] == "updated"
                with Session(setup.admin) as session, session.begin():
                    grant = session.scalar(select(Grant).where(
                        Grant.category_id == setup.category, Grant.principal_id == setup.human,
                    ))
                    grant.expires_at = now() - timedelta(seconds=1)
                denied = await http.get(path + "/" + str(identity), headers=setup.headers)
                assert denied.status_code == 403 and result["summary"] not in denied.text
                assert provider.calls == 1

    asyncio.run(actual())
