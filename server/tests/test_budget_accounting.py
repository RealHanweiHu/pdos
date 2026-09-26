from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from typing import TypedDict, Unpack
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.ai.budget_accounting import (
    BudgetAccountingError,
    LegacyUsageEvidence,
    LegacyUsageReconciler,
)
from app.ai.budget_ledger import BudgetLedger, BudgetLedgerError, BudgetReceipt
from app.db.schema import tables
from tests.test_application_authorization import LedgerFixture, TransitionArguments
from tests.test_budget_ledger import SERVER_ROOT, profile, reserve
from tests.test_budget_ledger import ledger_db as ledger_db
from tests.test_migrations import EXPECTED_HEAD
from tests.test_model_gateway_schema import valid_invocation


class TraceChanges(TypedDict, total=False):
    status: str
    error_code: str
    created_at: datetime
    usage_status: str
    input_meter_version: str


def seed_trace(engine: Engine, tenant: UUID, *, known: bool = False, **changes: object) -> UUID:
    row = valid_invocation(tenant)
    if known:
        row.update(usage_status="known", input_meter_version="normalized_input.v1")
    row.update(changes)
    with engine.begin() as connection:
        connection.execute(tables.model_invocations.insert(), row)
    identifier = row["id"]
    assert isinstance(identifier, UUID)
    return identifier


def owner(engine: Engine, tenant: UUID, **changes: object) -> UUID:
    user_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            tables.users.insert(),
            {
                "id": user_id,
                "tenant_id": tenant,
                "username": str(user_id),
                "display_name": "Synthetic verifier",
                "role": "owner",
                **changes,
            },
        )
    return user_id


def setup_ledger(engine: Engine, tenant: UUID, run: UUID) -> BudgetLedger:
    ledger = BudgetLedger(engine)
    ledger.open_lineage(tenant_id=tenant, run_id=run, profile=profile())
    return ledger


def test_known_unbound_usage_reduces_available_daily_budget(ledger_db: LedgerFixture) -> None:
    engine, tenant, runs = ledger_db
    seed_trace(engine, tenant, known=True, input_tokens=75, output_tokens=5, total_tokens=80)
    ledger = setup_ledger(engine, tenant, runs[0])
    with pytest.raises(BudgetLedgerError, match="BUDGET_TENANT_TOKENS_EXHAUSTED"):
        reserve(ledger, tenant, runs[0], tokens=21, limit=100)
    assert reserve(ledger, tenant, runs[0], tokens=20, limit=100).entry.held_tokens == 20


@pytest.mark.parametrize("status", ["legacy_unverified", "unknown", "partial"])
def test_unresolved_old_usage_does_not_disappear_at_midnight(
    ledger_db: LedgerFixture, status: str
) -> None:
    engine, tenant, runs = ledger_db
    values: TraceChanges = dict(
        status="provider_error",
        error_code="PROVIDER_TRANSPORT_ERROR",
        created_at=datetime.now(UTC) - timedelta(days=30),
    )
    if status != "legacy_unverified":
        values.update({"usage_status": status, "input_meter_version": "normalized_input.v1"})
    seed_trace(engine, tenant, **values)
    ledger = setup_ledger(engine, tenant, runs[0])
    with pytest.raises(BudgetLedgerError, match="BUDGET_LEGACY_USAGE_UNRESOLVED"):
        reserve(ledger, tenant, runs[0], tokens=1)


def test_old_verified_usage_is_not_today_and_other_tenant_is_isolated(
    ledger_db: LedgerFixture,
) -> None:
    engine, tenant, runs = ledger_db
    seed_trace(engine, tenant, known=True, created_at=datetime.now(UTC) - timedelta(days=2))
    other = uuid4()
    with engine.begin() as connection:
        connection.execute(
            tables.tenants.insert(), {"id": other, "slug": str(other), "name": "Other"}
        )
    seed_trace(engine, other)
    assert (
        reserve(
            setup_ledger(engine, tenant, runs[0]), tenant, runs[0], tokens=20, limit=20
        ).entry.held_tokens
        == 20
    )


def test_verified_resolution_preserves_trace_and_corrections_are_append_only(
    ledger_db: LedgerFixture,
) -> None:
    engine, tenant, runs = ledger_db
    trace_id = seed_trace(engine, tenant)
    reviewer = owner(engine, tenant)
    service = LegacyUsageReconciler(engine)
    evidence = LegacyUsageEvidence(
        evidence_ref="synthetic-provider-receipt-v1", input_tokens=30, output_tokens=5
    )
    with engine.connect() as connection:
        before = dict(connection.execute(select(tables.model_invocations)).mappings().one())
    first = service.reconcile(
        tenant_id=tenant, invocation_id=trace_id, reviewer_user_id=reviewer, evidence=evidence
    )
    assert (
        service.reconcile(
            tenant_id=tenant, invocation_id=trace_id, reviewer_user_id=reviewer, evidence=evidence
        )
        == first
    )
    ledger = setup_ledger(engine, tenant, runs[0])
    with pytest.raises(BudgetLedgerError, match="BUDGET_TENANT_TOKENS_EXHAUSTED"):
        reserve(ledger, tenant, runs[0], tokens=20, limit=50)
    revised = LegacyUsageEvidence(
        evidence_ref="synthetic-corrected-receipt-v2", input_tokens=5, output_tokens=5
    )
    with pytest.raises(BudgetAccountingError, match="LEGACY_USAGE_REVISION_CONFLICT"):
        service.reconcile(
            tenant_id=tenant, invocation_id=trace_id, reviewer_user_id=reviewer, evidence=revised
        )
    service.reconcile(
        tenant_id=tenant,
        invocation_id=trace_id,
        reviewer_user_id=reviewer,
        evidence=revised,
        expected_revision=1,
    )
    assert reserve(ledger, tenant, runs[0], tokens=20, limit=30).entry.held_tokens == 20
    with engine.connect() as connection:
        assert dict(connection.execute(select(tables.model_invocations)).mappings().one()) == before
        assert len(connection.execute(select(tables.legacy_usage_resolutions)).all()) == 2
    with pytest.raises(DBAPIError, match="append-only"), engine.begin() as connection:
        connection.execute(update(tables.legacy_usage_resolutions).values(input_tokens=0))


@pytest.mark.parametrize("changes", [{"role": "engineer"}, {"is_active": False}])
def test_only_current_tenant_owner_or_admin_can_resolve_usage(
    ledger_db: LedgerFixture, changes: dict[str, object]
) -> None:
    engine, tenant, _ = ledger_db
    trace_id = seed_trace(engine, tenant)
    reviewer = owner(engine, tenant, **changes)
    with pytest.raises(BudgetAccountingError, match="LEGACY_USAGE_REVIEW_FORBIDDEN"):
        LegacyUsageReconciler(engine).reconcile(
            tenant_id=tenant,
            invocation_id=trace_id,
            reviewer_user_id=reviewer,
            evidence=LegacyUsageEvidence(evidence_ref="synthetic", input_tokens=0, output_tokens=0),
        )


def test_resolution_cannot_reclassify_known_usage_or_cross_tenant(ledger_db: LedgerFixture) -> None:
    engine, tenant, _ = ledger_db
    reviewer = owner(engine, tenant)
    known = seed_trace(engine, tenant, known=True)
    service = LegacyUsageReconciler(engine)
    for target in (known, uuid4()):
        with pytest.raises(BudgetAccountingError, match="LEGACY_USAGE_TARGET_INVALID"):
            service.reconcile(
                tenant_id=tenant,
                invocation_id=target,
                reviewer_user_id=reviewer,
                evidence=LegacyUsageEvidence(
                    evidence_ref="synthetic", input_tokens=0, output_tokens=0
                ),
            )
    with pytest.raises(BudgetAccountingError, match="LEGACY_USAGE_REVIEW_FORBIDDEN"):
        service.reconcile(
            tenant_id=uuid4(),
            invocation_id=known,
            reviewer_user_id=reviewer,
            evidence=LegacyUsageEvidence(evidence_ref="synthetic", input_tokens=0, output_tokens=0),
        )


def test_concurrent_resolution_requires_one_revision_winner(ledger_db: LedgerFixture) -> None:
    engine, tenant, _ = ledger_db
    trace_id, reviewer = seed_trace(engine, tenant), owner(engine, tenant)
    barrier = Barrier(2)

    def reconcile(value: int) -> UUID | str:
        barrier.wait(timeout=5)
        try:
            return LegacyUsageReconciler(engine).reconcile(
                tenant_id=tenant,
                invocation_id=trace_id,
                reviewer_user_id=reviewer,
                evidence=LegacyUsageEvidence(
                    evidence_ref=f"synthetic-{value}", input_tokens=value, output_tokens=0
                ),
            )
        except BudgetAccountingError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reconcile, [10, 20]))
    assert results.count("LEGACY_USAGE_REVISION_CONFLICT") == 1


def test_current_tenant_setting_can_lower_a_stale_gateway_snapshot(
    ledger_db: LedgerFixture,
) -> None:
    engine, tenant, runs = ledger_db
    reviewer = owner(engine, tenant)
    with engine.begin() as connection:
        connection.execute(
            tables.tenant_model_settings.insert(),
            {
                "id": uuid4(),
                "tenant_id": tenant,
                "provider": "minimax",
                "model": "MiniMax-M2.7",
                "daily_token_budget": 10,
                "updated_by_user_id": reviewer,
            },
        )
    ledger = setup_ledger(engine, tenant, runs[0])
    with pytest.raises(BudgetLedgerError, match="BUDGET_TENANT_TOKENS_EXHAUSTED"):
        reserve(ledger, tenant, runs[0], tokens=20, limit=1000)


def test_budget_call_tag_without_actual_ledger_is_not_a_free_bypass(
    ledger_db: LedgerFixture,
) -> None:
    engine, tenant, runs = ledger_db
    seed_trace(
        engine,
        tenant,
        known=True,
        budget_call_id=uuid4(),
        run_id=runs[0],
        input_tokens=75,
        output_tokens=5,
        total_tokens=80,
    )
    with pytest.raises(BudgetLedgerError, match="BUDGET_TENANT_TOKENS_EXHAUSTED"):
        reserve(setup_ledger(engine, tenant, runs[0]), tenant, runs[0], tokens=21, limit=100)


def test_migration_preserves_old_values_and_refuses_new_evidence_loss(
    ledger_db: LedgerFixture,
) -> None:
    engine, tenant, _ = ledger_db
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    command.downgrade(config, "0062_model_budget_evidence")
    trace_id = seed_trace(engine, tenant)
    command.upgrade(config, "head")
    with engine.connect() as connection:
        trace = (
            connection.execute(
                select(tables.model_invocations).where(tables.model_invocations.c.id == trace_id)
            )
            .mappings()
            .one()
        )
        assert trace["usage_status"] == "legacy_unverified"
        assert trace["input_tokens"] == 12 and trace["output_tokens"] == 8
    reviewer = owner(engine, tenant)
    LegacyUsageReconciler(engine).reconcile(
        tenant_id=tenant,
        invocation_id=trace_id,
        reviewer_user_id=reviewer,
        evidence=LegacyUsageEvidence(evidence_ref="synthetic", input_tokens=12, output_tokens=8),
    )
    with pytest.raises(
        RuntimeError, match="refusing downgrade: normalized or reconciled usage evidence"
    ):
        command.downgrade(config, "0062_model_budget_evidence")
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == EXPECTED_HEAD
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"usage_status": "invented"},
        {"usage_status": "known", "input_meter_version": "legacy_unverified"},
        {"usage_status": "not_invoked", "input_meter_version": "normalized_input.v1"},
    ],
)
def test_database_rejects_inconsistent_usage_provenance(
    ledger_db: LedgerFixture, changes: TraceChanges
) -> None:
    engine, tenant, _ = ledger_db
    with pytest.raises(IntegrityError, match="usage_evidence_consistent"):
        seed_trace(engine, tenant, **changes)


def test_linked_aggregate_trace_is_not_charged_again(ledger_db: LedgerFixture) -> None:
    import httpx2

    from tests.test_model_budget_controller import call, controller, gateway, response
    from tests.test_model_gateway import RiskOutput

    engine, tenant, runs = ledger_db
    with httpx2.Client(transport=httpx2.MockTransport(lambda _: response())) as client:
        result = gateway(engine, client, controller(engine)).invoke_structured(
            call(tenant, runs[0]), RiskOutput
        )
    assert result.status == "succeeded"
    # First call settled 10 and its aggregate trace says 10. Only 10 was spent.
    second = setup_ledger(engine, tenant, runs[1])
    assert reserve(second, tenant, runs[1], tokens=10, limit=20).entry.held_tokens == 10


def test_known_response_larger_than_unsettled_hold_is_not_undercounted(
    ledger_db: LedgerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx2

    from tests.test_model_budget_controller import call, controller, gateway, response
    from tests.test_model_gateway import RiskOutput

    engine, tenant, runs = ledger_db
    ledger = BudgetLedger(engine)
    transition = ledger.transition

    def fail_settle(**kwargs: Unpack[TransitionArguments]) -> BudgetReceipt:
        if kwargs["action"] == "settle":
            raise BudgetLedgerError("SYNTHETIC_RECEIPT_FAILURE")
        return transition(**kwargs)

    monkeypatch.setattr(ledger, "transition", fail_settle)
    with httpx2.Client(
        transport=httpx2.MockTransport(lambda _: response(inputs=7, outputs=40))
    ) as client:
        result = gateway(engine, client, controller(engine, ledger=ledger)).invoke_structured(
            call(tenant, runs[0]), RiskOutput
        )
    assert result.error_code == "BUDGET_RECEIPT_FAILED"
    second = setup_ledger(engine, tenant, runs[1])
    # Held=30, known response=47. Another run cannot exploit the 17-token gap.
    with pytest.raises(BudgetLedgerError, match="BUDGET_TENANT_TOKENS_EXHAUSTED"):
        reserve(second, tenant, runs[1], tokens=1, limit=47)


def test_database_rejects_cross_tenant_resolution_foreign_key(ledger_db: LedgerFixture) -> None:
    engine, tenant, _ = ledger_db
    trace_id, reviewer = seed_trace(engine, tenant), owner(engine, tenant)
    LegacyUsageReconciler(engine).reconcile(
        tenant_id=tenant,
        invocation_id=trace_id,
        reviewer_user_id=reviewer,
        evidence=LegacyUsageEvidence(evidence_ref="synthetic", input_tokens=12, output_tokens=8),
    )
    other = uuid4()
    with engine.begin() as connection:
        connection.execute(
            tables.tenants.insert(), {"id": other, "slug": str(other), "name": "Other"}
        )
    with engine.connect() as connection:
        row = dict(connection.execute(select(tables.legacy_usage_resolutions)).mappings().one())
    row.update(id=uuid4(), tenant_id=other)
    with pytest.raises(IntegrityError, match="foreign key"), engine.begin() as connection:
        connection.execute(tables.legacy_usage_resolutions.insert(), row)


def test_known_overrun_deficit_survives_day_change_until_settled(
    ledger_db: LedgerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx2

    from tests.test_model_budget_controller import call, controller, gateway, response
    from tests.test_model_gateway import RiskOutput

    engine, tenant, runs = ledger_db
    ledger = BudgetLedger(engine)
    transition = ledger.transition

    def fail_settle(**kwargs: Unpack[TransitionArguments]) -> BudgetReceipt:
        if kwargs["action"] == "settle":
            raise BudgetLedgerError("SYNTHETIC_RECEIPT_FAILURE")
        return transition(**kwargs)

    monkeypatch.setattr(ledger, "transition", fail_settle)
    with httpx2.Client(
        transport=httpx2.MockTransport(lambda _: response(inputs=7, outputs=40))
    ) as client:
        assert (
            gateway(engine, client, controller(engine, ledger=ledger))
            .invoke_structured(call(tenant, runs[0]), RiskOutput)
            .error_code
            == "BUDGET_RECEIPT_FAILED"
        )
    shift_budget_history_to_yesterday(engine, tenant)
    second = setup_ledger(engine, tenant, runs[1])
    with pytest.raises(BudgetLedgerError, match="BUDGET_TENANT_TOKENS_EXHAUSTED"):
        reserve(second, tenant, runs[1], tokens=1, limit=47)


def test_delayed_aggregate_does_not_rebill_yesterdays_settled_call(
    ledger_db: LedgerFixture,
) -> None:
    import httpx2

    from tests.test_model_budget_controller import call, controller, gateway, response
    from tests.test_model_gateway import RiskOutput

    engine, tenant, runs = ledger_db
    inv = call(tenant, runs[0])
    with httpx2.Client(transport=httpx2.MockTransport(lambda _: response())) as client:
        assert (
            gateway(engine, client, controller(engine)).invoke_structured(inv, RiskOutput).status
            == "succeeded"
        )
    shift_budget_history_to_yesterday(engine, tenant)
    next_day = datetime.now(UTC)
    seed_trace(
        engine,
        tenant,
        known=True,
        budget_call_id=inv.model_call_id,
        run_id=runs[0],
        input_tokens=7,
        output_tokens=3,
        total_tokens=10,
        created_at=next_day,
    )
    second = setup_ledger(engine, tenant, runs[1])
    assert reserve(second, tenant, runs[1], tokens=10, limit=10).entry.held_tokens == 10


def shift_budget_history_to_yesterday(engine: Engine, tenant: UUID) -> None:
    """Seed historical facts in pdos_test; runtime APIs never receive a test clock."""
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text("""
            UPDATE cehub_ai.budget_journal SET created_at = created_at - interval '1 day',
                dispatched_at = dispatched_at - interval '1 day' WHERE tenant_id = :tenant
        """),
            dict(tenant=tenant),
        )
        connection.execute(
            text("""
            UPDATE cehub_ai.model_invocations SET created_at = created_at - interval '1 day'
            WHERE tenant_id = :tenant
        """),
            dict(tenant=tenant),
        )
