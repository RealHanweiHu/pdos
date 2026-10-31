"""Native evaluation controls. Scripted turns exercise paths, never score answers."""

import importlib.util
import json
import os
from collections import deque
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

from pdos_agent_runtime.graph import in_registered_agent_graph
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bootstrap import Bootstrap, RuntimePorts
from pdos_next.agent_kernel.disclosure import disclosure
from pdos_next.agent_kernel.graph import AgentKernel
from pdos_next.agent_kernel.host import BoundHost
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.agent_kernel.types import ModelTurn, ToolCall, WireAgentOutput
from pdos_next.domain.preproject.category_models import KnowledgeEntry
from pdos_next.enterprise_search.indexing import project
from pdos_next.models import Artifact
from pdos_next.providers.types import ProviderUsage
from tests.agent_kernel.test_context_corrections_pg import edit, read_state, work_path
from tests.agent_kernel.test_gateway import configured_route
from tests.agent_kernel.test_run_continuation import scope
from tests.enterprise_search.test_retrieval_pg import register, session_for
from tests.preproject.test_g0 import post, request

ROOT = Path(__file__).resolve().parents[4]
CASES = {case["id"]: case for case in json.loads((
    ROOT / "docs/evaluations/xiaopai-v0/context-questions.json"
).read_text())["cases"]}
NOT_SCORED = ["answer_correctness", "citation_semantics", "real_usage_latency_cost"]


def materialized(case):
    filename = ROOT / "pdos-next/tools/xiaopai_context_admission_baseline.py"
    spec = importlib.util.spec_from_file_location("eval_v0_baseline", filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    turns = module.materialize(case)
    return turns, module.raw_measurement(case, turns)


def finish(setup, identity, summary, constraints=()):
    Bootstrap(setup.engine, ports=RuntimePorts()).store.finish(scope(setup, identity), {
        "status": "completed", "summary": summary, "result": {"context_proposals": {
            "constraints": [{"run_id": str(identity), "text": text} for text in constraints],
        }}, "questions": [], "unfinished": [],
    })


def change(setup, session_id, action, **fields):
    state = read_state(setup, session_id)
    response = setup.client.post(work_path(setup, session_id), headers=setup.headers, json={
        "expected_revision": state["revision"], "request_key": str(uuid4()),
        "action": action, **fields,
    })
    assert response.status_code == 200, response.text
    return state, response.json()


def select_context(setup, session_id, kind, refs=()):
    before = read_state(setup, session_id)
    response, _ = edit(setup, session_id, before, kind, refs)
    assert response.status_code == 200, response.text
    return before, response.json()


def knowledge(setup, definition, *, previous=None, label):
    artifact = register(setup, label, definition)
    data = {"kind": "boundary", "content": {"definition": definition},
        "source_refs": [{"type": "artifact", "id": str(artifact), "version": 1,
                         "line": 1, "quote": definition}]}
    if previous:
        data["supersedes"] = {"lineage_id": previous["lineage_id"],
                              "expected_version": previous["version"]}
    response = post(setup, request(setup, "category.knowledge.add", data))
    assert response.status_code == 200, response.text
    receipt = response.json()
    with Session(setup.admin) as session:
        row = session.scalar(select(KnowledgeEntry).where(
            KnowledgeEntry.lineage_id == UUID(receipt["subject_id"])
        ).order_by(KnowledgeEntry.version.desc()))
        value = {"source_type": "knowledge", "source_id": str(row.id),
            "lineage_id": str(row.lineage_id), "version": row.version,
            "artifact_id": str(artifact), "artifact_revision": 1,
            "receipt_id": receipt["id"], "definition": definition}
    with session_for(setup) as session:
        project(session, setup.ctx, "knowledge", UUID(value["source_id"]))
    return value


def choice(value):
    return {"source_type": value["source_type"], "source_id": value["source_id"],
            "expected_revision": value["version"]}


class ScriptedProvider:
    """Zero measured usage; real registered READs and gateway own all provenance."""

    def __init__(self, plan=(), *, summary="模型无关原生控制回放；答案质量未评分。",
                 constraints=(), history=False, extract=False):
        self.plan, self.summary, self.constraints = deque(plan), summary, list(constraints)
        self.history, self.calls = history, 0
        self.extract = extract
        self.requests, self.values, self.fragments, self.seen = [], [], {}, set()

    def close(self):
        pass

    def turn(self, route, *, system, tools, messages, output_schema, **_kwargs):
        assert in_registered_agent_graph()
        assert route.base_url == "https://synthetic-provider.test/v1"
        assert tools == disclosure(default_registry(), "main", ()) and len(tools) == 61
        assert output_schema == WireAgentOutput.model_json_schema()
        self.requests.append(deepcopy(messages))
        phase, self.calls = self.calls, self.calls + 1

        def read(name, arguments):
            return ModelTurn(calls=(ToolCall(id=f"scripted-{phase}", name=name,
                arguments=arguments),), usage=ProviderUsage(0, 0))

        for message in messages:
            if message["role"] != "tool" or message["tool_call_id"] in self.seen:
                continue
            self.seen.add(message["tool_call_id"])
            value = json.loads(message["content"])
            assert "error" not in value, value
            if value.get("format") == "json_fragment":
                parts = self.fragments.setdefault(value["result_handle"], {})
                parts[value["page"]] = value["preview"]
                if value["read_more"]:
                    return read("result.read", value["read_more"]["arguments"])
                value = json.loads("".join(parts[index] for index in sorted(parts)))
            self.values.append(value)
        if self.history:
            selected = self.history if isinstance(self.history, dict) else None
            self.history = False
            context = json.loads(messages[0]["content"])["context"]
            return read("conversation.history", selected or {
                "before": context["conversation"]["turns"][-1]["run_id"], "page_size": 25,
            })
        if self.plan:
            name, arguments = self.plan.popleft()
            return read(name, arguments)
        if self.extract:
            self.extract = False
            selected = next(value["items"] for value in reversed(self.values) if "items" in value)
            assert 1 <= len(selected) <= 8
            return read("assistant.extract", {
                "citation_ids": [item["citation_id"] for item in selected],
            })
        return ModelTurn(structured={"status": "completed", "summary": self.summary,
            "result": {"context_proposals": {"constraints": self.constraints}},
            "questions": [], "unfinished": []}, usage=ProviderUsage(0, 0))


def execute(setup, identity, goal, focus, provider):
    route = replace(configured_route(), context_window_tokens=focus + 2048 + 4000,
                    max_output_tokens=2048)
    owner = Bootstrap(setup.engine, ports=RuntimePorts(
        provider_client=provider, preload=lambda _: ()))
    owner.route_for = lambda _: route
    owner.provider_for = lambda *_: "synthetic-assistant-no-egress"
    bound = scope(setup, identity)
    # Unmetered synthetic wire-byte reservation, not a change to context focus.
    with Session(setup.admin) as session, session.begin():
        run = session.get(AgentRun, identity)
        assert run.state == "queued"
        run.token_limit = 2_000_000
    host = BoundHost(owner.store, replace(owner.adapters(), cost_required=False))
    result = AgentKernel(host, owner.registry).execute(bound, goal=goal)
    with Session(setup.admin) as session:
        run = session.get(AgentRun, identity)
        context = deepcopy(run.versions.get("work_state"))
        calls = list(session.scalars(select(AgentToolCall).where(
            AgentToolCall.run_id == identity).order_by(AgentToolCall.created_at, AgentToolCall.id)))
        budgets = [deepcopy(call.result["context_budget"]) for call in calls
                   if call.tool == "model" and call.state == "completed"]
        reads = [{"id": str(call.id), "tool": call.tool,
            "execution_binding": deepcopy(call.execution_binding),
            "result": deepcopy(call.result)} for call in calls if call.tool != "model"]
        assert len(budgets) == provider.calls
        assert run.held_tokens == run.used_tokens == 0
    for budget in budgets:
        assert budget["focus"] == focus and not budget["over_focus"]
        assert budget["window"] == focus + 2048 + 4000
    return {"run_id": str(identity), "output": result["output"], "work_state": context,
            "context_budget": budgets, "reads": reads, "provider_dispatches": provider.calls,
            "requests": provider.requests, "values": provider.values}


def assert_immutable_artifacts(setup, sources):
    with Session(setup.admin) as session:
        for item in sources:
            row = session.get(Artifact, UUID(item["artifact_id"]))
            assert row.revision == item["artifact_revision"] == 1
            assert row.content == item["definition"]


def observation(case, focus, runs, bindings, *, partial=()):
    value = {"version": "context-native-observation/v1", "case_id": case["id"],
        "f_budget_tokens": focus, "native_binding_status": "partial" if partial else "bound",
        "status": "native_control_checks_passed", "scripted_provider": True,
        "real_model_calls": 0,
        "provider_dispatches": sum(row["provider_dispatches"] for row in runs),
        "context_budget": [budget for row in runs for budget in row["context_budget"]],
        "bindings": bindings, "model_quality_score": None, "not_scored": NOT_SCORED,
        "binding_limitations": list(partial), "usage_basis": "unmeasured_scripted_zero_only"}
    folder = os.environ.get("PDOS_CONTEXT_NATIVE_OUTPUT_DIR")
    if folder:
        directory = Path(folder)
        assert directory.is_absolute() and directory.is_dir()
        target = directory / f"{case['id']}-F{focus}.json"
        with target.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, default=str)
            stream.write("\n")
    return value
