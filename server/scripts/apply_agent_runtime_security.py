"""Re-apply and verify the production Agent database boundary after migrations."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.deployment.preflight import (
    UnsafeProductionConfigurationError,
    validate_production_database_url,
)


class UnsafeSecurityApplyError(RuntimeError):
    """Raised before or after an unsafe production security application."""


def _security_sql_path() -> Path:
    candidates = (
        Path(__file__).resolve().parents[2]
        / "infra"
        / "postgres"
        / "security"
        / "agent-runtime.sql",
        Path(__file__).resolve().parents[1]
        / "infra"
        / "postgres"
        / "security"
        / "agent-runtime.sql",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise UnsafeSecurityApplyError("Agent runtime security SQL is missing from the image")


def _production_connection_info() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise UnsafeSecurityApplyError("required environment variable is missing: DATABASE_URL")
    try:
        url = make_url(database_url)
    except ArgumentError as error:
        raise UnsafeSecurityApplyError("DATABASE_URL is not a valid database URL") from error
    username = url.username
    database = url.database
    if username != "pdos_app":
        raise UnsafeSecurityApplyError("Agent security must be applied by pdos_app")
    if database != "pdos":
        raise UnsafeSecurityApplyError("Agent security may only target the pdos database")
    if not url.drivername.startswith("postgresql") or not url.password:
        raise UnsafeSecurityApplyError("DATABASE_URL must be an authenticated PostgreSQL URL")
    try:
        validate_production_database_url(database_url, username="pdos_app")
    except UnsafeProductionConfigurationError as error:
        raise UnsafeSecurityApplyError(str(error)) from error
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def apply_agent_runtime_security() -> None:
    connection_info = _production_connection_info()
    security_sql = _security_sql_path().read_text()
    with (
        psycopg.connect(connection_info, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(security_sql, prepare=False)
        cursor.execute(
            """
            SELECT
                has_table_privilege('pdos_worker', 'cehub_event.events', 'SELECT'),
                has_table_privilege(
                    'pdos_worker', 'cehub_ai.agent_runs', 'INSERT'
                ),
                has_table_privilege(
                    'pdos_worker', 'cehub_project.projects', 'UPDATE'
                ),
                has_table_privilege(
                    'pdos_agent', 'cehub_project.projects', 'INSERT'
                ),
                has_table_privilege(
                    'pdos_agent', 'cehub_ai.model_invocations', 'INSERT'
                ),
                has_table_privilege(
                    'pdos_agent', 'cehub_ai.findings', 'INSERT'
                ),
                has_table_privilege(
                    'pdos_agent', 'cehub_event.integration_outbox', 'INSERT'
                ),
                has_table_privilege(
                    'pdos_agent', 'cehub_core.dingtalk_user_bindings', 'SELECT'
                )
            """
        )
        privileges = cursor.fetchone()
    expected = (True, True, False, False, True, False, False, False)
    if privileges != expected:
        raise UnsafeSecurityApplyError(
            "Agent runtime privilege verification failed after security application"
        )


def main() -> int:
    try:
        apply_agent_runtime_security()
    except (OSError, psycopg.Error, UnsafeSecurityApplyError) as error:
        raise SystemExit(f"Agent runtime security apply refused: {error}") from error
    print("Production Agent runtime security boundary applied and verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
