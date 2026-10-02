from __future__ import annotations

import os
from contextlib import suppress
from ipaddress import ip_address

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class UnsafeTestDatabaseError(ValueError):
    """Raised before a test command can connect to a non-test database."""


def require_test_database_url(value: str) -> str:
    try:
        url = make_url(value)
        database_name, host, port = url.database, url.host, url.port
    except (ArgumentError, ValueError, TypeError):
        # Parser errors can include the supplied URL. Never echo credentials.
        message = "TEST_DATABASE_URL must be valid and target the pdos_test database"
        raise UnsafeTestDatabaseError(message) from None

    if database_name != "pdos_test":
        message = "Refusing test execution: TEST_DATABASE_URL must target pdos_test"
        raise UnsafeTestDatabaseError(message)

    # libpq query overrides could route an apparently safe URL to another endpoint.
    if {key.lower() for key in url.query} & {"host", "hostaddr", "port", "dbname", "service"}:
        raise UnsafeTestDatabaseError(
            "Refusing test execution: specify the test endpoint in the URL, not query overrides"
        )

    normalized_host = (host or "").lower().rstrip(".")
    local = normalized_host == "localhost"
    with suppress(ValueError):
        local = local or ip_address(normalized_host).is_loopback
    if local and port == 57432:
        raise UnsafeTestDatabaseError(
            "Refusing test execution: local port 57432 is a protected integration database"
        )

    return value


def configured_test_database_url() -> str:
    """Require an explicit process environment value; never fall back to .env."""
    value = os.getenv("TEST_DATABASE_URL")
    if not value or not value.strip():
        message = (
            "TEST_DATABASE_URL must be explicitly set in the process environment and target "
            "an isolated pdos_test database; .env and PDOS_TEST_DATABASE_URL are not used"
        )
        raise UnsafeTestDatabaseError(message)

    return require_test_database_url(value)


def main() -> None:
    configured_test_database_url()
    print("Verified isolated test database: pdos_test")


if __name__ == "__main__":
    main()
