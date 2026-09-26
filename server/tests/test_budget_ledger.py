"""Real PostgreSQL token admission and recovery; no model/provider calls."""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, select, text, update
from sqlalchemy.exc import DBAPIError

from app.ai.budget_ledger import BudgetLedger, BudgetLedgerError, BudgetReceipt
from app.contracts.runtime_policy import RunBudgetProfile
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from tests.db_cleanup import clear_test_tenants
from tests.test_findings_service import seed_reviewable_finding

SERVER_ROOT = Path(__file__).resolve().parents[1]
LedgerFixture = tuple[Engine, UUID, list[UUID]]


def profile(**changes: object) -> RunBudgetProfile:
    return RunBudgetProfile.model_validate(
        {
            "key": "synthetic-test",
            "version": "test-v1",
            "input_token_limit": 80,
            "output_token_reserve": 20,
            "lineage_token_limit": 200,
            "tool_call_limit": 4,
            "model_call_limit": 3,
            "active_seconds": 60,
            "lifetime_seconds": 86400,
            **changes,
        }
    )


@pytest.fixture
def ledger_db() -> Iterator[tuple[Engine, UUID, list[UUID]]]:
    url = configured_test_database_url()
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    command.upgrade(Config(str(SERVER_ROOT / "alembic.ini")), "head")
    engine = create_engine(psycopg_database_url(url))
    try:
        with engine.begin() as connection:
            clear_test_tenants(connection)
        ids = seed_reviewable_finding(url)
        # This fixture needs a valid run/project, not the helper's unrelated
        # model trace and Finding. Keep those out of budget accounting fixtures.
        with engine.begin() as connection:
            connection.execute(
                text("TRUNCATE cehub_ai.findings, cehub_ai.model_invocations CASCADE")
            )
        tenant_id, root_run = UUID(str(ids["tenant_id"])), UUID(str(ids["run_id"]))
        runs = [root_run]
        with engine.begin() as connection:
            connection.execute(
                update(tables.agent_runs).values(status="running", completed_at=None)
            )
            original = dict(connection.execute(select(tables.agent_runs)).mappings().one())
            for index in range(1, 4):
                row = {
                    **original,
                    "id": uuid4(),
                    "window_started_at": original["window_started_at"] + timedelta(days=index),
                    "window_ended_at": original["window_ended_at"] + timedelta(days=index),
                }
                connection.execute(tables.agent_runs.insert(), row)
                runs.append(row["id"])
        yield engine, tenant_id, runs
    finally:
        with engine.begin() as connection:
            clear_test_tenants(connection)
        engine.dispose()
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def reserve(
    ledger: BudgetLedger,
    tenant: UUID,
    run: UUID,
    attempt: UUID | None = None,
    *,
    tokens: int = 80,
    limit: int = 1000,
) -> BudgetReceipt:
    return ledger.reserve(
        tenant_id=tenant,
        run_id=run,
        attempt_id=attempt or uuid4(),
        call_kind="model",
        input_tokens=tokens,
        output_tokens=0,
        tenant_daily_token_limit=limit,
    )


def settle(ledger: BudgetLedger, tenant: UUID, attempt: UUID, tokens: int = 60) -> BudgetReceipt:
    assert ledger.transition(
        tenant_id=tenant, attempt_id=attempt, action="dispatch"
    ).dispatch_granted
    return ledger.transition(
        tenant_id=tenant,
        attempt_id=attempt,
        action="settle",
        charged_tokens=tokens,
        reconciliation_ref="synthetic-usage:verified",
    )


def test_linked_runs_share_frozen_profile_and_do_not_reset_usage(ledger_db: LedgerFixture) -> None:
    engine, tenant, runs = ledger_db
    ledger = BudgetLedger(engine)
    lineage = ledger.open_lineage(tenant_id=tenant, run_id=runs[0], profile=profile())
    assert ledger.open_lineage(tenant_id=tenant, run_id=runs[0], profile=profile()) == lineage
    with pytest.raises(BudgetLedgerError, match="PROFILE_CONFLICT"):
        ledger.open_lineage(
            tenant_id=tenant, run_id=runs[0], profile=profile(lineage_token_limit=400)
        )
    ledger.link_run(tenant_id=tenant, lineage_id=lineage, run_id=runs[1])
    first = reserve(ledger, tenant, runs[0])
    settle(ledger, tenant, first.entry.attempt_id, 150)
    with pytest.raises(BudgetLedgerError, match="LINEAGE_TOKENS_EXHAUSTED"):
        reserve(ledger, tenant, runs[1])
    with engine.connect() as c:
        assert c.execute(select(tables.budget_lineages.c.id)).scalars().all() == [lineage]
        assert len(c.execute(select(tables.budget_journal)).all()) == 3


def test_attempt_replay_unknown_and_settlement_preserve_full_hold(ledger_db: LedgerFixture) -> None:
    engine, tenant, runs = ledger_db
    ledger = BudgetLedger(engine)
    ledger.open_lineage(tenant_id=tenant, run_id=runs[0], profile=profile())
    attempt = uuid4()
    assert reserve(ledger, tenant, runs[0], attempt).changed
    assert not reserve(ledger, tenant, runs[0], attempt).changed
    with pytest.raises(BudgetLedgerError, match="ATTEMPT_CONFLICT"):
        reserve(ledger, tenant, runs[0], attempt, tokens=70)
    assert ledger.transition(
        tenant_id=tenant, attempt_id=attempt, action="dispatch"
    ).dispatch_granted
    assert not ledger.transition(
        tenant_id=tenant, attempt_id=attempt, action="dispatch"
    ).dispatch_granted
    unknown = ledger.transition(tenant_id=tenant, attempt_id=attempt, action="unknown")
    assert unknown.entry.held_tokens == 80 and unknown.entry.charged_tokens is None
    assert unknown.entry.reserved_cost_microusd is None
    with pytest.raises(BudgetLedgerError, match="TRANSITION_INVALID"):
        ledger.transition(tenant_id=tenant, attempt_id=attempt, action="cancel")
    with pytest.raises(BudgetLedgerError, match="LINEAGE_CALL_BUSY"):
        reserve(ledger, tenant, runs[0])
    settled = ledger.transition(
        tenant_id=tenant,
        attempt_id=attempt,
        action="settle",
        charged_tokens=95,
        reconciliation_ref="synthetic:usage-1",
    )
    assert settled.entry.held_tokens == 0 and settled.entry.charged_tokens == 95
    assert not ledger.transition(
        tenant_id=tenant,
        attempt_id=attempt,
        action="settle",
        charged_tokens=95,
        reconciliation_ref="synthetic:usage-1",
    ).changed
    with pytest.raises(BudgetLedgerError, match="SETTLEMENT_CONFLICT"):
        ledger.transition(
            tenant_id=tenant,
            attempt_id=attempt,
            action="settle",
            charged_tokens=0,
            reconciliation_ref="synthetic:usage-1",
        )
    assert not reserve(ledger, tenant, runs[0], attempt).changed
    assert reserve(ledger, tenant, runs[0]).entry.held_tokens == 80


def test_pre_dispatch_cancellation_releases_reservation_and_call_count(
    ledger_db: LedgerFixture,
) -> None:
    engine, tenant, runs = ledger_db
    ledger = BudgetLedger(engine)
    ledger.open_lineage(tenant_id=tenant, run_id=runs[0], profile=profile(model_call_limit=1))
    first = reserve(ledger, tenant, runs[0])
    cancelled = ledger.transition(
        tenant_id=tenant, attempt_id=first.entry.attempt_id, action="cancel"
    )
    assert cancelled.entry.charged_tokens == cancelled.entry.held_tokens == 0
    second = reserve(ledger, tenant, runs[0])
    settle(ledger, tenant, second.entry.attempt_id, 20)
    with pytest.raises(BudgetLedgerError, match="CALL_COUNT_EXHAUSTED"):
        reserve(ledger, tenant, runs[0])


def test_concurrent_same_attempt_gets_one_reservation_and_one_dispatch(
    ledger_db: LedgerFixture,
) -> None:
    engine, tenant, runs = ledger_db
    BudgetLedger(engine).open_lineage(tenant_id=tenant, run_id=runs[0], profile=profile())
    attempt = uuid4()
    barrier = Barrier(2)

    def work(_: int) -> tuple[bool, bool]:
        ledger = BudgetLedger(engine)
        barrier.wait()
        result = reserve(ledger, tenant, runs[0], attempt)
        sent = ledger.transition(tenant_id=tenant, attempt_id=attempt, action="dispatch")
        return result.changed, sent.dispatch_granted

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(work, range(2)))
    assert sum(r[0] for r in results) == sum(r[1] for r in results) == 1


@pytest.mark.parametrize(
    "limit,expected", [(120, "TENANT_TOKENS_EXHAUSTED"), (1000, "TENANT_CALL_BUSY")]
)
def test_concurrent_lineages_cannot_over_reserve_tenant(
    ledger_db: LedgerFixture, limit: int, expected: str
) -> None:
    engine, tenant, runs = ledger_db
    ledger = BudgetLedger(engine)
    for run in runs[:3]:
        ledger.open_lineage(tenant_id=tenant, run_id=run, profile=profile())
    barrier = Barrier(3)

    def work(run: UUID) -> int | str:
        barrier.wait()
        try:
            return reserve(BudgetLedger(engine), tenant, run, limit=limit).entry.held_tokens
        except BudgetLedgerError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(work, runs[:3]))
    assert sum(isinstance(r, int) for r in results) == (1 if limit == 120 else 2)
    assert f"BUDGET_{expected}" in results


def test_tenant_and_run_binding_fail_closed(ledger_db: LedgerFixture) -> None:
    engine, tenant, runs = ledger_db
    ledger = BudgetLedger(engine)
    lineage = ledger.open_lineage(tenant_id=tenant, run_id=runs[0], profile=profile())
    with pytest.raises(BudgetLedgerError, match="RUN_SCOPE_INVALID"):
        ledger.open_lineage(tenant_id=uuid4(), run_id=runs[0], profile=profile())
    with pytest.raises(BudgetLedgerError, match="LINEAGE_SCOPE_INVALID"):
        ledger.link_run(tenant_id=tenant, lineage_id=uuid4(), run_id=runs[1])
    other = ledger.open_lineage(tenant_id=tenant, run_id=runs[1], profile=profile())
    assert other != lineage
    with pytest.raises(BudgetLedgerError, match="RUN_ALREADY_BOUND"):
        ledger.link_run(tenant_id=tenant, lineage_id=lineage, run_id=runs[1])
    with pytest.raises(BudgetLedgerError, match="RUN_SCOPE_INVALID"):
        reserve(ledger, uuid4(), runs[0])


def test_journal_and_bindings_are_append_only_and_downgrade_preserves_evidence(
    ledger_db: LedgerFixture,
) -> None:
    engine, tenant, runs = ledger_db
    with engine.connect() as c:
        original_head = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    command.downgrade(config, "0059_invocation_cost_evidence")
    command.upgrade(config, "head")
    ledger = BudgetLedger(engine)
    ledger.open_lineage(tenant_id=tenant, run_id=runs[0], profile=profile())
    first = reserve(ledger, tenant, runs[0])
    settle(ledger, tenant, first.entry.attempt_id)
    for table in (tables.budget_lineages, tables.budget_run_links, tables.budget_journal):
        with pytest.raises(DBAPIError, match="append-only"), engine.begin() as c:
            c.execute(table.delete())
    with pytest.raises(DBAPIError, match="append-only"), engine.begin() as c:
        c.execute(update(tables.budget_journal).values(charged_tokens=0))
    # The current outer migration protects the same persistent budget history
    # before older migrations are reached; this does not test their guard in isolation.
    with pytest.raises(DBAPIError, match="persistent budget history"):
        command.downgrade(config, "0059_invocation_cost_evidence")
    with engine.connect() as c:
        assert (
            c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == original_head
        )


def test_unknown_hold_survives_utc_day_change(
    ledger_db: LedgerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, tenant, runs = ledger_db
    ledger = BudgetLedger(engine)
    real_lock = ledger._lock
    offset = timedelta(days=-1)

    def clock(connection: Connection, tenant_id: UUID) -> datetime:
        return real_lock(connection, tenant_id) + offset

    monkeypatch.setattr(ledger, "_lock", clock)
    for run in runs[:2]:
        ledger.open_lineage(tenant_id=tenant, run_id=run, profile=profile(lifetime_seconds=604800))
    first = reserve(ledger, tenant, runs[0])
    ledger.transition(tenant_id=tenant, attempt_id=first.entry.attempt_id, action="dispatch")
    ledger.transition(tenant_id=tenant, attempt_id=first.entry.attempt_id, action="unknown")
    offset = timedelta(0)
    with pytest.raises(BudgetLedgerError, match="TENANT_TOKENS_EXHAUSTED"):
        reserve(ledger, tenant, runs[1], limit=120)
    ledger.transition(
        tenant_id=tenant,
        attempt_id=first.entry.attempt_id,
        action="settle",
        charged_tokens=20,
        reconciliation_ref="synthetic-next-day-reconciliation",
    )
    assert reserve(ledger, tenant, runs[1], limit=120).changed


def test_expiry_blocks_dispatch_without_renewing_lineage(ledger_db: LedgerFixture) -> None:
    engine, tenant, runs = ledger_db
    ledger = BudgetLedger(engine)
    from time import sleep

    policy = profile(active_seconds=1, lifetime_seconds=2)
    lineage = ledger.open_lineage(tenant_id=tenant, run_id=runs[0], profile=policy)
    first = reserve(ledger, tenant, runs[0])
    sleep(2.05)
    assert ledger.open_lineage(tenant_id=tenant, run_id=runs[0], profile=policy) == lineage
    with pytest.raises(BudgetLedgerError, match="LINEAGE_EXPIRED"):
        ledger.transition(tenant_id=tenant, attempt_id=first.entry.attempt_id, action="dispatch")
    with pytest.raises(BudgetLedgerError, match="LINEAGE_EXPIRED"):
        reserve(ledger, tenant, runs[0])
    assert (
        ledger.transition(
            tenant_id=tenant, attempt_id=first.entry.attempt_id, action="cancel"
        ).entry.held_tokens
        == 0
    )


def test_completed_run_cannot_reserve_or_dispatch_but_can_reconcile(
    ledger_db: LedgerFixture,
) -> None:
    engine, tenant, runs = ledger_db
    ledger = BudgetLedger(engine)
    ledger.open_lineage(tenant_id=tenant, run_id=runs[0], profile=profile())
    first = reserve(ledger, tenant, runs[0])
    ledger.transition(tenant_id=tenant, attempt_id=first.entry.attempt_id, action="dispatch")
    with engine.begin() as c:
        c.execute(
            update(tables.agent_runs)
            .where(tables.agent_runs.c.id == runs[0])
            .values(status="succeeded", completed_at=text("clock_timestamp()"))
        )
    with pytest.raises(BudgetLedgerError, match="RUN_NOT_RUNNING"):
        reserve(ledger, tenant, runs[0])
    settled = ledger.transition(
        tenant_id=tenant,
        attempt_id=first.entry.attempt_id,
        action="settle",
        charged_tokens=35,
        reconciliation_ref="late-real-receipt-test",
    )
    assert settled.entry.charged_tokens == 35
    replay = reserve(ledger, tenant, runs[0], first.entry.attempt_id)
    assert not replay.changed and replay.entry.reservation_status == "settled"
    assert not ledger.transition(
        tenant_id=tenant, attempt_id=first.entry.attempt_id, action="dispatch"
    ).dispatch_granted


def test_missing_price_cannot_enable_monetary_limit(ledger_db: LedgerFixture) -> None:
    engine, tenant, runs = ledger_db
    ledger = BudgetLedger(engine)
    ledger.open_lineage(
        tenant_id=tenant, run_id=runs[0], profile=profile(monetary_limit_microusd=100)
    )
    with pytest.raises(BudgetLedgerError, match="MONETARY_ENFORCEMENT_UNAVAILABLE"):
        reserve(ledger, tenant, runs[0])
    with engine.connect() as c:
        assert c.execute(select(tables.budget_journal.c.id)).first() is None


def test_sql_null_does_not_bypass_cancellation_usage_constraint(ledger_db: LedgerFixture) -> None:
    engine, tenant, runs = ledger_db
    ledger = BudgetLedger(engine)
    ledger.open_lineage(tenant_id=tenant, run_id=runs[0], profile=profile())
    reserve(ledger, tenant, runs[0])
    with engine.connect() as c:
        invalid = dict(c.execute(select(tables.budget_journal)).mappings().one())
    invalid.update(
        id=uuid4(),
        revision=2,
        reservation_status="cancelled_before_dispatch",
        held_tokens=0,
        charged_tokens=None,
    )
    with pytest.raises(DBAPIError, match="lifecycle"), engine.begin() as c:
        c.execute(tables.budget_journal.insert(), invalid)


def test_budget_columns_and_foreign_keys_match_migration(ledger_db: LedgerFixture) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.db.schema import metadata

    engine, _, _ = ledger_db
    names = {
        "budget_lineages",
        "budget_run_links",
        "budget_journal",
        "legacy_usage_resolutions",
        "model_call_sessions",
        "model_call_events",
        "model_call_mode_events",
    }
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={
                "include_schemas": True,
                "include_object": lambda obj, name, kind, reflected, compared: (
                    kind != "table" or name in names
                ),
                "compare_server_default": True,
            },
        )
        assert compare_metadata(context, metadata) == []


def test_database_rejects_cross_tenant_lineage_binding(ledger_db: LedgerFixture) -> None:
    engine, tenant, runs = ledger_db
    lineage = BudgetLedger(engine).open_lineage(tenant_id=tenant, run_id=runs[0], profile=profile())
    other = uuid4()
    with engine.begin() as c:
        c.execute(
            tables.tenants.insert(), {"id": other, "slug": str(other), "name": "Other tenant"}
        )
    with pytest.raises(DBAPIError, match="foreign key"), engine.begin() as c:
        c.execute(
            tables.budget_run_links.insert(),
            {
                "tenant_id": other,
                "run_id": runs[0],
                "lineage_id": lineage,
                "created_at": c.execute(text("SELECT clock_timestamp()")).scalar_one(),
            },
        )
