"""Application ceilings can be disabled without erasing usage or widening Agent policy."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, update

from app.ai.application_authorization import issue_application_authorization
from app.ai.budget_evidence import BudgetUsageEvidence
from app.ai.budget_ledger import BudgetLedger, BudgetLedgerError
from app.ai.model_call_fence import ModelCallFence
from app.db.schema import tables
from tests.test_agent_budget_reservation import binding
from tests.test_budget_ledger import SERVER_ROOT, profile, reserve
from tests.test_budget_ledger import ledger_db as ledger_db


def prepare(engine, tenant, runs, *, authorized=True, daily=1000):
    ledger = BudgetLedger(engine)
    for run in runs:
        ledger.open_lineage(tenant_id=tenant, run_id=run, profile=profile())
    with engine.begin() as c:
        actor = c.execute(
            select(tables.users.c.id).where(tables.users.c.username == "reviewer")
        ).scalar_one()
        c.execute(
            tables.tenant_model_settings.insert(),
            dict(
                id=uuid4(),
                tenant_id=tenant,
                provider="minimax",
                model="MiniMax-M2.7",
                daily_token_budget=daily,
                token_budget_enforced=False,
            ),
        )
        if authorized:
            for run in runs:
                issue_application_authorization(
                    c, tenant_id=tenant, run_id=run, actor_user_id=actor, purpose="chat_answer"
                )
    return ledger


def bound_reserve(ledger, tenant, run, *, tokens=80, daily=1):
    body = binding()
    receipt = ledger.reserve(
        tenant_id=tenant,
        run_id=run,
        attempt_id=uuid4(),
        call_kind="model",
        input_tokens=tokens,
        output_tokens=20,
        tenant_daily_token_limit=daily,
        request_binding=body,
    )
    return receipt, body


def test_unlimited_application_reserves_above_daily_and_lineage_ceilings(ledger_db):
    engine, tenant, runs = ledger_db
    ledger = prepare(engine, tenant, [runs[0]], authorized=False)
    receipt, body = bound_reserve(ledger, tenant, runs[0], daily=1000)
    ledger.transition(tenant_id=tenant, attempt_id=receipt.entry.attempt_id, action="dispatch")
    usage = BudgetUsageEvidence(
        request_digest=body.request_digest,
        input_tokens=140,
        output_tokens=10,
        request_id="synthetic-receipt",
    )
    ledger.transition(
        tenant_id=tenant,
        attempt_id=receipt.entry.attempt_id,
        action="settle",
        charged_tokens=150,
        usage_evidence=usage,
        reconciliation_ref=usage.evidence_ref,
        provider_request_id=usage.request_id,
    )
    ledger.link_run(tenant_id=tenant, lineage_id=receipt.entry.lineage_id, run_id=runs[1])
    with engine.begin() as c:
        c.execute(update(tables.tenant_model_settings).values(daily_token_budget=1))
        actor = c.execute(
            select(tables.users.c.id).where(tables.users.c.username == "reviewer")
        ).scalar_one()
        issue_application_authorization(
            c, tenant_id=tenant, run_id=runs[1], actor_user_id=actor, purpose="chat_answer"
        )
    admitted, _ = bound_reserve(ledger, tenant, runs[1], tokens=300)
    assert admitted.changed and admitted.entry.reserved_tokens == 320
    with engine.connect() as c:
        settled = (
            c.execute(
                select(tables.budget_journal).where(
                    tables.budget_journal.c.reservation_status == "settled"
                )
            )
            .mappings()
            .one()
        )
        assert settled["charged_tokens"] == 150


def test_disabled_application_setting_does_not_disable_unbound_owner_budget(ledger_db):
    engine, tenant, runs = ledger_db
    ledger = prepare(engine, tenant, [runs[0]], authorized=False, daily=1)
    with pytest.raises(BudgetLedgerError, match="TENANT_TOKENS_EXHAUSTED"):
        reserve(ledger, tenant, runs[0])


@pytest.mark.parametrize("state", ["running", "unclosed", "finished"])
def test_unknown_usage_only_releases_confirmed_finished_execution_slots(ledger_db, state):
    engine, tenant, runs = ledger_db
    ledger = prepare(engine, tenant, runs[:3], authorized=False)
    fence = ModelCallFence(engine)
    for run in runs[:2]:
        receipt, body = bound_reserve(ledger, tenant, run, daily=1000)
        ledger.transition(tenant_id=tenant, attempt_id=receipt.entry.attempt_id, action="dispatch")
        ledger.transition(tenant_id=tenant, attempt_id=receipt.entry.attempt_id, action="unknown")
        with engine.connect() as c:
            project = c.execute(
                select(tables.agent_runs.c.project_id).where(tables.agent_runs.c.id == run)
            ).scalar_one()
        session = fence.begin(
            tenant_id=tenant,
            run_id=run,
            project_id=project,
            agent_key="project_intelligence",
            budgeted=True,
        )
        if state != "unclosed":
            invocation = uuid4()
            with engine.begin() as c:
                c.execute(
                    tables.model_invocations.insert(),
                    dict(
                        id=invocation,
                        tenant_id=tenant,
                        run_id=run,
                        project_id=project,
                        agent_key="project_intelligence",
                        prompt_version="synthetic-test",
                        provider="minimax",
                        model="MiniMax-M2.7",
                        protocol="openai-compatible",
                        status="provider_error",
                        error_code="PROVIDER_TRANSPORT_ERROR",
                        structured_attempts=1,
                        usage_status="unknown",
                        input_meter_version="normalized_input.v1",
                        cost_status="unknown",
                        budget_call_id=body.model_call_id,
                        model_call_session_id=session,
                    ),
                )
            fence.finish(tenant_id=tenant, session_id=session, invocation_id=invocation)
        if state != "running":
            with engine.begin() as c:
                c.execute(
                    update(tables.agent_runs)
                    .where(tables.agent_runs.c.id == run)
                    .values(
                        status="degraded",
                        completed_at=datetime.now(UTC),
                        error_code="PROVIDER_TRANSPORT_ERROR",
                    )
                )
    with engine.begin() as c:
        c.execute(update(tables.tenant_model_settings).values(daily_token_budget=1))
        actor = c.execute(
            select(tables.users.c.id).where(tables.users.c.username == "reviewer")
        ).scalar_one()
        issue_application_authorization(
            c, tenant_id=tenant, run_id=runs[2], actor_user_id=actor, purpose="chat_answer"
        )
    with engine.connect() as c:
        before = (
            c.execute(select(tables.budget_journal).order_by(tables.budget_journal.c.id))
            .mappings()
            .all()
        )
    if state == "finished":
        assert bound_reserve(ledger, tenant, runs[2])[0].changed
    else:
        with pytest.raises(BudgetLedgerError, match="TENANT_CALL_BUSY"):
            bound_reserve(ledger, tenant, runs[2])
    with engine.connect() as c:
        old = (
            c.execute(
                select(tables.budget_journal)
                .where(tables.budget_journal.c.run_id.in_(runs[:2]))
                .order_by(tables.budget_journal.c.id)
            )
            .mappings()
            .all()
        )
        assert old == before
        unknown = [r for r in old if r["reservation_status"] == "unknown"]
        assert len(unknown) == 2 and all(
            r["held_tokens"] == r["reserved_tokens"] and r["charged_tokens"] is None
            for r in unknown
        )


def test_current_migration_round_trip_and_disabled_history_guard(ledger_db):
    engine, tenant, runs = ledger_db
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    command.downgrade(config, "0429_preview_legacy_usage_holds")
    command.upgrade(config, "head")
    prepare(engine, tenant, [runs[0]])
    with pytest.raises(RuntimeError, match="policy history must be preserved"):
        command.downgrade(config, "0429_preview_legacy_usage_holds")
