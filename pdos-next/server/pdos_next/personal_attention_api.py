"""Authenticated personal attention GET; no command or materialization side effects."""

from typing import Annotated, Literal

from fastapi import Query
from pydantic import Field
from sqlalchemy.exc import OperationalError

from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.personal_attention import read
from pdos_next.schema_base import StrictModel
from pdos_next.service import Context


class AttentionPage(StrictModel):
    queue: Literal["decide", "receive", "verify", "external"]
    cursor: str | None = Field(default=None, min_length=1, max_length=2048)
    page_size: int = Field(default=20, ge=1, le=100)


def register_routes(app, engine, auth_dependency):
    @app.get("/v1/personal/attention")
    def attention(page: Annotated[AttentionPage, Query()], ctx: Context = auth_dependency):
        try:
            with tenant_session(
                engine,
                ctx.tenant_id,
                actor_id=ctx.actor_id,
                requester_id=ctx.requester_id,
                read_snapshot=True,
            ) as s:
                return read(s, ctx, page.queue, page.cursor, page.page_size)
        except OperationalError:
            raise DomainError(
                "SOURCE_UNAVAILABLE", "暂未读取到当前注意项，请重新读取。", 503
            ) from None
