"""Personal notifications, settings, live delivery (SSE) and its 30-second polling fallback.

D74 (P77): the browser keeps one SSE stream open; when it drops, the page polls
`/changes` every 30 seconds and, once a stream is back, fetches what changed
since its last cursor. Both only say "something changed"; content is always
read through the normal, access-checked endpoints.
"""

import asyncio
import json
from typing import Annotated
from uuid import UUID

from fastapi import Header, Query, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from pdos_next.core.database import category_transaction, tenant_session
from pdos_next.core.schema_base import StrictModel
from pdos_next.core.service import Context
from pdos_next.domain.manufacturing.baseline.api import _query
from pdos_next.errors import DomainError

from . import service

ROOT = "/v1/personal/notifications"
# Server-side check interval, keepalive and stream lifetime (the browser reconnects).
STREAM = {"interval": 2.0, "keepalive": 15.0, "lifetime": 120.0}


class Changes(StrictModel):
    since: str = ""
    threads: str = ""


def _threads(value):
    ids = []
    for part in [item for item in (value or "").split(",") if item][:20]:
        try:
            ids.append(str(UUID(part)))
        except ValueError as error:
            raise DomainError("INVALID_PAYLOAD", "讨论标识无效。", 422) from error
    return ids


def _cursor_text(value):
    if len(value) > 64 or any(char not in "0123456789." for char in value):
        raise DomainError("INVALID_PAYLOAD", "游标无效。", 422)
    return value


def register_routes(app, engine, auth_dependency, auth_engine=None):
    from pdos_next.domain.projects.team import handover

    def reading(ctx):
        return tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            read_snapshot=True,
        )

    def lanes(s, ctx):
        # A removed member still hears about their own open items (P56-1).
        from sqlalchemy import text

        for project in s.execute(
            text("SELECT project_id FROM my_handover_projects(:t)"), {"t": ctx.tenant_id}
        ).scalars():
            handover.open_lane(s, ctx, project, None, None)

    @app.get(ROOT)
    def notifications(
        request: Request, query: Annotated[service.Query, Query()], ctx: Context = auth_dependency
    ):
        _query(request, {"view", "category", "unread", "before", "page_size"})
        with reading(ctx) as s:
            lanes(s, ctx)
            return service.listing(s, ctx, query)

    @app.post(ROOT + "/state")
    def notification_state(
        request: Request, data: service.StateChange, ctx: Context = auth_dependency
    ):
        _query(request, set())
        return category_transaction(engine, ctx, lambda s: service.change_state(s, ctx, data))

    @app.get(ROOT + "/changes")
    def notification_changes(
        request: Request, query: Annotated[Changes, Query()], ctx: Context = auth_dependency
    ):
        _query(request, {"since", "threads"})
        with reading(ctx) as s:
            lanes(s, ctx)
            return service.changes(s, ctx, _cursor_text(query.since), _threads(query.threads))

    @app.get(ROOT + "/stream")
    async def notification_stream(
        request: Request,
        ctx: Context = auth_dependency,
        authorization: str | None = Header(default=None),
        last_event_id: str | None = Header(default=None),
    ):
        _query(request, {"threads", "since"})
        threads = _threads(request.query_params.get("threads"))
        since = _cursor_text(last_event_id or request.query_params.get("since") or "")
        token = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""

        def poll():
            if auth_engine is not None:
                from pdos_next.core.accounts.sign_in import peek

                if not peek(auth_engine, token):
                    raise DomainError("UNAUTHENTICATED", "会话已失效，请重新登录。", 401)
            with reading(ctx) as s:
                service._personal(s, ctx)
                lanes(s, ctx)
                return service.cursor(s, ctx, threads)

        first = await run_in_threadpool(poll)

        async def events():
            state = first
            yield "retry: 5000\n\n"
            yield _event("ready", state["cursor"], state)
            if since and since != state["cursor"]:
                # Reconnected after a gap: the page fetches what it missed (D74).
                yield _event("changed", state["cursor"], state)
            loop = asyncio.get_running_loop()
            started = last_beat = loop.time()
            while loop.time() - started < STREAM["lifetime"]:
                await asyncio.sleep(STREAM["interval"])
                if await request.is_disconnected():
                    return
                try:
                    current = await run_in_threadpool(poll)
                except DomainError as error:
                    yield _event("closed", "", {"code": error.code})
                    return
                if current != state:
                    state = current
                    yield _event("changed", state["cursor"], state)
                    last_beat = loop.time()
                elif loop.time() - last_beat >= STREAM["keepalive"]:
                    yield ": keepalive\n\n"
                    last_beat = loop.time()
            yield _event("reconnect", state["cursor"], state)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.get("/v1/personal/notification-preferences/{project_id}")
    def notification_preferences(
        request: Request, project_id: UUID, ctx: Context = auth_dependency
    ):
        _query(request, set())
        with reading(ctx) as s:
            return service.preferences(s, ctx, project_id)

    @app.post("/v1/personal/notification-preferences")
    def save_notification_preference(
        request: Request, data: service.Preference, ctx: Context = auth_dependency
    ):
        _query(request, set())
        return category_transaction(engine, ctx, lambda s: service.save_preference(s, ctx, data))

    @app.get("/v1/personal/handover")
    def my_handover(request: Request, ctx: Context = auth_dependency):
        _query(request, set())
        with reading(ctx) as s:
            service._personal(s, ctx)
            return handover.mine(s, ctx)


def _event(name, identity, data):
    lines = [f"event: {name}"]
    if identity:
        lines.append(f"id: {identity}")
    lines.append("data: " + json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(lines) + "\n\n"
