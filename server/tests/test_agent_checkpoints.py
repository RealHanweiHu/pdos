"""Independent pdos_test only: actual factory, worker, Agent, trace and checkpoint recovery."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NoReturn
from uuid import UUID, uuid4

import httpx2
import pytest
from alembic import command
from alembic.config import Config
from psycopg import Error as PsycopgError
from sqlalchemy import Engine, Row, text, update
from sqlalchemy.exc import DBAPIError

from app.ai import executor as executor_module
from app.ai import runtime_factory
from app.ai.budget_adoption import (
    AGENT_METER_DIGEST_KEY,
    AGENT_METER_PATH_KEY,
    AGENT_MODE_KEY,
    AGENT_PROFILE_KEY,
)
from app.ai.budget_ledger import BudgetLedger
from app.ai.checkpoints import AgentCheckpointError, AgentResultCheckpoints
from app.ai.embeddings import EmbeddingResult
from app.ai.executor import AgentAssessment
from app.ai.gateway import GatewayResult
from app.ai.lease_heartbeat import AgentLeaseLostError
from app.ai.model_call_fence import ModelCallFence
from app.ai.run_store import ClaimedAgentRun, RestrictedAgentRunStore
from app.ai.runtime_contract import FrozenRunContext
from app.db.schema import tables
from app.worker.dispatcher import AgentDispatcher
from tests.test_agent_database_security import (
    SERVER_ROOT,
    FakeEmbeddingGateway,
    seed_verified_memory,
)
from tests.test_agent_database_security import (
    secured_agent_database_url as secured_agent_database_url,
)
from tests.test_event_budget_adoption import event_scope as event_scope
from tests.test_input_metering import publication
from tests.test_model_budget_controller import evidence, response, rows
from tests.test_model_gateway import qualification

EventScope = tuple[Engine, Engine, Engine, dict[str, UUID | int]]
CheckpointSetup = tuple[
    Engine,
    Engine,
    Engine,
    dict[str, UUID | int],
    dict[str, str],
    list[httpx2.Request],
    dict[str, object],
]


def scope_id(ids: dict[str, UUID | int], name: str) -> UUID:
    value = ids[name]
    assert isinstance(value, UUID)
    return value


@pytest.fixture
def setup(
    event_scope: EventScope, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> CheckpointSetup:
    owner, worker, agent, ids = event_scope
    AgentDispatcher(worker, budget_profile_key="short").dispatch_tenant(
        tenant_id=scope_id(ids, "tenant_a")
    )
    # The second tenant is a scope-negative fixture, not new work for this recovery cycle.
    with worker.begin() as c:
        c.execute(
            tables.agent_dispatcher_cursors.insert().values(
                id=uuid4(),
                tenant_id=scope_id(ids, "tenant_b"),
                consumer_key="agent_dispatcher_v1",
                last_event_row_id=ids["event_b"],
            )
        )
    AgentDispatcher(worker).seal_due_runs()
    path, _, digest = publication(tmp_path, qualified_input_limit=6000)
    output: dict[str, object] = dict(
        disposition="human_review_candidate",
        candidate_type="risk_suggestion",
        summary="Review the event evidence.",
        proposed_payload=dict(title="Evidence risk", likelihood=3, impact=4),
        evidence_event_ids=[ids["event_a"]],
        confidence=0.8,
    )
    calls: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return response(json.dumps(output))

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
        }
    )
    return owner, worker, agent, ids, env, calls, output


def expire(owner: Engine, run_id: UUID) -> None:
    with owner.begin() as c:
        c.execute(
            text("""UPDATE cehub_ai.agent_runs SET run_context=run_context ||
            jsonb_build_object('_lease_expires_at',clock_timestamp()) WHERE id=:run"""),
            {"run": run_id},
        )


def crash_after_result(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch, *, after_finding: bool = False
) -> UUID:
    owner, _, _, _, env, _, _ = setup
    with runtime_factory.configured_agent_runtime(env) as runtime:
        original = runtime.executor._create_finding

        def crash(
            *,
            claim: ClaimedAgentRun,
            context: FrozenRunContext,
            result: GatewayResult[AgentAssessment],
            created_at: datetime,
        ) -> NoReturn:
            if after_finding:
                original(claim=claim, context=context, result=result, created_at=created_at)
            expire(owner, claim.id)
            raise AgentLeaseLostError("synthetic lost worker")

        monkeypatch.setattr(runtime.executor, "_create_finding", crash)
        result = runtime.executor.execute_next()
    assert result.error_code == "AGENT_RUN_LEASE_LOST", result
    assert rows(owner, tables.agent_runs)[0]["status"] == "running"
    assert len(rows(owner, tables.agent_result_checkpoints)) == 1
    assert result.run_id is not None
    return result.run_id


@pytest.mark.parametrize("disposition", ["candidate", "no_action"])
def test_actual_worker_and_new_executor_resume_without_model_or_budget_reset(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch, disposition: str
) -> None:
    owner, worker, _, _, env, calls, output = setup
    if disposition == "no_action":
        output.update(
            disposition="no_action",
            candidate_type=None,
            proposed_payload=None,
            evidence_event_ids=[],
        )
    run_id = crash_after_result(setup, monkeypatch)
    lineage, journal = rows(owner, tables.budget_lineages), rows(owner)
    before = rows(owner, tables.agent_runs)[0]
    cycle = AgentDispatcher(worker).dispatch_once()
    assert cycle.recovered_run_count == 1 and cycle.stopped_run_count == 0
    with runtime_factory.configured_agent_runtime(env) as runtime:
        result = runtime.executor.execute_next()
        assert result.status == "succeeded", result
        assert runtime.executor.execute_next().status == "idle"
    assert result.run_id == run_id and len(calls) == 1
    assert rows(owner, tables.budget_lineages) == lineage and rows(owner) == journal
    after = rows(owner, tables.agent_runs)[0]
    assert (
        evidence(after["run_context"])["_lease_token"]
        != evidence(before["run_context"])["_lease_token"]
    )
    assert len(rows(owner, tables.budget_activity_spans)) == 2
    assert len(rows(owner, tables.findings)) == (1 if disposition == "candidate" else 0)
    assert rows(owner, tables.agent_run_recoveries)[0]["action"] == "resume_queued"


def test_existing_finding_receipt_completes_run_without_duplicate_action(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, worker, _, _, env, calls, _ = setup
    crash_after_result(setup, monkeypatch, after_finding=True)
    finding = rows(owner, tables.findings)[0]
    actions = rows(owner, tables.finding_actions)
    assert AgentDispatcher(worker).dispatch_once().recovered_run_count == 1
    with runtime_factory.configured_agent_runtime(env) as runtime:
        assert runtime.executor.execute_next().status == "idle"
    assert len(calls) == 1 and rows(owner, tables.findings) == [finding]
    assert rows(owner, tables.finding_actions) == actions
    assert rows(owner, tables.agent_runs)[0]["status"] == "succeeded"
    recovery = rows(owner, tables.agent_run_recoveries)[0]
    assert recovery["action"] == "receipt_completed" and recovery["finding_id"] == finding["id"]


@pytest.mark.parametrize("receipt", ["missing", "session", "reservation"])
def test_missing_checkpoint_and_unknown_receipts_stop_without_model_or_release(
    setup: CheckpointSetup, receipt: str
) -> None:
    owner, worker, agent, ids, env, calls, _ = setup
    store = RestrictedAgentRunStore(agent)
    claim = store.claim(started_at=datetime.now(UTC))
    assert claim is not None
    with store.scope(claim):
        if receipt == "session":
            ModelCallFence(agent, store).begin(
                tenant_id=scope_id(ids, "tenant_a"),
                run_id=claim.id,
                project_id=scope_id(ids, "project_a"),
                agent_key="project_intelligence",
                budgeted=True,
            )
        elif receipt == "reservation":
            BudgetLedger(owner).reserve(
                tenant_id=scope_id(ids, "tenant_a"),
                run_id=claim.id,
                attempt_id=uuid4(),
                call_kind="model",
                input_tokens=10,
                output_tokens=20,
                tenant_daily_token_limit=100000,
            )
    journal = rows(owner)
    expire(owner, claim.id)
    cycle = AgentDispatcher(worker).dispatch_once()
    assert cycle.stopped_run_count == 1
    expected = (
        "AGENT_CHECKPOINT_MISSING" if receipt == "missing" else "AGENT_RECOVERY_RECEIPT_UNKNOWN"
    )
    assert rows(owner, tables.agent_runs)[0]["error_code"] == expected
    assert rows(owner) == journal
    with runtime_factory.configured_agent_runtime(env) as runtime:
        assert runtime.executor.execute_next().status == "idle"
    assert calls == []


def test_recovery_refuses_changed_runtime(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, worker, _, _, env, calls, _ = setup
    crash_after_result(setup, monkeypatch)
    AgentDispatcher(worker).dispatch_once()
    monkeypatch.setattr(executor_module, "checkpoint_runtime_digest", lambda _: "b" * 64)
    with runtime_factory.configured_agent_runtime(env) as runtime:
        result = runtime.executor.execute_next()
    assert result.error_code == "AGENT_CHECKPOINT_VERSION_MISMATCH"
    assert len(calls) == 1 and not rows(owner, tables.findings)


def test_recovery_attempt_limit_is_persisted(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, worker, agent, _, _, calls, _ = setup
    run = crash_after_result(setup, monkeypatch)
    AgentDispatcher(worker).dispatch_once()
    store = RestrictedAgentRunStore(agent)
    claim = store.claim(started_at=datetime.now(UTC))
    assert claim is not None
    assert claim.id == run
    expire(owner, run)
    AgentDispatcher(worker).dispatch_once()
    assert rows(owner, tables.agent_runs)[0]["error_code"] == "AGENT_RECOVERY_ATTEMPT_LIMIT"
    assert len(calls) == 1 and len(rows(owner, tables.agent_run_recoveries)) == 2


@pytest.mark.parametrize("when", ["before_queue", "after_queue"])
def test_paused_subscription_blocks_recovery_at_both_boundaries(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch, when: str
) -> None:
    owner, worker, _, _, env, calls, _ = setup
    crash_after_result(setup, monkeypatch)
    if when == "after_queue":
        AgentDispatcher(worker).dispatch_once()
    with owner.begin() as c:
        c.execute(
            update(tables.agent_subscriptions).values(
                status="paused", paused_reason="synthetic revoked subscription"
            )
        )
    if when == "before_queue":
        assert AgentDispatcher(worker).dispatch_once().stopped_run_count == 1
    else:
        with runtime_factory.configured_agent_runtime(env) as runtime:
            assert runtime.executor.execute_next().status == "idle"
    assert rows(owner, tables.agent_runs)[0]["error_code"] == "AGENT_AUTHORIZATION_CHANGED"
    assert len(calls) == 1 and not rows(owner, tables.findings)


def test_changed_project_source_stops_saved_result_without_model(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, worker, _, ids, env, calls, _ = setup
    crash_after_result(setup, monkeypatch)
    AgentDispatcher(worker).dispatch_once()
    with owner.begin() as c:
        c.execute(
            update(tables.projects)
            .where(tables.projects.c.id == scope_id(ids, "project_a"))
            .values(name="Changed after model checkpoint")
        )
    with runtime_factory.configured_agent_runtime(env) as runtime:
        result = runtime.executor.execute_next()
    assert result.error_code == "AGENT_CHECKPOINT_SOURCES_CHANGED"
    assert len(calls) == 1 and not rows(owner, tables.findings)


@pytest.mark.parametrize("withdrawn", [False, True])
def test_memory_observation_recheck_never_repeats_embedding(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch, withdrawn: bool
) -> None:
    owner, worker, _, ids, env, calls, _ = setup
    embeddings: list[str] = []

    class CountedEmbedding(FakeEmbeddingGateway):
        def embed(self, value: str) -> EmbeddingResult:
            embeddings.append(value)
            return super().embed(value)

    @contextmanager
    def configured(_: Mapping[str, str] | None) -> Iterator[CountedEmbedding]:
        yield CountedEmbedding()

    monkeypatch.setattr(runtime_factory, "configured_embedding_gateway", configured)
    memory = seed_verified_memory(
        owner,
        tenant_id=scope_id(ids, "tenant_a"),
        project_id=scope_id(ids, "project_a"),
        suffix="A-checkpoint",
    )
    crash_after_result(setup, monkeypatch)
    AgentDispatcher(worker).dispatch_once()
    if withdrawn:
        with owner.begin() as c:
            c.execute(
                update(tables.memories)
                .where(tables.memories.c.id == memory)
                .values(status="draft", verified_by_user_id=None, verified_at=None)
            )
    with runtime_factory.configured_agent_runtime(env) as runtime:
        result = runtime.executor.execute_next()
    assert len(calls) == len(embeddings) == 1
    assert result.status == ("failed" if withdrawn else "succeeded"), result
    if withdrawn:
        assert result.error_code == "AGENT_CHECKPOINT_SOURCES_CHANGED"
        assert not rows(owner, tables.findings)


def test_degraded_completed_model_result_is_reused_without_new_attempt(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, worker, _, _, env, calls, output = setup
    output[
        "evidence_event_ids"
    ] = []  # Invalid candidate; normal bounded schema repair is exhausted.
    crash_after_result(setup, monkeypatch)
    checkpoint = evidence(rows(owner, tables.agent_result_checkpoints)[0]["body"])
    assert evidence(checkpoint["result"])["status"] == "degraded"
    before = len(calls)
    AgentDispatcher(worker).dispatch_once()
    with runtime_factory.configured_agent_runtime(env) as runtime:
        result = runtime.executor.execute_next()
    assert (
        result.status == "degraded"
        and result.error_code == evidence(checkpoint["result"])["error_code"]
    )
    assert len(calls) == before and not rows(owner, tables.findings)


@pytest.mark.parametrize("rollout", ["shadow", "disabled"])
def test_resuming_checkpoint_rechecks_capability_stop(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch, rollout: str
) -> None:
    from app.ai.capability_contract import CapabilityRollout
    from app.ai.runtime_contract import AgentKey
    from tests.rollout_support import set_agent_rollout

    owner, worker, _, _, env, calls, _ = setup
    crash_after_result(setup, monkeypatch)
    AgentDispatcher(worker).dispatch_once()
    set_agent_rollout(monkeypatch, AgentKey.PROJECT_INTELLIGENCE, CapabilityRollout(rollout))
    with runtime_factory.configured_agent_runtime(env) as runtime:
        result = runtime.executor.execute_next()
    assert result.error_code == f"CAPABILITY_{rollout.upper()}"
    assert len(calls) == 1 and not rows(owner, tables.findings)


def test_checkpoint_scope_idempotency_immutability_and_role_separation(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, worker, agent, ids, _, _, _ = setup
    crash_after_result(setup, monkeypatch)
    original = rows(owner, tables.agent_result_checkpoints)[0]
    AgentDispatcher(worker).dispatch_once()
    store = RestrictedAgentRunStore(agent)
    claim = store.claim(started_at=datetime.now(UTC))
    assert claim is not None
    port = AgentResultCheckpoints(agent, store)
    with store.scope(claim):
        saved = port.load(claim)
        assert saved is not None
        assert port.save(claim, json.dumps(saved)) == original["id"]
        saved["result"]["output"]["summary"] = "conflicting output"
        with pytest.raises(AgentCheckpointError, match="AGENT_CHECKPOINT_CONFLICT"):
            port.save(claim, json.dumps(saved))
        saved["context"]["tenant_id"] = str(scope_id(ids, "tenant_b"))
        with pytest.raises(AgentCheckpointError, match="AGENT_CHECKPOINT_INVALID"):
            port.save(claim, json.dumps(saved))
        with agent.begin() as c:
            store.bind(c)
            for sql in [
                "SELECT * FROM cehub_ai.agent_result_checkpoints",
                "SELECT * FROM cehub_ai.recover_expired_agent_runs(1)",
            ]:
                with pytest.raises(DBAPIError) as denied, c.begin_nested():
                    c.execute(text(sql))
                assert isinstance(denied.value.orig, PsycopgError)
                assert denied.value.orig.sqlstate == "42501"
    for table in (tables.agent_result_checkpoints, tables.agent_run_recoveries):
        with pytest.raises(DBAPIError, match="append-only"), owner.begin() as c:
            c.execute(table.delete())
    with worker.begin() as c:
        with pytest.raises(DBAPIError) as denied, c.begin_nested():
            c.execute(
                text("SELECT cehub_ai.load_agent_result_checkpoint(:run,:token)"),
                {"run": claim.id, "token": claim.lease_token},
            )
        assert isinstance(denied.value.orig, PsycopgError)
        assert denied.value.orig.sqlstate == "42501"


def test_concurrent_supervisors_record_one_recovery(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, worker, _, _, _, _, _ = setup
    crash_after_result(setup, monkeypatch)

    def recover(_: int) -> Sequence[Row[tuple[object, ...]]]:
        with worker.begin() as c:
            return c.execute(text("SELECT * FROM cehub_ai.recover_expired_agent_runs(100)")).all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(recover, range(2)))
    assert sum(map(len, results)) == 1
    assert len(rows(owner, tables.agent_run_recoveries)) == 1


def test_checkpoint_migration_and_metadata_preserve_evidence(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.db.schema import metadata

    owner, _, _, _, _, _, _ = setup
    with owner.connect() as c:
        context = MigrationContext.configure(
            c,
            opts={
                "include_schemas": True,
                "compare_server_default": True,
                "include_object": lambda obj, name, kind, reflected, compared: (
                    kind != "table"
                    or name
                    in {
                        "agent_result_checkpoints",
                        "agent_run_recoveries",
                        "model_invocations",
                        "findings",
                    }
                ),
            },
        )
        assert compare_metadata(context, metadata) == []
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    command.downgrade(config, "0072_active_execution_budget")
    command.upgrade(config, "head")
    crash_after_result(setup, monkeypatch)
    with pytest.raises(
        DBAPIError,
        match=(
            "persistent (checkpoint recovery|tool observation|tool intent|event authorization|"
            "context manifest or runtime bundle) "
            "history"
        ),
    ):
        command.downgrade(config, "0072_active_execution_budget")


@pytest.mark.parametrize("scope", ["tenant", "run"])
@pytest.mark.parametrize("reference", ["trace", "checkpoint", "finding"])
def test_physical_receipt_keys_reject_other_scope(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch, scope: str, reference: str
) -> None:
    owner, worker, _, ids, _, _, _ = setup
    run_id = crash_after_result(setup, monkeypatch, after_finding=True)
    checkpoint = rows(owner, tables.agent_result_checkpoints)[0]
    finding = rows(owner, tables.findings)[0]
    if scope == "tenant":
        with owner.begin() as c:
            c.execute(
                tables.agent_dispatcher_cursors.delete().where(
                    tables.agent_dispatcher_cursors.c.tenant_id == scope_id(ids, "tenant_b")
                )
            )
        AgentDispatcher(worker, budget_profile_key="short").dispatch_tenant(
            tenant_id=scope_id(ids, "tenant_b")
        )
        other = next(
            r for r in rows(owner, tables.agent_runs) if r["tenant_id"] == scope_id(ids, "tenant_b")
        )
    else:
        other = dict(next(r for r in rows(owner, tables.agent_runs) if r["id"] == run_id))
        other.update(
            id=uuid4(),
            status="queued",
            started_at=None,
            completed_at=None,
            error_code=None,
            run_context={},
        )
        start, end = other["window_started_at"], other["window_ended_at"]
        assert isinstance(start, datetime) and isinstance(end, datetime)
        other["window_started_at"] = start + timedelta(days=1)
        other["window_ended_at"] = end + timedelta(days=1)
        with owner.begin() as c:
            c.execute(tables.agent_runs.insert().values(**other))
    if reference == "trace":
        target = tables.agent_result_checkpoints
        values = dict(checkpoint, id=uuid4(), tenant_id=other["tenant_id"], run_id=other["id"])
        constraint = "fk_checkpoint_trace_scope"
    else:
        target = tables.agent_run_recoveries
        values = dict(
            id=uuid4(),
            tenant_id=other["tenant_id"],
            run_id=other["id"],
            checkpoint_id=checkpoint["id"] if reference == "checkpoint" else None,
            finding_id=finding["id"] if reference == "finding" else None,
            action="stopped",
            reason="synthetic",
            expired_lease_token=uuid4(),
            created_at=datetime.now(UTC),
        )
        constraint = f"fk_recovery_{reference}_scope"
    with pytest.raises(DBAPIError, match=constraint), owner.begin() as c:
        c.execute(target.insert().values(**values))
