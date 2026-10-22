from sqlalchemy import select, text

from pdos_next.clock import now
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal


def fail(code, reason, message, status=409, **detail):
    error = DomainError(code, message, status, detail=detail)
    error.detail["reason"] = reason
    raise error


def installed(s):
    from pdos_next.request_proof import snapshot_scalar

    if not snapshot_scalar(
        s, ("m3", "installed"), text("SELECT to_regclass('public.proposals') IS NOT NULL")
    ):
        fail("SOURCE_UNAVAILABLE", "m3_schema_pending", "M3 提前候选尚未安装到此环境。", 503)


def human(s, ctx):
    p = s.get(Principal, ctx.actor_id)
    if (
        not p
        or p.kind != "human"
        or not p.active
        or ctx.actor_id != ctx.requester_id
        or ctx.run_id
        or ctx.agent_run_id
    ):
        fail("NAMED_DECISION_REQUIRED", "human_only", "此操作只由具名本人办理。", 403)


def member(s, ctx, person_id, *, reviewer=False):
    result = s.execute(
        select(Principal, Grant)
        .join(
            Grant, (Grant.tenant_id == Principal.tenant_id) & (Grant.principal_id == Principal.id)
        )
        .where(
            Principal.tenant_id == ctx.tenant_id,
            Principal.id == person_id,
            Grant.category_id == ctx.category_id,
        )
        .with_for_update(read=True)
    ).first()
    if (
        not result
        or not result[0].active
        or result[0].kind != "human"
        or (result[1].expires_at is not None and result[1].expires_at <= now())
        or (reviewer and not result[1].product_manager)
    ):
        fail(
            "FORBIDDEN_SCOPE" if reviewer else "VALIDATION_FAILED",
            "reviewer_not_eligible" if reviewer else "assignee_not_member",
            "评审人须有当前品类的产品经理能力。" if reviewer else "负责人须是品类有效成员。",
            403,
        )
    return result[1]


def proposal(s, ctx, proposal_id, *, lock=False):
    from .models import Proposal

    installed(s)
    query = select(Proposal).where(
        Proposal.tenant_id == ctx.tenant_id,
        Proposal.category_id == ctx.category_id,
        Proposal.id == proposal_id,
    )
    row = (
        s.get(Proposal, proposal_id)
        if not lock and getattr(s, "info", {}).get("read_snapshot")
        else s.scalar(query.with_for_update() if lock else query)
    )
    if not row or row.tenant_id != ctx.tenant_id or row.category_id != ctx.category_id:
        fail("NOT_FOUND", "proposal_not_found", "提案不存在或不在当前受众内。", 404)
    return row


def editable(s, ctx, proposal_id):
    row = proposal(s, ctx, proposal_id, lock=True)
    if row.status not in {"draft", "returned"}:
        fail("VERSION_CONFLICT", "proposal_locked", "此提案已锁定；退回后可继续编辑。")
    return row
