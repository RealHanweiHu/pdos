"""Pure real-graph/real-host composition with ORM-shaped in-memory read receipts."""

import asyncio
import hashlib
import json
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from uuid import uuid4, uuid5

import pytest

from pdos_next.agent_kernel.execution import check_run_binding
from pdos_next.agent_kernel.host import BoundHost, KernelAdapters
from pdos_next.agent_kernel.models import AgentToolCall
from pdos_next.agent_kernel.read_execution import ReadSource
from pdos_next.agent_kernel.research_adapter import ResearchArtifacts
from pdos_next.agent_kernel.research_graph import ResearchGraph
from pdos_next.agent_kernel.research_read_ledger import page_result, restore_page
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.errors import DomainError
from pdos_next.research.service import ResearchChild
from pdos_next.research.tools import ReadInput
from pdos_next.research.types import LedgerDraft, ReadPage, ResearchTask, Snapshot
from pdos_next.service import digest
from tests.agent_kernel.research.test_research import service
from tests.agent_kernel.test_read_execution import fixture


class ReadStore:
    def __init__(self, f):
        self.f, self.calls = f, {}

    def current(self, scope):
        check_run_binding(self.f.run, scope)

    @contextmanager
    def transaction(self, scope):
        self.current(scope)
        yield self.f.session, self.f.run

    def claim(self, scope, key, tool, arguments, *, execution_binding):
        self.current(scope)
        call = self.calls.get(key)
        if call is None:
            call = AgentToolCall(
                id=uuid4(), tenant_id=scope.tenant_id, run_id=scope.run_id,
                tool=tool, call_key=key, input_digest=digest([tool, arguments]),
                execution_binding=deepcopy(execution_binding), state="started",
            )
            self.calls[key] = call
        assert call.execution_binding == execution_binding
        assert call.input_digest == digest([tool, arguments])
        return call.id, deepcopy(call.result)

    def settle(self, scope, call_id, *, result):
        self.current(scope)
        call = next(value for value in self.calls.values() if value.id == call_id)
        call.result, call.state = deepcopy(result), "completed"

    def release_call(self, *_args, **_kwargs):
        pytest.fail("Successful synthetic read must not release")

    def emit(self, *_):
        pass


def composed(tmp_path, *, with_artifacts=True):
    f = fixture("research")
    f.registry = default_registry()
    f.run.versions["tool_definitions"]["research"] = digest(f.registry.definitions("research"))
    f.model.execution_binding["tool_definitions_digest"] = (
        f.run.versions["tool_definitions"]["research"]
    )
    store = ReadStore(f)
    host = BoundHost(store, KernelAdapters(
        route_for=lambda _: f.route, project_context=lambda *_: {},
        verify_result=lambda *_: None, prepare_candidate=lambda *_: None,
        execute_command=lambda *_: None, tool_registry=f.registry,
    ))

    def turn(scope, *, messages, **_):
        tool_results = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        index = len(tool_results)
        if index == 2:
            page = tool_results[-1]
            return ModelTurn(structured={
                "status": "completed", "summary": "Synthetic", "result": {"rows": [{
                    "free_key": "pressure", "quote": "Pressure: 20 psi",
                    "snapshot_id": page["snapshot_id"], "locator": page["locator"],
                }]}, "questions": [], "unfinished": [],
            })
        name, arguments = (
            ("research.search", {"query": "pump"}) if index == 0
            else ("research.read", {"url": tool_results[-1]["hits"][0]["url"]})
        )
        call = ToolCall(id=f"native-{index}", name=name, arguments=arguments)
        identity = uuid5(scope.run_id, str(index))
        row = AgentToolCall(
            id=identity, tenant_id=scope.tenant_id, run_id=scope.run_id, tool="model",
            state="completed", error_code=None, receipt_id=None,
            execution_binding=deepcopy(f.model.execution_binding),
            result={"calls": [call.model_dump(mode="json")]},
        )
        f.session.rows[(AgentToolCall, identity)] = row
        return ModelTurn(calls=(call,), ledger_call_id=identity)

    host.gateway = NS(turn=turn)
    artifacts = ResearchArtifacts(tmp_path, current=store.current)
    graph = ResearchGraph(host, artifacts=artifacts if with_artifacts else None)
    return f, store, graph, artifacts


def test_real_graph_binds_search_and_raw_read_to_actual_model_and_replays(tmp_path):
    f, store, graph, _ = composed(tmp_path)
    task = ResearchTask("synthetic", "read pressure")
    first_service = service()
    first = ResearchChild(first_service, f.scope, task)
    rows = asyncio.run(graph(task, first))
    assert len(rows) == 1 and len(store.calls) == 2
    for call in store.calls.values():
        binding = call.execution_binding
        assert binding["read_kind"] == "ordinary/v1"
        assert binding["isolation"] == "research"
        assert binding["model_call_id"] in {
            str(uuid5(f.scope.run_id, "0")), str(uuid5(f.scope.run_id, "1")),
        }
        assert "page_chars" not in binding
    raw = next(c.result for c in store.calls.values() if c.tool == "research.read")
    assert raw["markdown"] == next(iter(first.pages.values())).markdown
    assert "execution_ref" not in raw  # Only the host's returned envelope adds authority.
    replay_service = service()
    replay = ResearchChild(replay_service, f.scope, task)
    assert asyncio.run(graph(task, replay)) == rows
    assert replay.pages == first.pages
    assert replay.searches == first.searches and replay.reads == first.reads
    assert replay_service.transport.requests == []
    assert replay_service.search_adapter.queries == []
    # Search replay restores the original URL grant; paging uses the immutable restored cache.
    page = asyncio.run(replay.read("https://maker.example/specs"))
    assert page == next(iter(first.pages.values()))
    assert replay_service.transport.requests == []


def page_fixture(tmp_path):
    f, store, _, artifacts = composed(tmp_path)
    text = "参数🌡️：20 摄氏度\n未读尾部：完整快照"
    snapshot = Snapshot(
        uuid4(), "https://maker.example/specs", "https://maker.example/specs", "参数",
        "摘要", datetime.now(UTC), text, hashlib.sha256(text.encode()).hexdigest(),
        "public-web:maker.example", "unverified_public_page",
    )
    artifacts.save_snapshot(f.scope, snapshot)
    page = ReadPage(snapshot, "chars:0:10", text[:10], 10)
    child = ResearchChild(service(), f.scope, ResearchTask("unicode", "read"))
    data = ReadInput(url=snapshot.url)
    return f, store, artifacts, page, child, data


def test_unicode_page_restores_quote_and_full_snapshot_coverage(tmp_path):
    _, store, artifacts, page, child, data = page_fixture(tmp_path)
    previous = page_result(page)
    assert restore_page(
        child, data, previous, artifacts=artifacts, current=store.current
    ) == previous
    row = child.verify(LedgerDraft(
        free_key="temperature", quote="参数🌡️：20", snapshot_id=page.snapshot.id,
        locator=page.locator,
    ))
    assert row.snapshot_id == page.snapshot.id
    assert child.unread_locations()[0].locator == f"chars:10:{len(page.snapshot.markdown)}"
    following = asyncio.run(child.read(page.snapshot.url, cursor=10))
    assert following.snapshot == page.snapshot
    assert not child._service.transport.requests


@pytest.mark.parametrize("change", ["unread_text", "metadata", "missing", "no_artifacts",
                                    "wrong_page", "wrong_url", "revoked"])
def test_restore_fails_closed_before_granting_quote_authority(tmp_path, change):
    f, store, artifacts, page, child, data = page_fixture(tmp_path)
    previous = page_result(page)
    path = artifacts._path(f.scope, page.snapshot.id)
    if change in {"unread_text", "metadata"}:
        snapshot = page.snapshot
        if change == "unread_text":
            markdown = snapshot.markdown[:10] + "篡改后续内容"
            snapshot = replace(snapshot, markdown=markdown,
                               content_hash=hashlib.sha256(markdown.encode()).hexdigest())
        else:
            snapshot = replace(snapshot, final_url="https://different.example/")
        # Even an internally self-consistent replacement fails the complete snapshot digest.
        encoded = json.loads(json.dumps(asdict(snapshot), default=str))
        payload = {"kind": "public_web_snapshot", "value": encoded}
        path.write_text(json.dumps({"payload": payload, "digest": digest(payload)}))
    elif change == "missing":
        path.unlink()
    elif change == "no_artifacts":
        artifacts = None
    elif change == "wrong_page":
        previous["markdown"] = "forged quote"
    elif change == "wrong_url":
        data = ReadInput(url="https://different.example/")
    elif change == "revoked":
        f.run.state = "cancelled"
    with pytest.raises(DomainError):
        restore_page(child, data, previous, artifacts=artifacts, current=store.current)
    assert not child.pages and not child.reads
    assert not child._service.transport.requests


def test_actual_bound_host_rejects_unbound_read_before_any_fetch(tmp_path, monkeypatch):
    f, store, graph, _ = composed(tmp_path)
    child = ResearchChild(service(), f.scope, ResearchTask("unbound", "read"))

    class ProbeKernel:
        def __init__(self, host, *_args, **_kwargs):
            self.host = host

        def execute(self, scope, **_):
            return self.host.read(scope, f.registry.get("research.search"),
                                  {"query": "pump"}, "unbound")

    monkeypatch.setattr("pdos_next.agent_kernel.research_graph.AgentKernel", ProbeKernel)
    with pytest.raises(DomainError, match="读取须绑定"):
        asyncio.run(graph(child.task, child))
    assert not store.calls and not child._service.search_adapter.queries


def test_completed_bound_read_without_artifacts_never_falls_back_to_network(tmp_path, monkeypatch):
    f, store, graph, _ = composed(tmp_path, with_artifacts=False)
    task = ResearchTask("no-artifacts", "read pressure")
    first = ResearchChild(service(), f.scope, task)
    asyncio.run(graph(task, first))
    call = next(c for c in store.calls.values() if c.tool == "research.read")
    source = ReadSource(
        model_call_id=call.execution_binding["model_call_id"], response_index=0,
    )
    replay = ResearchChild(service(), f.scope, task)

    class ProbeKernel:
        def __init__(self, host, *_args, **_kwargs):
            self.host = host

        def execute(self, scope, **_):
            return self.host.read(
                scope, f.registry.get("research.read"),
                {"url": "https://maker.example/specs"}, call.call_key, source=source,
            )

    monkeypatch.setattr("pdos_next.agent_kernel.research_graph.AgentKernel", ProbeKernel)
    with pytest.raises(DomainError, match="原运行快照文件"):
        asyncio.run(graph(task, replay))
    assert not replay.pages and not replay._service.transport.requests
    assert call.state == "completed"


def test_unbound_harness_is_not_promoted_to_execution_authority(tmp_path, monkeypatch):
    f, _, graph, _ = composed(tmp_path)
    graph.host = NS(current=lambda _: None)
    child = ResearchChild(service(), f.scope, ResearchTask("unbound", "read"))

    class ProbeKernel:
        def __init__(self, host, *_args, **_kwargs):
            self.host = host

        def execute(self, scope, **_):
            raw = self.host.read(scope, f.registry.get("research.search"),
                                 {"query": "pump"}, "unbound")
            assert "execution_ref" not in raw and "execution_binding" not in raw
            with pytest.raises(DomainError, match="实际模型账本"):
                self.host.read(scope, f.registry.get("research.search"),
                               {"query": "pump"}, "unbound", source=f.source)
            return {"output": {"status": "completed", "result": {"rows": []}}}

    monkeypatch.setattr("pdos_next.agent_kernel.research_graph.AgentKernel", ProbeKernel)
    assert asyncio.run(graph(child.task, child)) == []


def test_registered_port_dispatch_precedes_raw_fetch(tmp_path, monkeypatch):
    f, store, graph, _ = composed(tmp_path)
    child = ResearchChild(service(), f.scope, ResearchTask("registered", "read"))
    sentinel, seen = {"selected": "registered-port-dispatch-only"}, []

    def registered_read(host, actual_child, spec, arguments, intent_key, *, source):
        seen.append((host, actual_child, spec.name, arguments, intent_key, source))
        return sentinel

    graph.registered_reads = NS(read=registered_read)

    class ProbeKernel:
        def __init__(self, host, *_args, **_kwargs):
            self.host = host

        def execute(self, scope, **_):
            result = self.host.read(
                scope, f.registry.get("research.read"),
                {"url": "https://maker.example/specs"}, "dispatch-test", source=f.source,
            )
            assert result is sentinel
            return {"output": {"status": "completed", "result": {"rows": []}}}

    monkeypatch.setattr("pdos_next.agent_kernel.research_graph.AgentKernel", ProbeKernel)
    assert asyncio.run(graph(child.task, child)) == []
    assert seen == [(graph.host, child, "research.read",
                     {"url": "https://maker.example/specs"}, "dispatch-test", f.source)]
    assert not child._service.transport.requests and not store.calls


def test_registered_port_no_match_keeps_actual_raw_read_ordinary(tmp_path):
    f, store, graph, _ = composed(tmp_path)
    seen = []

    def no_match(*args, **kwargs):
        seen.append((args, kwargs))
        return None

    graph.registered_reads = NS(read=no_match)
    child = ResearchChild(service(), f.scope, ResearchTask("unregistered", "read pressure"))
    assert len(asyncio.run(graph(child.task, child))) == 1
    assert len(seen) == 1 and isinstance(seen[0][1]["source"], ReadSource)
    call = next(c for c in store.calls.values() if c.tool == "research.read")
    assert call.execution_binding["read_kind"] == "ordinary/v1"
    assert len(child._service.transport.requests) == 1


def test_registered_port_does_not_promote_pure_harness(tmp_path, monkeypatch):
    f, _, graph, _ = composed(tmp_path)
    graph.host = NS(current=lambda _: None)

    def forbidden_port(*_args, **_kwargs):
        pytest.fail("A pure unbound harness cannot select registered snapshot authority")

    graph.registered_reads = NS(read=forbidden_port)
    child = ResearchChild(service(), f.scope, ResearchTask("fake", "read"))
    child._service.register_user_message(f.scope, "https://maker.example/specs")

    class ProbeKernel:
        def __init__(self, host, *_args, **_kwargs):
            self.host = host

        def execute(self, scope, **_):
            raw = self.host.read(scope, f.registry.get("research.read"),
                                 {"url": "https://maker.example/specs"}, "unbound")
            assert "execution_ref" not in raw and "execution_binding" not in raw
            return {"output": {"status": "completed", "result": {"rows": []}}}

    monkeypatch.setattr("pdos_next.agent_kernel.research_graph.AgentKernel", ProbeKernel)
    assert asyncio.run(graph(child.task, child)) == []
    assert len(child._service.transport.requests) == 1
