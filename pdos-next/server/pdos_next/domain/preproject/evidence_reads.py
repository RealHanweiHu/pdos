"""Evidence views under the current reader's database audience, with pinned versions."""

from uuid import UUID

from sqlalchemy import select, text

from pdos_next.category_scope import category_scope
from pdos_next.models import Claim

from .access import fail, proposal


def claim_view(row):
    return {
        "id": str(row.id),
        "version": row.revision,
        "status": row.status,
        "proposal_id": str(row.proposal_id) if row.proposal_id else None,
        "product_id": str(row.product_id) if row.product_id else None,
        "nature": row.nature,
        "availability": row.availability,
        "content": row.content,
        "statement": row.statement,
        "vendor_claimed": row.vendor_claimed,
        "source": {
            "kind": row.source_kind,
            "id": str(row.snapshot_id if row.source_kind == "snapshot" else row.artifact_id),
            "version": row.source_revision,
            "locator": row.source_locator or f"line:{row.line}",
            "quote": row.quote,
        },
        "privacy": row.privacy,
        "origin": row.origin,
        "writer_id": str(row.writer_id),
        "run_id": str(row.run_id) if row.run_id else None,
        "confirmed_by": str(row.confirmed_by) if row.confirmed_by else None,
        "receipt_id": str(row.receipt_id) if row.receipt_id else None,
    }


def claims(s, ctx, *, proposal_id=None, status="active", cursor=None, page_size=50):
    category_scope(s, ctx)
    if status not in {None, "active", "withdrawn", "reverted"} or not 1 <= page_size <= 200:
        fail("VALIDATION_FAILED", "claim_filter_invalid", "事实状态或分页大小无效。")
    if proposal_id:
        proposal(s, ctx, proposal_id)
    query = select(Claim).where(
        Claim.tenant_id == ctx.tenant_id, Claim.category_id == ctx.category_id
    )
    if proposal_id:
        query = query.where(Claim.proposal_id == proposal_id)
    if status:
        query = query.where(Claim.status == status)
    if cursor:
        try:
            cursor = UUID(str(cursor))
        except (TypeError, ValueError):
            fail("VALIDATION_FAILED", "cursor_invalid", "分页游标无效。")
        query = query.where(Claim.id > cursor)
    rows = list(s.scalars(query.order_by(Claim.id).limit(page_size + 1)))
    return {
        "items": [claim_view(row) for row in rows[:page_size]],
        "next_cursor": str(rows[page_size - 1].id) if len(rows) > page_size else None,
        "as_of": s.scalar(text("SELECT transaction_timestamp()")).isoformat(),
    }


def claim(s, ctx, identity):
    category_scope(s, ctx)
    row = s.get(Claim, identity)
    if not row or row.tenant_id != ctx.tenant_id or row.category_id != ctx.category_id:
        fail("NOT_FOUND", "claim_not_found", "事实不存在或不在当前受众内。", 404)
    return claim_view(row)
