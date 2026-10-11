"""Quality routes bound to the host authentication and tenant transaction."""

from uuid import UUID

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.service import Context

from . import service
from .schemas import QualityReading


def register_routes(app: FastAPI, engine, auth_dependency):
    """Register reads/inputs only; common commands retain all write ownership."""

    @app.get(
        "/v1/categories/{category_id}/products/{product_id}/quality-execution",
        response_model=QualityReading,
    )
    def quality_execution(
        product_id: UUID,
        issue_id: UUID | None = None,
        run_id: UUID | None = None,
        build_id: UUID | None = None,
        ctx: Context = auth_dependency,
    ):
        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=True,
        ) as s:
            # The service already returns QualityReading.model_dump(mode="json").
            # FastAPI retains its response-model validation and serialization.
            return service.list_quality(
                s,
                ctx,
                product_id,
                issue_id=issue_id,
                run_id=run_id,
                build_id=build_id,
            )

    @app.post("/v1/categories/{category_id}/products/{product_id}/quality-execution/inputs")
    def quality_execution_inputs(product_id: UUID, data: Command, ctx: Context = auth_dependency):
        if data.product_id != product_id:
            raise DomainError("FORBIDDEN_SCOPE", "命令不在当前型号范围。", 403)
        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=True,
        ) as s:
            return jsonable_encoder(service.inputs(s, ctx, product_id, data))
