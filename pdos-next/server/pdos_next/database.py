import os
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


def engine_for(url: str):
    if not url.startswith("postgresql+psycopg://"):
        raise RuntimeError("Explicit PostgreSQL psycopg URL required; no environment fallback")
    return create_engine(url, pool_pre_ping=True, hide_parameters=True)


def configured_engines():
    return engine_for(os.environ["DATABASE_URL"]), engine_for(os.environ["AUTH_DATABASE_URL"])


@contextmanager
def tenant_session(engine, tenant_id: UUID):
    with Session(engine) as session, session.begin():
        session.execute(
            text("SELECT set_config('pdos.tenant_id', :tenant, true)"),
            {"tenant": str(tenant_id)},
        )
        yield session
