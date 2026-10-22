import os
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import create_engine, func, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session


def engine_for(url: str):
    if not url.startswith("postgresql+psycopg://"):
        raise RuntimeError("Explicit PostgreSQL psycopg URL required; no environment fallback")
    return create_engine(url, pool_pre_ping=True, hide_parameters=True)


def configured_engines():
    return engine_for(os.environ["DATABASE_URL"]), engine_for(os.environ["AUTH_DATABASE_URL"])


@contextmanager
def tenant_session(
    engine,
    tenant_id: UUID,
    *,
    actor_id=None,
    requester_id=None,
    category_id=None,
    read_snapshot=False,
):
    with Session(engine) as session, session.begin():
        if read_snapshot:
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            session.execute(text("SET TRANSACTION READ ONLY"))
        session.info["read_snapshot"] = read_snapshot
        session.execute(
            text(
                "SELECT set_config('pdos.tenant_id', :tenant, true), "
                "set_config('pdos.actor_id', :actor, true), "
                "set_config('pdos.requester_id', :requester, true), "
                "set_config('pdos.category_id', :category, true)"
            ),
            {
                "tenant": str(tenant_id),
                "actor": str(actor_id) if actor_id else "",
                "requester": str(requester_id or actor_id) if (requester_id or actor_id) else "",
                "category": str(category_id) if category_id else "",
            },
        )
        session.info["scope"] = (tenant_id, actor_id, requester_id or actor_id, category_id)
        yield session


def require_context(session, ctx):
    """A domain caller cannot borrow another actor's transaction or read proof."""
    from pdos_next.errors import DomainError

    scope = getattr(session, "info", {}).get("scope")
    if scope and (
        scope[:3] != (ctx.tenant_id, ctx.actor_id, ctx.requester_id)
        or (scope[3] is not None and scope[3] != ctx.category_id)
    ):
        raise DomainError("FORBIDDEN_SCOPE", "请求身份与事务范围不符。", 403)


def category_for_product(product_id):
    """Persisted model category resolved under the current RLS scope."""
    return func.category_for_product(product_id)


def category_transaction(engine, ctx, action):
    """Retry only PostgreSQL transaction aborts, each with a fresh scope and proof."""
    for attempt in range(3):
        try:
            with tenant_session(
                engine,
                ctx.tenant_id,
                actor_id=ctx.actor_id,
                requester_id=ctx.requester_id,
                category_id=ctx.category_id,
            ) as s:
                return action(s)
        except DBAPIError as error:
            if getattr(error.orig, "sqlstate", None) not in {"40001", "40P01"} or attempt == 2:
                raise
