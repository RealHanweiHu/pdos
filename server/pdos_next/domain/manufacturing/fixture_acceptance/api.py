"""Read route for fixture acceptances (D306); writes use the common command path."""

from uuid import UUID

from pdos_next.core.database import tenant_session
from pdos_next.core.service import Context

from . import service


def register_routes(app, engine, auth_dependency):
    @app.get(
        "/v1/categories/{category_id}/products/{product_id}/projects/{project_id}/fixture-acceptances"
    )
    def fixture_acceptances(product_id: UUID, project_id: UUID, ctx: Context = auth_dependency):
        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
        ) as s:
            return service.list_acceptances(s, ctx, product_id, project_id)
