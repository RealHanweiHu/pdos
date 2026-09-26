"""Persist missing-input handoffs, retaining the original model receipt and budget."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, func, select, text

from app.ai.application_leases import bind_write
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.call_identity import ModelCallSlot, model_call_id
from app.db.schema import tables
from app.domain.test_plan_changes import TestPlanChangePayload, digest


def save_test_plan_wait(
    c: Connection, *, tenant: UUID, run: UUID, finding: UUID, payload: TestPlanChangePayload
) -> bool:
    if not payload.questions:
        return False
    auth = (
        c.execute(
            select(tables.application_authorizations).where(
                tables.application_authorizations.c.tenant_id == tenant,
                tables.application_authorizations.c.run_id == run,
            )
        )
        .mappings()
        .one_or_none()
    )
    if auth is None:
        return False  # Historical unbudgeted adapters retain their original lifecycle.
    checkpoint = c.execute(
        select(tables.application_result_checkpoints.c.id).where(
            tables.application_result_checkpoints.c.tenant_id == tenant,
            tables.application_result_checkpoints.c.run_id == run,
            tables.application_result_checkpoints.c.model_call_id
            == model_call_id(run, ModelCallSlot.TEST_PLAN_SUGGESTION),
        )
    ).scalar_one_or_none()
    if checkpoint is None:
        raise BudgetLedgerError("APPLICATION_WAIT_CHECKPOINT_REQUIRED")
    c.execute(
        tables.application_input_waits.insert().values(
            id=uuid4(),
            tenant_id=tenant,
            run_id=run,
            finding_id=finding,
            checkpoint_id=checkpoint,
            owner_user_id=auth["principal_id"],
            created_at=func.clock_timestamp(),
            expires_at=auth["expires_at"],
            body=dict(
                version="application-wait.v1",
                goal="补充测试计划调整所需信息",
                summary=payload.summary,
                questions=payload.questions,
                plan_id=str(payload.base_plan_id),
                base_digest=payload.base_digest,
                candidate_digest=digest(payload.model_dump(mode="json")),
                sources=payload.source_snapshots,
                next_action="reply_or_review_finding",
                completed_receipts=[str(checkpoint), str(finding)],
                non_retryable=["unknown_model_receipt", "expired_authorization"],
            ),
        )
    )
    return True


def resume_wait(
    c: Connection,
    gateway: Any,
    *,
    tenant: UUID,
    parent_run: UUID | None,
    child_run: UUID,
    queued_child: bool = False,
) -> None:
    if parent_run is None:
        return
    wait = (
        c.execute(
            select(tables.application_input_waits)
            .where(
                tables.application_input_waits.c.tenant_id == tenant,
                tables.application_input_waits.c.run_id == parent_run,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if wait is None or wait["resolution"] in {
        "finding_accepted",
        "finding_rejected",
        "finding_applied",
    }:
        return
    if wait["resolved_at"] is not None:
        raise BudgetLedgerError("APPLICATION_INPUT_ALREADY_RESOLVED")
    now = c.execute(select(func.clock_timestamp())).scalar_one()
    auths = {
        r["run_id"]: r
        for r in c.execute(
            select(tables.application_authorizations).where(
                tables.application_authorizations.c.tenant_id == tenant,
                tables.application_authorizations.c.run_id.in_([parent_run, child_run]),
            )
        ).mappings()
    }
    parent, child = auths.get(parent_run), auths.get(child_run)
    if (
        now >= wait["expires_at"]
        or parent is None
        or child is None
        or parent["principal_id"] != child["principal_id"]
        or parent["pins"] != child["pins"]
        or parent["body"]["policy_version"] != child["body"]["policy_version"]
        or parent["lineage_id"] != child["lineage_id"]
    ):
        raise BudgetLedgerError("APPLICATION_WAIT_AUTHORIZATION_CHANGED")
    if queued_child:
        fresh = c.execute(
            text("""SELECT 1 FROM cehub_ai.agent_runs
            WHERE tenant_id=:tenant AND id=:run AND status='running'
             AND run_context->>'application_queue_version'='1'
             AND xmin::text::numeric=pg_current_xact_id()::text::numeric % 4294967296"""),
            {"tenant": tenant, "run": child_run},
        ).scalar_one_or_none()
        if fresh is None:
            raise BudgetLedgerError("APPLICATION_WAIT_QUEUE_CREATION_REQUIRED")
    else:
        bind_write(c, gateway, tenant, child_run)
    c.execute(
        tables.application_input_waits.update()
        .where(
            tables.application_input_waits.c.id == wait["id"],
        )
        .values(resolved_at=now, resolution="input_received", continuation_run_id=child_run)
    )
    c.execute(
        tables.agent_runs.update()
        .where(
            tables.agent_runs.c.tenant_id == tenant,
            tables.agent_runs.c.id == parent_run,
            tables.agent_runs.c.status == "waiting_input",
        )
        .values(status="succeeded", completed_at=now, updated_at=now)
    )
