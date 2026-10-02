"""Authenticated request retry can take over an expired, fully receipted result."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, RowMapping, select, text
from sqlalchemy.exc import DBAPIError

from app.ai.application_authorization import policy_version
from app.ai.application_leases import ApplicationLeaseKeeper
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.call_identity import ModelCallSlot, model_call_id
from app.db.schema import tables

SLOTS = {
    "event_issue": ModelCallSlot.EVENT_ISSUE,
    "product_matrix": ModelCallSlot.PRODUCT_MATRIX,
    "product_work": ModelCallSlot.PRODUCT_WORK,
    "product_evaluation": ModelCallSlot.PRODUCT_EVALUATION,
    "portfolio_explanation": ModelCallSlot.PORTFOLIO_EXPLANATION,
    "executive_brief": ModelCallSlot.EXECUTIVE_BRIEF,
    "cost_reduction": ModelCallSlot.COST_REDUCTION,
    "supplier_recovery": ModelCallSlot.SUPPLIER_RECOVERY,
    "meeting_planning": ModelCallSlot.MEETING_PLANNING,
    "intake_organization": ModelCallSlot.INTAKE_ORGANIZATION,
    "process_template_configuration": ModelCallSlot.PROCESS_TEMPLATE,
    "quality_work_package": ModelCallSlot.QUALITY_WORK_PACKAGE,
    "change_work_package": ModelCallSlot.CHANGE_WORK_PACKAGE,
    "meeting_minutes": ModelCallSlot.MEETING_MINUTES,
    "meeting_actions": ModelCallSlot.MEETING_ACTIONS,
    "meeting_decisions": ModelCallSlot.MEETING_DECISIONS,
    "meeting_business": ModelCallSlot.MEETING_BUSINESS,
    "meeting_reading": ModelCallSlot.MEETING_READING,
    "chat_answer": ModelCallSlot.CHAT_ANSWER,
    "risk_suggestion": ModelCallSlot.RISK_SUGGESTION,
    "test_plan_suggestion": ModelCallSlot.TEST_PLAN_SUGGESTION,
    "report_mapping": ModelCallSlot.REPORT_MAPPING,
}


def try_resume(
    c: Connection,
    gateway: Any,
    row: RowMapping,
    *,
    actor: UUID,
    auth_version: int | None,
    purpose: str,
    recovery_call_id: UUID | None = None,
) -> bool:
    if row["status"] != "running" and not (
        row["status"] == "degraded" and row["error_code"] == "APPLICATION_RUN_LEASE_EXPIRED"
    ):
        return False
    checkpoint = c.execute(
        select(tables.application_result_checkpoints.c.id).where(
            tables.application_result_checkpoints.c.tenant_id == row["tenant_id"],
            tables.application_result_checkpoints.c.run_id == row["id"],
            tables.application_result_checkpoints.c.model_call_id
            == (recovery_call_id or model_call_id(row["id"], SLOTS[purpose])),
        )
    ).scalar_one_or_none()
    if checkpoint is None:
        return False
    keeper = getattr(gateway, "application_lease_keeper", None)
    profile = getattr(gateway, "creation_budget_profile", None)
    if not isinstance(keeper, ApplicationLeaseKeeper) or profile is None:
        raise BudgetLedgerError("APPLICATION_RECOVERY_BUDGET_REQUIRED")
    auth = c.execute(
        select(tables.application_authorizations.c.body).where(
            tables.application_authorizations.c.tenant_id == row["tenant_id"],
            tables.application_authorizations.c.run_id == row["id"],
        )
    ).scalar_one()
    if auth["purpose"] != purpose:
        raise BudgetLedgerError("APPLICATION_RECOVERY_SCOPE_INVALID")
    try:
        token = c.execute(
            text("""SELECT cehub_ai.claim_application_result_run(
            :t,:r,:actor,:version,:owner,:cp,:policy,CAST(:profile AS jsonb))"""),
            dict(
                t=row["tenant_id"],
                r=row["id"],
                actor=actor,
                version=auth_version,
                owner=keeper.owner_id,
                cp=checkpoint,
                policy=policy_version(),
                profile=json.dumps(profile.model_dump(mode="json")),
            ),
        ).scalar_one()
    except DBAPIError as error:
        code = getattr(getattr(error.orig, "diag", None), "message_primary", "")
        if getattr(error.orig, "sqlstate", None) == "22023" and code.startswith(
            ("APPLICATION_", "BUDGET_")
        ):
            raise BudgetLedgerError(code) from error
        raise
    if token is None:
        return False
    keeper.register_recovery(row["tenant_id"], row["id"], token)
    return True


def original_observation(c: Connection, row: RowMapping) -> RowMapping:
    return (
        c.execute(
            select(tables.application_context_observations).where(
                tables.application_context_observations.c.tenant_id == row["tenant_id"],
                tables.application_context_observations.c.run_id == row["id"],
            )
        )
        .mappings()
        .one()
    )


def is_recovery(gateway: object, tenant: UUID, run: UUID) -> bool:
    keeper = getattr(gateway, "application_lease_keeper", None)
    return isinstance(keeper, ApplicationLeaseKeeper) and keeper.is_recovery(tenant, run)
