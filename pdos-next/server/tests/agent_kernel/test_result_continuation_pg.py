"""Ordinary-role PostgreSQL provenance, real source guards, synthetic model ledgers."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from pdos_agent_runtime.graph import registered_graph_context
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bindings import ModelBinding, execution_key
from pdos_next.agent_kernel.context_budget import estimate_tokens
from pdos_next.agent_kernel.domain_reads import DomainReads
from pdos_next.agent_kernel.gateway import AgentGateway
from pdos_next.agent_kernel.host import BoundHost, KernelAdapters
from pdos_next.agent_kernel.models import AgentToolCall
from pdos_next.agent_kernel.persistence import KernelStore
from pdos_next.agent_kernel.read_execution import ReadSource
from pdos_next.agent_kernel.result_continuation import serialized
from pdos_next.contracts import Command
from pdos_next.errors import DomainError
from pdos_next.models import Artifact
from pdos_next.service import digest, execute
from tests.agent_kernel.test_domain_adapter_transactions import fixture
from tests.agent_kernel.test_gateway import configured_route
from tests.agent_kernel.test_transactions import human_session, run


def model_call(store, scope, binding, tool, arguments):
    identity, _ = store.claim(
        scope, "synthetic-continuation-model:" + str(uuid4()), "model", {"synthetic": True},
        execution_binding=binding.model_dump(mode="json"),
    )
    store.settle(scope, identity, result={"calls": [{"name": tool, "arguments": arguments}]})
    return ReadSource(model_call_id=identity, response_index=0)


def registered_read(host, scope, tool, arguments, source):
    return host.read(
        scope, host.adapters.tool_registry.get(tool), arguments,
        execution_key(scope.run_id, source.model_call_id, source.response_index), source=source,
    )


def test_real_long_source_page_replay_rechecks_withdrawal_and_isolation(setup, monkeypatch):
    with human_session(setup) as session:
        receipt = execute(session, setup.ctx, Command(
            command_id=uuid4(), idempotency_key=str(uuid4()), category_id=setup.category,
            operation="evidence.artifact.register", expected_revision=1,
            payload={"title": "长合成资料", "source_label": "离线合成",
                     "content": "Synthetic exact source\n" + "合成续读资料" * 4_000,
                     "visibility": "category"},
        ))
    identity = UUID(receipt["subject_id"])
    f = fixture(setup, artifact_id=identity)
    store = KernelStore(setup.engine)
    child = f.scope.child("extract", artifact_ids={identity})
    binding = ModelBinding(
        model_version=f.route.version, model_route_digest=f.route.digest,
        tool_definitions_digest=digest(f.registry.definitions("extract")),
        prompt_digest=digest("fixed synthetic extraction"), isolation="extract", cancel_epoch=0,
    )
    with store.transaction(child, lock=True) as (_, current):
        current.versions = {**current.versions,
            "tool_definitions": {**current.versions["tool_definitions"],
                                 "extract": binding.tool_definitions_digest},
            "prompt_prefixes": {**current.versions["prompt_prefixes"],
                                "extract": binding.prompt_digest}}
    reads = DomainReads(store, f.adapter)
    host = BoundHost(store, KernelAdapters(
        route_for=lambda _: f.route, project_context=lambda *_: {},
        verify_result=lambda *args: args[1], prepare_candidate=lambda *_: None,
        execute_command=lambda *_: None, read_tools=reads.handlers(), tool_registry=f.registry,
    ))
    arguments = {"artifact_version_id": str(identity)}
    source = model_call(store, child, binding, "evidence.artifact.read", arguments)
    full = registered_read(host, child, "evidence.artifact.read", arguments, source)
    preview = host.tool_message(child, f.registry.get("evidence.artifact.read"), full)
    assert preview["truncated"] and preview["total_pages"] > 1
    assert estimate_tokens(serialized(preview)) <= 4_000
    page_args = {"handle": preview["result_handle"], "page": 2}
    page_source = model_call(store, child, binding, "result.read", page_args)
    settle = store.settle
    class WorkerInterrupted(BaseException):
        pass
    def stop_before_settle(bound, call_id, **kwargs):
        with store.transaction(bound) as (session, _):
            if session.get(AgentToolCall, call_id).tool == "result.read":
                raise WorkerInterrupted()
        return settle(bound, call_id, **kwargs)
    monkeypatch.setattr(store, "settle", stop_before_settle)
    with pytest.raises(WorkerInterrupted):
        registered_read(host, child, "result.read", page_args, page_source)
    monkeypatch.setattr(store, "settle", settle)
    # Both workers use the exact durable model response/intent. The advisory
    # fence waits, then each worker revalidates the source before returning.
    with ThreadPoolExecutor(max_workers=2) as executor:
        concurrent = [executor.submit(
            registered_read, host, child, "result.read", page_args, page_source,
        ) for _ in range(2)]
        second, replayed = [future.result() for future in concurrent]
    assert replayed == second
    assert second["page"] == 2 and estimate_tokens(serialized(second)) <= 4_000
    assert registered_read(host, child, "result.read", page_args, page_source) == second
    with store.transaction(child) as (session, current):
        original = session.get(AgentToolCall, UUID(full["execution_ref"]["call_id"]))
        assert original.result == {
            key: value for key, value in full.items() if key != "execution_ref"
        }
        assert session.scalar(select(func.count()).select_from(AgentToolCall).where(
            AgentToolCall.run_id == current.id, AgentToolCall.tool == "result.read")) == 1
    from pdos_next.agent_kernel.result_continuation import ResultReadInput

    with pytest.raises(DomainError) as main_denied:
        host.continue_result(f.scope, ResultReadInput.model_validate(page_args))
    assert main_denied.value.code == "FORBIDDEN_SCOPE"
    with Session(setup.admin) as session, session.begin():
        session.get(Artifact, identity).status = "withdrawn"
    with pytest.raises(DomainError) as withdrawn:
        registered_read(host, child, "result.read", page_args, page_source)
    assert withdrawn.value.code in {"FORBIDDEN_SCOPE", "SOURCE_UNAVAILABLE"}


def test_context_incomplete_has_zero_model_ledger_and_zero_reserved_budget(setup):
    store, scope = run(setup)
    route = replace(configured_route(), context_window_tokens=8_192, max_output_tokens=1_024)
    gateway = AgentGateway(store, route_for=lambda _: route, cost_required=False, client=object())
    with registered_graph_context("xiaopai"), pytest.raises(DomainError) as error:
        gateway.turn(scope, system="fixed", messages=[{
            "role": "user", "content": "必需问题" * 4_000,
        }], tools=[], output_schema={})
    assert error.value.reason == "CONTEXT_INCOMPLETE"
    assert error.value.detail["missing"][1]["field"] == "current_question"
    with store.transaction(scope) as (session, current):
        assert current.held_tokens == current.used_tokens == 0
        assert session.scalar(select(func.count()).select_from(AgentToolCall).where(
            AgentToolCall.run_id == current.id)) == 0


def test_reduced_context_keeps_omitted_fields_and_run_frozen_preferences(setup, monkeypatch):
    from pdos_next.agent_kernel.context_projection import check_messages
    from pdos_next.database import tenant_session
    from pdos_next.personal_preference_schemas import Preferences, PreferenceSave
    from pdos_next.personal_preferences import save

    monkeypatch.setenv("PDOS_ENVIRONMENT", "production")
    f = fixture(setup)
    store = KernelStore(setup.engine)
    historical_id = str(uuid4())
    def project_context(bound, goal, fields):
        return {
            "goal": goal, "sources": [],
            "category": {"id": str(bound.category_id), "name": "合成", "purpose": "合成",
                         "unplanned_field": "PRIVATE OMITTED BODY"},
            "conversation": {
                "session_id": str(bound.session_id), "root_goal": "原用户问题",
                "root_run_id": historical_id, "turns": [{
                    "run_id": historical_id, "goal": "用户原话不得缩减", "status": "completed",
                    "historical_outcome": {"summary": "合成历史回答" * 1_000,
                                           "unfinished": [], "research": []},
                    "outcome_state": "current", "sources": [], "original_record": {
                        "run_id": historical_id, "session_id": str(bound.session_id),
                    },
                }], "next_before": None, "fact_policy": "历史记录，不作当前事实",
            },
        }
    host = BoundHost(store, KernelAdapters(
        route_for=lambda _: configured_route(), project_context=project_context,
        verify_result=lambda *args: args[1], prepare_candidate=lambda *_: None,
        execute_command=lambda *_: None, tool_registry=f.registry,
    ))
    projected = host.skill_context(f.scope, "保留用户问题", bindings=())
    frozen = projected["context"]["personal_preferences"]
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                        requester_id=setup.human) as session:
        save(session, replace(setup.ctx, category_id=None), PreferenceSave(
            expected_revision=0, preferences=Preferences(answer_language="en"),
        ))
    assert host.skill_context(f.scope, "保留用户问题", bindings=()) == projected
    host.context_guard(f.scope)  # A changed explicit preference does not revoke a frozen Run.
    original = [{"role": "user", "content": json.dumps({"goal": "保留用户问题", **projected})}]
    check_messages(store, f.scope, original, ())
    reduced, budget = host.admit_context(
        f.scope, route=replace(configured_route(), context_window_tokens=8_192,
                               max_output_tokens=1_024),
        system="fixed", tools=[], messages=original, output_schema={}, loaded_skills=(),
    )
    envelope = json.loads(reduced[0]["content"])
    assert budget["reductions"] and envelope["context_ref"] != projected["context_ref"]
    assert envelope["omitted_fields"] == projected["omitted_fields"]
    assert envelope["omitted_fields"] == ["/category/unplanned_field"]
    assert envelope["context"]["personal_preferences"] == frozen
    assert envelope["context"]["conversation"]["turns"][0]["goal"] == "用户原话不得缩减"
    assert "PRIVATE OMITTED BODY" not in str(envelope)
    check_messages(store, f.scope, reduced, ())


def test_actual_extract_child_reads_fragments_before_returning_verified_rows(setup):
    from types import SimpleNamespace

    from pdos_next.agent_kernel.extract_graph import ExtractGraph
    from pdos_next.agent_kernel.extract_read_ledger import ExtractReadLedger
    from pdos_next.agent_kernel.extract_sources import seal_for
    from pdos_next.agent_kernel.tools import default_registry
    from pdos_next.agent_kernel.types import ModelTurn, ToolCall
    from pdos_next.providers.types import ProviderUsage
    from pdos_next.service import Context
    from tests.agent_kernel.test_extract_dispatch import task

    with human_session(setup) as session:
        receipt = execute(session, setup.ctx, Command(
            command_id=uuid4(), idempotency_key=str(uuid4()), category_id=setup.category,
            operation="evidence.artifact.register", expected_revision=1,
            payload={"title": "隔离图长合成资料", "source_label": "离线合成",
                     "content": "Synthetic exact source\n" + "合成续读资料" * 1_000,
                     "visibility": "category"},
        ))
    identity = UUID(receipt["subject_id"])
    store, scope = run(setup, read_sources=[{
        "artifact_id": str(identity), "expected_revision": 1, "product_id": None,
    }], data_categories=("internal",), token_limit=1_000_000)
    child = scope.child("extract", artifact_ids={identity})
    def context(bound):
        return Context(bound.tenant_id, bound.writer_id, bound.requester_id,
                       category_id=bound.category_id)
    reads = DomainReads(store, SimpleNamespace(context=context))
    with store.transaction(child) as (session, _):
        seal, _source = seal_for(session, context(child), None, identity, 1)

    class FragmentClient:
        def __init__(self):
            self.calls, self.pages = 0, None

        def turn(self, route, **kwargs):
            self.calls += 1
            assert {tool["name"] for tool in kwargs["tools"]} == {
                "evidence.artifact.read", "result.read",
            }
            values = [json.loads(message["content"]) for message in kwargs["messages"]
                      if message["role"] == "tool"]
            if not values:
                call = ToolCall(id="original", name="evidence.artifact.read", arguments={
                    "artifact_version_id": str(identity),
                })
            elif values[-1].get("read_more"):
                self.pages = values[-1]["total_pages"]
                next_page = values[-1]["read_more"]
                call = ToolCall(id="fragment", name=next_page["tool"],
                                arguments=next_page["arguments"])
            else:
                full = json.loads("".join(value["preview"] for value in values))
                assert full["artifact_version_id"] == str(identity)
                return ModelTurn(usage=ProviderUsage(10, 2), structured={
                    "status": "completed", "summary": "合成核对", "questions": [], "unfinished": [],
                    "result": {"rows": [{"artifact_version_id": str(identity), "locator": "line:1",
                                         "quote": "Synthetic exact source", "kind": "functional",
                                         "statement": "合成需求陈述", "missing": []}]},
                })
            return ModelTurn(calls=(call,), usage=ProviderUsage(10, 2))

    client = FragmentClient()
    host = BoundHost(store, KernelAdapters(
        route_for=lambda _: replace(configured_route(), context_window_tokens=200_000),
        provider_for=lambda *_: "synthetic-result-child-no-egress", provider_client=client,
        cost_required=False, project_context=lambda *_: {}, verify_result=lambda *args: args[1],
        prepare_candidate=lambda *_: None, execute_command=lambda *_: None,
        read_tools=reads.handlers(), tool_registry=default_registry(),
    ))
    ledger = ExtractReadLedger([seal])
    rows, rejected = ExtractGraph(
        host, artifact_read=lambda bound, arguments: reads.call(
            bound, arguments, name="evidence.artifact.read",
        ),
    )(child, seal, task(), ledger)
    assert len(rows) == 1 and not rejected and client.pages >= 2
    assert rows[0]["quote"] == "Synthetic exact source"
    assert ledger.coverage(str(identity))["parsed_text"]["fully_read"]
    assert client.calls == client.pages + 1
    with store.transaction(child) as (session, current):
        count = session.scalar(select(func.count()).select_from(AgentToolCall).where(
            AgentToolCall.run_id == current.id, AgentToolCall.tool == "result.read"))
        assert count == client.pages - 1
