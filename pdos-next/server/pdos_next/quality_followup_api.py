"""Single-Issue follow-up reads and inputs; common commands own every write."""

from uuid import UUID

from fastapi import FastAPI, Query, Request
from fastapi.encoders import jsonable_encoder

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.service import Context


def register_routes(app: FastAPI, engine, auth_dependency):
    @app.get("/v1/categories/{category_id}/products/{product_id}/quality-followup")
    def followup_read(
        product_id: UUID,
        request: Request,
        issue_id: UUID,
        revision: int | None = Query(default=None, ge=1, le=2_147_483_647),
        ctx: Context = auth_dependency,
    ):
        from pdos_next.quality_followup_views import list_quality_followup

        if any(
            name not in {"issue_id", "revision"} or len(request.query_params.getlist(name)) != 1
            for name in request.query_params
        ):
            raise DomainError("INVALID_REQUEST", "请选择一个明确问题及可选历史版本。", 400)
        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=True,
        ) as s:
            return jsonable_encoder(
                list_quality_followup(s, ctx, product_id, issue_id=issue_id, revision=revision)
            )

    @app.post("/v1/categories/{category_id}/products/{product_id}/quality-followup/inputs")
    def followup_inputs(product_id: UUID, data: Command, ctx: Context = auth_dependency):
        from pdos_next.domain.capa_effectiveness import service as candidates
        from pdos_next.domain.capa_verification import commands as links
        from pdos_next.domain.quality_followup import service as followup

        if data.product_id != product_id:
            raise DomainError("FORBIDDEN_SCOPE", "命令不在当前型号范围。", 403)
        if data.operation in {followup.ROOT_CAUSE, followup.COMPLETE}:
            handler = followup
        elif data.operation == links.OPERATION:
            handler = links
        elif data.operation == candidates.OPERATION:
            handler = candidates
        else:
            raise DomainError(
                "INVALID_REQUEST", "此入口只接受根因、实际完成、整改回链或验证候选。", 400
            )
        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=data.operation == candidates.OPERATION,
        ) as s:
            return jsonable_encoder(handler.inputs(s, ctx, product_id, data))
