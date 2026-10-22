"""Authenticated selected-scope reading and read-only inputs; writes use common Command."""

from uuid import UUID

from fastapi import FastAPI, Query, Request

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.service import Context

from .schemas import PAYLOADS, Kind, ObjectRef, PreparationReading, PreparationView


def _query(request, allowed):
    if any(key not in allowed for key in request.query_params) or any(
        len(request.query_params.getlist(key)) != 1 for key in request.query_params
    ):
        raise DomainError("INVALID_PAYLOAD", "请使用唯一明确的制造准备范围。", 422)


def register_routes(app: FastAPI, engine, auth_dependency):
    @app.get("/v1/categories/{category_id}/products/{product_id}/manufacturing-preparations")
    def preparation_history(
        request: Request,
        product_id: UUID,
        project_id: UUID,
        process_id: UUID | None = None,
        history_cursor: str | None = None,
        ctx: Context = auth_dependency,
    ):
        from .service import list_preparations

        _query(request, {"project_id", "process_id", "history_cursor"})
        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=True,
        ) as s:
            value = list_preparations(
                s,
                ctx,
                product_id,
                project_id=project_id,
                process_id=process_id,
                history_cursor=history_cursor,
            )
            return PreparationReading.model_validate(value).model_dump(mode="json")

    @app.get(
        "/v1/categories/{category_id}/products/{product_id}/manufacturing-preparations/{kind}/{object_id}"
    )
    def fixed_preparation(
        request: Request,
        product_id: UUID,
        kind: Kind,
        object_id: UUID,
        revision: int = Query(ge=1),
        ctx: Context = auth_dependency,
    ):
        from .service import get_preparation

        _query(request, {"revision"})
        ref = ObjectRef(kind=kind, id=object_id, revision=revision)
        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=True,
        ) as s:
            _, value = get_preparation(s, ctx, product_id, ref)
            return PreparationView.model_validate(value).model_dump(mode="json")

    @app.post(
        "/v1/categories/{category_id}/products/{product_id}/manufacturing-preparations/inputs"
    )
    def preparation_inputs(
        request: Request, product_id: UUID, data: Command, ctx: Context = auth_dependency
    ):
        from .service import inputs

        _query(request, set())
        if data.product_id != product_id:
            raise DomainError("FORBIDDEN_SCOPE", "命令不在这个型号范围。", 403)
        if data.operation not in PAYLOADS:
            raise DomainError("FORBIDDEN_SCOPE", "该入口只核对制造准备资料。", 403)
        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
        ) as s:
            return inputs(s, ctx, product_id, data)
