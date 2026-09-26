"""Independent pdos_test: database clocks, cumulative time and actual scoped model ports."""

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event
from uuid import UUID, uuid4

import httpx2
import pytest
from alembic import command
from alembic.config import Config
from psycopg import Error as PsycopgError
from sqlalchemy import Engine, select, text, update
from sqlalchemy.exc import DBAPIError

from app.ai.budget_ledger import BudgetLedger, BudgetLedgerError, BudgetReceipt
from app.ai.run_store import ClaimedAgentRun, RestrictedAgentRunStore
from app.db.schema import tables
from tests.test_agent_checkpoints import CheckpointSetup, scope_id
from tests.test_agent_checkpoints import setup as setup
from tests.test_agent_database_security import (
    secured_agent_database_url as secured_agent_database_url,
)
from tests.test_budget_ledger import SERVER_ROOT, profile, reserve
from tests.test_budget_ledger import ledger_db as ledger_db
from tests.test_event_budget_adoption import event_scope as event_scope
from tests.test_model_budget_controller import (
    LedgerDatabase,
    call,
    controller,
    gateway,
    response,
    rows,
)
from tests.test_model_call_fence_security import scope as scope
from tests.test_model_gateway import RiskOutput

ModelCallScope = tuple[
    Engine, Engine, RestrictedAgentRunStore, ClaimedAgentRun, dict[str, UUID | int], UUID
]


def pause(engine: Engine, seconds: float) -> None:
    with engine.connect() as c:
        c.execute(text("SELECT pg_sleep(:seconds)"), {"seconds": seconds})


def finish(engine: Engine, run: UUID) -> None:
    with engine.begin() as c:
        c.execute(
            update(tables.agent_runs)
            .where(tables.agent_runs.c.id == run)
            .values(status="succeeded", completed_at=datetime(2100, 1, 1, tzinfo=UTC))
        )


def span_time(span: Mapping[str, object], field: str) -> datetime:
    value = span[field]
    assert isinstance(value, datetime)
    return value


def test_linked_run_wait_does_not_spend_or_reset_cumulative_activity(
    ledger_db: LedgerDatabase,
) -> None:
    engine, tenant, runs = ledger_db
    ledger = BudgetLedger(engine)
    policy = profile(active_seconds=1)
    lineage = ledger.open_lineage(tenant_id=tenant, run_id=runs[0], profile=policy)
    pause(engine, 0.35)
    finish(engine, runs[0])
    first = rows(engine, tables.budget_activity_spans)[0]
    assert (
        0.3 <= (span_time(first, "stopped_at") - span_time(first, "started_at")).total_seconds() < 1
    )
    pause(engine, 1.1)  # Human waiting between actual parent and child runs.
    ledger.require_active(tenant_id=tenant, run_id=runs[0])
    ledger.link_run(tenant_id=tenant, lineage_id=lineage, run_id=runs[1])
    pause(engine, 0.75)
    for run in runs[:2]:
        with pytest.raises(BudgetLedgerError, match="BUDGET_ACTIVE_TIME_EXHAUSTED"):
            ledger.require_active(tenant_id=tenant, run_id=run)
    assert span_time(rows(engine, tables.budget_activity_spans)[0], "started_at").year != 2100
    assert len(rows(engine, tables.budget_activity_spans)) == 2


def test_queued_runs_start_only_when_claimed_and_same_run_resume_keeps_history(
    ledger_db: LedgerDatabase,
) -> None:
    engine, tenant, runs = ledger_db
    ledger = BudgetLedger(engine)
    with engine.begin() as c:
        c.execute(
            update(tables.agent_runs)
            .where(tables.agent_runs.c.id == runs[0])
            .values(status="queued", started_at=None)
        )
    ledger.open_lineage(tenant_id=tenant, run_id=runs[0], profile=profile(active_seconds=1))
    pause(engine, 1.1)
    assert not rows(engine, tables.budget_activity_spans)
    with engine.begin() as c:
        c.execute(
            update(tables.agent_runs)
            .where(tables.agent_runs.c.id == runs[0])
            .values(status="running", started_at=datetime(2100, 1, 1, tzinfo=UTC))
        )
        c.execute(
            update(tables.agent_runs)
            .where(tables.agent_runs.c.id == runs[0])
            .values(run_context={"server_test": True})
        )
    assert len(rows(engine, tables.budget_activity_spans)) == 1
    pause(engine, 0.4)
    finish(engine, runs[0])
    with engine.begin() as c:
        c.execute(
            update(tables.agent_runs)
            .where(tables.agent_runs.c.id == runs[0])
            .values(status="running", completed_at=None)
        )
    pause(engine, 0.7)
    assert len(rows(engine, tables.budget_activity_spans)) == 2
    with pytest.raises(BudgetLedgerError, match="BUDGET_ACTIVE_TIME_EXHAUSTED"):
        reserve(ledger, tenant, runs[0])


def test_event_lease_adoption_keeps_the_original_activity_segment(
    ledger_db: LedgerDatabase,
) -> None:
    engine, tenant, runs = ledger_db
    BudgetLedger(engine).open_lineage(tenant_id=tenant, run_id=runs[0], profile=profile())
    before = rows(engine, tables.budget_activity_spans)[0]
    token = uuid4()
    with engine.begin() as c:
        c.execute(
            text("""UPDATE cehub_ai.agent_runs SET run_context=run_context ||
          jsonb_build_object('_lease_token',CAST(:token AS text),
           '_lease_expires_at',clock_timestamp()+interval '60 seconds') WHERE id=:run"""),
            dict(token=str(token), run=runs[0]),
        )
    after = sorted(
        rows(engine, tables.budget_activity_spans), key=lambda r: span_time(r, "started_at")
    )
    assert len(after) == 2
    assert after[0]["id"] == before["id"] and after[0]["lease_token"] is None
    assert after[0]["stopped_at"] is not None
    assert after[1]["lease_token"] == token and after[1]["stopped_at"] is None


def test_active_deadline_denies_dispatch_but_preserves_cancellation_and_settlement(
    ledger_db: LedgerDatabase,
) -> None:
    engine, tenant, runs = ledger_db
    ledger = BudgetLedger(engine)
    ledger.open_lineage(tenant_id=tenant, run_id=runs[0], profile=profile(active_seconds=1))
    first = reserve(ledger, tenant, runs[0])
    pause(engine, 1.1)
    with pytest.raises(BudgetLedgerError, match="BUDGET_ACTIVE_TIME_EXHAUSTED"):
        ledger.transition(tenant_id=tenant, attempt_id=first.entry.attempt_id, action="dispatch")
    assert (
        ledger.transition(
            tenant_id=tenant, attempt_id=first.entry.attempt_id, action="cancel"
        ).entry.held_tokens
        == 0
    )
    assert not reserve(ledger, tenant, runs[0], first.entry.attempt_id).changed
    with pytest.raises(BudgetLedgerError, match="BUDGET_ACTIVE_TIME_EXHAUSTED"):
        reserve(ledger, tenant, runs[0])


@pytest.mark.parametrize("limit", ["active", "lifetime"])
def test_late_owner_gateway_response_keeps_actual_usage_and_withholds_output(
    ledger_db: LedgerDatabase, limit: str
) -> None:
    engine, tenant, runs = ledger_db
    calls: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        pause(engine, 1.1)
        return response()

    with httpx2.Client(transport=httpx2.MockTransport(respond)) as client:
        result = gateway(
            engine,
            client,
            controller(
                engine,
                budget_profile=profile(
                    active_seconds=1, lifetime_seconds=1 if limit == "lifetime" else 86400
                ),
            ),
        ).invoke_structured(call(tenant, runs[0]), RiskOutput)
    expected = "BUDGET_LINEAGE_EXPIRED" if limit == "lifetime" else "BUDGET_ACTIVE_TIME_EXHAUSTED"
    assert result.error_code == expected and result.output is None
    assert len(calls) == 1
    assert rows(engine)[-1]["charged_tokens"] == 10 and rows(engine)[-1]["held_tokens"] == 0
    trace = rows(engine, tables.model_invocations)[0]
    assert trace["total_tokens"] == 10 and trace["usage_status"] == "known"
    assert rows(engine, tables.model_call_events)[-1]["state"] == "closed"


def test_old_lineage_activity_is_unknown_instead_of_reset_on_upgrade(
    ledger_db: LedgerDatabase,
) -> None:
    engine, tenant, runs = ledger_db
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    command.downgrade(config, "0071_agent_lease_expiry")
    ledger = BudgetLedger(engine)
    ledger.open_lineage(tenant_id=tenant, run_id=runs[0], profile=profile())
    command.upgrade(config, "head")
    assert not rows(engine, tables.budget_activity_coverage)
    with pytest.raises(BudgetLedgerError, match="BUDGET_ACTIVE_HISTORY_UNAVAILABLE"):
        reserve(ledger, tenant, runs[0])


def test_history_is_trigger_owned_and_protected_from_downgrade(ledger_db: LedgerDatabase) -> None:
    engine, tenant, runs = ledger_db
    BudgetLedger(engine).open_lineage(tenant_id=tenant, run_id=runs[0], profile=profile())
    for table in (tables.budget_activity_coverage, tables.budget_activity_spans):
        with pytest.raises(DBAPIError, match="lifecycle triggers"), engine.begin() as c:
            c.execute(table.delete())
        with pytest.raises(DBAPIError, match="lifecycle triggers"), engine.begin() as c:
            c.execute(table.update().values(started_at=datetime.now(UTC)))
    with pytest.raises(DBAPIError, match="persistent budget history"):
        command.downgrade(Config(str(SERVER_ROOT / "alembic.ini")), "0071_agent_lease_expiry")


def test_activity_schema_matches_metadata(ledger_db: LedgerDatabase) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.db.schema import metadata

    engine, _, _ = ledger_db
    with engine.connect() as c:
        context = MigrationContext.configure(
            c,
            opts={
                "include_schemas": True,
                "compare_server_default": True,
                "include_object": lambda obj, name, kind, reflected, compared: (
                    kind != "table" or name in {"budget_activity_coverage", "budget_activity_spans"}
                ),
            },
        )
        assert compare_metadata(context, metadata) == []


def test_activity_binding_rollback_is_atomic(ledger_db: LedgerDatabase) -> None:
    engine, tenant, runs = ledger_db
    with pytest.raises(RuntimeError, match="rollback"), engine.begin() as c:
        now = c.execute(text("SELECT clock_timestamp()")).scalar_one()
        lineage = uuid4()
        c.execute(
            tables.budget_lineages.insert().values(
                id=lineage,
                tenant_id=tenant,
                profile=profile().model_dump(mode="json"),
                profile_digest="a" * 64,
                created_at=now,
                absolute_deadline=text("clock_timestamp() + interval '1 day'"),
            )
        )
        c.execute(
            tables.budget_run_links.insert().values(
                tenant_id=tenant, run_id=runs[0], lineage_id=lineage, created_at=now
            )
        )
        assert c.execute(select(tables.budget_activity_spans)).first()
        raise RuntimeError("rollback")
    for table in (
        tables.budget_lineages,
        tables.budget_run_links,
        tables.budget_activity_coverage,
        tables.budget_activity_spans,
    ):
        assert not rows(engine, table)


def test_expired_worker_stops_activity_clock_at_lease_deadline(ledger_db: LedgerDatabase) -> None:
    engine, tenant, runs = ledger_db
    with engine.begin() as c:
        c.execute(
            text("""UPDATE cehub_ai.agent_runs SET run_context=jsonb_build_object(
                '_lease_token',CAST(:token AS text),
                '_lease_expires_at',clock_timestamp()+interval '0.4 seconds')
            WHERE id=:run"""),
            {"token": str(uuid4()), "run": runs[0]},
        )
    ledger = BudgetLedger(engine)
    ledger.open_lineage(tenant_id=tenant, run_id=runs[0], profile=profile(active_seconds=1))
    pause(engine, 1.1)
    ledger.require_active(tenant_id=tenant, run_id=runs[0])
    span = rows(engine, tables.budget_activity_spans)[0]
    assert (
        0
        < (span_time(span, "lease_expires_at") - span_time(span, "started_at")).total_seconds()
        < 0.5
    )


def test_finding_publication_rechecks_time_at_database_write(ledger_db: LedgerDatabase) -> None:
    engine, tenant, runs = ledger_db
    ledger = BudgetLedger(engine)
    ledger.open_lineage(tenant_id=tenant, run_id=runs[0], profile=profile(active_seconds=1))
    pause(engine, 1.1)
    # The trigger denies before checking payload constraints; no provider or business write.
    with pytest.raises(DBAPIError, match="BUDGET_ACTIVE_TIME_EXHAUSTED"), engine.begin() as c:
        c.execute(
            text("INSERT INTO cehub_ai.findings(tenant_id,run_id) VALUES(:t,:r)"),
            {"t": tenant, "r": runs[0]},
        )
    assert not rows(engine, tables.findings)


def test_reservation_rechecks_activity_after_waiting_for_run_lock(
    ledger_db: LedgerDatabase,
) -> None:
    engine, tenant, runs = ledger_db
    ledger = BudgetLedger(engine)
    ledger.open_lineage(tenant_id=tenant, run_id=runs[0], profile=profile(active_seconds=1))
    entered = Event()

    def waiting() -> BudgetReceipt:
        entered.set()
        return reserve(ledger, tenant, runs[0])

    with ThreadPoolExecutor(max_workers=1) as pool:
        with engine.begin() as c:
            c.execute(
                text("SELECT id FROM cehub_ai.agent_runs WHERE id=:run FOR UPDATE"),
                {"run": runs[0]},
            )
            future = pool.submit(waiting)
            assert entered.wait(2)
            c.execute(text("SELECT pg_sleep(1.1)"))
        with pytest.raises(BudgetLedgerError, match="BUDGET_ACTIVE_TIME_EXHAUSTED"):
            future.result(timeout=5)
    assert not rows(engine)


def test_claimed_legacy_run_rejects_late_budget_binding(scope: ModelCallScope) -> None:
    from app.ai.lease_heartbeat import AgentLeaseLostError

    owner, _, store, claim, ids, _ = scope
    # This negative case deliberately never issues a new event authorization.
    # The shared prepare helper now does so and would turn it into an authorized run.
    BudgetLedger(owner).open_lineage(
        tenant_id=scope_id(ids, "tenant_a"), run_id=claim.id, profile=profile(active_seconds=1)
    )
    with pytest.raises(AgentLeaseLostError):
        store.renew(claim)
    assert rows(owner, tables.model_invocations) == []
    assert rows(owner, tables.budget_journal) == []


def test_authorized_restricted_activity_scope_preserves_renewal_and_table_isolation(
    setup: CheckpointSetup,
) -> None:
    from app.ai.agent_budget import RestrictedBudgetLedger

    owner, _, agent, ids, _, _, _ = setup
    store = RestrictedAgentRunStore(agent)
    claim = store.claim(started_at=datetime.now(UTC))
    assert claim is not None
    with store.scope(claim):
        port = RestrictedBudgetLedger(agent, store)
        started = rows(owner, tables.budget_activity_spans)[0]["started_at"]
        store.renew(claim)
        assert rows(owner, tables.budget_activity_spans)[0]["started_at"] == started
        port.require_active(tenant_id=scope_id(ids, "tenant_a"), run_id=claim.id)
        with pytest.raises(BudgetLedgerError, match="BUDGET_RUN_SCOPE_INVALID"):
            port.require_active(tenant_id=uuid4(), run_id=claim.id)
        with agent.begin() as c:
            store.bind(c)
            for sql in [
                "SELECT * FROM cehub_ai.budget_activity_spans",
                "DELETE FROM cehub_ai.budget_activity_coverage",
                "SELECT cehub_ai.check_run_active_budget(:tenant,:run)",
            ]:
                with pytest.raises(DBAPIError) as denied, c.begin_nested():
                    c.execute(text(sql), {"tenant": ids["tenant_a"], "run": claim.id})
                assert isinstance(denied.value.orig, PsycopgError)
                assert denied.value.orig.sqlstate == "42501"
