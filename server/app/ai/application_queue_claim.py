"""Claim an already budgeted application request in the caller's tenant transaction."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, RowMapping, func, select, text

from app.ai.application_authorization import policy_version
from app.ai.application_leases import ApplicationLeaseKeeper
from app.ai.budget_ledger import BudgetLedger, BudgetLedgerError
from app.db.schema import tables


def claim_application_queue(
    c: Connection, gateway: Any, row: RowMapping, *, auth_version: int | None, purpose: str
) -> RowMapping:
    keeper = getattr(gateway, "application_lease_keeper", None)
    profile = getattr(gateway, "creation_budget_profile", None)
    if not isinstance(keeper, ApplicationLeaseKeeper) or profile is None:
        raise BudgetLedgerError("APPLICATION_QUEUE_BUDGET_REQUIRED")
    link = BudgetLedger._link(c, row["tenant_id"], row["id"])
    auth = (
        c.execute(
            select(tables.application_authorizations).where(
                tables.application_authorizations.c.tenant_id == row["tenant_id"],
                tables.application_authorizations.c.run_id == row["id"],
            )
        )
        .mappings()
        .one()
    )
    if (
        link is None
        or auth["body"]["purpose"] != purpose
        or link["profile"] != profile.model_dump(mode="json")
        or auth["pins"]["auth_version"] != auth_version
        or auth["body"]["policy_version"] != policy_version()
    ):
        raise BudgetLedgerError("APPLICATION_AUTHORIZATION_CHANGED")
    claimed = (
        c.execute(
            tables.agent_runs.update()
            .where(
                tables.agent_runs.c.tenant_id == row["tenant_id"],
                tables.agent_runs.c.id == row["id"],
            )
            .values(
                status="running",
                started_at=func.clock_timestamp(),
                updated_at=func.clock_timestamp(),
            )
            .returning(tables.agent_runs)
        )
        .mappings()
        .one()
    )
    if not c.execute(
        text("SELECT cehub_ai.application_authorization_is_current(:r)"), {"r": row["id"]}
    ).scalar_one():
        raise BudgetLedgerError("APPLICATION_AUTHORIZATION_CHANGED")
    c.execute(
        text("SELECT cehub_ai.check_run_active_budget(:t,:r)"),
        {"t": row["tenant_id"], "r": row["id"]},
    )
    keeper.issue(c, row["tenant_id"], row["id"])
    return claimed
