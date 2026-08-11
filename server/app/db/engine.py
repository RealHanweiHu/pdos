"""Application database engine construction."""

from functools import lru_cache

from sqlalchemy import Engine, create_engine

from app.db.url import psycopg_database_url
from app.settings import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        psycopg_database_url(settings.database_url),
        pool_pre_ping=True,
    )
