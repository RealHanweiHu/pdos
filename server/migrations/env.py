from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db.url import psycopg_database_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# S0-2 replaces this with the canonical application metadata before migration 0001.
target_metadata = None


def database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        message = "DATABASE_URL must be set explicitly for Alembic commands"
        raise RuntimeError(message)
    return psycopg_database_url(url)


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
