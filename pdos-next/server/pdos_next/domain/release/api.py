"""Scoped fixed-package preparation and reads; effects use common Commands."""

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

    @app.get("/v1/categories/{category_id}/products/{product_id}/release-packages")
    def package_history(
        request: Request,
        product_id: UUID,
        project_id: UUID,
        history_cursor: str | None = None,
        ctx: Context = auth_dependency,
    ):
        from .service import list_packages

        _query(request, {"project_id", "history_cursor"})
        with session(ctx, reading=True) as s:
            return list_packages(
                s, ctx, product_id, project_id=project_id, history_cursor=history_cursor
            )

    @app.get("/v1/categories/{category_id}/products/{product_id}/release-packages/{package_id}")
    def package_detail(
        request: Request, product_id: UUID, package_id: UUID, ctx: Context = auth_dependency
    ):
        from .service import get_package

        _query(request, set())
        with session(ctx, reading=True) as s:
            return get_package(s, ctx, product_id, package_id)[1]

    @app.post("/v1/categories/{category_id}/products/{product_id}/release/inputs")
    def release_inputs(
        request: Request, product_id: UUID, data: Command, ctx: Context = auth_dependency
    ):
        from .service import inputs

        _query(request, set())
        with session(ctx) as s:
            return inputs(s, ctx, product_id, data)
