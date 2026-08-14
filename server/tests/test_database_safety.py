import pytest

from app.db.test_safety import UnsafeTestDatabaseError, require_test_database_url
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
