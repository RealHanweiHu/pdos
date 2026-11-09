"""Routes for the single-project overview and the manager cockpit; reads only."""

from uuid import UUID

from pdos_next.core.database import tenant_session
from pdos_next.core.service import Context

from .overview import overview
from .portfolio import cockpit


def register_routes(app, engine, auth_dependency):
    @app.get("/v1/categories/{category_id}/products/{product_id}/projects/{project_id}/overview")
    def project_overview(product_id: UUID, project_id: UUID, ctx: Context = auth_dependency):
        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=True,
        ) as s:
            return overview(s, ctx, product_id, project_id)

    @app.get("/v1/personal/project-cockpit")
    def project_cockpit(ctx: Context = auth_dependency):
        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            read_snapshot=True,
        ) as s:
            return cockpit(s, ctx)
