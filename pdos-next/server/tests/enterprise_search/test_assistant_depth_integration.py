"""Public start and real BoundHost/claim/settle enforce durable lookup effort."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from threading import RLock
from types import SimpleNamespace
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator

from pdos_next.agent_kernel.bindings import ModelBinding, execution_key
from pdos_next.agent_kernel.models import AgentToolCall
from pdos_next.agent_kernel.read_execution import ReadSource
from pdos_next.agent_kernel.registry import ToolRegistry
from pdos_next.agent_kernel.types import RunScope
from pdos_next.enterprise_search import assistant_depth as depth
from pdos_next.enterprise_search import assistant_ledger
from pdos_next.errors import DomainError
from pdos_next.service import Context, digest
from tests.agent_kernel.test_bound_read_host import MemorySession, make_host


class WorkerLost(BaseException):
    """A stopped worker never executes the ordinary caught-error cleanup."""


class Claims(MemorySession):
    def scalar(self, statement):
        params = statement.compile().params
        if "call_key_1" in params:
            return next((row for (kind, _), row in self.rows.items()
                         if kind is AgentToolCall and row.call_key == params["call_key_1"]), None)
        return self.rows.get((AgentToolCall, params.get("id_1")))

    def scalars(self, statement):
        params = statement.compile().params
        excluded = params["id_1"]
        rows = [row for (kind, _), row in self.rows.items() if kind is AgentToolCall
                and row.tool in depth.TOOLS and row.state in {"started", "completed"}
                and row.id != excluded]
        return SimpleNamespace(all=lambda: rows)


def host_case(*, mode="quick"):
    f = make_host()
    registry = ToolRegistry([
        replace(f.spec, name="assistant.search"), replace(f.spec, name="assistant.extract"),
    ])
    f.run.continued_from_id = uuid4() if mode == "deep" else None
    if mode is not None:
        f.run.versions[depth.KEY] = depth.starting_profile(
            "deep" if mode == "deep" else None,
            SimpleNamespace(id=f.run.continued_from_id) if f.run.continued_from_id else None,
        )
    f.run.versions["tool_definitions"] = {"main": digest(registry.definitions())}
    f.store.session = Claims(f.run, f.model)
    lock = RLock()
    f.locks, f.callbacks, f.restores = [], 0, 0

    @contextmanager
    def fence(_scope, key, *, wait=False):
        f.locks.append((key, wait))
        with lock:
            yield

    def callback(_scope, _args):
        f.callbacks += 1
        if getattr(f, "crash", False):
            raise WorkerLost("Synthetic process loss before settle")
        return {"items": []}

    def restore(_scope, _args, previous):
        f.restores += 1
        return deepcopy(previous)

    f.store.composition_lock = fence
    f.host.adapters = replace(f.host.adapters, tool_registry=registry,
        read_tools={name: callback for name in depth.TOOLS},
        read_resumes={name: lambda bound, args, **_kwargs: callback(bound, args)
                      for name in depth.TOOLS},
        read_restores={name: restore for name in depth.TOOLS})
    f.registry = registry
    return f


def request_read(f, tool="assistant.search", arguments=None):
    arguments = arguments or {"query": "漏气"}
    model = AgentToolCall(
        id=uuid4(), tenant_id=f.run.tenant_id, run_id=f.run.id, tool="model", state="completed",
        error_code=None, receipt_id=None,
        execution_binding=ModelBinding.model_validate(f.model.execution_binding).model_copy(
            update={"tool_definitions_digest": digest(f.registry.definitions())},
        ).model_dump(mode="json"),
        result={"calls": [{"id": "provider-label", "name": tool, "arguments": arguments}]},
    )
    f.store.session.rows[AgentToolCall, model.id] = model
    source = ReadSource(model_call_id=model.id, response_index=0)
    return f.registry.get(tool), deepcopy(arguments), execution_key(f.run.id, model.id, 0), source


def read(f, prepared):
    spec, arguments, intent, source = prepared
    return f.host.read(f.scope, spec, arguments, intent, source=source)


def test_real_host_fast_search_is_single_and_completed_restore_does_not_consume_more():
    f = host_case()
    original = request_read(f)
    assert read(f, original)["items"] == []
    assert read(f, original)["items"] == []
    with pytest.raises(DomainError) as failure:
        read(f, request_read(f))
    assert failure.value.reason == "MODEL_BUDGET_EXCEEDED"
    assert f.callbacks == f.restores == 1
    assert ("assistant-depth/v1", True) in f.locks
    completed = [row for (kind, _id), row in f.store.session.rows.items()
                 if kind is AgentToolCall and row.tool == "assistant.search"
                 and row.state == "completed"]
    assert len(completed) == 1


def test_interrupted_same_actual_read_claim_resumes_and_settles_one_row():
    f = host_case()
    original = request_read(f)
    f.crash = True
    with pytest.raises(WorkerLost):
        read(f, original)
    assert not f.store.released
    started_id = f.store.session.call.id
    f.crash = False
    read(f, original)
    assert f.store.session.call.id == started_id and f.store.session.call.state == "completed"
    assert f.callbacks == 2 and f.store.settled == 1


def test_legacy_no_profile_keeps_original_multi_search_contract_and_no_new_fence():
    f = host_case(mode=None)
    read(f, request_read(f))
    read(f, request_read(f))
    assert f.callbacks == 2 and all(key != "assistant-depth/v1" for key, _wait in f.locks)


def test_deep_permits_four_actual_searches_then_blocks_fifth():
    f = host_case(mode="deep")
    for _index in range(4):
        read(f, request_read(f))
    with pytest.raises(DomainError):
        read(f, request_read(f))
    assert f.callbacks == 4


def test_fast_extract_budget_is_distinct_fixed_sources_across_actual_model_claims(monkeypatch):
    f = host_case()
    ids = [str(uuid4()) for _ in range(4)]
    sources = {cid: {"source_type": "issue", "source_id": str(uuid4()),
                     "source_revision": 1, "content_hash": "a" * 64} for cid in ids}
    monkeypatch.setattr(assistant_ledger, "select_issued", lambda _s, _scope, chosen: {
        str(cid): sources[str(cid)] for cid in chosen
    })
    first = request_read(f, "assistant.extract", {"citation_ids": ids[:2]})
    read(f, first)
    read(f, request_read(f, "assistant.extract", {"citation_ids": ids[2:3]}))
    read(f, first)  # Same complete read is reauthorized, not added to the budget.
    with pytest.raises(DomainError):
        read(f, request_read(f, "assistant.extract", {"citation_ids": ids[3:]}))
    assert f.callbacks == 2 and f.restores == 1


@pytest.mark.parametrize("requested,parent_present,expected", [
    (None, False, "quick"), (None, True, "quick"), ("deep", True, "deep"),
])
def test_actual_public_start_freezes_server_profile_before_workflow_dispatch(
    monkeypatch, requested, parent_present, expected,
):
    from pdos_next.agent_kernel import api, conversation

    tenant, human, category = uuid4(), uuid4(), uuid4()
    ctx = Context(tenant, human, human, category_id=category)
    parent = SimpleNamespace(id=uuid4(), private_context=False, data_categories=["public"],
                             customer_identities=(), session_id=uuid4()) if parent_present else None
    data = api.StartInput(goal="继续核对", idempotency_key="actual-start-depth",
                          continue_from_run_id=parent.id if parent else None,
                          lookup_depth=requested)
    effective = data.model_copy(update={"session_id": parent.session_id if parent else uuid4()})
    row = SimpleNamespace(id=uuid4(), tenant_id=tenant, requester_id=human, category_id=category,
                          session_id=effective.session_id, state="queued", versions={},
                          continued_from_id=parent.id if parent else None)
    scalars = iter([None] * (3 if parent_present else 2))
    events, dispatched = [], []
    session = SimpleNamespace(execute=lambda *_args, **_kwargs: None,
                              scalar=lambda *_args: next(scalars), add=events.append)

    @contextmanager
    def transaction(*_args, **_kwargs):
        yield session

    def create(_session, _ctx, **kwargs):
        assert kwargs["continued_from_id"] == (parent.id if parent else None)
        return row

    async def dispatch(_reference):
        assert depth.mode_for(row) == expected
        dispatched.append(row.id)

    binding = SimpleNamespace(private_context=False, data_categories=("public",),
                              customer_identities=(), read_sources=[])
    monkeypatch.setattr(api, "tenant_session", transaction)
    monkeypatch.setattr(api, "create_run", create)
    monkeypatch.setattr(conversation, "prepare", lambda *_args: (effective, parent))
    ports = api.ApiPorts(writer_for=lambda *_args: uuid4(), binding_for=lambda *_args: binding,
                         start_workflow=dispatch, signal_workflow=None, cancel_workflow=None)
    router = api.router(None, context_dependency=lambda: ctx, ports=ports)
    endpoint = next(route.endpoint for route in router.routes
                    if getattr(route, "path", None) == "/v1/categories/{category_id}/agent-runs"
                    and "POST" in route.methods)
    result = asyncio.run(endpoint(data, ctx=ctx))
    assert result["run_id"] == str(row.id) and dispatched == [row.id]
    assert events[0].body["type"] == "accepted"


def test_deep_without_actual_parent_is_rejected_and_legacy_context_remains_absent():
    with pytest.raises(DomainError):
        depth.starting_profile("deep", None)
    f = host_case(mode=None)
    assert depth.context_value(f.run) is None
    f.run.versions[depth.KEY] = depth.starting_profile(None, None)
    value = depth.context_value(f.run)
    Draft202012Validator(depth.CONTEXT_SCHEMA).validate(value)
    assert value["mode"] == "quick" and value["max_search_calls"] == 1
    assert isinstance(f.scope, RunScope)


def test_concurrent_search_claims_share_one_fence_and_only_one_reaches_source_io():
    f = host_case()
    requests = [request_read(f), request_read(f)]

    def attempt(prepared):
        try:
            return read(f, prepared)
        except DomainError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        values = list(executor.map(attempt, requests))
    assert sum(isinstance(value, dict) for value in values) == 1
    assert sum(isinstance(value, DomainError) for value in values) == 1
    assert f.callbacks == 1


def test_real_host_projects_frozen_depth_into_closed_dynamic_context_only(monkeypatch):
    from pdos_next.agent_kernel import context_projection

    f = host_case()
    f.run.versions["personal_preferences_context"] = {
        "revision": 0, "source": "explicit_user_settings", "use": "personalization_only",
        "answer_language": "auto", "response_detail": "balanced", "role": None,
        "department": None, "navigation_candidates": [],
        "role_defaults": {"welcome_examples": [], "summary_sections": []},
    }
    f.host.adapters = replace(f.host.adapters, project_context=lambda *_args: {
        "goal": "核对资料", "sources": [],
    })
    values = []

    def snapshot(_store, _scope, **kwargs):
        assert not kwargs["issues"]
        assert kwargs["schema"]["additionalProperties"] is False
        values.append(kwargs["value"])
        return "synthetic-snapshot"

    monkeypatch.setattr(context_projection, "snapshot", snapshot)
    result = f.host.skill_context(f.scope, "核对资料", bindings=())
    assert result["context"]["assistant_depth"]["mode"] == "quick"
    f.run.versions.pop(depth.KEY)
    legacy = f.host.skill_context(f.scope, "核对资料", bindings=())
    assert "assistant_depth" not in legacy["context"]
    assert len(values) == 2
