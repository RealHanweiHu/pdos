"""Approved trigger clocks exercised through real Worker and lease-scoped Agent ports."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import NoReturn
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.ai import runtime_factory
from app.ai.executor import AgentAssessment
from app.ai.gateway import GatewayInvocation, GatewayResult
from app.ai.lease_heartbeat import AgentLeaseLostError
from app.ai.run_store import RestrictedAgentRunStore
from app.db.schema import tables
from app.worker.dispatcher import AgentDispatcher, DispatchResult
from app.worker.trigger_policy import FREQUENT_EDITS, MILESTONES, policy_for_event
from tests.test_agent_checkpoints import CheckpointSetup
from tests.test_agent_checkpoints import setup as setup
from tests.test_agent_database_security import SERVER_ROOT
from tests.test_agent_database_security import (
    secured_agent_database_url as secured_agent_database_url,
)
from tests.test_agent_dispatcher import append_event
from tests.test_event_budget_adoption import EventScope, scope_id
from tests.test_event_budget_adoption import event_scope as event_scope
from tests.test_model_budget_controller import rows


@pytest.fixture(name="model_setup")
def configure_model_fixture(setup: CheckpointSetup) -> CheckpointSetup:
    return setup


@pytest.fixture
def scope(event_scope: EventScope) -> EventScope:
    owner, worker, _, ids = event_scope
    with worker.begin() as c:
        for suffix in ("a", "b"):
            c.execute(
                tables.agent_dispatcher_cursors.insert().values(
                    id=uuid4(),
                    tenant_id=ids[f"tenant_{suffix}"],
                    consumer_key="agent_dispatcher_v1",
                    last_event_row_id=ids[f"event_{suffix}"],
                )
            )
    return event_scope


def add(scope: EventScope, *, kind: str = "ISSUE_CREATED", when: datetime | None = None) -> int:
    owner, _, _, ids = scope
    with owner.begin() as c:
        return append_event(
            c,
            tenant_id=scope_id(ids, "tenant_a"),
            project_id=scope_id(ids, "project_a"),
            event_type=kind,
            occurred_at=when or datetime.now(UTC),
        )


def dispatch(scope: EventScope) -> DispatchResult:
    _, worker, _, ids = scope
    return AgentDispatcher(
        worker, scheduling="approved", budget_profile_key="short"
    ).dispatch_tenant(tenant_id=scope_id(ids, "tenant_a"))


def test_trigger_map_matches_approved_inventory_and_routes() -> None:
    from app.ai.runtime_contract import agents_for_event
    from scripts.runtime_adoption_inventory import events

    inventory = {e["event"]: e for e in events()}
    for key in MILESTONES | FREQUENT_EDITS:
        assert agents_for_event(key)
        assert inventory[key]["proposed_trigger_policy"] == policy_for_event(key)
    with pytest.raises(ValueError, match="no approved"):
        policy_for_event("AI_FINDING_CREATED")


def test_milestones_queue_in_creation_transaction_and_same_timestamp_does_not_drop(
    scope: EventScope,
) -> None:
    owner, _, _, _ = scope
    now = datetime.now(UTC)
    ids = [add(scope, when=now), add(scope, when=now)]
    assert dispatch(scope).created_run_count == 2
    runs = rows(owner, tables.agent_runs)
    assert {r["dispatch_key"] for r in runs} == {f"event:{i}" for i in ids}
    assert all(
        r["status"] == "queued"
        and r["dispatch_deadline"] == now + timedelta(seconds=180)
        and r["window_started_at"] == r["window_ended_at"] == now
        for r in runs
    )
    assert len(rows(owner, tables.budget_lineages)) == 2
    assert dispatch(scope).created_run_count == 0
    assert not rows(owner)


def test_frequent_edits_keep_fixed_window_and_late_events_are_not_lost(scope: EventScope) -> None:
    owner, worker, _, _ = scope
    now = datetime.now(UTC) - timedelta(hours=1)
    start = datetime.fromtimestamp(int(now.timestamp()) // 900 * 900, UTC)
    first = add(scope, kind="DOCUMENT_UPLOADED", when=start + timedelta(seconds=1))
    second = add(scope, kind="DOCUMENT_UPLOADED", when=start + timedelta(seconds=2))
    result = dispatch(scope)
    assert result.created_run_count == 1 and result.merged_event_count == 1
    run = rows(owner, tables.agent_runs)[0]
    assert run["event_row_ids"] == [first, second] and run["dispatch_deadline"] is None
    started, ended = run["window_started_at"], run["window_ended_at"]
    assert isinstance(started, datetime) and isinstance(ended, datetime)
    assert ended - started == timedelta(seconds=900)
    AgentDispatcher(worker).seal_due_runs()
    late = add(scope, kind="DOCUMENT_UPLOADED", when=start + timedelta(seconds=3))
    assert dispatch(scope).created_run_count == 1
    assert any(r["event_row_ids"] == [late] for r in rows(owner, tables.agent_runs))


def test_real_agent_claim_prioritizes_milestone_over_older_background(scope: EventScope) -> None:
    owner, worker, agent, _ = scope
    add(scope, kind="DOCUMENT_UPLOADED", when=datetime.now(UTC) - timedelta(hours=1))
    dispatch(scope)
    AgentDispatcher(worker).seal_due_runs()
    event = add(scope)
    dispatch(scope)
    claim = RestrictedAgentRunStore(agent).claim(started_at=datetime.now(UTC))
    assert claim is not None
    assert claim.values["event_row_ids"] == [event]
    assert len(rows(owner, tables.budget_lineages)) == 2


def test_expired_queue_fails_without_model_or_new_budget(scope: EventScope) -> None:
    owner, worker, agent, _ = scope
    add(scope, when=datetime.now(UTC) - timedelta(seconds=181))
    dispatch(scope)
    budgets = rows(owner, tables.budget_lineages)
    assert RestrictedAgentRunStore(agent).claim(started_at=datetime.now(UTC)) is None
    run = rows(owner, tables.agent_runs)[0]
    assert run["status"] == "failed" and run["error_code"] == "AGENT_TRIGGER_DEADLINE_EXCEEDED"
    assert rows(owner, tables.budget_lineages) == budgets and not rows(owner)
    assert AgentDispatcher(worker).dispatch_once().stopped_run_count == 0


def test_lease_and_renewal_never_extend_trigger_deadline(scope: EventScope) -> None:
    owner, _, agent, _ = scope
    add(scope, when=datetime.now(UTC) - timedelta(seconds=150))
    dispatch(scope)
    store = RestrictedAgentRunStore(agent)
    claim = store.claim(started_at=datetime.now(UTC) + timedelta(days=1))
    assert claim is not None
    run = rows(owner, tables.agent_runs)[0]
    context = run["run_context"]
    assert isinstance(context, dict)
    expires_at = context["_lease_expires_at"]
    assert isinstance(expires_at, str)
    assert datetime.fromisoformat(expires_at) == run["dispatch_deadline"]
    assert store.renew(claim) == run["dispatch_deadline"]


@pytest.mark.parametrize("receipt", ["missing", "session", "reservation"])
def test_running_deadline_stops_recovery_and_old_worker(scope: EventScope, receipt: str) -> None:
    owner, worker, agent, _ = scope
    add(scope, when=datetime.now(UTC) - timedelta(seconds=177))
    dispatch(scope)
    store = RestrictedAgentRunStore(agent)
    claim = store.claim(started_at=datetime.now(UTC))
    assert claim is not None
    if receipt == "session":
        from app.ai.model_call_fence import ModelCallFence

        with store.scope(claim):
            ModelCallFence(agent, store).begin(
                tenant_id=claim.values["tenant_id"],
                run_id=claim.id,
                project_id=claim.values["project_id"],
                agent_key=claim.values["agent_key"],
                budgeted=True,
            )
    elif receipt == "reservation":
        from app.ai.budget_ledger import BudgetLedger

        BudgetLedger(owner).reserve(
            tenant_id=claim.values["tenant_id"],
            run_id=claim.id,
            attempt_id=uuid4(),
            call_kind="model",
            input_tokens=10,
            output_tokens=20,
            tenant_daily_token_limit=100000,
        )
    journal = rows(owner)
    with owner.connect() as c:
        c.execute(text("SELECT pg_sleep(3.1)"))
    with pytest.raises(AgentLeaseLostError):
        store.renew(claim)
    assert AgentDispatcher(worker).dispatch_once().stopped_run_count == 1
    run = rows(owner, tables.agent_runs)[0]
    expected = (
        "AGENT_TRIGGER_DEADLINE_EXCEEDED"
        if receipt == "missing"
        else "AGENT_RECOVERY_RECEIPT_UNKNOWN"
    )
    assert run["error_code"] == expected
    assert rows(owner, tables.agent_run_recoveries)[0]["action"] == "stopped"
    assert rows(owner) == journal


def test_dispatch_policy_cannot_be_rewritten_or_forged(scope: EventScope) -> None:
    owner, _, _, _ = scope
    add(scope)
    dispatch(scope)
    run = rows(owner, tables.agent_runs)[0]
    with pytest.raises(DBAPIError, match="immutable"), owner.begin() as c:
        c.execute(tables.agent_runs.update().values(dispatch_deadline=datetime.now(UTC)))
    forged = dict(run, id=uuid4(), dispatch_key="event:999999")
    with pytest.raises(DBAPIError, match="invalid milestone"), owner.begin() as c:
        c.execute(tables.agent_runs.insert().values(**forged))


def test_policy_schema_and_empty_roundtrip_preserve_history(scope: EventScope) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.db.schema import metadata

    owner, _, _, _ = scope
    with owner.connect() as c:
        context = MigrationContext.configure(
            c,
            opts=dict(
                include_schemas=True,
                include_object=lambda obj, name, kind, reflected, compared: (
                    kind != "table" or name == "agent_runs"
                ),
            ),
        )
        assert compare_metadata(context, metadata) == []
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    command.downgrade(config, "0074_checkpoint_scope_keys")
    command.upgrade(config, "head")
    add(scope)
    dispatch(scope)
    with pytest.raises(DBAPIError, match="persistent dispatch policy history"):
        command.downgrade(config, "0074_checkpoint_scope_keys")


def test_configured_executor_consumes_prioritized_run(model_setup: CheckpointSetup) -> None:
    owner, worker, _, ids, env, calls, output = model_setup
    output.update(
        disposition="no_action", candidate_type=None, proposed_payload=None, evidence_event_ids=[]
    )
    with owner.begin() as c:
        event = append_event(
            c,
            tenant_id=scope_id(ids, "tenant_a"),
            project_id=scope_id(ids, "project_a"),
            event_type="ISSUE_CREATED",
            occurred_at=datetime.now(UTC),
        )
    AgentDispatcher(worker, scheduling="approved", budget_profile_key="short").dispatch_tenant(
        tenant_id=scope_id(ids, "tenant_a")
    )
    with runtime_factory.configured_agent_runtime(env) as runtime:
        result = runtime.executor.execute_next()
    assert result.status == "succeeded", result
    run = next(r for r in rows(owner, tables.agent_runs) if r["id"] == result.run_id)
    assert run["dispatch_key"] == f"event:{event}" and len(calls) == 1
    assert len(rows(owner, tables.agent_result_checkpoints)) == 1


def test_legacy_failed_run_still_requires_actual_start(scope: EventScope) -> None:
    owner, worker, _, ids = scope
    add(scope)
    AgentDispatcher(worker).dispatch_tenant(tenant_id=scope_id(ids, "tenant_a"))
    with pytest.raises(DBAPIError, match="lifecycle_consistent"), owner.begin() as c:
        c.execute(
            tables.agent_runs.update().values(
                status="failed",
                completed_at=datetime.now(UTC),
                error_code="AGENT_TRIGGER_DEADLINE_EXCEEDED",
            )
        )


def test_trigger_source_cannot_be_changed_after_freeze(scope: EventScope) -> None:
    owner, _, _, _ = scope
    add(scope)
    dispatch(scope)
    with pytest.raises(DBAPIError, match="dispatch source is immutable"), owner.begin() as c:
        c.execute(tables.agent_runs.update().values(window_ended_at=datetime.now(UTC)))


@pytest.mark.parametrize("poll", ["2", "60"])
def test_worker_entrypoint_adopts_policy_and_bounds_poll(
    monkeypatch: pytest.MonkeyPatch, poll: str
) -> None:
    from types import SimpleNamespace

    from scripts import run_dispatcher

    class StopCycle(Exception):
        pass

    captured: dict[str, object] = {}

    class FakeDispatcher:
        def __init__(self, engine: Engine, **kwargs: object) -> None:
            captured.update(kwargs)

        def dispatch_once(self) -> NoReturn:
            raise StopCycle

    monkeypatch.setenv("PDOS_DISPATCHER_POLL_SECONDS", poll)
    monkeypatch.setattr(
        run_dispatcher, "required_database_url", lambda *a, **kw: "postgresql://test"
    )
    monkeypatch.setattr(run_dispatcher, "event_budget_profile", lambda *a: None)
    monkeypatch.setattr(
        run_dispatcher, "create_engine", lambda *a, **kw: SimpleNamespace(dispose=lambda: None)
    )
    monkeypatch.setattr(run_dispatcher, "AgentDispatcher", FakeDispatcher)
    if poll == "60":
        with pytest.raises(ValueError, match="between 0.1 and 5"):
            run_dispatcher.main()
        assert captured == {}
    else:
        with pytest.raises(StopCycle):
            run_dispatcher.main()
        assert captured["scheduling"] == "approved"


def test_completed_model_cannot_publish_after_trigger_deadline(
    model_setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, worker, _, ids, env, calls, _ = model_setup
    with owner.begin() as c:
        append_event(
            c,
            tenant_id=scope_id(ids, "tenant_a"),
            project_id=scope_id(ids, "project_a"),
            event_type="ISSUE_CREATED",
            occurred_at=datetime.now(UTC) - timedelta(seconds=175),
        )
    AgentDispatcher(worker, scheduling="approved", budget_profile_key="short").dispatch_tenant(
        tenant_id=scope_id(ids, "tenant_a")
    )
    with runtime_factory.configured_agent_runtime(env) as runtime:
        invoke = runtime.executor._model_invoker.invoke

        def delay_publication(invocation: GatewayInvocation) -> GatewayResult[AgentAssessment]:
            result = invoke(invocation)
            with owner.connect() as c:
                c.execute(text("SELECT pg_sleep(5.1)"))
            return result

        monkeypatch.setattr(runtime.executor._model_invoker, "invoke", delay_publication)
        result = runtime.executor.execute_next()
    assert result.error_code == "AGENT_RUN_LEASE_LOST"
    assert len(calls) == 1 and not rows(owner, tables.findings)
    assert not rows(owner, tables.agent_result_checkpoints)
    journal = rows(owner)
    assert journal and rows(owner, tables.model_invocations)
    assert AgentDispatcher(worker).dispatch_once().stopped_run_count == 1
    assert rows(owner) == journal
