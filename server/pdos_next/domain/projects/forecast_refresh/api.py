"""READ route for the project forecast; the refresh uses the common command endpoint."""

from uuid import UUID

from pdos_next.core.database import tenant_session
from pdos_next.core.service import Context


def register_routes(app, engine, auth_dependency):
    @app.get("/v1/categories/{category_id}/products/{product_id}/projects/{project_id}/forecast")
    def project_forecast(product_id: UUID, project_id: UUID, ctx: Context = auth_dependency):
        from .service import view

        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
        ) as s:
            return view(s, ctx, product_id, project_id)
