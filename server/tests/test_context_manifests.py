"""Actual model admission and restricted Manifest ports on independent pdos_test."""

from __future__ import annotations

import json
from collections.abc import Sequence
from importlib import import_module
from typing import NoReturn
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.ai import context_manifests, runtime_factory
from app.ai.budget_ledger import BudgetLedger
from app.ai.executor import AgentLoopStep, GatewayAgentModelInvoker
from app.ai.gateway import BoundedModelProviderAdapter, GatewayInvocation, GatewayResult
from app.ai.model_catalog import ResolvedModelRoute
from app.ai.observations import AgentObservationError
from app.ai.provider_adapters import ChatMessage, ProviderCallLimits, ProviderResponse
from app.ai.tools import AgentReadTools, ProjectContextResult
from app.contracts.runtime_records import ContextManifest
from app.db.schema import metadata, tables
from tests.migration_fixtures import rollback_migration_operations
from tests.test_agent_checkpoints import CheckpointSetup, crash_after_result
from tests.test_agent_checkpoints import setup as setup
from tests.test_agent_database_security import SERVER_ROOT
from tests.test_agent_database_security import (
    secured_agent_database_url as secured_agent_database_url,
)
from tests.test_agent_tool_loop import LoopSetup, final
from tests.test_agent_tool_loop import loop_setup as loop_setup
from tests.test_event_budget_adoption import event_scope as event_scope
from tests.test_event_budget_adoption import scope_id
from tests.test_model_budget_controller import rows
from tests.test_tool_dispatch_intents import active


def integer(value: object) -> int:
    assert isinstance(value, int)
    return value


def record(value: object) -> dict[str, object]:
    assert isinstance(value, dict) and all(isinstance(key, str) for key in value)
    return value


def test_actual_loop_has_admitted_revision_chain_and_exact_receipts(loop_setup: LoopSetup) -> None:
    owner, _, _, ids, env, calls, _ = loop_setup
    with runtime_factory.configured_agent_runtime(env) as runtime:
        result = runtime.executor.execute_next()
    assert result.status == "succeeded", result
    manifests = sorted(
        rows(owner, tables.agent_context_manifests), key=lambda r: integer(r["revision_no"])
    )
    assert len(manifests) == len(calls) == 2
    bundle = record(rows(owner, tables.agent_runs)[0]["execution_bundle"])
    system_prompt = json.loads(calls[0].content)["messages"][0]["content"]
    visible_tools = json.loads(system_prompt.rsplit("\nFROZEN_READ_ONLY_TOOLS\n", 1)[1])
    assert record(bundle["compiled"])["tools"] == visible_tools
    assert all(t["name"] != "web_fetch" for t in visible_tools)
    assert all("project_id" not in t["input_example"] for t in visible_tools)
    previous: UUID | None = None
    for index, row in enumerate(manifests, 1):
        manifest = ContextManifest.model_validate(row["body"])
        admission = next(j for j in rows(owner) if j["id"] == row["admission_id"])
        assert manifest.revision_no == index and manifest.parent_revision_id == previous
        assert manifest.estimated_input_tokens == integer(admission["input_tokens"]) > 0
        assert manifest.reserved_output_tokens == integer(admission["output_tokens"]) > 0
        assert admission["dispatched_at"] is None
        assert manifest.authorization_id == row["authorization_id"]
        assert manifest.release_bundle_version == bundle["release_bundle_version"]
        assert manifest.event_watermark is not None and manifest.event_watermark >= integer(
            ids["event_a"]
        )
        assert len(manifest.observation_ids) == 3 + index
        assert manifest.completeness == "context_incomplete" and manifest.missing
        assert any("search_memory" in s for s in manifest.omission_reasons)
        assert not manifest.skill_versions and manifest.goal_revision == 1
        assert str(manifest.authorization_id) not in calls[index - 1].content.decode()
        previous_id = row["id"]
        assert isinstance(previous_id, UUID)
        previous = previous_id
    assert manifests[0]["context_receipt_id"] != manifests[1]["context_receipt_id"]
    with owner.connect() as c:
        assert c.execute(
            text("""SELECT bool_and(body->>'digest'=
          encode(sha256(convert_to((body-'digest')::text,'UTF8')),'hex'))
          FROM cehub_ai.agent_context_manifests""")
        ).scalar_one()


def test_structured_retry_gets_separate_actual_token_reservation_revision(
    loop_setup: LoopSetup,
) -> None:
    owner, _, _, ids, env, calls, replies = loop_setup
    replies[:] = ["invalid", final(ids)]
    with runtime_factory.configured_agent_runtime(env) as runtime:
        assert runtime.executor.execute_next().status == "succeeded"
    manifests = rows(owner, tables.agent_context_manifests)
    assert len(calls) == len(manifests) == 2
    assert len({r["context_receipt_id"] for r in manifests}) == 1
    admissions = [j for j in rows(owner) if j["id"] in {r["admission_id"] for r in manifests}]
    assert {record(j["request_binding"])["structured_attempt"] for j in admissions} == {1, 2}
    assert len({record(j["request_binding"])["request_digest"] for j in admissions}) == 2
    assert rows(owner, tables.model_invocations)[0]["structured_attempts"] == 2


def test_manifest_failure_cancels_undispatched_reservation_and_sends_nothing(
    loop_setup: LoopSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, _, _, _, env, calls, _ = loop_setup

    def fail(*args: object, **kwargs: object) -> NoReturn:
        raise AgentObservationError("AGENT_MANIFEST_PINS_INVALID")

    monkeypatch.setattr(context_manifests, "freeze_manifest", fail)
    with runtime_factory.configured_agent_runtime(env) as runtime:
        result = runtime.executor.execute_next()
    assert result.error_code == "AGENT_MANIFEST_PINS_INVALID"
    assert calls == [] and rows(owner, tables.agent_context_manifests) == []
    journal = sorted(rows(owner), key=lambda r: integer(r["revision"]))
    assert journal[-1]["reservation_status"] == "cancelled_before_dispatch"
    assert journal[-1]["held_tokens"] == 0 and journal[-1]["dispatched_at"] is None
    assert rows(owner, tables.model_invocations)[0]["structured_attempts"] == 0


def test_direct_dispatch_cannot_skip_manifest(setup: CheckpointSetup) -> None:
    owner, _, _, ids, _, _, _ = setup
    with active(setup) as (claim, _):
        ledger = BudgetLedger(owner)
        attempt = uuid4()
        ledger.reserve(
            tenant_id=scope_id(ids, "tenant_a"),
            run_id=claim.id,
            attempt_id=attempt,
            call_kind="model",
            input_tokens=10,
            output_tokens=20,
            tenant_daily_token_limit=100000,
        )
        with pytest.raises(DBAPIError, match="BUDGET_CONTEXT_MANIFEST_REQUIRED"):
            ledger.transition(
                tenant_id=scope_id(ids, "tenant_a"), attempt_id=attempt, action="dispatch"
            )
    assert len(rows(owner)) == 1 and rows(owner)[0]["dispatched_at"] is None


def test_model_qualification_cannot_change_in_middle_of_run(
    loop_setup: LoopSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, _, _, _, env, calls, _ = loop_setup
    with runtime_factory.configured_agent_runtime(env) as runtime:
        invoker = runtime.executor._model_invoker
        assert isinstance(invoker, GatewayAgentModelInvoker)
        gateway = invoker._gateway
        original = invoker.decide

        def change(invocation: GatewayInvocation) -> GatewayResult[AgentLoopStep]:
            result = original(invocation)
            gateway._qualifications = [
                q.model_copy(update={"suite_digest": "f" * 64}) for q in gateway._qualifications
            ]
            return result

        monkeypatch.setattr(runtime.executor._model_invoker, "decide", change)
        result = runtime.executor.execute_next()
    assert result.error_code == "AGENT_MANIFEST_VERSION_CHANGED", result
    assert len(calls) == len(rows(owner, tables.agent_context_manifests)) == 1
    assert rows(owner, tables.findings) == []


def test_recovery_keeps_manifests_and_rejects_changed_runtime_bundle(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.worker.dispatcher import AgentDispatcher

    owner, worker, _, _, env, calls, _ = setup
    crash_after_result(setup, monkeypatch)
    before = rows(owner, tables.agent_context_manifests)
    assert AgentDispatcher(worker).dispatch_once().recovered_run_count == 1
    original = context_manifests.event_runtime_bundle

    def changed(agent_key: str, *, loop: bool) -> dict[str, object]:
        return {**original(agent_key, loop=loop), "release_bundle_version": "sha256:" + "f" * 64}

    monkeypatch.setattr(context_manifests, "event_runtime_bundle", changed)
    with runtime_factory.configured_agent_runtime(env) as runtime:
        result = runtime.executor.execute_next()
    assert result.error_code == "AGENT_BUNDLE_VERSION_CHANGED", result
    assert rows(owner, tables.agent_context_manifests) == before and len(calls) == 1
    assert rows(owner, tables.findings) == []


def test_manifest_metadata_and_empty_migration_roundtrip(loop_setup: LoopSetup) -> None:
    owner, _, _, _, _, _, _ = loop_setup
    names = {"agent_context_manifests", "agent_runs", "budget_journal"}
    with owner.connect() as c:
        context = MigrationContext.configure(
            c,
            opts=dict(
                include_schemas=True,
                include_object=lambda obj, name, kind, reflected, compared: (
                    kind != "table" or name in names
                ),
            ),
        )
        assert compare_metadata(context, metadata) == []
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    command.downgrade(config, "0079_event_authorization")
    command.upgrade(config, "head")


def test_manifest_history_is_private_immutable_and_scope_bound(loop_setup: LoopSetup) -> None:
    owner, worker, agent, ids, env, _, _ = loop_setup
    with runtime_factory.configured_agent_runtime(env) as runtime:
        assert runtime.executor.execute_next().status == "succeeded"
    for engine in (worker, agent):
        with pytest.raises(DBAPIError), engine.begin() as c:
            c.execute(tables.agent_context_manifests.select())
    with pytest.raises(DBAPIError, match="append-only"), owner.begin() as c:
        c.execute(tables.agent_context_manifests.delete())
    with pytest.raises(DBAPIError, match="immutable"), owner.begin() as c:
        c.execute(tables.agent_runs.update().values(execution_bundle=None))
    row = dict(rows(owner, tables.agent_context_manifests)[0])
    with pytest.raises(DBAPIError), owner.begin() as c:
        c.execute(
            tables.agent_context_manifests.insert().values(
                {**row, "id": uuid4(), "tenant_id": ids["tenant_b"]}
            )
        )
    with (
        rollback_migration_operations(owner),
        pytest.raises(DBAPIError, match="persistent context manifest or runtime bundle history"),
    ):
        import_module("migrations.versions.0080_context_manifests").downgrade()


def test_manifest_is_committed_before_actual_provider_dispatch(
    loop_setup: LoopSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ai.model_catalog import ProtocolKind

    owner, _, _, _, env, calls, _ = loop_setup
    with runtime_factory.configured_agent_runtime(env) as runtime:
        invoker = runtime.executor._model_invoker
        assert isinstance(invoker, GatewayAgentModelInvoker)
        adapter = invoker._gateway._adapters[ProtocolKind.OPENAI_COMPATIBLE]
        assert isinstance(adapter, BoundedModelProviderAdapter)
        original = adapter.complete_bounded

        def inspect(
            route: ResolvedModelRoute,
            messages: Sequence[ChatMessage],
            *,
            limits: ProviderCallLimits,
        ) -> ProviderResponse:
            records = rows(owner, tables.agent_context_manifests)
            assert len(records) == len(calls) + 1
            current = max(records, key=lambda r: integer(r["revision_no"]))
            journal = [j for j in rows(owner) if j["attempt_id"] == current["attempt_id"]]
            assert any(j["dispatched_at"] is not None for j in journal)
            assert record(current["body"])["reserved_output_tokens"] == limits.max_output_tokens
            return original(route, messages, limits=limits)

        monkeypatch.setattr(adapter, "complete_bounded", inspect)
        assert runtime.executor.execute_next().status == "succeeded"
    assert len(calls) == 2


def test_budget_rejection_never_fabricates_an_admitted_manifest(
    loop_setup: LoopSetup, monkeypatch: pytest.MonkeyPatch
) -> None:

    owner, _, _, ids, env, calls, _ = loop_setup
    original = AgentReadTools.get_project_context

    def fill(self: AgentReadTools, *, project_id: UUID) -> ProjectContextResult:
        for _ in range(1):
            BudgetLedger(owner).reserve(
                tenant_id=scope_id(ids, "tenant_a"),
                run_id=self._context.run_id,
                attempt_id=uuid4(),
                call_kind="model",
                input_tokens=10,
                output_tokens=10,
                tenant_daily_token_limit=100000,
            )
        return original(self, project_id=project_id)

    monkeypatch.setattr(AgentReadTools, "get_project_context", fill)
    with runtime_factory.configured_agent_runtime(env) as runtime:
        result = runtime.executor.execute_next()
    assert result.error_code == "BUDGET_LINEAGE_CALL_BUSY", result
    assert calls == [] and rows(owner, tables.agent_context_manifests) == []
    assert len(rows(owner)) == 1
    assert all(j["held_tokens"] == 20 for j in rows(owner))


def test_trace_cannot_claim_a_different_model_call_consumed_the_manifest(
    loop_setup: LoopSetup,
) -> None:
    owner, _, _, _, env, _, _ = loop_setup
    with runtime_factory.configured_agent_runtime(env) as runtime:
        assert runtime.executor.execute_next().status == "succeeded"
    trace = dict(rows(owner, tables.model_invocations)[0])
    with pytest.raises(DBAPIError, match="BUDGET_TRACE_MANIFEST_REQUIRED"), owner.begin() as c:
        c.execute(
            tables.model_invocations.insert().values(
                {**trace, "id": uuid4(), "budget_call_id": uuid4()}
            )
        )


def test_pre_manifest_dispatched_usage_can_still_be_settled(setup: CheckpointSetup) -> None:
    owner, _, _, ids, _, _, _ = setup
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    command.downgrade(config, "0079_event_authorization")
    with active(setup) as (claim, _):
        ledger = BudgetLedger(owner)
        attempt = uuid4()
        ledger.reserve(
            tenant_id=scope_id(ids, "tenant_a"),
            run_id=claim.id,
            attempt_id=attempt,
            call_kind="model",
            input_tokens=10,
            output_tokens=20,
            tenant_daily_token_limit=100000,
        )
        ledger.transition(
            tenant_id=scope_id(ids, "tenant_a"), attempt_id=attempt, action="dispatch"
        )
        command.upgrade(config, "head")
        ledger.transition(
            tenant_id=scope_id(ids, "tenant_a"),
            attempt_id=attempt,
            action="settle",
            charged_tokens=25,
            reconciliation_ref="old-dispatched-test-receipt",
        )
    journal = sorted(rows(owner), key=lambda r: integer(r["revision"]))
    assert journal[-1]["reservation_status"] == "settled" and journal[-1]["charged_tokens"] == 25
    assert rows(owner, tables.agent_context_manifests) == []
