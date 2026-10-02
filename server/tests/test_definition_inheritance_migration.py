"""Inheritance migration restores exact predecessor trigger bodies and comments."""

from importlib import import_module

from sqlalchemy import create_engine, text

from app.db.url import psycopg_database_url
from tests.migration_fixtures import rollback_migration_operations
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


def test_definition_inheritance_roundtrip(isolated_test_run_database: str) -> None:
    migration = import_module("migrations.versions.0402_definition_inheritance")
    engine = create_engine(psycopg_database_url(isolated_test_run_database))
    try:
        with rollback_migration_operations(engine) as c:

            def snapshot() -> dict[str, tuple[str, str | None]]:
                return {
                    name: tuple(
                        c.execute(
                            text(
                                "SELECT pg_get_functiondef(CAST(:name AS regprocedure)),"
                                "obj_description(CAST(:name AS regprocedure),'pg_proc')"
                            ),
                            {"name": name + "()"},
                        ).one()
                    )
                    for name in migration.FUNCTIONS
                }

            original = snapshot()
            migration.downgrade()
            assert all(
                "resolve_definition_content" not in value[0] for value in snapshot().values()
            )
            migration.upgrade()
            assert snapshot() == original
            for table in ["product_nodes", "product_definitions"]:
                assert not c.execute(
                    text(
                        f"SELECT has_table_privilege('pdos_agent','cehub_product.{table}',"
                        "'INSERT,UPDATE,DELETE')"
                    )
                ).scalar_one()
    finally:
        engine.dispose()
