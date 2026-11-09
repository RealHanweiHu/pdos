"""Project team and tenant role catalog endpoints; both writes are named-human T1."""

from uuid import UUID

from fastapi import Request

from pdos_next.core.database import category_transaction, tenant_session
from pdos_next.core.service import Context
from pdos_next.domain.manufacturing.baseline.api import _query

from . import roles, service

TEAM = "/v1/categories/{category_id}/products/{product_id}/projects/{project_id}/team"
CATALOG = "/v1/role-catalog"


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

    @app.get(TEAM)
    def project_team(
        request: Request, product_id: UUID, project_id: UUID, ctx: Context = auth_dependency
    ):
        _query(request, set())
        with reading(ctx) as s:
            return service.view(s, ctx, product_id, project_id)

    @app.post(TEAM)
    def set_project_team(
        request: Request,
        product_id: UUID,
        project_id: UUID,
        data: service.SetTeam,
        ctx: Context = auth_dependency,
    ):
        _query(request, set())
        return category_transaction(
            engine, ctx, lambda s: service.apply(s, ctx, product_id, project_id, data)
        )

    @app.get(CATALOG)
    def role_catalog(request: Request, ctx: Context = auth_dependency):
        _query(request, set())
        with reading(ctx) as s:
            return roles.reading(s, ctx)

    @app.post(CATALOG)
    def publish_role_catalog(
        request: Request, data: roles.PublishCatalog, ctx: Context = auth_dependency
    ):
        _query(request, set())
        return category_transaction(engine, ctx, lambda s: roles.publish(s, ctx, data))
