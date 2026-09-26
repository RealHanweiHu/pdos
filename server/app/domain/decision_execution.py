"""Resolve Decision follow-up evidence from actual domain execution receipts."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select

from app.db.schema import tables


def execution_receipt(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    decision: Any,
    audit_id: int,
) -> dict[str, object] | None:
    if decision.decision_kind in {"rebaseline", "definition_release"}:
        return None
    audit = (
        connection.execute(
            select(tables.audit_log).where(
                tables.audit_log.c.tenant_id == tenant_id,
                tables.audit_log.c.project_id == project_id,
                tables.audit_log.c.id == audit_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if audit is None or audit["timestamp"] < decision.decided_at:
        return None
    target_id = audit["entity_id"]
    # A receipt proves the specific linked target and its current execution,
    # never merely that an unrelated task or another Gate once succeeded.
    if decision.gate_id is not None:
        if audit["action"] != "gate.approve" or target_id != decision.gate_id:
            return None
        target = (
            connection.execute(
                select(tables.gates).where(
                    tables.gates.c.tenant_id == tenant_id,
                    tables.gates.c.project_id == project_id,
                    tables.gates.c.id == target_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if target is None or target["status"] != "approved":
            return None
        latest = (
            connection.execute(
                select(tables.gate_signoff_rounds)
                .where(
                    tables.gate_signoff_rounds.c.tenant_id == tenant_id,
                    tables.gate_signoff_rounds.c.project_id == project_id,
                    tables.gate_signoff_rounds.c.gate_id == target_id,
                )
                .order_by(tables.gate_signoff_rounds.c.round_number.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        if latest is None or str(latest["id"]) != (audit["context"] or {}).get("round_id"):
            return None
        label, kind = target["name"], "gate"
    elif decision.decision_kind == "ecn_effectivity":
        if audit["action"] != "change.ecn.effectivity_approved":
            return None
        target = (
            connection.execute(
                select(tables.engineering_change_notices).where(
                    tables.engineering_change_notices.c.tenant_id == tenant_id,
                    tables.engineering_change_notices.c.project_id == project_id,
                    tables.engineering_change_notices.c.id == target_id,
                    tables.engineering_change_notices.c.effectivity_decision_id == decision.id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if target is None or target["status"] != "erp_handoff":
            return None
        # Effectivity approval is this decision's action. ERP receipt/execution
        # remains its own lifecycle and is not asserted by this receipt.
        label, kind = target["title"], "ecn_effectivity"
    elif decision.decision_kind in {
        "technical_choice",
        "supplier_choice",
        "process_decision",
        "ccr_response",
    }:
        if audit["action"] not in {"task.transition"}:
            return None
        target = (
            connection.execute(
                select(tables.tasks).where(
                    tables.tasks.c.tenant_id == tenant_id,
                    tables.tasks.c.project_id == project_id,
                    tables.tasks.c.id == target_id,
                    tables.tasks.c.id == decision.follow_up_task_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if target is None or target["status"] != "done" or not target["completion_evidence_ref"]:
            return None
        saved = audit["after_snapshot"] or {}
        if (
            saved.get("status") != "done"
            or saved.get("completion_evidence_ref") != target["completion_evidence_ref"]
        ):
            return None
        # A reopened and subsequently re-completed task needs its new receipt.
        if target["completed_at"] is None or target["completed_at"] != audit["timestamp"]:
            return None
        label, kind = target["title"], "task"
    else:
        # Baseline/definition release require their real domain implementation;
        # neither free text nor a generic task can stand in for that hard action.
        return None
    return {
        "audit_id": audit_id,
        "kind": kind,
        "target_id": str(target_id),
        "label": label,
        "action": audit["action"],
        "executed_at": audit["timestamp"].isoformat(),
    }


def execution_choices(
    connection: Connection, *, tenant_id: UUID, project_id: UUID, decision: Any
) -> list[dict[str, object]]:
    target_id = decision.gate_id or decision.follow_up_task_id
    if decision.decision_kind == "ecn_effectivity":
        target_id = connection.execute(
            select(tables.engineering_change_notices.c.id).where(
                tables.engineering_change_notices.c.tenant_id == tenant_id,
                tables.engineering_change_notices.c.project_id == project_id,
                tables.engineering_change_notices.c.effectivity_decision_id == decision.id,
            )
        ).scalar_one_or_none()
    if target_id is None:
        return []
    audit_ids = connection.execute(
        select(tables.audit_log.c.id)
        .where(
            tables.audit_log.c.entity_id == target_id,
            tables.audit_log.c.tenant_id == tenant_id,
            tables.audit_log.c.project_id == project_id,
            tables.audit_log.c.timestamp >= decision.decided_at,
            tables.audit_log.c.action.in_(
                ("gate.approve", "change.ecn.effectivity_approved", "task.transition")
            ),
        )
        .order_by(tables.audit_log.c.id.desc())
    )
    results = []
    for audit_id in audit_ids.scalars():
        receipt = execution_receipt(
            connection,
            tenant_id=tenant_id,
            project_id=project_id,
            decision=decision,
            audit_id=audit_id,
        )
        if receipt is not None:
            results.append(receipt)
    return results
