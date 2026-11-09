"""Read routes for interface contracts (D312); writes use the common command path."""

from uuid import UUID

from pdos_next.core.database import tenant_session
from pdos_next.core.service import Context

from . import service

ROOT = "/v1/categories/{category_id}/products/{product_id}"


def register_routes(app, engine, auth_dependency):
    def reading(ctx):
        return tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=True,
        )

    @app.get(ROOT + "/projects/{project_id}/interfaces")
    def project_interfaces(product_id: UUID, project_id: UUID, ctx: Context = auth_dependency):
        with reading(ctx) as s:
            return service.list_interfaces(s, ctx, product_id, project_id)

    @app.get(ROOT + "/interfaces/{interface_id}")
    def interface_detail(product_id: UUID, interface_id: UUID, ctx: Context = auth_dependency):
        with reading(ctx) as s:
            return service.get_interface(s, ctx, product_id, interface_id)
