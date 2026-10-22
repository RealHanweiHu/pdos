"""Opaque shared-capacity reads within the caller's existing transaction."""

from sqlalchemy import func

from pdos_next.errors import DomainError
from pdos_next.request_proof import request_proof
from pdos_next.service import require_access


def capacity_summary(
    session, ctx, product_id, kind, identities, *, own=None, own_kind="build", watermark=()
):
    product = require_access(session, ctx, product_id)
    identities = tuple(sorted(set(identities), key=str))
    if not identities:
        return []
    proof = request_proof(session)
    key = ("physical-capacity", product_id, kind, identities, own, own_kind, watermark)
    if key not in proof.read_rows:
        values = session.scalar(
            func.physical_capacity_summary(
                ctx.tenant_id,
                product.category_id,
                product_id,
                kind,
                list(identities),
                own,
                own_kind,
            )
        )
        if not isinstance(values, list):
            raise DomainError("INTEGRITY_MISMATCH", "共享物理容量范围无法核对。")
        proof.read_rows[key] = values
    return proof.read_rows[key]
