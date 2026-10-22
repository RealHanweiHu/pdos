"""Read feedback; effects always enter the shared atomic command boundary."""

from uuid import UUID

from fastapi import Request

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.domain.manufacturing_baseline.api import _query
from pdos_next.service import Context


def register_routes(app, engine, auth_dependency):
    def session(ctx, *, reading=False):
        return tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=reading,
        )

    @app.get("/v1/categories/{category_id}/field-feedback")
    @app.get("/v1/categories/{category_id}/products/{product_id}/field-feedback")
    def feedback(
        request: Request,
        product_id: UUID | None = None,
        project_id: UUID | None = None,
        ctx: Context = auth_dependency,
    ):
        from .views import workspace

        _query(request, {"project_id"})
        with session(ctx, reading=True) as s:
            return workspace(s, ctx, product_id, project_id)

    @app.post("/v1/categories/{category_id}/field-feedback/inputs")
    @app.post("/v1/categories/{category_id}/products/{product_id}/field-feedback/inputs")
    def feedback_inputs(
        request: Request,
        data: Command,
        product_id: UUID | None = None,
        ctx: Context = auth_dependency,
    ):
        from .service import inputs

        _query(request, set())
        with session(ctx) as s:
            return inputs(s, ctx, product_id, data)
