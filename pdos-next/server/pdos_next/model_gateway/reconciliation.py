"""T1 accounting hooks inside the shared command transaction.

The common command service owns confirmation, deduplication and receipt/audit/
outbox. This module never sends a request, resumes a run or changes eligibility.
"""

from uuid import UUID

from sqlalchemy import select

from pdos_next.errors import DomainError
from pdos_next.model_gateway.reconciliation_schema import NormalizedUsage, ReconciliationPayload
from pdos_next.models import (
    BudgetReservation,
    Invocation,
    Principal,
    Product,
    Run,
    WorkRequest,
    now,
)

__all__ = ["NormalizedUsage", "ReconciliationPayload", "apply", "preview", "semantic", "validate"]


def _subject(s, ctx, product, call_id):
    from pdos_next.service import require_access

    actor = s.get(Principal, ctx.actor_id)
    if (
        actor is None
        or not actor.active
        or actor.kind != "human"
        or actor.tenant_id != ctx.tenant_id
        or ctx.actor_id != ctx.requester_id
        or ctx.run_id is not None
    ):
        raise DomainError("NAMED_DECISION_REQUIRED", "模型费用对账需要当前具名人员确认。", 403)
    require_access(s, ctx, product.id, write=True, lock=True)
    identity = s.scalar(
        select(BudgetReservation).where(
            BudgetReservation.tenant_id == ctx.tenant_id,
            BudgetReservation.call_id == call_id,
        )
    )
    if identity is None:
        raise DomainError("FORBIDDEN_SCOPE", "调用不在当前可读范围。", 403)
    run = s.scalar(
        select(Run)
        .where(
            Run.id == identity.run_id,
            Run.tenant_id == ctx.tenant_id,
            Run.product_id == product.id,
        )
        .with_for_update()
    )
    work = s.get(WorkRequest, run.work_id) if run else None
    # WorkRequest/Run are private to their accountable owner in the current model.
    # A product write grant alone cannot expose somebody else's private model call.
    if (
        run is None
        or run.requester_id != ctx.actor_id
        or work is None
        or work.tenant_id != ctx.tenant_id
        or work.product_id != product.id
        or work.accountable_owner_id != ctx.actor_id
    ):
        raise DomainError("FORBIDDEN_SCOPE", "调用不在当前可读范围。", 403)
    row = s.scalar(
        select(BudgetReservation)
        .where(BudgetReservation.id == identity.id, BudgetReservation.tenant_id == ctx.tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return row, run


def validate(s, ctx, command, product, payload: ReconciliationPayload):
    if command.operation != "ai.model_call.reconcile" or command.product_id != product.id:
        raise DomainError("FORBIDDEN_SCOPE", "模型费用对账命令范围不匹配。", 403)
    row, _ = _subject(s, ctx, product, payload.call_id)
    # The common service replays accepted intents before apply; do not reject an
    # original accepted revision here merely because that successful action advanced it.
    return row


def semantic(payload: ReconciliationPayload):
    return payload.model_dump(mode="json", exclude={"confirmation_token"})


def apply(s, ctx, command, product, payload: ReconciliationPayload):
    from pdos_next.model_gateway.persistent_budget import _apply_settlement, _settlement

    row = validate(s, ctx, command, product, payload)
    run = s.get(Run, row.run_id)
    if row.revision != payload.expected_revision:
        raise DomainError("VERSION_CONFLICT", "原调用的费用状态已变化，请重新核对。")
    if row.request_id and payload.request_id and row.request_id != payload.request_id:
        raise DomainError("MODEL_BUDGET_CONFLICT", "对账必须对应原调用编号。")
    invocation = s.scalar(
        select(Invocation).where(
            Invocation.tenant_id == ctx.tenant_id,
            Invocation.run_id == run.id,
            Invocation.call_id == payload.call_id,
        )
    )
    if (
        row.status == "reserved"
        and invocation is not None
        and invocation.status == "started"
        and run.lease_until is not None
        and run.lease_until > now()
    ):
        raise DomainError("MODEL_CALL_IN_FLIGHT", "原调用仍在执行，请等待明确结果后对账。")
    revision_before = row.revision
    if payload.resolution == "known":
        status = row.status if row.status in {"completed", "rejected"} else "completed"
        final = _settlement(
            payload.usage.provider_usage(), status, row.error_code, payload.request_id
        )
        exceeded = _apply_settlement(run, row, final)
    else:
        if row.status not in {"reserved", "unknown"}:
            raise DomainError("MODEL_BUDGET_CONFLICT", "已知费用不能退回未知状态。")
        # This acknowledges uncertainty, it neither estimates a fee nor releases held funds.
        row.status = "unknown"
        row.error_code = row.error_code or "MODEL_RESULT_UNKNOWN"
        row.request_id = row.request_id or payload.request_id
        exceeded = run.used_tokens + run.reserved_tokens > run.token_limit
    row.revision = revision_before + 1
    history = list(row.reconciliation_history or [])
    history.append(
        {
            "actor_id": str(ctx.actor_id),
            "resolution": payload.resolution,
            "reason_code": payload.reason_code,
            "evidence_ref": payload.evidence_ref,
            "request_id": row.request_id,
            "usage": payload.usage.model_dump() if payload.usage else None,
            "occurred_at": now().isoformat(),
            "prior_revision": revision_before,
        }
    )
    row.reconciliation_history = history
    # Transient result flag for the shared receipt builder. Preview derives the
    # same fact from persisted counters; no model outcome/qualification is changed.
    row.budget_exceeded = exceeded
    s.flush()
    return row, "model_call", "private"


def preview(s, ctx, product_id: UUID, call_id: UUID):
    product = s.scalar(
        select(Product)
        .where(Product.id == product_id, Product.tenant_id == ctx.tenant_id)
        .with_for_update()
    )
    if product is None:
        raise DomainError("FORBIDDEN_SCOPE", "产品不在当前授权范围。", 403)
    row, run = _subject(s, ctx, product, call_id)
    return {
        "call_id": str(row.call_id),
        "run_id": str(row.run_id),
        "revision": row.revision,
        "status": row.status,
        "held_tokens": row.reserved if row.status in {"reserved", "unknown"} else 0,
        "charged_tokens": row.charged,
        "usage": row.normalized_usage,
        "request_id": row.request_id,
        "provider_version": row.provider_version,
        "protocol": row.protocol,
        "route_digest": row.route_digest,
        "request_digest": row.request_digest,
        "settled_at": row.settled_at.isoformat() if row.settled_at else None,
        "run_status": run.status,
        "run_used_tokens": run.used_tokens,
        "run_reserved_tokens": run.reserved_tokens,
        "run_token_limit": run.token_limit,
        "budget_exceeded": run.used_tokens + run.reserved_tokens > run.token_limit,
        "model_result_unchanged": True,
        "can_retry": False,
        "history": row.reconciliation_history or [],
    }
