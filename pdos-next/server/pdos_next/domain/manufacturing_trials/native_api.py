"""Scoped Pilot reads and source preparation; writes use the common Command."""

from uuid import UUID

from fastapi import FastAPI, Request

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.domain.manufacturing_baseline.api import _query
from pdos_next.errors import DomainError
from pdos_next.service import Context

from .native_schemas import CREATE_OPERATION, RESULT_OPERATION


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

    @app.get("/v1/categories/{category_id}/products/{product_id}/pilots")
    def pilot_history(
        request: Request,
        product_id: UUID,
        project_id: UUID,
        history_cursor: str | None = None,
        ctx: Context = auth_dependency,
    ):
        from .native_service import list_pilots

        _query(request, {"project_id", "history_cursor"})
        with session(ctx, reading=True) as s:
            return list_pilots(
                s, ctx, product_id, project_id=project_id, history_cursor=history_cursor
            )

    @app.get("/v1/categories/{category_id}/products/{product_id}/pilots/{pilot_id}")
    def pilot_detail(
        request: Request, product_id: UUID, pilot_id: UUID, ctx: Context = auth_dependency
    ):
        from .native_service import get_pilot

        _query(request, set())
        with session(ctx, reading=True) as s:
            return get_pilot(s, ctx, product_id, pilot_id)[1]

    @app.post("/v1/categories/{category_id}/products/{product_id}/pilots/inputs")
    def pilot_inputs(
        request: Request, product_id: UUID, data: Command, ctx: Context = auth_dependency
    ):
        from .native_service import inputs

        _query(request, set())
        if data.product_id != product_id or data.operation not in {
            CREATE_OPERATION,
            RESULT_OPERATION,
        }:
            raise DomainError("FORBIDDEN_SCOPE", "请选择本型号Pilot操作。", 403)
        with session(ctx) as s:
            return inputs(s, ctx, product_id, data)
