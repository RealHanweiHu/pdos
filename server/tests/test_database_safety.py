import socket
from pathlib import Path

import dotenv
import psycopg
import pytest
from sqlalchemy.engine import Engine

from app.db.test_safety import (
    UnsafeTestDatabaseError,
    configured_test_database_url,
    require_test_database_url,
)
from app.db.url import psycopg_database_url


def test_test_database_guard_accepts_only_pdos_test() -> None:
    url = "postgresql://pdos:pdos@localhost:55432/pdos_test"

    assert require_test_database_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://pdos:pdos@localhost:55432/pdos",
        "postgresql://pdos:pdos@localhost:55432/postgres",
        "postgresql://pdos:pdos@localhost:55432/",
    ],
)
def test_test_database_guard_rejects_every_other_database(url: str) -> None:
    with pytest.raises(UnsafeTestDatabaseError, match="pdos_test"):
        require_test_database_url(url)


def test_plain_postgresql_url_uses_the_installed_psycopg_driver() -> None:
    value = "postgresql://pdos:pdos@localhost:55432/pdos_test"

    assert psycopg_database_url(value) == (
        "postgresql+psycopg://pdos:pdos@localhost:55432/pdos_test"
    )


def test_explicit_database_driver_is_preserved() -> None:
    value = "postgresql+psycopg://pdos:pdos@localhost:55432/pdos_test"

    assert psycopg_database_url(value) == value


@pytest.fixture(autouse=True)
def forbid_database_and_network_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Database and network access are forbidden in safety unit tests")

    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(psycopg, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_explicit_test_environment_is_required_even_with_dotenv_and_typo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str | None
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "TEST_DATABASE_URL=postgresql://fixture:fixture@localhost:57550/pdos_test\n"
    )
    monkeypatch.setenv(
        "PDOS_TEST_DATABASE_URL", "postgresql://fixture:fixture@localhost:57550/pdos_test"
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql://fixture:fixture@localhost:57550/pdos_test")
    if value is None:
        monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("TEST_DATABASE_URL", value)

    def no_dotenv(*args: object, **kwargs: object) -> None:
        raise AssertionError("The test guard must not load a dotenv file")

    monkeypatch.setattr(dotenv, "dotenv_values", no_dotenv)
    with pytest.raises(UnsafeTestDatabaseError, match="explicitly set"):
        configured_test_database_url()


@pytest.mark.parametrize(
    "host", ["localhost", "LOCALHOST", "localhost.", "127.0.0.1", "[::1]", "[0:0:0:0:0:0:0:1]"]
)
def test_protected_integration_endpoint_rejected_even_when_explicit(
    monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    value = f"postgresql+psycopg://fixture:fixture@{host}:57432/pdos_test"
    monkeypatch.setenv("TEST_DATABASE_URL", value)
    with pytest.raises(UnsafeTestDatabaseError, match="protected integration"):
        configured_test_database_url()
    with pytest.raises(UnsafeTestDatabaseError, match="protected integration"):
        require_test_database_url(value)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_explicit_isolated_endpoint_is_accepted_without_connecting(
    monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    value = f"postgresql+psycopg://fixture:fixture@{host}:57550/pdos_test"
    monkeypatch.setenv("TEST_DATABASE_URL", value)
    assert configured_test_database_url() == value


@pytest.mark.parametrize(
    "query",
    ["host=localhost&port=57432", "hostaddr=127.0.0.1", "service=integration", "dbname=other"],
)
def test_query_routing_cannot_bypass_endpoint_guard(query: str) -> None:
    with pytest.raises(UnsafeTestDatabaseError, match="query overrides"):
        require_test_database_url(f"postgresql://fixture:fixture@localhost:57550/pdos_test?{query}")


@pytest.mark.parametrize(
    "value",
    ["not-a-url", "postgresql://fixture:sensitive-placeholder@localhost:notaport/pdos_test"],
)
def test_malformed_urls_fail_without_exposing_url_or_credentials(value: str) -> None:
    with pytest.raises(UnsafeTestDatabaseError, match="must be valid") as caught:
        require_test_database_url(value)
    assert "sensitive-placeholder" not in str(caught.value)
    assert value not in str(caught.value)
    assert caught.value.__suppress_context__
