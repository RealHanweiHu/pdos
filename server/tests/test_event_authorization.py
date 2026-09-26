"""Service authorization on actual restricted event paths; synthetic provider only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.ai import runtime_factory
from app.ai.lease_heartbeat import AgentLeaseLostError
from app.ai.run_store import RestrictedAgentRunStore
from app.ai.tools import AgentReadTools, ToolPage
from app.contracts.runtime_records import AuthorizationEnvelope
from app.db.schema import metadata, tables
from app.worker.dispatcher import AgentDispatcher
from tests.test_agent_checkpoints import CheckpointSetup, crash_after_result
from tests.test_agent_checkpoints import setup as setup
from tests.test_agent_database_security import SERVER_ROOT
from tests.test_agent_database_security import (
    secured_agent_database_url as secured_agent_database_url,
)
from tests.test_event_budget_adoption import EventScope, scope_id
from tests.test_event_budget_adoption import event_scope as event_scope
from tests.test_model_budget_controller import rows
from tests.test_tool_dispatch_intents import active, prepare


def pause(worker: Engine) -> None:
    with worker.begin() as c:
        c.execute(
            tables.agent_subscriptions.update().values(status="paused", paused_reason="revoked")
        )


def test_actual_runtime_records_service_authority_and_links_receipts_without_actor_egress(
    setup: CheckpointSetup,
) -> None:
    owner, _, _, ids, env, calls, _ = setup
    actor = uuid4()
    with owner.begin() as c:
        c.execute(
            tables.users.insert().values(
                id=actor,
                tenant_id=scope_id(ids, "tenant_a"),
                username="trigger",
                display_name="Trigger",
                role="customer",
            )
        )
        event = (
            c.execute(tables.events.select().where(tables.events.c.id == ids["event_a"]))
            .mappings()
            .one()
        )
        c.execute(
            tables.audit_log.insert().values(
                tenant_id=scope_id(ids, "tenant_a"),
                project_id=ids["project_a"],
                actor_user_id=actor,
                event_id=event["event_id"],
                action="created",
                entity="issue",
                entity_id=event["entity_id"],
                after_snapshot={"source": "test"},
            )
        )
    with runtime_factory.configured_agent_runtime(env) as runtime:
        result = runtime.executor.execute_next()
    assert result.status == "succeeded", result
    row = rows(owner, tables.agent_authorizations)[0]
    envelope = AuthorizationEnvelope.model_validate(row["body"])
    run = rows(owner, tables.agent_runs)[0]
    assert envelope.principal_kind == "service"
    assert envelope.principal_id == run["subscription_id"] != actor
    assert envelope.trigger_actor_user_id == actor and envelope.delegation_id is None
    assert envelope.scope.ref_id == ids["project_a"]
    assert envelope.expires_at == rows(owner, tables.budget_lineages)[0]["absolute_deadline"]
    assert {s.kind for s in envelope.sources} == {"project", "agent_subscription"}
    for table in (tables.agent_tool_observations, tables.agent_context_receipts):
        assert rows(owner, table) and {r["authorization_id"] for r in rows(owner, table)} == {
            row["id"]
        }
    assert str(actor) not in calls[0].content.decode()
    assert str(envelope.principal_id) not in calls[0].content.decode()
    assert len(rows(owner, tables.findings)) == 1


def test_checkpoint_recovery_reuses_immutable_authorization_and_original_budget(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, worker, _, _, env, calls, _ = setup
    crash_after_result(setup, monkeypatch)
    before, budget = rows(owner, tables.agent_authorizations), rows(owner)
    assert AgentDispatcher(worker).dispatch_once().recovered_run_count == 1
    with runtime_factory.configured_agent_runtime(env) as runtime:
        assert runtime.executor.execute_next().status == "succeeded"
    assert len(calls) == 1 and rows(owner, tables.agent_authorizations) == before
    assert rows(owner) == budget


@pytest.mark.parametrize("reactivate", [False, True])
def test_revocation_immediately_fences_live_lease_and_reactivation_cannot_resurrect(
    setup: CheckpointSetup, reactivate: bool
) -> None:
    owner, worker, _, _, _, _, _ = setup
    with active(setup) as (claim, port):
        envelope = port.authorization()
        assert envelope is not None
        call = prepare(port, claim, "before-revoke")
        pause(worker)
        if reactivate:
            with worker.begin() as c:
                c.execute(
                    tables.agent_subscriptions.update().values(status="active", paused_reason=None)
                )
        for action in (
            port.authorization,
            lambda: port.dispatch(call),
            lambda: prepare(port, claim, "after-revoke"),
        ):
            with pytest.raises(AgentLeaseLostError):
                action()
        with worker.begin() as c:
            recovery = (
                c.execute(text("SELECT * FROM cehub_ai.recover_expired_agent_runs(100)"))
                .mappings()
                .one()
            )
        assert recovery["reason"] == "AGENT_AUTHORIZATION_CHANGED"
        assert rows(owner, tables.agent_authorizations)[0]["id"] == envelope.id
        assert not rows(owner, tables.agent_tool_dispatches)
        assert rows(owner, tables.agent_runs)[0]["status"] == "failed"
        assert rows(owner, tables.agent_service_principals)[0]["revision"] == (
            3 if reactivate else 2
        )


def test_revocation_between_observation_and_model_blocks_egress(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, worker, _, _, env, calls, _ = setup
    original = AgentReadTools.search_memory

    def revoke(
        self: AgentReadTools, *, project_id: UUID, query: str, offset: int = 0, limit: int = 20
    ) -> ToolPage:
        result = original(self, project_id=project_id, query=query, offset=offset, limit=limit)
        pause(worker)
        return result

    monkeypatch.setattr(AgentReadTools, "search_memory", revoke)
    with runtime_factory.configured_agent_runtime(env) as runtime:
        result = runtime.executor.execute_next()
    assert result.error_code == "AGENT_RUN_LEASE_LOST"
    assert calls == [] and rows(owner, tables.findings) == []
    with worker.begin() as c:
        assert (
            c.execute(text("SELECT * FROM cehub_ai.recover_expired_agent_runs(100)"))
            .mappings()
            .one()["reason"]
            == "AGENT_AUTHORIZATION_CHANGED"
        )


def test_paused_queued_run_stops_without_fabricated_start_or_authorization(
    setup: CheckpointSetup,
) -> None:
    owner, worker, agent, _, _, calls, _ = setup
    pause(worker)
    assert RestrictedAgentRunStore(agent).claim(started_at=datetime.now(UTC)) is None
    run = rows(owner, tables.agent_runs)[0]
    assert run["status"] == "failed" and run["started_at"] is None
    assert run["error_code"] == "AGENT_AUTHORIZATION_CHANGED"
    assert rows(owner, tables.agent_authorizations) == [] and calls == []


def test_authorization_and_service_identity_are_private_and_history_is_immutable(
    setup: CheckpointSetup,
) -> None:
    owner, worker, agent, _, _, _, _ = setup
    with active(setup) as (_, port):
        assert port.authorization() is not None
    for engine in (worker, agent):
        for table in (tables.agent_authorizations, tables.agent_service_principals):
            with pytest.raises(DBAPIError), engine.begin() as c:
                c.execute(table.select())
            with engine.connect() as c:
                assert not c.execute(
                    text("SELECT has_table_privilege(current_user,:t,'INSERT,UPDATE,DELETE')"),
                    {"t": table.fullname},
                ).scalar_one()
        with pytest.raises(DBAPIError), engine.begin() as c:
            c.execute(text("SELECT cehub_ai.issue_event_authorization(NULL,NULL)"))
    with pytest.raises(DBAPIError, match="append-only"), owner.begin() as c:
        c.execute(tables.agent_authorizations.delete())
    with pytest.raises(DBAPIError, match="subscription lifecycle"), owner.begin() as c:
        c.execute(tables.agent_service_principals.update().values(revision=100))
    with pytest.raises(DBAPIError, match="persistent event authorization history"):
        command.downgrade(Config(str(SERVER_ROOT / "alembic.ini")), "0078_event_loop_binding")


def test_authorization_metadata_matches_migration_and_empty_downgrade_roundtrip(
    setup: CheckpointSetup,
) -> None:
    owner, _, _, _, _, _, _ = setup
    names = {
        "agent_authorizations",
        "agent_service_principals",
        "agent_tool_observations",
        "agent_context_receipts",
    }
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
    command.downgrade(config, "0078_event_loop_binding")
    command.upgrade(config, "head")


@pytest.mark.parametrize("budgeted", [True, False])
@pytest.mark.parametrize("agent_key", ["executive_intelligence", "supplier_intelligence"])
def test_tenant_projections_filter_to_authorized_anchor_before_rows_and_counts(
    event_scope: EventScope, budgeted: bool, agent_key: str
) -> None:
    owner, worker, agent, ids = event_scope
    hidden = uuid4()
    with owner.begin() as c:
        c.execute(tables.agent_subscriptions.update().values(agent_key=agent_key))
        subscription = (
            c.execute(
                tables.agent_subscriptions.select().where(
                    tables.agent_subscriptions.c.tenant_id == ids["tenant_a"]
                )
            )
            .mappings()
            .one()
        )
        c.execute(
            text("SELECT set_config('pdos.event_budget_profile',:profile,true)"),
            {"profile": "short" if budgeted else ""},
        )
        c.execute(
            tables.agent_runs.insert().values(
                id=uuid4(),
                tenant_id=scope_id(ids, "tenant_a"),
                project_id=ids["project_a"],
                subscription_id=subscription["id"],
                agent_key=agent_key,
                status="debouncing",
                window_started_at=datetime.now(UTC) - timedelta(minutes=17),
                window_ended_at=datetime.now(UTC) - timedelta(minutes=1),
                first_event_row_id=ids["event_a"],
                last_event_row_id=ids["event_a"],
                event_count=1,
                event_row_ids=[ids["event_a"]],
                run_context={},
            )
        )
        workflow = uuid4()
        c.execute(
            tables.workflows.insert().values(
                id=workflow,
                tenant_id=scope_id(ids, "tenant_a"),
                code="hidden",
                name="Separate workflow",
            )
        )
        c.execute(
            tables.projects.insert().values(
                id=hidden,
                tenant_id=scope_id(ids, "tenant_a"),
                workflow_id=workflow,
                code="HIDDEN",
                name="Outside anchor",
                status="active",
            )
        )
        supplier = uuid4()
        c.execute(
            tables.suppliers.insert().values(
                id=supplier, tenant_id=scope_id(ids, "tenant_a"), code="S", name="Supplier"
            )
        )
        for project in (hidden, ids["project_a"]):
            c.execute(
                tables.events.insert().values(
                    tenant_id=scope_id(ids, "tenant_a"),
                    project_id=project,
                    event_id=str(uuid4()),
                    event_type="SUPPLIER_DELAY_REPORTED",
                    schema_version=1,
                    source="test",
                    entity="supplier_delay",
                    entity_id=uuid4(),
                    payload={"supplier_id": str(supplier)},
                )
            )
    AgentDispatcher(worker).seal_due_runs()
    store = RestrictedAgentRunStore(agent)
    claim = store.claim(started_at=datetime.now(UTC))
    assert claim is not None
    view = (
        "agent_portfolio_projection"
        if agent_key == "executive_intelligence"
        else "agent_supplier_delay_projection"
    )
    with store.scope(claim), agent.connect() as c:
        store.bind(c)
        projects = set(c.execute(text(f"SELECT project_id FROM cehub_ai.{view}")).scalars())
    assert projects == ({ids["project_a"]} if budgeted else {ids["project_a"], hidden})


def test_revocation_preserves_outstanding_reservations(setup: CheckpointSetup) -> None:
    from app.ai.budget_ledger import BudgetLedger

    owner, worker, _, ids, _, _, _ = setup
    with active(setup) as (claim, _):
        BudgetLedger(owner).reserve(
            tenant_id=scope_id(ids, "tenant_a"),
            run_id=claim.id,
            attempt_id=uuid4(),
            call_kind="model",
            input_tokens=10,
            output_tokens=20,
            tenant_daily_token_limit=100000,
        )
        before = rows(owner)
        pause(worker)
        with worker.begin() as c:
            assert (
                c.execute(text("SELECT * FROM cehub_ai.recover_expired_agent_runs(100)"))
                .mappings()
                .one()["reason"]
                == "AGENT_AUTHORIZATION_CHANGED"
            )
        held_tokens = before[-1]["held_tokens"]
        assert isinstance(held_tokens, int)
        assert rows(owner) == before and held_tokens > 0


def test_old_execution_without_envelope_stops_without_backfill(setup: CheckpointSetup) -> None:
    from tests.test_agent_checkpoints import expire

    owner, worker, agent, _, _, _, _ = setup
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    command.downgrade(config, "0078_event_loop_binding")
    store = RestrictedAgentRunStore(agent)
    claim = store.claim(started_at=datetime.now(UTC))
    assert claim is not None
    expire(owner, claim.id)
    command.upgrade(config, "head")
    with worker.begin() as c:
        result = (
            c.execute(text("SELECT * FROM cehub_ai.recover_expired_agent_runs(100)"))
            .mappings()
            .one()
        )
    assert result["reason"] == "AGENT_AUTHORIZATION_CHANGED"
    assert rows(owner, tables.agent_authorizations) == []
    assert rows(owner, tables.agent_service_principals) == []
