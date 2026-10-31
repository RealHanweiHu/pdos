"""Offline provider over the same actual HTTP/Temporal/PG graph as assistant cases."""

import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from langgraph.checkpoint.postgres import PostgresSaver
from temporalio.client import Client
from temporalio.worker import Worker

from pdos_next.agent_kernel.activities import KernelActivities, configure_agent_kernel
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.host import BoundHost
from pdos_next.agent_kernel.skills import SkillCatalog
from pdos_next.agent_kernel.temporal_port import TemporalPort, workflow_id
from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.api import create_app
from pdos_next.database import tenant_session
from pdos_next.domain.builds.service import _build, _linked
from pdos_next.enterprise_search.assistant_graph import AssistantExtractGraph
from pdos_next.enterprise_search.comparison_graph import AssistantComparisonGraph
from pdos_next.providers.types import ProviderUsage
from pdos_next.schemas.verification.contracts import BuildRef, ConfigurationRef
from pdos_next.workflows.checkpoints import verified_checkpoint_url
from pdos_next.workflows.xiaopai import XiaopaiWork
from tests.agent_kernel.test_model_configuration_transactions import configured, submit
from tests.enterprise_search.test_assistant_pg import SyntheticClient

PREPARATION = "verification.preparation.record"
REQUEST = "verification.request.create"


def bound_target(work):
    # Keep the real issued bearer token; the handoff facade's helper tokens map
    # predates its separate quality login. Never replace server identities/ACLs.
    person = SimpleNamespace(**vars(work.quality))
    person.tokens = {**person.tokens,
                     person.human: person.headers["Authorization"].removeprefix("Bearer ")}
    with tenant_session(person.engine, person.tenant, actor_id=person.human,
                        category_id=person.category) as session:
        build = _build(session, person.ctx, person.product, UUID(str(work.build_id)))
        _project, engineering, manufacturing, _reads = _linked(
            session, person.ctx, person.product, build, new_consumption=True,
        )
        selection = BuildRef(
            id=build.id, revision=build.revision, product_id=build.product_id,
            project_id=build.project_id,
            engineering_configuration=ConfigurationRef(
                id=engineering["id"], revision=engineering["revision"],
            ),
            manufacturing_configuration=ConfigurationRef(
                id=manufacturing["id"], revision=manufacturing["revision"],
            ),
        )
    return person, selection.model_dump(mode="json")


def output(status="completed", *, result=None, questions=(), summary="已保留固定准备候选。"):
    return ModelTurn(structured={
        "status": status, "summary": summary, "result": result or {},
        "questions": list(questions), "unfinished": [],
    }, usage=ProviderUsage(10, 2))


def call(name, arguments):
    return ModelTurn(calls=(ToolCall(id="synthetic-" + str(uuid4()), name=name,
                                    arguments=arguments),), usage=ProviderUsage(10, 2))


def json_messages(messages):
    for message in messages:
        try:
            value = json.loads(message.get("content") or "{}")
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            yield message, value


class VerificationClient:
    """Actual registered model calls; no forged server ledger or provider egress."""

    def __init__(self, source, purpose, *, missing_count=False):
        self.source, self.purpose = source, purpose
        self.parent = SyntheticClient()
        self.phase, self.calls, self.child_calls, self.step = "parent", 0, 0, 0
        self.missing_count, self.waiting = missing_count, False
        self.arguments, self.context, self.messages = None, None, []

    def close(self):
        pass

    def turn(self, route, **kwargs):
        from pdos_agent_runtime.graph import in_registered_agent_graph

        assert in_registered_agent_graph()
        self.calls += 1
        if self.phase == "parent":
            return self.parent.turn(route, **kwargs)
        names = {tool["name"] for tool in kwargs["tools"]}
        messages = kwargs["messages"]
        self.messages.append((names, deepcopy(messages)))
        values = [value for row, value in json_messages(messages) if row["role"] == "tool"]
        if names == {"assistant.passage.read", "result.read"}:
            self.child_calls += 1
            context = json.loads(messages[0]["content"])["context"]
            if not values:
                return call("assistant.passage.read", {
                    "citation_id": context["citation_id"], "cursor": 0, "page_chars": 2000,
                })
            quote = values[-1]["text"].splitlines()[0]
            return output(result={"rows": [{"citation_id": context["citation_id"],
                                            "statement": quote, "quote": quote}]})
        assert PREPARATION in names, "Server-fixed test_verification must actually be disclosed"
        assert "assistant.passage.read" not in names
        contexts = [value["context"]["verification_action"]
                    for _row, value in json_messages(messages)
                    if isinstance(value.get("context"), dict)
                    and "verification_action" in value["context"]]
        assert contexts, "Use actual projected context, never a fabricated run identity"
        self.context = contexts[-1]
        if self.step == 0:
            self.step = 1
            return call("assistant.materials.read", {"artifact_ids": [self.source["artifact_id"]]})
        if self.step == 1:
            self.step = 2
            row = next(row for row in values[-1]["items"]
                       if row["source_id"] == self.source["artifact_id"])
            return call("assistant.extract", {"citation_ids": [row["citation_id"]]})
        if self.step == 2:
            if self.missing_count and not self.waiting:
                self.waiting = True
                return output("needs_input", questions=[{
                    "id": "sample_count", "question": "本次明确准备多少件样本？",
                    "why": "数量尚未明确，不能默认一件。", "options": [],
                    "recommended": None, "allow_free_text": True, "depends_on": [],
                }], summary="已核对资料，样本数量仍待本人明确。")
            count = 3
            if self.waiting:
                answers = [value["answers"] for _row, value in json_messages(messages)
                           if "answers" in value]
                assert answers and answers[-1]["sample_count"] == "3"
                count = int(answers[-1]["sample_count"])
            target = self.context["target"]
            self.arguments = {
                "request_id": self.context["request_id"], "expected_request_revision": 0,
                "build_id": target["id"], "expected_build_revision": target["revision"],
                "title": "Synthetic assistant re-verification preparation",
                "purpose": self.purpose, "return_form": "逐项原始读数与另行具名专业结论",
                "items": [{"id": "dimension", "feature": "Synthetic dimension",
                           "drawing": deepcopy(self.source), "method": None, "criterion": None,
                           "sample_count": count, "cavities": ["A", "B"]}],
                "sources": [deepcopy(self.source)], "reason": "依据已核对的历史讨论准备复验",
            }
            self.step = 3
            return call(PREPARATION, deepcopy(self.arguments))
        assert self.step == 3
        self.step = 4
        return output()


class LostResponseTransport(httpx.AsyncBaseTransport):
    """Drop one response after the actual ASGI command transaction committed."""

    def __init__(self, app):
        self.inner = httpx.ASGITransport(app=app)
        self.drop_command_id = None
        self.lost = 0

    async def handle_async_request(self, request):
        response = await self.inner.handle_async_request(request)
        if request.method == "POST" and request.url.path.endswith("/commands"):
            payload = json.loads(request.content)
            if response.status_code == 200 and payload["command_id"] == self.drop_command_id:
                await response.aread()
                await response.aclose()
                self.drop_command_id = None
                self.lost += 1
                raise httpx.ReadError("synthetic response lost after commit", request=request)
        return response

    async def aclose(self):
        await self.inner.aclose()


@asynccontextmanager
async def actual_runtime(person, provider, monkeypatch):
    # Same verified local runtime setup as test_assistant_temporal_pg.run_http_case.
    address = os.environ["PDOS_TEMPORAL_ADDRESS"]
    endpoint = urlsplit("//" + address)
    assert endpoint.hostname in {"127.0.0.1", "localhost", "::1"} and endpoint.port
    checkpoint_url = os.environ["PDOS_CHECKPOINT_DATABASE_URL"]
    checkpoint = verified_checkpoint_url(checkpoint_url)
    management, runtime, command = configured(person)
    try:
        command["payload"]["metadata"]["context_window_tokens"] = 200_000
        saved, _ = submit(person, management, command)
        assert saved.status_code == 200, saved.text
        skill = SkillCatalog().configuration("test_verification")
        enable = {"command_id": str(uuid4()), "idempotency_key": str(uuid4()),
                  "category_id": str(person.category), "product_id": None,
                  "expected_revision": 1, "source_read_set": [], "operation": "ai.skill.enable",
                  "payload": {"skill_key": skill.key, "expected_revision": 0,
                              "skill_version": skill.version, "skill_digest": skill.digest,
                              "enabled": True}}
        enabled, _ = submit(person, management, enable)
        assert enabled.status_code == 200, enabled.text  # Enable only; no T0 qualification.
        runtime = replace(runtime, provider_client=provider, preload=lambda _: ())
        bootstrap = Bootstrap(person.engine, ports=runtime)
        adapters = replace(bootstrap.adapters(), cost_required=False,
                           provider_for=lambda *_args: "synthetic-assistant-no-egress")
        host = BoundHost(bootstrap.store, adapters)
        adapter = bootstrap._assistant_adapter
        adapter.graph = AssistantExtractGraph(
            host, adapter, checkpointer_factory=lambda: PostgresSaver.from_conn_string(checkpoint),
        )
        adapter.comparison_graph = AssistantComparisonGraph(
            host, adapter, checkpointer_factory=lambda: PostgresSaver.from_conn_string(checkpoint),
        )
        monkeypatch.setattr(person.engine, "_pdos_agent_kernel_adapters", None, raising=False)
        configure_agent_kernel(person.engine, adapters)
        temporal = await Client.connect(address, namespace=os.environ["PDOS_TEMPORAL_NAMESPACE"])
        assert await temporal.service_client.check_health()
        port = TemporalPort(temporal, task_queue="verification-action-offline-" + str(uuid4()))
        ports = bootstrap.api_ports(port)

        def binding(*args):
            value = bootstrap.binding_for(*args)
            value.token_limit = 2_000_000
            return value

        app = create_app(person.engine, person.auth, agent_runtime_ports=runtime,
                         agent_api_ports=replace(ports, binding_for=binding))
        activities = KernelActivities(person.engine, checkpoint_url=checkpoint_url,
                                      technical_engine=person.dispatch)
        transport = LostResponseTransport(app)
        with ThreadPoolExecutor(max_workers=2) as executor:
            async with (
                Worker(temporal, task_queue=port.task_queue, workflows=[XiaopaiWork],
                       activities=[activities.advance, activities.reconcile],
                       activity_executor=executor),
                httpx.AsyncClient(transport=transport, base_url="http://synthetic.local") as http,
            ):
                yield SimpleNamespace(http=http, temporal=temporal, provider=provider,
                                      transport=transport, person=person,
                                      path=f"/v1/categories/{person.category}/agent-runs")
    finally:
        management.close()


async def start(runtime, payload, *, complete=True, accepted_statuses=("completed",)):
    response = await runtime.http.post(runtime.path, headers=runtime.person.headers, json=payload)
    assert response.status_code == 202, response.text
    identity = UUID(response.json()["run_id"])
    handle = runtime.temporal.get_workflow_handle(workflow_id(runtime.person.tenant, identity))
    if complete:
        result = await asyncio.wait_for(handle.result(), 90)
        assert result["status"] in accepted_statuses, result
    return identity, handle


async def question_ready(runtime, identity):
    async def wait():
        while True:
            response = await runtime.http.get(runtime.path + f"/{identity}/events",
                                              headers=runtime.person.headers)
            assert response.status_code == 200, response.text
            data = response.json()
            if data["status"] == "waiting_input":
                return next(row["event"] for row in data["items"]
                            if row["event"]["type"] == "needs_input")
            assert data["status"] not in {"failed", "partial", "completed", "cancelled"}, data
            await asyncio.sleep(0.2)
    return await asyncio.wait_for(wait(), 90)


async def candidate(runtime, identity):
    response = await runtime.http.get(runtime.path + f"/{identity}/candidates",
                                      headers=runtime.person.headers)
    assert response.status_code == 200, response.text
    rows = [row for row in response.json()["items"]
            if row.get("kind") == "verification_preparation"]
    assert len(rows) == 1, response.text
    return rows[0]
