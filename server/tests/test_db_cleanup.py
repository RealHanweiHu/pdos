"""Cleanup safety and restoration checks without opening a database connection."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Connection, create_engine
from sqlalchemy.engine import make_url

from app.db.test_safety import UnsafeTestDatabaseError
from tests.db_cleanup import clear_test_tenants

TEST_URL = "postgresql+psycopg://test:test@localhost:57550/pdos_test"


def relation(oid: int, name: str, **changes: object) -> dict[str, object]:
    return {
        "oid": oid,
        "schema_name": "cehub_core",
        "table_name": name,
        "relkind": "r",
        "relrowsecurity": False,
        "has_inheritance": False,
        "incompatible_trigger": False,
        "has_rule": False,
        "can_clear": True,
        **changes,
    }


class CleanupHarness:
    def __init__(self) -> None:
        self.connection = MagicMock(spec=Connection)
        self.connection.engine = MagicMock()
        self.connection.engine.url = make_url(TEST_URL)
        # Engine construction supplies the real quoting rules without connecting.
        self.connection.dialect = create_engine(TEST_URL).dialect
        self.connection.in_transaction.return_value = True
        self.connection.connection.driver_connection.autocommit = False
        self.savepoint = self.connection.begin_nested.return_value
        self.state: dict[str, object] = {
            "database_name": "pdos_test",
            "replication_role": "origin",
            "isolation_level": "read committed",
            "transaction_has_xid": False,
            "can_set_replication_role": True,
            "has_publication": False,
        }
        self.catalog = [relation(10, "tenants"), relation(20, "empty"), relation(30, 'quo"ted')]
        self.second_catalog: list[dict[str, object]] | None = None
        self.catalog_reads = 0
        self.occupied = [10, 30]
        self.commands: list[str] = []
        self.fail_on: str | None = None
        self.connection.execute.side_effect = self.execute

    def execute(self, statement: object, parameters: Any = None) -> MagicMock:
        sql = str(statement).strip()
        self.commands.append(sql)
        if self.fail_on and sql.startswith(self.fail_on):
            raise RuntimeError("synthetic database failure")
        result = MagicMock()
        if sql.startswith("SELECT pg_catalog.current_database()"):
            result.mappings.return_value.one.return_value = self.state
        elif sql.startswith("WITH RECURSIVE"):
            self.catalog_reads += 1
            result.mappings.return_value = (
                self.second_catalog
                if self.catalog_reads > 1 and self.second_catalog is not None
                else self.catalog
            )
        elif sql.startswith("SELECT 10::oid"):
            result.scalars.return_value = self.occupied
        elif sql.startswith("DELETE"):
            result.rowcount = 2
        elif sql.startswith("SELECT pg_catalog.set_config"):
            result.scalar_one.return_value = parameters["role"]
        return result

    def clear(self) -> Any:
        return clear_test_tenants(cast(Connection, self.connection))


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> CleanupHarness:
    monkeypatch.setenv("TEST_DATABASE_URL", TEST_URL)
    return CleanupHarness()


@pytest.mark.parametrize("role", ["origin", "local"])
def test_only_occupied_tables_are_deleted_and_role_restored_before_return(
    harness: CleanupHarness, role: str
) -> None:
    harness.state["replication_role"] = role
    result = harness.clear()
    assert result.method == "delete"
    assert result.table_count == 3
    assert result.changed_table_count == 2
    assert result.deleted_rows == 4
    assert [sql for sql in harness.commands if sql.startswith("DELETE")] == [
        'DELETE FROM ONLY "cehub_core"."tenants"',
        'DELETE FROM ONLY "cehub_core"."quo""ted"',
    ]
    assert "replica" in harness.commands[-4]
    assert "set_config" in harness.commands[-1]
    assert harness.connection.execute.call_args.args[1] == {"role": role}
    harness.savepoint.commit.assert_called_once()
    harness.savepoint.rollback.assert_not_called()
    harness.connection.commit.assert_not_called()


def test_already_empty_closure_keeps_triggers_enabled(harness: CleanupHarness) -> None:
    harness.occupied = []
    result = harness.clear()
    assert result.changed_table_count == 0
    assert result.deleted_rows == 0
    assert not any(sql.startswith(("SET LOCAL", "DELETE", "TRUNCATE")) for sql in harness.commands)


@pytest.mark.parametrize(
    "changes",
    [
        {"relkind": "p"},
        {"has_inheritance": True},
        {"relrowsecurity": True},
        {"incompatible_trigger": True},
        {"has_rule": True},
        {"can_clear": False},
    ],
)
def test_incompatible_tables_preserve_original_truncate_behavior(
    harness: CleanupHarness, changes: dict[str, object]
) -> None:
    harness.catalog[1] = relation(20, "special", **changes)
    result = harness.clear()
    assert result.method == "truncate"
    assert result.fallback_reason
    assert harness.commands[-1] == "TRUNCATE TABLE cehub_core.tenants CONTINUE IDENTITY CASCADE"
    assert not any(sql.startswith(("SET LOCAL", "DELETE")) for sql in harness.commands)


@pytest.mark.parametrize(
    "changes",
    [
        {"can_set_replication_role": False},
        {"transaction_has_xid": True},
        {"isolation_level": "repeatable read"},
        {"has_publication": True},
    ],
)
def test_transaction_or_permission_limit_uses_original_truncate(
    harness: CleanupHarness, changes: dict[str, object]
) -> None:
    harness.state.update(changes)
    result = harness.clear()
    assert result.method == "truncate"
    assert result.fallback_reason
    assert harness.catalog_reads == 0


def test_catalog_change_while_locking_does_not_delete_stale_subset(harness: CleanupHarness) -> None:
    harness.second_catalog = [*harness.catalog, relation(40, "new_child")]
    result = harness.clear()
    assert result.method == "truncate"
    assert result.table_count == 4
    assert not any(sql.startswith(("SET LOCAL", "DELETE")) for sql in harness.commands)


@pytest.mark.parametrize("failure", ["SET LOCAL", "DELETE", "SELECT pg_catalog.set_config"])
def test_any_fast_cleanup_failure_rolls_back_savepoint_and_is_not_hidden(
    harness: CleanupHarness, failure: str
) -> None:
    harness.fail_on = failure
    with pytest.raises(RuntimeError, match="synthetic database failure"):
        harness.clear()
    harness.savepoint.rollback.assert_called_once()
    harness.savepoint.commit.assert_not_called()
    assert not any(sql.startswith("TRUNCATE") for sql in harness.commands)


def test_failed_rollback_invalidates_connection_instead_of_returning_it_to_pool(
    harness: CleanupHarness,
) -> None:
    harness.fail_on = "DELETE"
    harness.savepoint.rollback.side_effect = RuntimeError("rollback failed")
    with pytest.raises(RuntimeError, match="rollback failed"):
        harness.clear()
    harness.connection.invalidate.assert_called_once()


@pytest.mark.parametrize(
    "url",
    [
        TEST_URL.replace("pdos_test", "pdos"),
        TEST_URL.replace("localhost", "remote.example"),
        TEST_URL.replace("57550", "57551"),
        TEST_URL + "?host=remote.example",
        TEST_URL + "?service=production",
    ],
)
def test_unsafe_or_different_endpoint_rejected_without_sql(
    harness: CleanupHarness, url: str
) -> None:
    harness.connection.engine.url = make_url(url)
    with pytest.raises(UnsafeTestDatabaseError):
        harness.clear()
    harness.connection.execute.assert_not_called()


def test_autocommit_rejected_without_sql(harness: CleanupHarness) -> None:
    harness.connection.connection.driver_connection.autocommit = True
    with pytest.raises(UnsafeTestDatabaseError, match="autocommit"):
        harness.clear()
    harness.connection.execute.assert_not_called()


@pytest.mark.parametrize("changes", [{"database_name": "pdos"}, {"replication_role": "replica"}])
def test_wrong_actual_database_or_disabled_trigger_entry_is_rejected(
    harness: CleanupHarness, changes: dict[str, object]
) -> None:
    harness.state.update(changes)
    with pytest.raises(UnsafeTestDatabaseError):
        harness.clear()
    harness.connection.begin_nested.assert_not_called()
