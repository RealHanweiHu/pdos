"""Selected-scope publication reads and inputs; decisions use the common command route."""

from uuid import UUID

from fastapi import FastAPI, Query, Request

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.service import Context

from .api import _query
from .publication_schemas import OPERATION


def register_routes(app: FastAPI, engine, auth_dependency):
    @app.get("/v1/categories/{category_id}/products/{product_id}/manufacturing-publications")
    def publication_history(
        request: Request,
        product_id: UUID,
        project_id: UUID,
        history_cursor: str | None = None,
        ctx: Context = auth_dependency,
    ):
        from .publication_service import list_publications

        _query(request, {"project_id", "history_cursor"})
        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=True,
        ) as s:
            return list_publications(
                s, ctx, product_id, project_id=project_id, history_cursor=history_cursor
            )

    @app.get(
        "/v1/categories/{category_id}/products/{product_id}/manufacturing-publications/{publication_id}"
    )
    def fixed_publication(
        request: Request,
        product_id: UUID,
        publication_id: UUID,
        revision: int = Query(ge=1),
        ctx: Context = auth_dependency,
    ):
        from .publication_service import get_publication

        _query(request, {"revision"})
        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=True,
        ) as s:
            _, view = get_publication(s, ctx, product_id, publication_id, revision=revision)
            return view

    @app.post(
        "/v1/categories/{category_id}/products/{product_id}/manufacturing-publications/inputs"
    )
    def publication_inputs(
        request: Request, product_id: UUID, data: Command, ctx: Context = auth_dependency
    ):
        from .publication_service import inputs

        _query(request, set())
        if data.product_id != product_id or data.operation != OPERATION:
            raise DomainError("FORBIDDEN_SCOPE", "请选择本型号的制造基线发布。", 403)
        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
        ) as s:
            return inputs(s, ctx, product_id, data)
