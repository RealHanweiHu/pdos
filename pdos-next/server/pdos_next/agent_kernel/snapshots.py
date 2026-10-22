"""Domain-transaction snapshot registration from server-held immutable work artifacts."""

from pdos_next.database import require_context
from pdos_next.errors import DomainError
from pdos_next.models import Receipt

from .models import AgentRun, PublicWebSnapshot


def register_snapshot(session, ctx, scope, artifacts, *, artifact_id, receipt_id):
    require_context(session, ctx)
    run = session.get(AgentRun, scope.run_id)
    receipt = session.get(Receipt, receipt_id)
    if (
        not run
        or run.tenant_id != ctx.tenant_id
        or run.requester_id != ctx.requester_id
        or not receipt
        or receipt.requester_id != ctx.requester_id
        or receipt.category_id != ctx.category_id
        or ctx.category_id is None
    ):
        raise DomainError("FORBIDDEN_SCOPE", "快照须引用当前运行与真实领域回执。")
    snapshot = artifacts.snapshot(scope, artifact_id)
    if run.category_id == ctx.category_id:
        permitted = (
            receipt.operation == "research.snapshot.register" and receipt.subject_id == snapshot.id
        )
    else:
        permitted = (
            run.category_id is None
            and not run.private_context
            and receipt.operation == "category.create"
            and receipt.subject_id == ctx.category_id
        )
    if not permitted:
        raise DomainError("FORBIDDEN_SCOPE", "快照登记回执与品类范围不同。")
    prior = session.get(PublicWebSnapshot, snapshot.id)
    if prior:
        if prior.registered_by_run_id != run.id or prior.content_hash != snapshot.content_hash:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "快照身份已有不同来源。")
        return prior
    row = PublicWebSnapshot(
        id=snapshot.id,
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        owner_id=ctx.requester_id,
        visibility="private" if run.private_context else "category",
        registered_by_run_id=run.id,
        receipt_id=receipt.id,
        **{
            key: getattr(snapshot, key)
            for key in (
                "url",
                "final_url",
                "title",
                "summary",
                "retrieved_at",
                "markdown",
                "content_hash",
                "provider",
                "credibility",
                "status",
            )
        },
    )
    session.add(row)
    session.flush()
    return row
