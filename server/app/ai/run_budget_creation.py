"""Trusted metadata port called inside an application's new-run transaction."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from sqlalchemy import Connection

from app.ai.budget_ledger import BudgetLedger
from app.contracts.runtime_policy import RunBudgetProfile


@runtime_checkable
class RunBudgetSource(Protocol):
    @property
    def creation_budget_profile(self) -> RunBudgetProfile | None: ...


def freeze_created_application_run(
    connection: Connection,
    gateway: object,
    *,
    tenant_id: UUID,
    run_id: UUID,
    parent_run_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    purpose: str | None = None,
    auth_version: int | None = None,
    issue_lease: bool = True,
) -> None:
    # Legacy/fake providers need no budget metadata. A configured budget factory
    # uses ExistingRunBudgetLedger: a missing creation hook cannot cause late
    # provisioning or a fallback model call.
    profile = gateway.creation_budget_profile if isinstance(gateway, RunBudgetSource) else None
    if profile is None and parent_run_id is not None:
        # A legacy process continuing an already budgeted conversation must not
        # turn its next run into an unbound escape hatch. Admission will require
        # a budget controller for this inherited link as for the original run.
        parent = BudgetLedger._link(connection, tenant_id, parent_run_id)
        if parent is not None:
            profile = RunBudgetProfile.model_validate(parent["profile"])
    if profile is not None:
        BudgetLedger.freeze_created_run(
            connection,
            tenant_id=tenant_id,
            run_id=run_id,
            profile=profile,
            parent_run_id=parent_run_id,
        )
        if actor_user_id is not None and purpose is not None:
            from app.ai.application_authorization import issue_application_authorization

            issue_application_authorization(
                connection,
                tenant_id=tenant_id,
                run_id=run_id,
                actor_user_id=actor_user_id,
                purpose=purpose,
                auth_version=auth_version,
            )
            from app.ai.application_leases import ApplicationLeaseKeeper
            from app.ai.budget_ledger import BudgetLedgerError

            keeper = getattr(gateway, "application_lease_keeper", None)
            if not isinstance(keeper, ApplicationLeaseKeeper):
                raise BudgetLedgerError("APPLICATION_RUN_LEASE_REQUIRED")
            if issue_lease:
                keeper.issue(connection, tenant_id, run_id)
