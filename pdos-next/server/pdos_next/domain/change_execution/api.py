"""Thin host-registered HTTP routes; domain guards and the caller UOW own writes."""

from uuid import UUID

from fastapi import FastAPI, Request
from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.service import Context

from .schemas import GraphCaptureInput


def _query(request: Request, allowed):
    if any(key not in allowed for key in request.query_params) or any(
        len(request.query_params.getlist(key)) != 1 for key in request.query_params
    ):
        raise DomainError("INVALID_PAYLOAD", "请使用唯一明确的变更范围。", 422)


def register_routes(app: FastAPI, engine, auth_dependency):
    """Use the host's existing authenticated Depends value; never create a login path."""

    @app.get("/v1/products/{product_id}/change-execution")
    def change_execution(
        request: Request,
        product_id: UUID,
        issue_id: UUID | None = None,
        change_id: UUID | None = None,
        ctx: Context = auth_dependency,
    ):
        from .service import list_changes

        _query(request, {"issue_id", "change_id"})
        with tenant_session(engine, ctx.tenant_id) as session:
            return list_changes(session, ctx, product_id, issue_id=issue_id, change_id=change_id)

    @app.post("/v1/products/{product_id}/change-execution/inputs")
    def change_execution_inputs(
        request: Request, product_id: UUID, data: Command, ctx: Context = auth_dependency
    ):
        from pdos_next.command_handlers import handler

        from .service import inputs

        _query(request, set())
        if data.product_id != product_id:
            raise DomainError("FORBIDDEN_SCOPE", "命令不在当前产品范围。", 403)
        with tenant_session(engine, ctx.tenant_id) as session:
            module = handler(data.operation)
            if data.operation in {
                "change.order.prepare",
                "change.order.approve",
                "change.implementation.record",
                "change.selection.decide",
            }:
                return module.inputs(session, ctx, product_id, data)
            return inputs(session, ctx, product_id, data)

    @app.post("/v1/products/{product_id}/change-execution/captures")
    def change_execution_capture(
        product_id: UUID, data: GraphCaptureInput, ctx: Context = auth_dependency
    ):
        from .service import prepare_capture

        # The recoverable graph is committed in its own tenant UOW. A later
        # impact command owns its sole Receipt/Audit/Outbox and can roll back
        # without deleting this prepared capture.
        with tenant_session(engine, ctx.tenant_id) as session:
            return prepare_capture(session, ctx, product_id, data)

    from pdos_next.change_order_store import CaptureInput

    @app.post("/v1/products/{product_id}/change-execution/implementation-captures")
    def implementation_capture(
        product_id: UUID, data: CaptureInput, ctx: Context = auth_dependency
    ):
        from pdos_next.change_implementation_owner import prepare_capture

        with tenant_session(engine, ctx.tenant_id) as session:
            return prepare_capture(session, ctx, product_id, data)
