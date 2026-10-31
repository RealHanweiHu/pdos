"""Authenticated self-service preferences; no AI tool or business command route."""

from typing import Annotated

from fastapi import Query
from sqlalchemy.exc import OperationalError

from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.personal_preference_schemas import NavigationOptions, PreferenceSave
from pdos_next.personal_preferences import options, read, save
from pdos_next.service import Context


def register_routes(app, engine, auth_dependency):
    def perform(ctx, action, *, writing=False):
        try:
            with tenant_session(
                engine, ctx.tenant_id, actor_id=ctx.actor_id,
                requester_id=ctx.requester_id, read_snapshot=not writing,
            ) as session:
                return action(session)
        except OperationalError:
            raise DomainError("SOURCE_UNAVAILABLE", "个人偏好暂不可用，请重新读取。", 503) from None

    @app.get("/v1/personal/preferences")
    def preferences(ctx: Context = auth_dependency):
        return perform(ctx, lambda session: read(session, ctx))

    @app.post("/v1/personal/preferences")
    def preference_save(data: PreferenceSave, ctx: Context = auth_dependency):
        return perform(ctx, lambda session: save(session, ctx, data), writing=True)

    @app.get("/v1/personal/preferences/options")
    def preference_options(data: Annotated[NavigationOptions, Query()],
                           ctx: Context = auth_dependency):
        return perform(ctx, lambda session: options(session, ctx, data))
