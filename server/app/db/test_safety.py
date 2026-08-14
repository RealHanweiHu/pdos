from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class UnsafeTestDatabaseError(ValueError):
    """Raised before a test command can connect to a non-test database."""


def require_test_database_url(value: str) -> str:
    try:
        database_name = make_url(value).database
    except ArgumentError as error:
        message = "TEST_DATABASE_URL must be valid and target the pdos_test database"
        raise UnsafeTestDatabaseError(message) from error

    if database_name != "pdos_test":
        message = "Refusing test execution: TEST_DATABASE_URL must target pdos_test"
        raise UnsafeTestDatabaseError(message)

    return value


def configured_test_database_url(env_file: Path | None = None) -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if value is None:
        values = dotenv_values(env_file or REPOSITORY_ROOT / ".env")
        candidate = values.get("TEST_DATABASE_URL")
        value = candidate if isinstance(candidate, str) else None

    if not value:
        message = "TEST_DATABASE_URL must be set and target the pdos_test database"
        raise UnsafeTestDatabaseError(message)

    return require_test_database_url(value)


def main() -> None:
    configured_test_database_url()
    print("Verified isolated test database: pdos_test")


if __name__ == "__main__":
    main()
