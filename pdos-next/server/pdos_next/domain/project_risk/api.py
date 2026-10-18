"""Ordinary project reads and zero-write input preparation."""

from uuid import UUID

from fastapi import Request

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.domain.manufacturing_baseline.api import _query
from pdos_next.service import Context


def register_routes(app, engine, auth_dependency):
    def session(ctx, reading=False):
        return tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=reading,
        )

    @app.get("/v1/categories/{category_id}/products/{product_id}/project-work/risks")
    def project_risks(
        request: Request, product_id: UUID, project_id: UUID, ctx: Context = auth_dependency
    ):
        from .views import workspace

        _query(request, {"project_id"})
        with session(ctx, True) as s:
            return workspace(s, ctx, product_id, project_id)

    @app.post("/v1/categories/{category_id}/products/{product_id}/project-work/risks/inputs")
    def project_risk_inputs(
        request: Request, product_id: UUID, data: Command, ctx: Context = auth_dependency
    ):
        from .service import inputs

        _query(request, set())
        with session(ctx) as s:
            return inputs(s, ctx, product_id, data)
