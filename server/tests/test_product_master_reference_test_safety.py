"""Pure URL guard checks; literals are never allocation or connection evidence."""

import pytest

from app.db.test_safety import UnsafeTestDatabaseError
from tests.product_master_reference_fixtures import checked_master_reference_test_database_url


@pytest.mark.parametrize("host", ["localhost.", "127.0.0.1", "[::1]"])
@pytest.mark.parametrize("port", [57432, 57433, 57434, 57439, 57440])
def test_retained_local_targets_are_rejected_before_shared_database_fixture(
    monkeypatch: pytest.MonkeyPatch, host: str, port: int
) -> None:
    monkeypatch.setenv("TEST_DATABASE_URL", f"postgresql://test:test@{host}:{port}/pdos_test")
    with pytest.raises(UnsafeTestDatabaseError):
        checked_master_reference_test_database_url()


def test_explicit_process_url_is_required_without_legacy_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv("PDOS_TEST_DATABASE_URL", "postgresql://test:test@localhost:65499/pdos_test")
    with pytest.raises(UnsafeTestDatabaseError, match="explicitly set"):
        checked_master_reference_test_database_url()


def test_other_database_name_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql://test:test@localhost:65499/pdos")
    with pytest.raises(UnsafeTestDatabaseError, match="must target pdos_test"):
        checked_master_reference_test_database_url()


def test_nonretained_url_shape_does_not_require_a_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = "postgresql://test:test@127.0.0.1:65499/pdos_test"
    monkeypatch.setenv("TEST_DATABASE_URL", value)
    assert checked_master_reference_test_database_url() == value
