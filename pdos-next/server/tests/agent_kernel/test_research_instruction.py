"""Versioned child context and real graph bindings; no database or external calls."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from threading import Barrier, RLock
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from pdos_next.agent_kernel import research_graph
from pdos_next.agent_kernel.models import AgentEvent
from pdos_next.agent_kernel.research_graph import ResearchGraph
from pdos_next.agent_kernel.research_instruction import ResearchInstruction
from pdos_next.agent_kernel.skills import SkillCatalog
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.agent_kernel.types import ModelTurn, RunScope
from pdos_next.errors import DomainError
from pdos_next.research.types import ResearchTask
from pdos_next.service import digest


class Session:
    def __init__(self):
        self.events = {}
        self.enabled = True
        self.flushed = 0

    def scalar(self, query):
        if "max(" in str(query):
            return max((e.sequence for e in self.events.values()), default=0)
        return NS(enabled=self.enabled)

    def add(self, row):
        assert isinstance(row, AgentEvent)
        self.events[row.id] = row

    def get(self, model, identity):
        assert model is AgentEvent
        return self.events.get(identity)

    def flush(self):
        self.flushed += 1


class Store:
    def __init__(self, scope):
        self.session = Session()
        self.run = NS(id=scope.run_id, versions={"existing": "preserved"})
        self.locks = []
        self.mutex = RLock()
        self.checked = []

    @contextmanager
    def transaction(self, scope, *, lock=False):
        self.locks.append(lock)
        assert lock, "Instruction initialization/replay must lock the shared Run"
        with self.mutex:
            yield self.session, self.run

    def authority(self, session, scope):
        assert session is self.session
        self.checked.append(scope)


def fixture():
    scope = RunScope(*(uuid4() for _ in range(6)), isolation="research")
    store, catalog = Store(scope), SkillCatalog()
    instruction = ResearchInstruction(store, catalog)
    return NS(scope=scope, store=store, catalog=catalog, instruction=instruction)


def fail_code(code, callback):
    with pytest.raises(DomainError) as error:
        callback()
    assert error.value.code == code


def test_initial_capture_persists_exact_event_and_only_child_section():
    f = fixture()
    bound = f.instruction(f.scope)
    event = f.store.session.events[bound.skill.load_event_id]
    assert event.tenant_id == f.scope.tenant_id and event.run_id == f.scope.run_id
    assert event.body == {
        "type": "skill_loaded", "key": "public_research", "version": bound.skill.version,
        "digest": bound.skill.digest, "isolation": "research",
    }
    assert f.store.run.versions["existing"] == "preserved"
    assert f.store.run.versions["research_instruction"] == {
        **{k: v for k, v in bound.context().items() if k != "instruction"},
        "load_event_id": str(event.id),
    }
    assert digest(bound.instruction) == bound.instruction_digest
    assert "research.search" in bound.instruction and "research.read" in bound.instruction
    assert "category.knowledge.add" not in bound.instruction
    assert "## 示例" not in bound.instruction and "## 工具" not in bound.instruction
    assert f.store.session.flushed == 1 and f.store.locks == [True]


def test_recovery_reuses_event_without_rewriting_versions():
    f = fixture()
    bound = f.instruction(f.scope)
    versions = f.store.run.versions
    assert f.instruction(f.scope) == bound
    assert f.store.run.versions is versions
    assert len(f.store.session.events) == f.store.session.flushed == 1
    assert f.store.locks == [True, True]


def test_concurrent_children_share_one_locked_capture():
    f = fixture()
    barrier = Barrier(4)

    def capture(_):
        barrier.wait()
        return f.instruction(f.scope)

    with ThreadPoolExecutor(max_workers=4) as pool:
        bindings = list(pool.map(capture, range(4)))
    assert all(binding == bindings[0] for binding in bindings)
    assert len(f.store.session.events) == f.store.session.flushed == 1
    assert f.store.locks == [True] * 4


@pytest.mark.parametrize("isolation", ["main", "extract", "mcp"])
def test_other_isolation_cannot_capture_research_instruction(isolation):
    f = fixture()
    fail_code("FORBIDDEN_SCOPE", lambda: f.instruction(replace(f.scope, isolation=isolation)))
    assert not f.store.locks


@pytest.mark.parametrize("captured", [False, True])
def test_disabled_skill_rejected_before_first_call_and_on_recovery(captured):
    f = fixture()
    if captured:
        f.instruction(f.scope)
    f.store.session.enabled = False
    fail_code("FORBIDDEN_SCOPE", lambda: f.instruction(f.scope))
    assert len(f.store.session.events) == int(captured)


@pytest.mark.parametrize("change", ["version", "child_content", "other_content"])
def test_any_bound_skill_change_rejected(change):
    f = fixture()
    f.instruction(f.scope)
    skill = f.catalog._skills["public_research"]
    replacement = {
        "version": {"version": skill.version + "-changed"},
        "child_content": {"content": skill.content.replace("没有写工具", "只可读取")},
        "other_content": {"content": "Changed main instructions\n" + skill.content},
    }[change]
    f.catalog._skills[skill.key] = replace(skill, **replacement)
    fail_code("VERSION_CONFLICT", lambda: f.instruction(f.scope))
    assert len(f.store.session.events) == 1


@pytest.mark.parametrize("content", ["No section", "### 子任务说明\n\n## End",
                                     "### 子任务说明\na\n### 子任务说明\nb"])
def test_missing_empty_or_ambiguous_child_section_is_unavailable(content):
    f = fixture()
    skill = f.catalog._skills["public_research"]
    f.catalog._skills[skill.key] = replace(skill, content=content)
    fail_code("SOURCE_UNAVAILABLE", lambda: f.instruction(f.scope))
    assert not f.store.session.events


@pytest.mark.parametrize("change", ["missing", "tenant", "run", "isolation", "digest", "wrapped"])
def test_actual_loading_event_is_required_and_scope_exact(change):
    f = fixture()
    bound = f.instruction(f.scope)
    event = f.store.session.events[bound.skill.load_event_id]
    if change == "missing":
        f.store.session.events.clear()
    elif change in {"tenant", "run"}:
        setattr(event, change + "_id", uuid4())
    elif change == "wrapped":
        event.body = {"type": "research_child", "event_type": "skill_loaded"}
    else:
        event.body = {**event.body, change: "main" if change == "isolation" else "0" * 64}
    fail_code("FORBIDDEN_SCOPE", lambda: f.instruction(f.scope))


@pytest.mark.parametrize("previous", ["bad", {}, {"load_event_id": "bad"}])
def test_malformed_persisted_version_fails_closed(previous):
    f = fixture()
    f.store.run.versions["research_instruction"] = previous
    fail_code("VERSION_CONFLICT", lambda: f.instruction(f.scope))


class Host:
    def __init__(self):
        self.models = []
        self.events = []
        self.currents = 0
        self.cancelled = False
        self.gateway = NS(turn=self.model)

    def current(self, bound):
        self.currents += 1
        if self.cancelled:
            raise DomainError("CANCELLED_RUN", "synthetic cancellation")

    def model(self, bound, **kwargs):
        self.models.append(kwargs)
        return ModelTurn(structured={
            "status": "completed", "summary": "No findings", "result": {"rows": []},
            "questions": [], "unfinished": [],
        })

    def emit(self, bound, event):
        self.events.append(event)


def graph_fixture():
    f = fixture()
    f.host, f.saver = Host(), InMemorySaver()
    f.graph = ResearchGraph(
        f.host, instruction_for=f.instruction,
        checkpointer_factory=lambda: nullcontext(f.saver),
    )
    f.task = ResearchTask("same-task", "Read public sources")
    f.child = NS(_scope=f.scope)
    return f


def execute(f):
    return asyncio.run(f.graph(f.task, f.child))


def test_actual_graph_appends_only_child_context_and_passes_real_skill_binding_to_gateway():
    f = graph_fixture()
    assert execute(f) == []
    call = f.host.models[0]
    binding = f.instruction(f.scope)
    context = json.loads(call["messages"][0]["content"])["context"]
    assert context["research_skill"] == binding.context()
    assert call["loaded_skills"] == (binding.skill,)
    assert binding.instruction not in call["system"]
    assert {tool["name"] for tool in call["tools"]} == {
        "research.search", "research.read", "result.read",
    }
    assert "category.knowledge.add" not in json.dumps(context)
    assert all(event["type"] == "research_child" for event in f.host.events)
    assert len(f.store.session.events) == 1


def test_completed_graph_recovery_checks_instruction_without_replaying_model():
    f = graph_fixture()
    execute(f)
    before = len(f.store.checked)
    assert execute(f) == []
    assert len(f.host.models) == 1 and len(f.store.checked) > before
    f.store.session.enabled = False
    fail_code("FORBIDDEN_SCOPE", lambda: execute(f))
    assert len(f.host.models) == 1


def test_completed_graph_recovery_preserves_current_cancel_guard():
    f = graph_fixture()
    execute(f)
    f.host.cancelled = True
    fail_code("CANCELLED_RUN", lambda: execute(f))
    assert len(f.host.models) == 1


def test_legacy_checkpoint_never_claims_instruction_binding_without_actual_context():
    f = graph_fixture()
    legacy = ResearchGraph(f.host, checkpointer_factory=lambda: nullcontext(f.saver))

    def interrupted(bound, **kwargs):
        f.host.models.append(kwargs)
        raise RuntimeError("synthetic Activity interruption before provider completion")

    f.host.gateway.turn = interrupted
    with pytest.raises(RuntimeError, match="synthetic Activity interruption"):
        asyncio.run(legacy(f.task, f.child))
    assert len(f.host.models) == 1
    assert "research_skill" not in f.host.models[0]["messages"][0]["content"]
    f.host.gateway.turn = f.host.model
    fail_code("VERSION_CONFLICT", lambda: execute(f))
    assert len(f.host.models) == 1  # A rejected legacy context cannot reach the provider.


def capture_ports(monkeypatch, f):
    captured = []

    class Kernel:
        def __init__(self, ports, *args, **kwargs):
            captured.append(ports)

        def execute(self, *args, **kwargs):
            return {"output": {"status": "completed", "result": {"rows": []}}}

    monkeypatch.setattr(research_graph, "AgentKernel", Kernel)
    execute(f)
    return captured[0]


def test_child_model_rechecks_binding_and_does_not_accept_caller_loaded_skills(monkeypatch):
    f = graph_fixture()
    ports = capture_ports(monkeypatch, f)
    messages = [{"role": "user", "content": json.dumps({"context": ports.context()})}]
    ports.model(f.scope, messages=messages, loaded_skills=("untrusted",))
    assert f.host.models[-1]["loaded_skills"] == (f.instruction(f.scope).skill,)
    f.store.session.enabled = False
    fail_code("FORBIDDEN_SCOPE", lambda: ports.model(f.scope))
    assert len(f.host.models) == 1


@pytest.mark.parametrize("change", ["empty", "role", "invalid_json", "missing", "body", "digest"])
def test_model_cannot_bind_instruction_absent_or_changed_in_actual_context(monkeypatch, change):
    f = graph_fixture()
    ports = capture_ports(monkeypatch, f)
    context = ports.context()
    if change in {"body", "digest"}:
        field = "instruction" if change == "body" else "instruction_digest"
        context["research_skill"][field] = "modified"
    elif change == "missing":
        del context["research_skill"]
    messages = [{"role": "user", "content": json.dumps({"context": context})}]
    if change == "empty":
        messages = []
    elif change == "role":
        messages[0]["role"] = "assistant"
    elif change == "invalid_json":
        messages[0]["content"] = "not json"
    fail_code("VERSION_CONFLICT", lambda: ports.model(f.scope, messages=messages))
    assert not f.host.models


@pytest.mark.parametrize("method", ["prepare", "write", "receipt"])
def test_child_instruction_does_not_grant_write_ports(monkeypatch, method):
    f = graph_fixture()
    ports = capture_ports(monkeypatch, f)
    fail_code("FORBIDDEN_SCOPE", lambda: getattr(ports, method)(f.scope))
    assert not ports.enabled(f.scope, object()) and not ports.qualified(f.scope, object())


def test_read_restore_callback_rechecks_instruction_before_returning_cached_search(monkeypatch):
    f = graph_fixture()
    ports = capture_ports(monkeypatch, f)

    def restore_only(*args, restore, **kwargs):
        f.store.session.enabled = False
        return restore({"hits": [], "provider": "synthetic"})

    f.host.read_callback = restore_only
    fail_code("FORBIDDEN_SCOPE", lambda: ports.read(
        f.scope, default_registry().get("research.search"), {"query": "public"}, "intent",
    ))
