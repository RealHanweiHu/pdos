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

    @app.get("/v1/categories/{category_id}/products/{product_id}/change-execution")
    def change_execution(
        request: Request,
        product_id: UUID,
        project_id: UUID | None = None,
        issue_id: UUID | None = None,
        field_feedback_id: UUID | None = None,
        change_id: UUID | None = None,
        history_cursor: str | None = None,
        capture_cursor: str | None = None,
        ctx: Context = auth_dependency,
    ):
        from .service import list_changes

        _query(
            request,
            {
                "project_id",
                "issue_id",
                "field_feedback_id",
                "change_id",
                "history_cursor",
                "capture_cursor",
            },
        )
        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=True,
        ) as session:
            return list_changes(
                session,
                ctx,
                product_id,
                project_id=project_id,
                issue_id=issue_id,
                field_feedback_id=field_feedback_id,
                change_id=change_id,
                history_cursor=history_cursor,
                capture_cursor=capture_cursor,
            )

    @app.get("/v1/categories/{category_id}/products/{product_id}/change-execution/order-context")
    def change_order_context(
        request: Request, product_id: UUID, change_id: UUID, ctx: Context = auth_dependency
    ):
        from pdos_next.change_preparation_view import order_context

        _query(request, {"change_id"})
        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=True,
        ) as session:
            return order_context(session, ctx, product_id, change_id)

    from pdos_next.change_preparation_view import SelectionMaterialInput

    @app.post(
        "/v1/categories/{category_id}/products/{product_id}/change-execution/selection-material"
    )
    def change_selection_material(
        request: Request,
        product_id: UUID,
        data: SelectionMaterialInput,
        ctx: Context = auth_dependency,
    ):
        from pdos_next.change_preparation_view import selection_material

        _query(request, set())
        # Candidate preparation performs no business writes or T2 consumption.
        # Existing selection.inputs uses FOR UPDATE, requiring an ordinary UOW.
        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
        ) as session:
            return selection_material(session, ctx, product_id, data)

    @app.post("/v1/categories/{category_id}/products/{product_id}/change-execution/inputs")
    def change_execution_inputs(
        request: Request, product_id: UUID, data: Command, ctx: Context = auth_dependency
    ):
        from pdos_next.command_handlers import handler

        from .service import inputs

        _query(request, set())
        if data.product_id != product_id:
            raise DomainError("FORBIDDEN_SCOPE", "命令不在当前型号范围。", 403)
        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
        ) as session:
            module = handler(data.operation)
            if data.operation in {
                "change.order.prepare",
                "change.order.approve",
                "change.implementation.record",
                "change.effectivity.record",
                "change.verification.record",
                "change.close",
                "change.selection.decide",
            }:
                return module.inputs(session, ctx, product_id, data)
            return inputs(session, ctx, product_id, data)

    @app.post("/v1/categories/{category_id}/products/{product_id}/change-execution/captures")
    def change_execution_capture(
        product_id: UUID, data: GraphCaptureInput, ctx: Context = auth_dependency
    ):
        from .service import prepare_capture

        # The recoverable graph is committed in its own tenant UOW. A later
        # impact command owns its sole Receipt/Audit/Outbox and can roll back
        # without deleting this prepared capture.
        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
        ) as session:
            return prepare_capture(session, ctx, product_id, data)

    from pdos_next.change_order_store import CaptureInput

    @app.post(
        "/v1/categories/{category_id}/products/{product_id}/change-execution/implementation-captures"
    )
    def implementation_capture(
        product_id: UUID, data: CaptureInput, ctx: Context = auth_dependency
    ):
        from pdos_next.change_implementation_owner import capture_view, prepare_capture

        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
        ) as session:
            return capture_view(prepare_capture(session, ctx, product_id, data))


    from pdos_next.change_completion_schemas import CompletionMaterial

    @app.get("/v1/categories/{category_id}/products/{product_id}/change-execution/completion-context")
    def completion_context(request: Request, product_id: UUID, change_id: UUID,
                           ctx: Context = auth_dependency):
        from pdos_next.change_completion_view import completion_context as read

        _query(request, {"change_id"})
        with tenant_session(engine, ctx.tenant_id, actor_id=ctx.actor_id,
                            requester_id=ctx.requester_id, category_id=ctx.category_id,
                            read_snapshot=True) as session:
            return read(session, ctx, product_id, change_id)

    @app.post("/v1/categories/{category_id}/products/{product_id}/change-execution/completion-material")
    def completion_material(request: Request, product_id: UUID, data: CompletionMaterial,
                            ctx: Context = auth_dependency):
        from pdos_next.change_completion_view import completion_material as prepare

        _query(request, set())
        with tenant_session(engine, ctx.tenant_id, actor_id=ctx.actor_id,
                            requester_id=ctx.requester_id, category_id=ctx.category_id) as session:
            return prepare(session, ctx, product_id, data)
