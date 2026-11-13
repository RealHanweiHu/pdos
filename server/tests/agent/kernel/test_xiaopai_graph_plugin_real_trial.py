"""Stage 3 trial (P100): the plugin path with the real model on a synthetic tenant.

Opt-in only. It sends synthetic questions to the configured provider and costs real
tokens, so it runs only when PDOS_GRAPH_PLUGIN_REAL_TRIAL names the host's model runtime
metadata file to copy the provider entry from (the API key itself stays in the host's
secure store and is never read here). Everything else is the isolated ``pdos_test``.

  PDOS_GRAPH_PLUGIN_REAL_TRIAL=/abs/path/model-runtime.json \\
  PDOS_GRAPH_PILOT_EVIDENCE=/abs/path/trial.jsonl \\
  uv run pytest tests/agent/kernel/test_xiaopai_graph_plugin_real_trial.py -q -s
"""

import asyncio
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from pdos_next.agent.kernel.activities import KernelActivities, configure_agent_kernel
from pdos_next.agent.kernel.bootstrap import Bootstrap
from pdos_next.agent.kernel.models import AgentRun, AgentToolCall, TenantAdministrator
from pdos_next.agent.kernel.temporal_port import SWITCH, TemporalPort, workflow_id
from pdos_next.api import create_app
from pdos_next.workflows.worker import graph_plugin
from pdos_next.workflows.xiaopai import XiaopaiWork
from pdos_next.workflows.xiaopai_graph import XiaopaiGraphWork
from tests.agent.enterprise_search.test_retrieval_pg import index, register
from tests.agent.kernel import test_budget_management as budgets
from tests.agent.kernel.test_model_configuration_transactions import submit
from tests.agent.kernel.xiaopai_graph_plugin_harness import BINARY, payloads, scheduled

SOURCE = os.environ.get("PDOS_GRAPH_PLUGIN_REAL_TRIAL")
pytestmark = pytest.mark.skipif(
    not SOURCE or not BINARY.is_file(),
    reason="Opt-in real-provider trial: set PDOS_GRAPH_PLUGIN_REAL_TRIAL",
)

MATERIAL = (
    "TP-200 车载充气泵 试产记录（合成）。\n"
    "一、气密：首批 50 台中 3 台在 8 bar 保压 60 秒时压降超过 0.3 bar，判定为漏气。\n"
    "原因：出气嘴 O 型圈压缩量不足，线径 1.5 mm 偏小。\n"
    "措施：O 型圈改为线径 1.8 mm、材料 NBR70；复测 50 台全部合格。\n"
    "二、噪声：满载 1 米处 78 dB(A)，目标 75 dB(A)，未达标，待改电机支架减振垫。\n"
    "三、温升：连续工作 15 分钟缸体表面 92 ℃，低于 105 ℃ 限值。\n"
)
CASES = [
    ("plain_answer", "personal", "用三句话说明 IP67 防护等级的含义，不需要查资料。"),
    ("material_question", "category",
     "根据已登记的试产记录，TP-200 的漏气问题原因是什么、采取了什么措施？请给出依据。"),
    ("needs_scope", "category", "帮我整理一下还没解决的问题。"),
]


def host_config(tmp_path, tenant):
    """The host's provider entry, rebound to this run's synthetic tenant."""
    source = json.loads(Path(SOURCE).read_text())
    model, secret = source["models"][0], source["secrets"][0]
    value = {
        "format_version": source["format_version"], "kms": source["kms"],
        "secrets": [{**secret, "tenant_id": str(tenant)}],
        "models": [{**model, "tenant_id": str(tenant)}],
    }
    path = tmp_path / "model-runtime.json"
    path.touch(mode=0o600)
    path.write_text(json.dumps(value))
    return path, model


@pytest.mark.parametrize("setup", [{"test_authorization_hours": 4}], indirect=True)
def test_real_provider_runs_on_the_plugin_path(setup, tmp_path, monkeypatch):
    path, model = host_config(tmp_path, setup.tenant)
    monkeypatch.setenv("PDOS_TENANT_RUNTIME_CONFIG", str(path))
    monkeypatch.setenv("PDOS_ENVIRONMENT", "development")
    monkeypatch.setenv("PDOS_STATE_DB_PORT", os.environ["TEST_DATABASE_PORT"])
    monkeypatch.setenv("PDOS_STATE_DB_MARKER", os.environ["TEST_DATABASE_MARKER"])
    monkeypatch.setenv(SWITCH, str(setup.tenant))
    from pdos_next.agent.model_configuration.host import runtime_ports
    from pdos_next.schemas.model_configuration import ModelMetadata

    with Session(setup.admin) as session, session.begin():
        session.add(TenantAdministrator(tenant_id=setup.tenant, principal_id=setup.human))
    ports = runtime_ports(setup.engine)
    from fastapi.testclient import TestClient

    management = TestClient(create_app(setup.engine, setup.auth, agent_runtime_ports=ports))
    saved, _ = submit(setup, management, {
        "command_id": str(uuid4()), "idempotency_key": str(uuid4()),
        "operation": "model.configuration.save", "category_id": str(setup.category),
        "expected_revision": 1, "product_id": None, "source_read_set": [],
        "payload": {"expected_revision": 0, "enabled": True, "metadata": ModelMetadata(
            protocol=model["protocol"], base_url=model["base_url"], model=model["model"],
            model_version=model["model_version"],
            # Without it the kernel assumes a small window and stops before any request.
            context_window_tokens=200_000,
        ).model_dump(mode="json")},
    })
    assert saved.status_code == 200, saved.text
    # The person's own model budget, set through the real T1 command. The local
    # development policy for this provider keeps accounting but does not cap it.
    budgets.allocate(setup)
    index(setup, register(setup, "TP-200 试产记录", MATERIAL))
    bootstrap = Bootstrap(setup.engine, ports=ports)
    monkeypatch.setattr(setup.engine, "_pdos_agent_kernel_adapters", None, raising=False)
    configure_agent_kernel(setup.engine, bootstrap.adapters())
    observed, reasons = [], []
    # Record why a node stopped or a result failed verification (reason and frames
    # only, as the evaluation runtime does); behaviour is unchanged.
    import sys

    from pdos_next.errors import DomainError

    original = DomainError.__init__

    def explain(self, code, message, *args, **kwargs):
        original(self, code, message, *args, **kwargs)
        frames, frame = [], sys._getframe(1)
        while frame is not None and len(frames) < 5:
            name = frame.f_code.co_filename
            if "/pdos_next/" in name:
                frames.append(
                    f"{name.split('/pdos_next/')[-1]}:{frame.f_lineno}:{frame.f_code.co_name}"
                )
            frame = frame.f_back
        reasons.append({"code": self.code, "reason": self.reason, "message": self.message,
                        "frames": frames})

    monkeypatch.setattr(DomainError, "__init__", explain)

    async def actual():
        environment = await WorkflowEnvironment.start_local(dev_server_existing_path=str(BINARY))
        try:
            port = TemporalPort(environment.client, task_queue="trial-" + str(uuid4()))
            def binding(*args):
                # Same per-run allowance as the real evaluation runs, so a run ends on
                # its own terms rather than on the default synthetic allowance.
                value = bootstrap.binding_for(*args)
                value.token_limit = 2_000_000
                return value

            app = create_app(
                setup.engine, setup.auth, agent_runtime_ports=ports,
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
                ) as http:
                    for name, where, goal in CASES:
                        observed.append(await one(environment, http, name, where, goal))
        finally:
            await environment.shutdown()

    async def one(environment, http, name, where, goal):
        path = ("/v1/personal/agent-runs" if where == "personal"
                else f"/v1/categories/{setup.category}/agent-runs")
        began = time.monotonic()
        started = await http.post(path, headers=setup.headers, json={
            "goal": goal, "idempotency_key": str(uuid4()),
        })
        assert started.status_code == 202, started.text
        run_id = UUID(started.json()["run_id"])
        handle = environment.client.get_workflow_handle(workflow_id(setup.tenant, run_id))
        answered = 0
        task = asyncio.ensure_future(handle.result())
        while not task.done():
            await asyncio.wait([task], timeout=1)
            if task.done():
                break
            pending = await handle.query(XiaopaiGraphWork.pending_input)
            if pending and "questions" in pending[0] and answered < 2:
                answers = {
                    question["id"]: "只看 TP-200 这个型号，范围是已登记试产记录里未达标的项目。"
                    for question in pending[0]["questions"]
                }
                submitted = await http.post(
                    f"{path}/{run_id}/answers", headers=setup.headers,
                    json={"answers": answers, "idempotency_key": "answer:" + str(uuid4())},
                )
                assert submitted.status_code == 202, submitted.text
                answered += 1
                while await handle.query(XiaopaiGraphWork.pending_input):
                    await asyncio.sleep(0.2)
        result = await asyncio.wait_for(task, 600)
        elapsed = time.monotonic() - began
        histories, plugin, _ = [], *graph_plugin(setup.engine, technical_engine=setup.dispatch)
        async for execution in environment.client.list_workflows(f'WorkflowId="{handle.id}"'):
            history = await environment.client.get_workflow_handle(
                execution.id, run_id=execution.run_id,
            ).fetch_history()
            await Replayer(workflows=[XiaopaiGraphWork], plugins=[plugin]).replay_workflow(history)
            histories.append(history)
        with Session(setup.admin) as session:
            run = session.get(AgentRun, run_id)
            calls = session.execute(
                select(AgentToolCall.tool, AgentToolCall.state, func.count())
                .where(AgentToolCall.run_id == run_id)
                .group_by(AgentToolCall.tool, AgentToolCall.state)
            ).all()
            summary = (run.result or {}).get("summary")
            record = {
                "case": name, "status": result.get("status"),
                "error_code": result.get("error_code") or run.error_code,
                "seconds": round(elapsed, 1), "answers_given": answered,
                "used_tokens": run.used_tokens, "held_tokens": run.held_tokens,
                "ledger": sorted(f"{tool}:{state}:{count}" for tool, state, count in calls),
                "workflow_type": (await handle.describe()).workflow_type,
                "workflow_executions": len(histories),
                "history_events": [len(history.events) for history in histories],
                "history_json_bytes": [len(h.to_json().encode()) for h in histories],
                "largest_payload_bytes": max(
                    len(line.encode()) for h in histories for line in payloads(h).split("\n")
                ),
                "activities": [name for h in histories for name in scheduled(h)],
                "summary_chars": len(summary or ""),
            }
        record["domain_errors"] = [
            f"{item['code']}/{item['reason']}@{item['frames'][0] if item['frames'] else '?'}"
            for item in reasons
        ]
        for item in reasons:
            print("REASON", name, json.dumps(item, ensure_ascii=False))
        # What verification told the model to fix, as recorded in graph state.
        feedback = sorted({
            found for h in histories
            for found in re.findall(r"字段核对错误：(\[.*?\])。list_type", payloads(h))
        })
        record["verification_feedback"] = feedback
        for item in feedback:
            print("VERIFY", name, item[:500])
        reasons.clear()
        print("TRIAL", json.dumps(record, ensure_ascii=False))
        if summary:
            print("ANSWER", name, summary[:300])
        target = os.environ.get("PDOS_GRAPH_PILOT_EVIDENCE")
        if target:
            with Path(target).open("a") as handle_:
                handle_.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    asyncio.run(actual())
    assert [item["workflow_type"] for item in observed] == ["XiaopaiGraphWork"] * len(CASES)
    assert all(item["held_tokens"] == 0 for item in observed)
    assert all(item["status"] in {"completed", "partial"} for item in observed), observed
