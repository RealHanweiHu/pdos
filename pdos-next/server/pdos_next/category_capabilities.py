"""Presentation-only category capabilities from existing current memberships."""

from sqlalchemy import select

from pdos_next.database import require_context
from pdos_next.models import Grant, Principal, now
from pdos_next.request_proof import authority_current


def product_management_categories(session, ctx, category_ids):
    require_context(session, ctx)
    if not category_ids or ctx.actor_id != ctx.requester_id or ctx.run_id or ctx.agent_run_id:
        return set()
    rows = session.execute(
        select(Principal, Grant)
        .join(
            Grant,
            (Grant.tenant_id == Principal.tenant_id) & (Grant.principal_id == Principal.id),
        )
        .where(
            Principal.tenant_id == ctx.tenant_id,
            Principal.id == ctx.actor_id,
            Grant.category_id.in_(category_ids),
        )
    )
    at = now()
    return {
        grant.category_id
        for person, grant in rows
        if person.kind == "human"
        and grant.product_manager
        and authority_current([(person, grant)], at)
    }
