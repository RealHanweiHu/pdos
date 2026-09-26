"""Only run on an isolated pdos_test cluster: fixtures configure global roles."""

from __future__ import annotations

import json
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from importlib import import_module
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from psycopg import Error as PsycopgError
from sqlalchemy import Connection, Engine, RowMapping, select, text, update
from sqlalchemy.exc import DBAPIError

from app.ai.agent_budget import RestrictedBudgetTransitions
from app.ai.budget_evidence import BudgetRequestBinding, BudgetUsageEvidence
from app.ai.budget_ledger import BudgetLedger, BudgetLedgerError
from app.ai.context_manifests import freeze_manifest
from app.ai.lease_heartbeat import AgentLeaseLostError
from app.ai.model_catalog import ProtocolKind, ProviderName
from app.ai.observations import AgentObservations
from app.ai.run_store import ClaimedAgentRun, RestrictedAgentRunStore
from app.db.schema import tables
from tests.agent_context_fixtures import freeze_project_invocation
from tests.migration_fixtures import rollback_migration_operations
from tests.test_agent_database_security import role_engine
from tests.test_agent_database_security import (
    secured_agent_database_url as secured_agent_database_url,
)
from tests.test_budget_ledger import profile
from tests.test_model_call_fence_security import authorize_budgeted_scope
from tests.test_model_call_fence_security import scope as scope
from tests.test_model_gateway import qualification

BudgetScope = tuple[
    Engine, Engine, RestrictedAgentRunStore, ClaimedAgentRun, dict[str, UUID | int], UUID
]


def scope_id(ids: dict[str, UUID | int], name: str) -> UUID:
    value = ids[name]
    assert isinstance(value, UUID)
    return value


def denied(
    connection: Connection,
    statement: str,
    parameters: Mapping[str, object],
    *,
    sqlstate: str = "42501",
) -> None:
    with pytest.raises(DBAPIError) as caught, connection.begin_nested():
        connection.execute(text(statement), parameters)
    assert isinstance(caught.value.orig, PsycopgError)
    assert caught.value.orig.sqlstate == sqlstate


def prepare(
    scope: BudgetScope, *, bound: bool = True
) -> tuple[BudgetLedger, RestrictedBudgetTransitions, UUID]:
    owner, agent, store, claim, ids, _ = scope
    ledger = BudgetLedger(owner)
    ledger.open_lineage(tenant_id=scope_id(ids, "tenant_a"), run_id=claim.id, profile=profile())
    authorize_budgeted_scope(scope)
    invocation = (
        freeze_project_invocation(
            agent,
            store,
            claim,
            tenant_id=scope_id(ids, "tenant_a"),
            project_id=scope_id(ids, "project_a"),
        )
        if bound
        else None
    )
    binding = (
        BudgetRequestBinding(
            model_call_id=invocation.model_call_id,
            structured_attempt=1,
            request_digest="a" * 64,
            provider=ProviderName.MINIMAX,
            model="MiniMax-M2.7",
            protocol=ProtocolKind.OPENAI_COMPATIBLE,
            qualification_ref="synthetic",
            meter_version="synthetic",
            qualified_window=8192,
            qualified_output_limit=20,
            output_parameter="max_tokens",
            output_limit=20,
        )
        if invocation is not None and invocation.model_call_id is not None
        else None
    )
    receipt = ledger.reserve(
        tenant_id=scope_id(ids, "tenant_a"),
        run_id=claim.id,
        attempt_id=uuid4(),
        call_kind="model",
        input_tokens=10,
        output_tokens=20,
        tenant_daily_token_limit=1000,
        request_binding=binding,
    )
    if invocation is not None:
        assert invocation.context_receipt_id is not None
        manifest = freeze_manifest(
            AgentObservations(agent, store),
            receipt_id=invocation.context_receipt_id,
            attempt_id=receipt.entry.attempt_id,
            qualification=qualification().model_dump(mode="json"),
            removed_paths=(),
        )
        assert manifest is not None and manifest.observation_ids
    return ledger, RestrictedBudgetTransitions(agent, store), receipt.entry.attempt_id


def usage() -> BudgetUsageEvidence:
    return BudgetUsageEvidence(
        request_digest="a" * 64, input_tokens=7, output_tokens=3, request_id="synthetic-中文"
    )


def latest(owner: Engine) -> RowMapping:
    with owner.connect() as c:
        return (
            c.execute(
                select(tables.budget_journal)
                .order_by(tables.budget_journal.c.revision.desc())
                .limit(1)
            )
            .mappings()
            .one()
        )


def test_scoped_dispatch_unknown_settle_and_owner_replay(scope: BudgetScope) -> None:
    owner, _, _, _, ids, _ = scope
    ledger, port, attempt = prepare(scope)
    grant = port.transition(attempt_id=attempt, action="dispatch")
    assert grant.dispatch_granted and grant.revision == 2
    assert not port.transition(attempt_id=attempt, action="dispatch").dispatch_granted
    unknown = port.transition(attempt_id=attempt, action="unknown")
    assert unknown.entry.held_tokens == 30 and unknown.entry.charged_tokens is None
    assert not port.transition(attempt_id=attempt, action="unknown").changed
    with pytest.raises(BudgetLedgerError, match="TRANSITION_INVALID"):
        port.transition(attempt_id=attempt, action="cancel")
    evidence = usage()
    settled = port.transition(attempt_id=attempt, action="settle", evidence=evidence)
    assert settled.entry.charged_tokens == 10 and settled.entry.held_tokens == 0
    assert settled.entry.reconciliation_ref == evidence.evidence_ref
    assert not port.transition(attempt_id=attempt, action="settle", evidence=evidence).changed
    assert not ledger.transition(
        tenant_id=scope_id(ids, "tenant_a"),
        attempt_id=attempt,
        action="settle",
        charged_tokens=10,
        reconciliation_ref=evidence.evidence_ref,
        provider_request_id=evidence.request_id,
        usage_evidence=evidence,
    ).changed
    assert latest(owner)["revision"] == 4


def test_cancel_before_dispatch_is_idempotent_and_never_grants(scope: BudgetScope) -> None:
    _, port, attempt = prepare(scope)
    assert port.transition(attempt_id=attempt, action="cancel").entry.held_tokens == 0
    assert not port.transition(attempt_id=attempt, action="cancel").changed
    with pytest.raises(BudgetLedgerError, match="TRANSITION_INVALID"):
        port.transition(attempt_id=attempt, action="dispatch")


@pytest.mark.parametrize("mixed", [False, True])
def test_concurrent_dispatch_grants_once_across_owner_and_agent_ports(
    scope: BudgetScope, mixed: bool
) -> None:
    _, agent, store, claim, ids, _ = scope
    ledger, _, attempt = prepare(scope)
    barrier = Barrier(2)

    def dispatch(index: int) -> bool:
        with store.scope(claim):
            barrier.wait()
            if index and mixed:
                return ledger.transition(
                    tenant_id=scope_id(ids, "tenant_a"), attempt_id=attempt, action="dispatch"
                ).dispatch_granted
            return (
                RestrictedBudgetTransitions(agent, store)
                .transition(attempt_id=attempt, action="dispatch")
                .dispatch_granted
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(dispatch, range(2))) == [False, True]


def test_unbound_reservation_and_invented_attempt_denied(scope: BudgetScope) -> None:
    _, port, attempt = prepare(scope, bound=False)
    with pytest.raises(BudgetLedgerError, match="BINDING_REQUIRED"):
        port.transition(attempt_id=attempt, action="dispatch")
    with pytest.raises(BudgetLedgerError, match="ATTEMPT_NOT_FOUND"):
        port.transition(attempt_id=uuid4(), action="dispatch")


@pytest.mark.parametrize(
    "setting", ["pdos.agent_lease_token", "pdos.tenant_id", "pdos.project_id", "pdos.agent_run_id"]
)
def test_forged_scope_never_mutates(scope: BudgetScope, setting: str) -> None:
    owner, agent, store, _, ids, _ = scope
    _, _, attempt = prepare(scope)
    value = scope_id(ids, "tenant_b") if setting == "pdos.tenant_id" else uuid4()
    with agent.begin() as c:
        store.bind(c)
        c.execute(
            text("SELECT set_config(:key, :value, true)"), dict(key=setting, value=str(value))
        )
        denied(
            c,
            "SELECT cehub_ai.agent_transition_model_budget(:attempt, :action, NULL)",
            dict(attempt=attempt, action="dispatch"),
        )
    assert latest(owner)["revision"] == 1


def test_unbound_session_direct_tables_common_function_and_worker_denied(
    scope: BudgetScope, secured_agent_database_url: str
) -> None:
    _, agent, store, claim, ids, _ = scope
    _, _, attempt = prepare(scope)
    with agent.begin() as c:
        denied(
            c,
            "SELECT cehub_ai.agent_transition_model_budget(:a, :x, NULL)",
            dict(a=attempt, x="dispatch"),
        )
        store.bind(c)
        denied(
            c,
            "SELECT cehub_ai.transition_bound_model_budget(:t, :r, :a, :x, NULL)",
            dict(t=scope_id(ids, "tenant_a"), r=claim.id, a=attempt, x="dispatch"),
        )
        for table in ["budget_journal", "budget_lineages", "budget_run_links"]:
            denied(c, f"SELECT * FROM cehub_ai.{table}", {})
            denied(c, f"INSERT INTO cehub_ai.{table} DEFAULT VALUES", {})
            denied(c, f"DELETE FROM cehub_ai.{table}", {})
        denied(c, "UPDATE cehub_project.projects SET id = id", {})
    worker = role_engine(secured_agent_database_url, "pdos_worker")
    try:
        with worker.begin() as c:
            denied(
                c,
                "SELECT cehub_ai.agent_transition_model_budget(:a, :x, NULL)",
                dict(a=attempt, x="dispatch"),
            )
    finally:
        worker.dispose()


@pytest.mark.parametrize("state", ["succeeded", "rotated"])
def test_revoked_execution_cannot_dispatch(scope: BudgetScope, state: str) -> None:
    owner, _, _, claim, _, _ = scope
    _, port, attempt = prepare(scope)
    with owner.begin() as c:
        values = (
            {"run_context": {"_lease_token": str(uuid4())}}
            if state == "rotated"
            else {"status": state, "completed_at": datetime.now(UTC)}
        )
        c.execute(
            update(tables.agent_runs).where(tables.agent_runs.c.id == claim.id).values(**values)
        )
    with pytest.raises(AgentLeaseLostError, match="AGENT_RUN_LEASE_LOST"):
        port.transition(attempt_id=attempt, action="dispatch")
    assert latest(owner)["dispatched_at"] is None


@pytest.mark.parametrize("bad", [None, "{}", "[]", "broken", "null", '{"input_tokens":true}'])
def test_sql_rejects_missing_or_malformed_receipt_without_releasing_hold(
    scope: BudgetScope, bad: str | None
) -> None:
    owner, agent, store, _, _, _ = scope
    _, port, attempt = prepare(scope)
    port.transition(attempt_id=attempt, action="dispatch")
    with agent.begin() as c:
        store.bind(c)
        denied(
            c,
            "SELECT cehub_ai.agent_transition_model_budget(:a, :x, :body)",
            dict(a=attempt, x="settle", body=bad),
            sqlstate="22023",
        )
    assert latest(owner)["held_tokens"] == 30 and latest(owner)["revision"] == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("input_tokens", True),
        ("input_tokens", -1),
        ("input_tokens", 1.1),
        ("cache_read_tokens", 100),
        ("request_digest", "b" * 64),
        ("request_id", {}),
        ("extra", "x"),
    ],
)
def test_sql_revalidates_receipt_when_python_is_bypassed(
    scope: BudgetScope, field: str, value: object
) -> None:
    owner, agent, store, _, _, _ = scope
    _, port, attempt = prepare(scope)
    port.transition(attempt_id=attempt, action="dispatch")
    data = usage().model_dump()
    data[field] = value
    with agent.begin() as c:
        store.bind(c)
        denied(
            c,
            "SELECT cehub_ai.agent_transition_model_budget(:a, :x, :body)",
            dict(a=attempt, x="settle", body=json.dumps(data)),
            sqlstate="22023",
        )
    assert latest(owner)["held_tokens"] == 30 and latest(owner)["revision"] == 2


def test_actual_overrun_retained_and_changed_settlement_refused(scope: BudgetScope) -> None:
    _, port, attempt = prepare(scope)
    port.transition(attempt_id=attempt, action="dispatch")
    evidence = usage().model_copy(update={"input_tokens": 100, "output_tokens": 20})
    result = port.transition(attempt_id=attempt, action="settle", evidence=evidence)
    assert result.entry.charged_tokens == 120 and result.entry.reserved_tokens == 30
    with pytest.raises(BudgetLedgerError, match="SETTLEMENT_CONFLICT"):
        port.transition(attempt_id=attempt, action="settle", evidence=usage())


def test_same_tenant_other_run_attempt_is_not_visible(scope: BudgetScope) -> None:
    owner, _, _, claim, ids, _ = scope
    ledger, port, attempt = prepare(scope)
    with owner.begin() as connection:
        original = dict(
            connection.execute(select(tables.agent_runs).where(tables.agent_runs.c.id == claim.id))
            .mappings()
            .one()
        )
        other = uuid4()
        connection.execute(
            tables.agent_runs.insert(),
            {
                **original,
                "id": other,
                "window_started_at": original["window_started_at"] + timedelta(days=1),
                "window_ended_at": original["window_ended_at"] + timedelta(days=1),
            },
        )
    # A service can bind a second run to the existing lineage without resetting it.
    ledger.link_run(
        tenant_id=scope_id(ids, "tenant_a"), lineage_id=latest(owner)["lineage_id"], run_id=other
    )
    with owner.begin() as connection:
        original = dict(connection.execute(select(tables.budget_journal)).mappings().one())
        second_attempt = uuid4()
        connection.execute(
            tables.budget_journal.insert(),
            {
                **original,
                "id": uuid4(),
                "run_id": other,
                "attempt_id": second_attempt,
            },
        )
    with pytest.raises(BudgetLedgerError, match="BUDGET_ATTEMPT_NOT_FOUND"):
        port.transition(attempt_id=second_attempt, action="dispatch")
    assert port.transition(attempt_id=attempt, action="dispatch").dispatch_granted


def test_terminal_run_cannot_release_hold_but_owner_can_reconcile(scope: BudgetScope) -> None:
    owner, _, _, claim, ids, _ = scope
    ledger, port, attempt = prepare(scope)
    port.transition(attempt_id=attempt, action="dispatch")
    with owner.begin() as connection:
        connection.execute(
            update(tables.agent_runs)
            .where(tables.agent_runs.c.id == claim.id)
            .values(status="failed", error_code="SYNTHETIC_STOP", completed_at=datetime.now(UTC))
        )
    with pytest.raises(AgentLeaseLostError, match="AGENT_RUN_LEASE_LOST"):
        port.transition(attempt_id=attempt, action="settle", evidence=usage())
    assert latest(owner)["held_tokens"] == 30
    evidence = usage()
    reconciled = ledger.transition(
        tenant_id=scope_id(ids, "tenant_a"),
        attempt_id=attempt,
        action="settle",
        charged_tokens=10,
        reconciliation_ref=evidence.evidence_ref,
        provider_request_id=evidence.request_id,
        usage_evidence=evidence,
    )
    assert reconciled.entry.charged_tokens == 10 and reconciled.entry.held_tokens == 0


def test_empty_transition_migration_round_trip_and_private_function(scope: BudgetScope) -> None:
    owner, _, _, _, _, _ = scope
    transition = import_module("migrations.versions.0066_bound_budget_transition")
    reservation = import_module("migrations.versions.0067_model_budget_reservation")
    with rollback_migration_operations(owner) as connection:
        reservation.downgrade()
        transition.downgrade()
        transition.upgrade()
        reservation.upgrade()
        record = (
            connection.execute(
                text("""
            SELECT p.prosecdef, p.proconfig, NOT EXISTS (
                SELECT 1 FROM aclexplode(coalesce(p.proacl, acldefault('f', p.proowner)))
                WHERE grantee = 0 AND privilege_type = 'EXECUTE'
            ) AS private
            FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'cehub_ai' AND p.proname = 'transition_bound_model_budget'
        """)
            )
            .mappings()
            .one()
        )
    assert not record["prosecdef"] and record["private"]
    assert record["proconfig"] == ["search_path=pg_catalog"]


def test_downgrade_refuses_bound_transition_history(scope: BudgetScope) -> None:
    owner, _, _, _, _, _ = scope
    _, port, attempt = prepare(scope)
    port.transition(attempt_id=attempt, action="dispatch")
    for revision, expected in (
        ("0067_model_budget_reservation", "budget reservation history exists"),
        ("0066_bound_budget_transition", "bound budget transitions exist"),
    ):
        with (
            pytest.raises(RuntimeError, match=expected),
            rollback_migration_operations(owner),
        ):
            import_module(f"migrations.versions.{revision}").downgrade()
    assert latest(owner)["revision"] == 2
