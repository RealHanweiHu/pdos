"""Fix SQL operator precedence without changing original provenance checks."""

from importlib import import_module

from sqlalchemy import create_engine, text

from tests.migration_fixtures import rollback_migration_operations
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


def test_empty_matrix_outcome_guard_roundtrip(isolated_test_run_database: str) -> None:
    migration = import_module("migrations.versions.0406_matrix_outcome_guard")
    engine = create_engine(isolated_test_run_database)
    try:
        with rollback_migration_operations(engine) as c:
            sql = text(
                "SELECT pg_get_functiondef('cehub_product.guard_matrix_outcome()'::regprocedure)"
            )
            current = c.execute(sql).scalar_one()
            assert migration.NEW in current
            migration.downgrade()
            previous = c.execute(sql).scalar_one()
            assert previous == current.replace(migration.NEW, migration.OLD)
            migration.upgrade()
            assert c.execute(sql).scalar_one() == current
    finally:
        engine.dispose()
