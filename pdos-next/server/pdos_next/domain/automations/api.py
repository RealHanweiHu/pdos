"""Authenticated configuration reads and explicit manual admission; no background impersonation."""

import asyncio
from uuid import UUID

from fastapi import Request

from pdos_next.agent_kernel.api import reference
from pdos_next.database import tenant_session
from pdos_next.domain.manufacturing_baseline.api import _query
from pdos_next.service import Context

from .schemas import Trigger


def register_routes(app, engine, auth_dependency, ports):
    def transaction(ctx, *, reading=False):
        return tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=reading,
        )

    @app.get("/v1/categories/{category_id}/automation-rules")
    def rules(request: Request, ctx: Context = auth_dependency):
        from .service import workspace

        _query(request, set())
        with transaction(ctx, reading=True) as s:
            return workspace(s, ctx)

    @app.get("/v1/categories/{category_id}/automation-rules/{rule_id}")
    def rule(request: Request, rule_id: UUID, ctx: Context = auth_dependency):
        from .service import detail

        _query(request, set())
        with transaction(ctx, reading=True) as s:
            return detail(s, ctx, rule_id)

    @app.post("/v1/categories/{category_id}/automation-rules/{rule_id}/trigger", status_code=202)
    async def trigger(
        request: Request, rule_id: UUID, data: Trigger, ctx: Context = auth_dependency
    ):
        from .runtime import admit

        _query(request, set())
        with transaction(ctx) as s:
            run, occurrence = admit(s, ctx, rule_id, data, ports)
            ref = reference(run, ctx)
            result = {
                "run_id": str(run.id),
                "rule_id": str(rule_id),
                "version_id": str(occurrence.published_version_id),
                "queued": True,
            }
        try:
            await asyncio.wait_for(ports.start_workflow(ref), timeout=5)
        except Exception:
            # The committed Run is recovered by the existing pending dispatcher, same ID.
            pass
        return result
