from typing import Annotated
from uuid import UUID

from fastapi import Query
from pydantic import Field

from pdos_next.database import category_transaction, tenant_session
from pdos_next.schema_base import StrictModel
from pdos_next.service import Context

from . import service


class Page(StrictModel):
    cursor: UUID | None = None
    page_size: int = Field(default=50, ge=1, le=100)


class MessagePage(StrictModel):
    before: int | None = Field(default=None, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


def register_routes(app, engine, auth_dependency):
    def read(ctx):
        return tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            read_snapshot=True,
        )

    @app.get("/v1/personal/inbox/conversations")
    def conversations(page: Annotated[Page, Query()], ctx: Context = auth_dependency):
        with read(ctx) as s:
            return service.list_conversations(s, ctx, page.cursor, page.page_size)

    @app.post("/v1/personal/inbox/conversations", status_code=201)
    def create(data: service.NewConversation, ctx: Context = auth_dependency):
        return category_transaction(engine, ctx, lambda s: service.create(s, ctx, data))

    @app.get("/v1/personal/inbox/conversations/{identity}/messages")
    def messages(
        identity: UUID, page: Annotated[MessagePage, Query()], ctx: Context = auth_dependency
    ):
        with read(ctx) as s:
            return service.messages(s, ctx, identity, page.before, page.page_size)

    @app.post("/v1/personal/inbox/conversations/{identity}/messages", status_code=201)
    def send(identity: UUID, data: service.NewMessage, ctx: Context = auth_dependency):
        return category_transaction(engine, ctx, lambda s: service.send(s, ctx, identity, data))

    @app.get("/v1/personal/inbox/states")
    def states(ctx: Context = auth_dependency):
        with read(ctx) as s:
            return service.states(s, ctx)

    @app.post("/v1/personal/inbox/states")
    def save_state(data: service.SaveState, ctx: Context = auth_dependency):
        return category_transaction(engine, ctx, lambda s: service.save_state(s, ctx, data))
