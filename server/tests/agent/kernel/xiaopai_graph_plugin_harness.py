"""Authenticated API → Temporal → plugin-executed 小Pai graph → real PG domain owner.

Only the provider is synthetic: a scripted client that counts every request it is sent.
The tenant switch, worker wiring, graph, node shell, ledger, reconciliation and API are
the real ones. The checkpoint database is not used.
"""

import asyncio
import base64
import contextlib
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from pdos_next.agent.kernel import graph_activities
from pdos_next.agent.kernel.activities import KernelActivities, configure_agent_kernel
from pdos_next.agent.kernel.bootstrap import Bootstrap
from pdos_next.agent.kernel.management import AgreementInput, register_agreement
from pdos_next.agent.kernel.models import AgentEvent, AgentRun, AgentToolCall
from pdos_next.agent.kernel.qualification_binding import model_identity
from pdos_next.agent.kernel.temporal_port import SWITCH, TemporalPort, workflow_id
from pdos_next.agent.kernel.types import ModelTurn, ToolCall
from pdos_next.api import create_app
from pdos_next.core.database import tenant_session
from pdos_next.core.models import now
from pdos_next.providers.types import ProviderUsage
from pdos_next.workflows.worker import graph_plugin
from pdos_next.workflows.xiaopai import XiaopaiWork
from pdos_next.workflows.xiaopai_graph import XiaopaiGraphWork
from tests.agent.kernel.test_domain_adapter_transactions import fixture
from tests.agent.kernel.test_model_configuration_transactions import configured, submit

BINARY = Path(__file__).resolve().parents[4] / ".local/tools/temporal"
SECRET = "sk-synthetic-provider-credential-0123456789"


def final(status="completed", **extra):
    return ModelTurn(usage=ProviderUsage(20, 10), structured={
        "status": status, "summary": "Synthetic verified actual fact", "result": {},
        "questions": [], "unfinished": [], **extra,
    })


def question(identity="market"):
    return final("needs_input", summary="Synthetic question", questions=[{
        "id": identity, "question": "目标市场是哪里？", "why": "决定认证范围",
        "options": [], "recommended": None, "allow_free_text": True, "depends_on": [],
    }])


class Scripted:
    """Each provider request takes the next step; a callable step may block or raise."""

    def __init__(self, steps):
        self.steps, self.calls, self.requests = list(steps), 0, []
        # Stands in for the connection's credential: held by the client only.
        self.api_key = SECRET

    def turn(self, route, **kwargs):
        from pdos_agent_runtime.graph import in_registered_agent_graph

        assert in_registered_agent_graph()
        self.calls += 1
        self.requests.append(kwargs["messages"])
        self.tools = kwargs["tools"]
        step = self.steps[self.calls - 1]
        return step(self) if callable(step) else step

    def close(self):
        pass


def prepare(setup, monkeypatch, steps, *, tenants=None):
    f = fixture(setup)
    management_client, runtime_ports, configuration = configured(setup)
    saved, _ = submit(setup, management_client, configuration)
    assert saved.status_code == 200, saved.text
    bootstrap = Bootstrap(setup.engine, ports=runtime_ports)
    f.route = bootstrap.route_for(f.scope)
    with Session(setup.admin) as session, session.begin():
        from pdos_next.agent.kernel.models import TenantSkillEnablement

        qualification = session.get(TenantSkillEnablement, f.qualification.id)
        qualification.qualified_model_version = f.route.version
        qualification.qualified_model_digest = model_identity(f.route)
    client = Scripted(steps)
    adapters = replace(
        bootstrap.adapters(), provider_for=lambda *_: "synthetic-offline-provider",
        provider_client=client, cost_required=False, preload=lambda _: ("public_research",),
    )
    monkeypatch.setattr(setup.engine, "_pdos_agent_kernel_adapters", None, raising=False)
    configure_agent_kernel(setup.engine, adapters)
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                        requester_id=setup.human, category_id=setup.category) as session:
        register_agreement(session, setup.ctx, AgreementInput(
            provider="synthetic-offline-provider", expected_revision=0,
            data_categories=["internal"], decision="批准", idempotency_key=str(uuid4()),
            retention_terms="fixture-only:no-contract-or-egress",
            training_terms="synthetic only", signed_on=now() - timedelta(minutes=1),
            expires_at=now() + timedelta(hours=1),
        ))
    monkeypatch.setenv(SWITCH, str(setup.tenant) if tenants is None else tenants)
    monkeypatch.setattr(graph_activities, "RECONCILE_AFTER_SECONDS", 1)
    return SimpleNamespace(
        setup=setup, f=f, client=client, bootstrap=bootstrap, runtime_ports=runtime_ports,
        claim=ToolCall(id="native", name="evidence.claim.record", arguments=f.arguments),
    )


def tool_turn(stack, identity="native"):
    call = stack.claim.model_copy(update={"id": identity})
    return ModelTurn(calls=(call,), usage=ProviderUsage(20, 10))


def serve(stack, body, *, token_limit=500000, timeout=90, in_process_worker=True):
    """Run ``body(context)`` with the API, a Temporal server and one worker up."""
    setup = stack.setup

    async def actual():
        environment = await WorkflowEnvironment.start_local(dev_server_existing_path=str(BINARY))
        try:
            port = TemporalPort(environment.client, task_queue="graph-" + str(uuid4()))
            ports = stack.bootstrap.api_ports(port)

            def binding(*args):
                value = stack.bootstrap.binding_for(*args)
                value.token_limit = token_limit
                return value

            app = create_app(
                setup.engine, setup.auth, agent_runtime_ports=stack.runtime_ports,
                agent_api_ports=replace(ports, binding_for=binding),
            )
            plugin, run_activities = graph_plugin(setup.engine, technical_engine=setup.dispatch)
            legacy = KernelActivities(setup.engine, technical_engine=setup.dispatch)
            with ThreadPoolExecutor(max_workers=4) as executor:
                async with (Worker(
                    environment.client, task_queue=port.task_queue,
                    # Both types registered, as in the production worker.
                    workflows=[XiaopaiWork, XiaopaiGraphWork],
                    activities=[*run_activities, legacy.reconcile],
                    plugins=[plugin], activity_executor=executor,
                ) if in_process_worker else contextlib.nullcontext()), httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://synthetic.local",
                ) as http, asyncio.timeout(timeout):
                    return await body(Context(stack, environment, http, port))
        finally:
            await environment.shutdown()

    return asyncio.run(actual())


class Context:
    def __init__(self, stack, environment, http, port):
        self.stack, self.environment, self.http, self.port = stack, environment, http, port
        self.setup = stack.setup
        self.path = f"/v1/categories/{self.setup.category}/agent-runs"

    async def start(self, goal="Synthetic actual source claim"):
        started = await self.http.post(self.path, headers=self.setup.headers, json={
            "goal": goal, "idempotency_key": str(uuid4()),
            "product_id": str(self.setup.product),
            "sources": [{"artifact_id": self.stack.f.arguments["artifact_id"],
                         "expected_revision": 1}],
        })
        assert started.status_code == 202, started.text
        return UUID(started.json()["run_id"])

    def handle(self, run_id):
        return self.environment.client.get_workflow_handle(
            workflow_id(self.setup.tenant, run_id)
        )

    async def result(self, run_id, seconds=60):
        return await asyncio.wait_for(self.handle(run_id).result(), seconds)

    async def answer(self, run_id, answers):
        submitted = await self.http.post(
            f"{self.path}/{run_id}/answers", headers=self.setup.headers,
            json={"answers": answers, "idempotency_key": "answer:" + str(uuid4())},
        )
        assert submitted.status_code == 202, submitted.text
        return submitted.json()["answer_ref"]

    async def waiting(self, run_id):
        """The pending question, once the workflow is waiting on it."""
        while True:
            pending = await self.handle(run_id).query(XiaopaiGraphWork.pending_input)
            if pending:
                return pending
            await asyncio.sleep(0.05)

    async def view(self, run_id):
        saved = await self.http.get(f"{self.path}/{run_id}", headers=self.setup.headers)
        assert saved.status_code == 200, saved.text
        return saved.json()

    async def histories(self, run_id):
        """Every execution of the run's workflow, oldest first (continue-as-new chain)."""
        found = []
        async for execution in self.environment.client.list_workflows(
            f'WorkflowId="{workflow_id(self.setup.tenant, run_id)}"'
        ):
            handle = self.environment.client.get_workflow_handle(
                execution.id, run_id=execution.run_id,
            )
            found.append((execution.start_time, await handle.fetch_history()))
        return [history for _, history in sorted(found, key=lambda item: item[0])]

    async def replay(self, history):
        plugin, _ = graph_plugin(self.setup.engine, technical_engine=self.setup.dispatch)
        await Replayer(
            workflows=[XiaopaiWork, XiaopaiGraphWork], plugins=[plugin],
        ).replay_workflow(history)


def scheduled(history):
    return [
        event.activity_task_scheduled_event_attributes.activity_type.name
        for event in history.events
        if event.HasField("activity_task_scheduled_event_attributes")
    ]


def payloads(history):
    return b"\n".join(
        base64.b64decode(value) for value in re.findall(r'"data":\s*"([^"]*)"', history.to_json())
    ).decode().encode().decode("unicode_escape")


def row(setup, run_id):
    with Session(setup.admin) as session:
        run = session.get(AgentRun, run_id)
        calls = session.scalars(
            select(AgentToolCall).where(AgentToolCall.run_id == run_id)
            .order_by(AgentToolCall.created_at)
        ).all()
        events = session.scalars(
            select(AgentEvent).where(AgentEvent.run_id == run_id).order_by(AgentEvent.sequence)
        ).all()
        return SimpleNamespace(
            state=run.state, error_code=run.error_code, versions=dict(run.versions),
            result=run.result, held_tokens=run.held_tokens,
            calls=[(call.tool, call.state) for call in calls],
            events=[event.body.get("type") for event in events],
        )


def record(case, histories):
    """Append measured history sizes to the evidence file named by the environment."""
    import json
    import os

    target = os.environ.get("PDOS_GRAPH_PILOT_EVIDENCE")
    if not target:
        return
    with Path(target).open("a") as handle:
        handle.write(json.dumps({
            "case": case, "workflow_executions": len(histories),
            "history_events": [len(history.events) for history in histories],
            "history_json_bytes": [len(history.to_json().encode()) for history in histories],
            "activities": sum(len(scheduled(history)) for history in histories),
        }, ensure_ascii=False) + "\n")


def record_value(case, value):
    import json
    import os

    target = os.environ.get("PDOS_GRAPH_PILOT_EVIDENCE")
    if target:
        with Path(target).open("a") as handle:
            handle.write(json.dumps({"case": case, **value}, ensure_ascii=False) + "\n")
