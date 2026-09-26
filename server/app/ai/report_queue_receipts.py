"""Finish the queued import in the same transaction as its draft batch."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, func, select

from app.ai.application_leases import bind_write
from app.ai.budget_ledger import BudgetLedger, BudgetLedgerError
from app.db.schema import tables


def require_import_lease(c: Connection, gateway: Any, tenant: UUID, run: UUID) -> None:
    row = (
        c.execute(
            select(tables.agent_runs)
            .where(
                tables.agent_runs.c.tenant_id == tenant,
                tables.agent_runs.c.id == run,
            )
            .with_for_update()
        )
        .mappings()
        .one()
    )
    if row["status"] != "running" or not row["run_context"].get("mapping_result"):
        raise BudgetLedgerError("APPLICATION_IMPORT_NOT_RUNNING")
    bind_write(c, gateway, tenant, run, success=True)
    BudgetLedger._require_active(c, tenant, run)


def complete_import(
    c: Connection, gateway: Any, *, tenant_id: UUID, run_id: UUID, batch_id: UUID
) -> None:
    staged = (
        c.execute(
            select(tables.application_import_inputs).where(
                tables.application_import_inputs.c.tenant_id == tenant_id,
                tables.application_import_inputs.c.run_id == run_id,
            )
        )
        .mappings()
        .one()
    )
    if staged["batch_id"] == batch_id:
        return
    require_import_lease(c, gateway, tenant_id, run_id)
    c.execute(
        tables.application_import_inputs.update()
        .where(
            tables.application_import_inputs.c.id == staged["id"],
        )
        .values(batch_id=batch_id, resolved_at=func.clock_timestamp())
    )
    c.execute(
        tables.agent_runs.update()
        .where(
            tables.agent_runs.c.tenant_id == tenant_id,
            tables.agent_runs.c.id == run_id,
        )
        .values(
            status="succeeded",
            completed_at=func.clock_timestamp(),
            updated_at=func.clock_timestamp(),
        )
    )
