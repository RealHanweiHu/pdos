"""Shared B3 creation authority and product persistence, within the caller's UOW."""

from uuid import uuid4

from sqlalchemy import text

from pdos_next.database import require_context
from pdos_next.errors import DomainError
from pdos_next.models import Product


def require_creation(s, ctx, *, product_id=None, decision=None):
    from pdos_next.service import require_access

    require_context(s, ctx)
    if decision is None:
        return require_access(s, ctx, product_id, write=True, lock=True)
    # A G0 reviewer may only read the category. The immutable named decision,
    # not a borrowed owner identity or a broad can_write grant, authorizes its outputs.
    if (
        ctx.run_id
        or ctx.agent_run_id
        or ctx.actor_id != ctx.requester_id
        or decision.tenant_id != ctx.tenant_id
        or decision.category_id != ctx.category_id
        or decision.decided_by != ctx.requester_id
        or decision.outcome != "approved"
        or (product_id is not None and product_id != decision.created_product_id)
        or not s.scalar(
            text("SELECT m3_reviewer(:t,:c,:p)"),
            {
                "t": ctx.tenant_id,
                "c": ctx.category_id,
                "p": decision.proposal_id,
            },
        )
    ):
        raise DomainError("NAMED_DECISION_REQUIRED", "创建结果须属于本次有效 G0 决定。", 403)
    return require_access(s, ctx, None, lock=True)


def create_product(
    s,
    ctx,
    *,
    name,
    purpose,
    owner_id=None,
    visibility="category",
    product_id=None,
    decision=None,
    parent_product_id=None,
):
    require_creation(s, ctx, decision=decision)
    if decision and product_id != decision.created_product_id:
        raise DomainError("FORBIDDEN_SCOPE", "型号不属于本次 G0 结果。", 403)
    product = Product(
        id=product_id or uuid4(),
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        name=name,
        purpose=purpose,
        owner_id=owner_id or ctx.requester_id,
        parent_product_id=parent_product_id,
        visibility=visibility,
    )
    s.add(product)
    s.flush([product])
    return product


def set_g0_targets(s, ctx, product, decision, *, price, segments):
    """M3's B3 supplement; absent commercial facts remain NULL."""
    from pdos_next.domain.preproject.category_models import ProductTargetSegment

    require_creation(s, ctx, product_id=product.id, decision=decision)
    s.execute(
        text(
            "UPDATE products SET target_price=:amount,target_price_currency=:currency,"
            "target_price_basis=:basis,target_price_includes_tax=:includes_tax,"
            "target_price_as_of=:as_of "
            "WHERE id=:id AND tenant_id=:tenant"
        ),
        {
            "id": product.id,
            "tenant": ctx.tenant_id,
            **{
                key: price.get(key)
                for key in ("amount", "currency", "basis", "includes_tax", "as_of")
            },
        },
    )
    for entry in segments:
        if (
            entry.kind != "segment"
            or entry.category_id != ctx.category_id
            or entry.tenant_id != ctx.tenant_id
        ):
            raise DomainError("FORBIDDEN_SCOPE", "目标细分须引用本品类的固定知识版本。", 403)
        s.add(
            ProductTargetSegment(
                tenant_id=ctx.tenant_id,
                category_id=ctx.category_id,
                product_id=product.id,
                segment_lineage_id=entry.lineage_id,
                segment_version=entry.version,
            )
        )
    s.flush()
