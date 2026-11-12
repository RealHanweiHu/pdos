"""READ routes for supplier commitments; writes use the common command endpoint."""

from uuid import UUID

from pdos_next.core.database import tenant_session
from pdos_next.core.service import Context


def register_routes(app, engine, auth_dependency):
    @app.get(
        "/v1/categories/{category_id}/products/{product_id}/builds/{build_id}/supply-commitments"
    )
    def supply_commitments(product_id: UUID, build_id: UUID, ctx: Context = auth_dependency):
        from .service import build_view

        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
        ) as s:
            return build_view(s, ctx, product_id, build_id)

    @app.get(
        "/v1/categories/{category_id}/products/{product_id}/supply-commitments/{commitment_id}"
    )
    def supply_commitment(product_id: UUID, commitment_id: UUID, ctx: Context = auth_dependency):
        from .service import get_commitment

        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
        ) as s:
            return get_commitment(s, ctx, product_id, commitment_id)
