"""Fast row cleanup for an exclusively owned, local ``pdos_test`` database.

Call ``clear_test_tenants(connection)`` at the start of ``engine.begin()`` and
commit that transaction before seeding or exercising application code. It clears
exactly the ordinary-table FK closure of ``TRUNCATE cehub_core.tenants CASCADE``
without resetting sequences. Unsupported catalog features use that original
TRUNCATE instead. Nothing is cached across migrations.

The fast path locks the complete closure, skips empty tables, and suppresses
ordinary DELETE/FK triggers only inside a savepoint. The original replication
role is restored before returning; failures roll back the savepoint. This does
not reclaim disk space or reproduce TRUNCATE's non-MVCC storage behavior, so it
is for test fixture row cleanup, never for testing TRUNCATE itself. No live test
or other database client may run concurrently with fixture cleanup.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Connection, text
from sqlalchemy.engine import URL, make_url

from app.db.test_safety import UnsafeTestDatabaseError, configured_test_database_url

_TRUNCATE = "TRUNCATE TABLE cehub_core.tenants CONTINUE IDENTITY CASCADE"
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_ENDPOINT_OVERRIDES = frozenset({"host", "hostaddr", "port", "dbname", "service", "servicefile"})

# UNION (not UNION ALL) makes self-references and FK cycles terminate. Any
# inheritance/partition edge falls back to PostgreSQL's own TRUNCATE expansion.
_CATALOG = text("""
WITH RECURSIVE targets(oid) AS (
    SELECT 'cehub_core.tenants'::pg_catalog.regclass::oid
    UNION
    SELECT fk.conrelid
    FROM pg_catalog.pg_constraint AS fk
    JOIN targets AS parent ON parent.oid = fk.confrelid
    WHERE fk.contype = 'f'
)
SELECT c.oid, n.nspname AS schema_name, c.relname AS table_name,
       c.relkind, c.relrowsecurity,
       EXISTS (
           SELECT 1 FROM pg_catalog.pg_inherits AS i
           WHERE i.inhrelid = c.oid OR i.inhparent = c.oid
       ) AS has_inheritance,
       EXISTS (
           SELECT 1 FROM pg_catalog.pg_trigger AS t
           WHERE t.tgrelid = c.oid AND t.tgenabled <> 'D'
             AND ((t.tgtype & 32) <> 0
                  OR ((t.tgtype & 8) <> 0 AND t.tgenabled IN ('A', 'R')))
       ) AS incompatible_trigger,
       EXISTS (
           SELECT 1 FROM pg_catalog.pg_rewrite AS r
           WHERE r.ev_class = c.oid AND r.ev_enabled <> 'D'
       ) AS has_rule,
       pg_catalog.has_table_privilege(c.oid, 'SELECT')
       AND pg_catalog.has_table_privilege(c.oid, 'DELETE')
       AND pg_catalog.has_table_privilege(c.oid, 'TRUNCATE') AS can_clear
FROM targets JOIN pg_catalog.pg_class AS c ON c.oid = targets.oid
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
ORDER BY c.oid
""")

_STATE = text("""
SELECT pg_catalog.current_database() AS database_name,
       pg_catalog.current_setting('session_replication_role') AS replication_role,
       pg_catalog.current_setting('transaction_isolation') AS isolation_level,
       pg_catalog.txid_current_if_assigned() IS NOT NULL AS transaction_has_xid,
       pg_catalog.has_parameter_privilege(
           CURRENT_USER, 'session_replication_role', 'SET'
       ) AS can_set_replication_role,
       EXISTS (SELECT 1 FROM pg_catalog.pg_publication) AS has_publication
""")


@dataclass(frozen=True)
class CleanupResult:
    method: Literal["delete", "truncate"]
    table_count: int
    changed_table_count: int | None
    deleted_rows: int | None
    fallback_reason: str | None = None


@dataclass(frozen=True)
class _Relation:
    oid: int
    schema: str
    name: str
    reason: str | None


def _local_endpoint(url: URL) -> tuple[str, int]:
    if (
        url.get_backend_name() != "postgresql"
        or url.database != "pdos_test"
        or url.host not in _LOCAL_HOSTS
        or _ENDPOINT_OVERRIDES.intersection(url.query)
    ):
        raise UnsafeTestDatabaseError(
            "Cleanup requires a direct local PostgreSQL connection to pdos_test"
        )
    return url.host, url.port or 5432


def _check_connection(connection: Connection) -> None:
    configured = _local_endpoint(make_url(configured_test_database_url()))
    actual = _local_endpoint(connection.engine.url)
    if actual != configured:
        raise UnsafeTestDatabaseError(
            "Cleanup connection does not match TEST_DATABASE_URL endpoint"
        )
    if not connection.in_transaction():
        raise UnsafeTestDatabaseError("Cleanup requires an explicit transaction")
    # SQLAlchemy can report a logical transaction even on an autocommit driver.
    driver = connection.connection.driver_connection
    if getattr(driver, "autocommit", True) is not False:
        raise UnsafeTestDatabaseError("Cleanup refuses an autocommit connection")


def _relations(connection: Connection) -> tuple[_Relation, ...]:
    relations: list[_Relation] = []
    for row in connection.execute(_CATALOG).mappings():
        reason = None
        if row["relkind"] != "r" or row["has_inheritance"]:
            reason = "inheritance, partition, or non-ordinary table"
        elif row["relrowsecurity"]:
            reason = "row security is enabled"
        elif row["incompatible_trigger"]:
            reason = "TRUNCATE or replica/always DELETE trigger"
        elif row["has_rule"]:
            reason = "table rewrite rule"
        elif not row["can_clear"]:
            reason = "SELECT, DELETE, or TRUNCATE privilege unavailable"
        relations.append(
            _Relation(int(row["oid"]), str(row["schema_name"]), str(row["table_name"]), reason)
        )
    if not relations:
        raise UnsafeTestDatabaseError("Cleanup target table is unavailable")
    return tuple(relations)


def _qualified(connection: Connection, relation: _Relation) -> str:
    quote = connection.dialect.identifier_preparer.quote_identifier
    return f"{quote(relation.schema)}.{quote(relation.name)}"


def _truncate(connection: Connection, count: int, reason: str) -> CleanupResult:
    connection.execute(text(_TRUNCATE))
    return CleanupResult("truncate", count, None, None, reason)


def _restore_role(connection: Connection, role: str) -> None:
    restored = connection.execute(
        text("SELECT pg_catalog.set_config('session_replication_role', :role, true)"),
        {"role": role},
    ).scalar_one()
    if restored != role:
        raise RuntimeError("Cleanup failed to restore session_replication_role")


def clear_test_tenants(connection: Connection) -> CleanupResult:
    """Empty the tenant TRUNCATE closure; never commit or grant DB privileges.

    Uses PostgreSQL 15+ parameter-privilege introspection. A pre-existing write
    transaction, non-READ-COMMITTED snapshot, unsupported table feature, or lack
    of SET privilege takes the original TRUNCATE path. Callers must let cleanup
    errors fail the fixture, not seed data after an unsuccessful cleanup.
    """
    _check_connection(connection)
    state = connection.execute(_STATE).mappings().one()
    if state["database_name"] != "pdos_test":
        raise UnsafeTestDatabaseError("Connected database is not pdos_test")
    role = str(state["replication_role"])
    if role not in {"origin", "local"}:
        raise UnsafeTestDatabaseError("Cleanup requires normal trigger enforcement on entry")

    # Savepoint rollback also reverses SET LOCAL on every error path. Checking
    # state precedes it so creating the savepoint cannot influence the XID test.
    savepoint = connection.begin_nested()
    try:
        if state["transaction_has_xid"]:
            result = _truncate(connection, 0, "transaction already has writes or row locks")
        elif state["isolation_level"] != "read committed":
            result = _truncate(connection, 0, "snapshot isolation differs from READ COMMITTED")
        elif not state["can_set_replication_role"]:
            result = _truncate(connection, 0, "SET privilege unavailable")
        elif state["has_publication"]:
            result = _truncate(connection, 0, "logical publication is configured")
        else:
            result = _clear_locked(connection, role)
        savepoint.commit()
        return result
    except BaseException:
        try:
            savepoint.rollback()
        except BaseException:
            # Never return a potentially replica-mode connection to its pool.
            connection.invalidate()
            raise
        raise


def _clear_locked(connection: Connection, role: str) -> CleanupResult:
    relations = _relations(connection)
    unsupported = next((r.reason for r in relations if r.reason), None)
    if unsupported:
        return _truncate(connection, len(relations), unsupported)

    # Matching TRUNCATE's table locks prevents inserts during the emptiness
    # probe, and blocks FK/schema changes once the closure has been locked.
    names = ", ".join("ONLY " + _qualified(connection, r) for r in relations)
    connection.execute(text(f"LOCK TABLE {names} IN ACCESS EXCLUSIVE MODE"))
    current = _relations(connection)
    if current != relations:
        return _truncate(connection, len(current), "catalog changed before all locks were acquired")

    probes = " UNION ALL ".join(
        f"SELECT {r.oid}::oid AS oid WHERE EXISTS (SELECT 1 FROM ONLY {_qualified(connection, r)})"
        for r in relations
    )
    occupied = set(connection.execute(text(probes)).scalars())
    if not occupied:
        return CleanupResult("delete", len(relations), 0, 0)

    connection.execute(text("SET LOCAL session_replication_role = replica"))
    deleted_rows = 0
    changed_tables = 0
    for relation in relations:
        if relation.oid in occupied:
            result = connection.execute(
                text(f"DELETE FROM ONLY {_qualified(connection, relation)}")
            )
            deleted_rows += result.rowcount
            changed_tables += 1
    _restore_role(connection, role)
    return CleanupResult("delete", len(relations), changed_tables, deleted_rows)
