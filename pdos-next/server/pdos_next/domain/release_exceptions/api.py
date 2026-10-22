"""Project-scoped exception reads; business writes use the common Command path."""

from uuid import UUID

from fastapi import FastAPI, Request

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.domain.manufacturing_baseline.api import _query
from pdos_next.service import Context


def register_routes(app: FastAPI, engine, auth_dependency):
    def session(ctx, *, reading=False):
        return tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=reading,
        )

    @app.get("/v1/categories/{category_id}/products/{product_id}/release-exceptions")
    def exception_history(
        request: Request,
        product_id: UUID,
        project_id: UUID,
        history_cursor: str | None = None,
        ctx: Context = auth_dependency,
    ):
        from .service import list_exceptions

        _query(request, {"project_id", "history_cursor"})
        with session(ctx, reading=True) as s:
            return list_exceptions(
                s, ctx, product_id, project_id=project_id, history_cursor=history_cursor
            )

    @app.get("/v1/categories/{category_id}/products/{product_id}/release-exceptions/{exception_id}")
    def exception_detail(
        request: Request,
        product_id: UUID,
        exception_id: UUID,
        ctx: Context = auth_dependency,
    ):
        from .service import get_exception

        _query(request, set())
        with session(ctx, reading=True) as s:
            return get_exception(s, ctx, product_id, exception_id)[1]

    @app.post("/v1/categories/{category_id}/products/{product_id}/release-exception/inputs")
    def exception_inputs(
        request: Request,
        product_id: UUID,
        data: Command,
        ctx: Context = auth_dependency,
    ):
        from .service import inputs

        _query(request, set())
        with session(ctx) as s:
            return inputs(s, ctx, product_id, data)
