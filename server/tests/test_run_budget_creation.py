"""Creation transaction rollback, immutable parent inheritance and no late allocation."""

from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, select

from app.ai.budget_adoption import approved_budget_profile
from app.ai.budget_ledger import BudgetLedger, BudgetLedgerError, ExistingRunBudgetLedger
from app.ai.run_budget_creation import freeze_created_application_run
from app.db.schema import tables
from tests.test_budget_ledger import ledger_db as ledger_db

LedgerFixture = tuple[Engine, UUID, list[UUID]]


class Configured:
    creation_budget_profile = approved_budget_profile("short")


def test_expired_parent_cannot_start_a_new_absolute_deadline(ledger_db: LedgerFixture) -> None:
    from sqlalchemy import text

    from tests.test_budget_ledger import profile

    class ShortLived:
        creation_budget_profile = profile(active_seconds=1, lifetime_seconds=1)

    engine, tenant, _ = ledger_db
    with engine.begin() as c:
        parent = new_run(c)
        parent_id = parent["id"]
        assert isinstance(parent_id, UUID)
        freeze_created_application_run(c, ShortLived(), tenant_id=tenant, run_id=parent_id)
        frozen = dict(c.execute(select(tables.budget_lineages)).mappings().one())
    with engine.connect() as c:
        c.execute(text("SELECT pg_sleep(1.05)"))
    with pytest.raises(BudgetLedgerError, match="LINEAGE_EXPIRED"), engine.begin() as c:
        child = new_run(c, offset=300)
        child_id = child["id"]
        assert isinstance(child_id, UUID)
        freeze_created_application_run(
            c, ShortLived(), tenant_id=tenant, run_id=child_id, parent_run_id=parent_id
        )
    with engine.connect() as c:
        assert dict(c.execute(select(tables.budget_lineages)).mappings().one()) == frozen
        assert c.execute(select(tables.budget_run_links.c.run_id)).scalars().all() == [parent["id"]]


def new_run(c: Connection, *, offset: int = 100) -> dict[str, object]:
    row: dict[str, object] = dict(
        c.execute(select(tables.agent_runs).order_by(tables.agent_runs.c.id).limit(1))
        .mappings()
        .one()
    )
    window_started_at = row["window_started_at"]
    window_ended_at = row["window_ended_at"]
    assert isinstance(window_started_at, datetime) and isinstance(window_ended_at, datetime)
    row.update(
        id=uuid4(),
        window_started_at=window_started_at + timedelta(days=offset),
        window_ended_at=window_ended_at + timedelta(days=offset),
    )
    c.execute(tables.agent_runs.insert(), row)
    return row


def test_new_application_run_and_budget_rollback_together(ledger_db: LedgerFixture) -> None:
    engine, tenant, _ = ledger_db
    with pytest.raises(RuntimeError), engine.begin() as c:
        run = new_run(c)
        run_id = run["id"]
        assert isinstance(run_id, UUID)
        freeze_created_application_run(c, Configured(), tenant_id=tenant, run_id=run_id)
        assert c.execute(select(tables.budget_run_links)).first() is not None
        raise RuntimeError("synthetic failure after budget binding")
    with engine.connect() as c:
        assert c.execute(select(tables.budget_lineages)).first() is None
        assert (
            c.execute(select(tables.agent_runs).where(tables.agent_runs.c.id == run["id"])).first()
            is None
        )


def test_committed_unbound_run_cannot_get_a_new_clock_at_model_admission(
    ledger_db: LedgerFixture,
) -> None:
    engine, tenant, runs = ledger_db
    with pytest.raises(BudgetLedgerError, match="RUN_CREATION_REQUIRED"), engine.begin() as c:
        freeze_created_application_run(c, Configured(), tenant_id=tenant, run_id=runs[0])
    with pytest.raises(BudgetLedgerError, match="RUN_UNBOUND"):
        ExistingRunBudgetLedger(engine).open_lineage(
            tenant_id=tenant,
            run_id=runs[0],
            profile=Configured.creation_budget_profile,
        )
    with engine.connect() as c:
        assert c.execute(select(tables.budget_lineages)).first() is None


@pytest.mark.parametrize("legacy_child", [False, True])
def test_linked_creation_keeps_original_budget_and_deadline_even_in_legacy_process(
    ledger_db: LedgerFixture, legacy_child: bool
) -> None:
    engine, tenant, _ = ledger_db
    with engine.begin() as c:
        root = new_run(c)
        root_id = root["id"]
        assert isinstance(root_id, UUID)
        freeze_created_application_run(c, Configured(), tenant_id=tenant, run_id=root_id)
        original = dict(c.execute(select(tables.budget_lineages)).mappings().one())
    with engine.begin() as c:
        child = new_run(c, offset=200)
        child_id = child["id"]
        assert isinstance(child_id, UUID)
        freeze_created_application_run(
            c,
            object() if legacy_child else Configured(),
            tenant_id=tenant,
            run_id=child_id,
            parent_run_id=root_id,
        )
    with engine.connect() as c:
        assert dict(c.execute(select(tables.budget_lineages)).mappings().one()) == original
        assert (
            c.execute(select(tables.budget_run_links.c.lineage_id)).scalars().all()
            == [original["id"]] * 2
        )


@pytest.mark.parametrize("reason", ["unbound", "profile", "scope"])
def test_invalid_parent_cannot_become_new_budget(ledger_db: LedgerFixture, reason: str) -> None:
    engine, tenant, runs = ledger_db
    if reason != "unbound":
        BudgetLedger(engine).open_lineage(
            tenant_id=tenant,
            run_id=runs[0],
            profile=approved_budget_profile("work_package" if reason == "profile" else "short"),
        )
    parent = uuid4() if reason == "scope" else runs[0]
    code = {
        "unbound": "PARENT_RUN_UNBOUND",
        "profile": "PROFILE_CONFLICT",
        "scope": "PARENT_SCOPE_INVALID",
    }[reason]
    with pytest.raises(BudgetLedgerError, match=code), engine.begin() as c:
        row = new_run(c)
        run_id = row["id"]
        assert isinstance(run_id, UUID)
        freeze_created_application_run(
            c, Configured(), tenant_id=tenant, run_id=run_id, parent_run_id=parent
        )
    with engine.connect() as c:
        assert (
            c.execute(select(tables.agent_runs).where(tables.agent_runs.c.id == row["id"])).first()
            is None
        )
