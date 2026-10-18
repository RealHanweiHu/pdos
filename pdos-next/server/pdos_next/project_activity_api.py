"""Authenticated read-only project activity; there is no activity write command."""

from uuid import UUID

from fastapi import Query, Request

from pdos_next.database import tenant_session
from pdos_next.domain.manufacturing_baseline.api import _query
from pdos_next.project_activity import project_activity
from pdos_next.service import Context


def register_routes(app, engine, auth_dependency):
    @app.get("/v1/categories/{category_id}/products/{product_id}/project-work/activity")
    def read_project_activity(
        request: Request,
        product_id: UUID,
        project_id: UUID,
        page_size: int = Query(default=20, ge=1, le=100),
        cursor: str | None = Query(default=None, min_length=1, max_length=2048),
        ctx: Context = auth_dependency,
    ):
        _query(request, {"project_id", "page_size", "cursor"})
        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=True,
        ) as session:
            return project_activity(
                session, ctx, product_id, project_id, page_size=page_size, cursor=cursor
            )
