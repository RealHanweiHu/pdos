"""Actual qualified factory, SQL read handlers and synthetic multi-turn provider."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import NoReturn
from uuid import UUID, uuid4

import httpx2
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.ai import runtime_factory
from app.ai.budget_adoption import (
    AGENT_METER_DIGEST_KEY,
    AGENT_METER_PATH_KEY,
    AGENT_MODE_KEY,
    AGENT_PROFILE_KEY,
)
from app.ai.embeddings import EmbeddingResult
from app.ai.executor import (
    AgentAssessment,
    AgentLoopStep,
    GatewayAgentModelInvoker,
    LoopToolRequest,
)
from app.ai.gateway import GatewayInvocation, GatewayResult
from app.ai.lease_heartbeat import AgentLeaseLostError
from app.ai.loop_policy import (
    LOOP_POLICY_PATH,
    LOOP_POLICY_SHA,
    LoopBinding,
    LoopQualification,
    configured_loop_binding,
    loop_contract_digest,
)
from app.ai.model_catalog import ProviderName
from app.ai.run_store import ClaimedAgentRun
from app.ai.runtime_contract import FrozenRunContext
from app.ai.tools import ToolPage
from app.db.schema import tables
from app.domain.model_governance import ModelGovernanceSnapshot
from app.worker.dispatcher import AgentDispatcher
from tests.migration_fixtures import rollback_migration_operations
from tests.test_agent_checkpoints import EventScope, expire, scope_id
from tests.test_agent_database_security import (
    FakeEmbeddingGateway,
    seed_verified_memory,
)
from tests.test_agent_database_security import (
    secured_agent_database_url as secured_agent_database_url,
)
from tests.test_agent_dispatcher import append_event
from tests.test_event_budget_adoption import event_scope as event_scope
from tests.test_input_metering import publication
from tests.test_model_budget_controller import evidence, response, rows
from tests.test_model_gateway import qualification
from tests.test_tool_observation_receipts import row_number

LoopSetup = tuple[
    Engine,
    Engine,
    Engine,
    dict[str, UUID | int],
    dict[str, str],
    list[httpx2.Request],
    list[dict[str, object] | str],
]


def final(ids: dict[str, UUID | int]) -> dict[str, object]:
    return dict(
        action="final",
        tool=None,
        assessment=dict(
            disposition="human_review_candidate",
            candidate_type="risk_suggestion",
            summary="Review observed evidence.",
            proposed_payload=dict(title="Evidence risk", likelihood=3, impact=4),
            evidence_event_ids=[ids["event_a"]],
            confidence=0.8,
        ),
    )


def tool(name: str = "get_recent_events", **args: object) -> dict[str, object]:
    return dict(action="tool", tool=dict(name=name, **args), assessment=None)


@pytest.fixture
def loop_setup(
    event_scope: EventScope,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> LoopSetup:
    owner, worker, agent, ids = event_scope
    window_tokens = getattr(request, "param", 8192)
    assert isinstance(window_tokens, int)
    path, _, digest = publication(tmp_path, qualified_input_limit=6000, window_tokens=window_tokens)
    document = LoopQualification(
        version="agent-read-loop-qualification.v1",
        status="passed",
        runtime_digest=loop_contract_digest(),
        provider=ProviderName.MINIMAX,
        model="MiniMax-M2.7",
        suite_version="synthetic-loop-test.v1",
        suite_digest="a" * 64,
        evidence_ref="synthetic fixture; not a real model qualification",
        approved_by="test fixture",
    )
    body = document.model_dump_json().encode()
    loop_path = tmp_path / "synthetic-loop-qualification.json"
    loop_path.write_bytes(body)
    binding = LoopBinding(qualification_sha256=sha256(body).hexdigest(), qualification=document)
    AgentDispatcher(worker, budget_profile_key="short", loop_binding=binding).dispatch_tenant(
        tenant_id=scope_id(ids, "tenant_a")
    )
    with worker.begin() as c:
        c.execute(
            tables.agent_dispatcher_cursors.insert().values(
                id=uuid4(),
                tenant_id=ids["tenant_b"],
                consumer_key="agent_dispatcher_v1",
                last_event_row_id=ids["event_b"],
            )
        )
    AgentDispatcher(worker).seal_due_runs()
    replies: list[dict[str, object] | str] = [tool(), final(ids)]
    calls: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return response(json.dumps(replies[min(len(calls) - 1, len(replies) - 1)]))

    original = httpx2.Client
    monkeypatch.setattr(
        httpx2,
        "Client",
        lambda **kw: original(transport=httpx2.MockTransport(respond), **kw),
    )
    monkeypatch.setattr(
        runtime_factory, "load_golden_qualifications", lambda *a, **kw: [qualification()]
    )
    env = dict(
        PDOS_AGENT_DATABASE_URL=agent.url.render_as_string(hide_password=False),
        PDOS_LLM_PROVIDER="minimax",
        PDOS_LLM_BASE_URL="https://fake-openai.local/v1",
        PDOS_LLM_API_KEY="test-only",
        PDOS_LLM_MODEL="MiniMax-M2.7",
    )
    env.update(
        {
            AGENT_MODE_KEY: "budgeted",
            AGENT_PROFILE_KEY: "short",
            AGENT_METER_PATH_KEY: str(path),
            AGENT_METER_DIGEST_KEY: digest,
            LOOP_POLICY_PATH: str(loop_path),
            LOOP_POLICY_SHA: sha256(body).hexdigest(),
        }
    )
    return owner, worker, agent, ids, env, calls, replies


def test_actual_loop_executes_requested_page_then_uses_observation_to_finish(
    loop_setup: LoopSetup,
) -> None:
    owner, _, _, ids, env, calls, replies = loop_setup
    with owner.begin() as c:
        for _ in range(25):
            append_event(
                c,
                tenant_id=scope_id(ids, "tenant_a"),
                project_id=scope_id(ids, "project_a"),
                event_type="ISSUE_CREATED",
                occurred_at=datetime.now(UTC),
            )
    event_ids = sorted(
        row_number(r, "id")
        for r in rows(owner, tables.events)
        if r["tenant_id"] == ids["tenant_a"] and r["project_id"] == ids["project_a"]
    )
    replies[0] = tool(after_id=event_ids[19])
    with runtime_factory.configured_agent_runtime(env) as runtime:
        result = runtime.executor.execute_next()
    assert result.status == "succeeded", result
    assert len(calls) == 2 and result.finding_id is not None
    bodies = [json.loads(c.content) for c in calls]
    assert bodies[0]["messages"][0] == bodies[1]["messages"][0]
    assert "web_fetch" not in bodies[0]["messages"][0]["content"]
    contexts = [
        json.loads(b["messages"][1]["content"].split("PDOS_CONTEXT_JSON\n")[1]) for b in bodies
    ]
    assert contexts[1]["loop"] == {"step": 1, "step_limit": 3}
    assert contexts[1]["tool_observations"][-1]["request"]["after_id"] == event_ids[19]
    assert any(r["reference_id"] == f"event:{event_ids[-1]}" for r in contexts[1]["references"])
    observations = sorted(
        rows(owner, tables.agent_tool_observations), key=lambda r: row_number(r, "sequence")
    )
    assert len(observations) == 5
    assert evidence(observations[-1]["input_body"])["after_id"] == event_ids[19]
    assert evidence(observations[-1]["metadata"])["status"] == "completed"
    traces = rows(owner, tables.model_invocations)
    assert len({t["budget_call_id"] for t in traces}) == 2
    assert len(rows(owner, tables.agent_context_receipts)) == 2
    assert len(rows(owner, tables.agent_context_observations)) == 4 + 5
    assert len(rows(owner, tables.budget_lineages)) == 1


def test_last_model_step_does_not_dispatch_a_tool_that_cannot_be_followed(
    loop_setup: LoopSetup,
) -> None:
    owner, _, _, _, env, calls, replies = loop_setup
    replies[:] = [tool()]
    with runtime_factory.configured_agent_runtime(env) as runtime:
        result = runtime.executor.execute_next()
    assert result.status == "degraded" and result.error_code == "AGENT_LOOP_MODEL_LIMIT", result
    assert len(calls) == 3 and len(rows(owner, tables.agent_tool_intents)) == 6
    assert rows(owner, tables.findings) == []


@pytest.mark.parametrize("bad", ["business_write", "wrong_agent", "injected_project"])
def test_model_cannot_expand_tool_or_project_authority(loop_setup: LoopSetup, bad: str) -> None:
    owner, _, _, ids, env, calls, replies = loop_setup
    if bad == "business_write":
        replies[:] = [tool("create_risk")]
    elif bad == "wrong_agent":
        replies[:] = [tool("get_quality_evidence")]
    else:
        replies[:] = [tool(project_id=str(ids["project_b"]))]
    with runtime_factory.configured_agent_runtime(env) as runtime:
        result = runtime.executor.execute_next()
    assert result.status in {"failed", "degraded"}
    assert len(calls) <= 3 and len(rows(owner, tables.agent_tool_intents)) == 4
    assert rows(owner, tables.findings) == []
    if bad == "wrong_agent":
        assert result.error_code == "AGENT_LOOP_TOOL_NOT_ALLOWED"


def test_missing_matching_publication_stops_frozen_loop_before_tools(loop_setup: LoopSetup) -> None:
    owner, _, _, _, env, calls, _ = loop_setup
    env.pop(LOOP_POLICY_PATH)
    env.pop(LOOP_POLICY_SHA)
    with runtime_factory.configured_agent_runtime(env) as runtime:
        result = runtime.executor.execute_next()
    assert result.error_code == "AGENT_LOOP_BINDING_MISMATCH"
    assert rows(owner, tables.agent_tool_intents) == [] and calls == []


def test_model_selection_change_between_steps_prevents_second_model_call(
    loop_setup: LoopSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, _, _, _, env, calls, _ = loop_setup
    with runtime_factory.configured_agent_runtime(env) as runtime:
        invoker = runtime.executor._model_invoker
        assert isinstance(invoker, GatewayAgentModelInvoker)
        gateway = invoker._gateway
        get = gateway._governance.get

        def changed(*, tenant_id: UUID, now: datetime | None = None) -> ModelGovernanceSnapshot:
            snapshot = get(tenant_id=tenant_id, now=now)
            return replace(snapshot, selection=None) if calls else snapshot

        monkeypatch.setattr(gateway._governance, "get", changed)
        result = runtime.executor.execute_next()
    assert result.error_code == "AGENT_LOOP_MODEL_BINDING_CHANGED"
    assert len(calls) == 1 and rows(owner, tables.findings) == []


def test_loop_checkpoint_recovery_reuses_final_result_and_checks_additional_reads(
    loop_setup: LoopSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, worker, _, _, env, calls, _ = loop_setup
    with runtime_factory.configured_agent_runtime(env) as runtime:

        def crash(
            *,
            claim: ClaimedAgentRun,
            context: FrozenRunContext,
            result: GatewayResult[AgentAssessment],
            created_at: datetime,
        ) -> NoReturn:
            expire(owner, claim.id)
            raise AgentLeaseLostError("synthetic after final result")

        monkeypatch.setattr(runtime.executor, "_create_finding", crash)
        assert runtime.executor.execute_next().error_code == "AGENT_RUN_LEASE_LOST"
    assert len(calls) == 2
    before = rows(owner, tables.agent_tool_intents)
    assert AgentDispatcher(worker).dispatch_once().recovered_run_count == 1
    with runtime_factory.configured_agent_runtime(env) as runtime:
        assert runtime.executor.execute_next().status == "succeeded"
    assert len(calls) == 2 and rows(owner, tables.agent_tool_intents) == before


def test_loop_binding_is_immutable_scoped_and_blocks_history_downgrade(
    loop_setup: LoopSetup,
) -> None:
    owner, _, agent, _, _, _, _ = loop_setup
    row = rows(owner, tables.agent_runs)[0]
    assert evidence(row["loop_binding"])["mode"] == "bounded_tools.v1"
    with pytest.raises(DBAPIError, match="immutable"), owner.begin() as c:
        c.execute(tables.agent_runs.update().values(loop_binding=None))
    with pytest.raises(DBAPIError, match="lease"), agent.begin() as c:
        c.execute(text("SELECT cehub_ai.read_agent_loop_binding()"))
    with (
        pytest.raises(DBAPIError, match="persistent event loop binding history"),
        rollback_migration_operations(owner),
    ):
        import_module("migrations.versions.0078_event_loop_binding").downgrade()


@pytest.mark.parametrize("change", ["digest", "runtime", "missing_pair", "failed"])
def test_qualification_must_be_exact_passed_operator_publication(
    loop_setup: LoopSetup, change: str
) -> None:
    _, _, _, _, env, _, _ = loop_setup
    from pathlib import Path

    path = Path(env[LOOP_POLICY_PATH])
    if change == "missing_pair":
        env.pop(LOOP_POLICY_SHA)
    elif change == "digest":
        env[LOOP_POLICY_SHA] = "0" * 64
    else:
        body = json.loads(path.read_text())
        body["status" if change == "failed" else "runtime_digest"] = (
            "failed" if change == "failed" else "0" * 64
        )
        path.write_text(json.dumps(body))
        env[LOOP_POLICY_SHA] = sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        configured_loop_binding(env)


def test_request_schema_rejects_wrong_cursor_and_conflicting_actions() -> None:
    with pytest.raises(ValueError):
        LoopToolRequest(name="get_recent_events", offset=2)
    with pytest.raises(ValueError):
        LoopToolRequest(name="search_memory", query="q", after_id=1)
    with pytest.raises(ValueError):
        AgentLoopStep(action="tool", tool=None, assessment=None)


def test_multiple_requests_share_budget_and_unavailable_memory_is_visible(
    loop_setup: LoopSetup,
) -> None:
    owner, _, _, ids, env, calls, replies = loop_setup
    replies[:] = [tool(), tool("search_memory", query="focused question"), final(ids)]
    with runtime_factory.configured_agent_runtime(env) as runtime:
        result = runtime.executor.execute_next()
    assert result.status == "succeeded", result
    assert len(calls) == 3 and len(rows(owner, tables.agent_tool_intents)) == 6
    last = json.loads(calls[-1].content)
    context = json.loads(last["messages"][1]["content"].split("PDOS_CONTEXT_JSON\n")[1])
    observation = context["tool_observations"][-1]
    assert observation["status"] == "unavailable" and observation["total_count"] is None
    assert observation["request"]["query"] == "focused question"


def test_model_selected_tool_cannot_bypass_original_tool_quota(
    loop_setup: LoopSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, _, _, _, env, calls, _ = loop_setup
    with runtime_factory.configured_agent_runtime(env) as runtime:
        invoker = runtime.executor._model_invoker
        assert isinstance(invoker, GatewayAgentModelInvoker)
        decide = invoker.decide

        def consume(invocation: GatewayInvocation) -> GatewayResult[AgentLoopStep]:
            port = runtime.executor._observations
            assert port is not None
            for i in range(4):
                port._call(
                    "SELECT cehub_ai.prepare_agent_tool_call(:call,:key,:tool,:args)",
                    call=uuid4(),
                    key=f"reserved.{i}",
                    tool="get_project_context",
                    args=json.dumps({"project_id": str(invocation.project_id)}),
                )
            return decide(invocation)

        monkeypatch.setattr(runtime.executor._model_invoker, "decide", consume)
        result = runtime.executor.execute_next()
    assert result.error_code == "BUDGET_TOOL_CALL_COUNT_EXHAUSTED"
    assert len(calls) == 1 and len(rows(owner, tables.agent_tool_dispatches)) == 4


def test_requested_handler_failure_records_observation_without_another_model(
    loop_setup: LoopSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ai.tools import AgentReadTools

    owner, _, _, _, env, calls, _ = loop_setup
    read = AgentReadTools.get_recent_events
    count = 0

    def fail_second(
        self: AgentReadTools, *, project_id: UUID, after_id: int = 0, limit: int = 20
    ) -> ToolPage:
        nonlocal count
        count += 1
        if count == 2:
            raise ValueError("synthetic handler failure")
        return read(self, project_id=project_id, after_id=after_id, limit=limit)

    monkeypatch.setattr(AgentReadTools, "get_recent_events", fail_second)
    with runtime_factory.configured_agent_runtime(env) as runtime:
        result = runtime.executor.execute_next()
    assert result.error_code == "TOOL_INPUT_INVALID" and len(calls) == 1
    last = max(rows(owner, tables.agent_tool_observations), key=lambda r: row_number(r, "sequence"))
    assert evidence(last["metadata"])["status"] == "failed" and rows(owner, tables.findings) == []


@pytest.mark.parametrize("withdrawn", [False, True])
@pytest.mark.parametrize("loop_setup", [16384], indirect=True)
def test_offset_memory_page_and_recovery_check_every_consumed_source(
    loop_setup: LoopSetup, monkeypatch: pytest.MonkeyPatch, withdrawn: bool
) -> None:
    owner, worker, _, ids, env, calls, replies = loop_setup
    # Twenty-five independently reviewed memories also emit their real lifecycle
    # events. Qualify a larger synthetic window for this recovery scenario while
    # retaining the production short profile and its output/tool/safety reserves.
    for i in range(25):
        seed_verified_memory(
            owner,
            tenant_id=scope_id(ids, "tenant_a"),
            project_id=scope_id(ids, "project_a"),
            suffix=f"a{i}",
        )
    replies[:] = [tool("search_memory", query="focused evidence", offset=20), final(ids)]
    embeds: list[str] = []

    class CountingEmbedding(FakeEmbeddingGateway):
        def embed(self, value: str) -> EmbeddingResult:
            embeds.append(value)
            return super().embed(value)

    with runtime_factory.configured_agent_runtime(env) as runtime:
        runtime.executor._embedding_gateway = CountingEmbedding()

        def crash(
            *,
            claim: ClaimedAgentRun,
            context: FrozenRunContext,
            result: GatewayResult[AgentAssessment],
            created_at: datetime,
        ) -> NoReturn:
            expire(owner, claim.id)
            raise AgentLeaseLostError("synthetic after loop result")

        monkeypatch.setattr(runtime.executor, "_create_finding", crash)
        result = runtime.executor.execute_next()
    assert result.error_code == "AGENT_RUN_LEASE_LOST", result
    last = max(rows(owner, tables.agent_tool_observations), key=lambda r: row_number(r, "sequence"))
    metadata = evidence(last["metadata"])
    output = evidence(last["output_body"])
    assert metadata["shown_count"] == metadata["total_count"] == 5
    assert output["total_count"] == 25 and not metadata["truncated"]
    if withdrawn:
        items = output["items"]
        assert isinstance(items, list)
        with owner.begin() as c:
            c.execute(
                tables.memories.update()
                .where(tables.memories.c.id == evidence(items[-1])["memory_id"])
                .values(status="draft", verified_by_user_id=None, verified_at=None)
            )
    assert AgentDispatcher(worker).dispatch_once().recovered_run_count == 1
    with runtime_factory.configured_agent_runtime(env) as runtime:
        runtime.executor._embedding_gateway = CountingEmbedding()
        result = runtime.executor.execute_next()
    assert len(calls) == 2 and len(embeds) == 2, (result, len(calls), len(embeds))
    if withdrawn:
        assert result.error_code == "AGENT_CHECKPOINT_SOURCES_CHANGED"
    else:
        assert result.status == "succeeded", result


def test_configured_loop_does_not_convert_an_unbound_fixed_pipeline_run(
    loop_setup: LoopSetup,
) -> None:
    owner, _, _, ids, env, calls, replies = loop_setup
    with runtime_factory.configured_agent_runtime(env) as runtime:
        assert runtime.executor.execute_next().status == "succeeded"
    old = dict(
        rows(owner, tables.agent_runs)[0],
        id=uuid4(),
        status="debouncing",
        loop_binding=None,
        execution_bundle=None,
        started_at=None,
        completed_at=None,
        run_context={},
    )
    start = old["window_started_at"]
    assert isinstance(start, datetime)
    old["window_started_at"] = start - timedelta(minutes=1)
    with owner.begin() as c:
        c.execute(text("SELECT set_config('pdos.event_budget_profile','short',true)"))
        c.execute(tables.agent_runs.insert().values(**old))
        c.execute(
            tables.agent_runs.update()
            .where(tables.agent_runs.c.id == old["id"])
            .values(status="queued")
        )
    replies[:] = [evidence(final(ids)["assessment"])]
    with runtime_factory.configured_agent_runtime(env) as runtime:
        result = runtime.executor.execute_next()
    assert result.status == "succeeded" and len(calls) == 3, result
    assert result.run_id == old["id"]
    assert (
        next(r for r in rows(owner, tables.agent_runs) if r["id"] == old["id"])["loop_binding"]
        is None
    )
