"""Dispatch deadline must be evaluated after database row-lock waits."""

from concurrent.futures import ThreadPoolExecutor
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.ai.budget_evidence import BudgetRequestBinding
from app.ai.budget_ledger import BudgetLedger, BudgetLedgerError
from app.ai.model_catalog import ProtocolKind, ProviderName
from app.db.schema import tables
from tests.test_budget_ledger import LedgerFixture, profile
from tests.test_budget_ledger import ledger_db as ledger_db


def test_waiting_for_run_lock_cannot_dispatch_after_lineage_deadline(
    ledger_db: LedgerFixture,
) -> None:
    engine, tenant, runs = ledger_db
    ledger = BudgetLedger(engine)
    ledger.open_lineage(
        tenant_id=tenant, run_id=runs[0], profile=profile(active_seconds=1, lifetime_seconds=2)
    )
    attempt = uuid4()
    binding = BudgetRequestBinding(
        model_call_id=uuid4(),
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
    ledger.reserve(
        tenant_id=tenant,
        run_id=runs[0],
        attempt_id=attempt,
        call_kind="model",
        input_tokens=10,
        output_tokens=20,
        tenant_daily_token_limit=1000,
        request_binding=binding,
    )

    def dispatch() -> str:
        try:
            ledger.transition(tenant_id=tenant, attempt_id=attempt, action="dispatch")
        except BudgetLedgerError as error:
            return error.code
        return "unexpected-grant"

    with ThreadPoolExecutor(max_workers=1) as executor:
        with engine.begin() as blocker:
            blocker.execute(
                select(tables.agent_runs.c.id)
                .where(tables.agent_runs.c.id == runs[0])
                .with_for_update()
            )
            future = executor.submit(dispatch)
            deadline = monotonic() + 5
            with engine.connect() as observer:
                while not observer.execute(
                    text("""
                    SELECT EXISTS (SELECT 1 FROM pg_stat_activity
                        WHERE datname = current_database() AND pid <> pg_backend_pid()
                          AND wait_event_type = 'Lock'
                          AND query LIKE '%transition_bound_model_budget%')
                """)
                ).scalar_one():
                    assert monotonic() < deadline, "dispatch never reached row lock"
                    sleep(0.02)
                    observer.commit()
                # Ensure the originally valid reservation expires during the wait.
                remaining = observer.execute(
                    text("""
                    SELECT extract(epoch FROM absolute_deadline - clock_timestamp())
                    FROM cehub_ai.budget_lineages WHERE tenant_id = :tenant
                """),
                    dict(tenant=tenant),
                ).scalar_one()
                sleep(max(0, float(remaining)) + 0.05)
            assert not future.done()
        assert future.result(timeout=5) == "BUDGET_LINEAGE_EXPIRED"
    with engine.connect() as connection:
        row = connection.execute(select(tables.budget_journal)).mappings().one()
    assert row["revision"] == 1 and row["dispatched_at"] is None and row["held_tokens"] == 30


@pytest.mark.parametrize("locked_table", ["agent_runs", "tenant_model_settings"])
def test_waiting_to_reserve_uses_post_lock_deadline(
    ledger_db: LedgerFixture, locked_table: str
) -> None:
    engine, tenant, runs = ledger_db
    ledger = BudgetLedger(engine)
    with engine.begin() as connection:
        connection.execute(
            tables.tenant_model_settings.insert(),
            dict(
                id=uuid4(),
                tenant_id=tenant,
                provider="minimax",
                model="MiniMax-M2.7",
                daily_token_budget=1000,
            ),
        )
    ledger.open_lineage(
        tenant_id=tenant, run_id=runs[0], profile=profile(active_seconds=1, lifetime_seconds=2)
    )

    def reserve() -> str:
        try:
            ledger.reserve(
                tenant_id=tenant,
                run_id=runs[0],
                attempt_id=uuid4(),
                call_kind="model",
                input_tokens=10,
                output_tokens=20,
                tenant_daily_token_limit=1000,
            )
        except BudgetLedgerError as error:
            return error.code
        return "unexpected-reservation"

    with ThreadPoolExecutor(max_workers=1) as executor:
        with engine.begin() as blocker:
            blocker.execute(
                text(
                    f"SELECT id FROM cehub_ai.{locked_table} WHERE tenant_id = :tenant FOR UPDATE"
                ),
                dict(tenant=tenant),
            )
            future = executor.submit(reserve)
            deadline = monotonic() + 5
            with engine.connect() as observer:
                while not observer.execute(
                    text("""
                    SELECT EXISTS (SELECT 1 FROM pg_stat_activity
                        WHERE datname=current_database() AND pid<>pg_backend_pid()
                        AND wait_event_type='Lock' AND query LIKE '%reserve_run_budget%')
                """)
                ).scalar_one():
                    assert monotonic() < deadline, "reservation never reached row lock"
                    sleep(0.02)
                    observer.commit()
                remaining = observer.execute(
                    text("""
                    SELECT extract(epoch FROM absolute_deadline-clock_timestamp())
                    FROM cehub_ai.budget_lineages WHERE tenant_id=:tenant
                """),
                    dict(tenant=tenant),
                ).scalar_one()
                sleep(max(0, float(remaining)) + 0.05)
            assert not future.done()
        assert future.result(timeout=5) == "BUDGET_LINEAGE_EXPIRED"
    with engine.connect() as connection:
        assert not connection.execute(select(tables.budget_journal)).first()
