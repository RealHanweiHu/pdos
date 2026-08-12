"""Apply or revert the Agent database boundary on the isolated test database only."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, cast

from sqlalchemy import create_engine

from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SECURITY_DIRECTORY = REPOSITORY_ROOT / "infra" / "postgres" / "security"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--revert", action="store_true")
    arguments = parser.parse_args()
    database_url = configured_test_database_url()
    filenames = (
        ("agent-runtime-revert.sql",)
        if arguments.revert
        else ("agent-runtime-roles.sql", "agent-runtime.sql")
    )
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            driver_connection = cast(Any, connection.connection.driver_connection)
            with driver_connection.cursor() as cursor:
                for filename in filenames:
                    cursor.execute((SECURITY_DIRECTORY / filename).read_text())
                if arguments.revert:
                    cursor.execute("ALTER ROLE pdos_worker PASSWORD NULL")
                    cursor.execute("ALTER ROLE pdos_agent PASSWORD NULL")
                else:
                    cursor.execute("ALTER ROLE pdos_worker PASSWORD 'pdos_worker_test_only'")
                    cursor.execute("ALTER ROLE pdos_agent PASSWORD 'pdos_agent_test_only'")
    finally:
        engine.dispose()
    action = "reverted" if arguments.revert else "applied"
    print(f"Agent runtime security boundary {action} on isolated pdos_test")


if __name__ == "__main__":
    main()
