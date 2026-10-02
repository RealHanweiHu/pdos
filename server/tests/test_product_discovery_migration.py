"""0400 actual PostgreSQL constraints, preserved downgrade comments and business-role boundaries."""

import json
from importlib import import_module

from sqlalchemy import CheckConstraint, create_engine, text

from app.db.schema import tables
from app.db.url import psycopg_database_url
from tests.migration_fixtures import rollback_migration_operations
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


def test_empty_roundtrip_matches_metadata_and_preserves_previous_comments(
    isolated_test_run_database: str,
) -> None:
    migration = import_module("migrations.versions.0400_product_discovery_findings")
    engine = create_engine(psycopg_database_url(isolated_test_run_database))
    try:
        with rollback_migration_operations(engine) as c:
            rfq = import_module("migrations.versions.0404_product_rfq_requirements")
            rfq.downgrade()
            inheritance = import_module("migrations.versions.0402_definition_inheritance")
            inheritance.downgrade()
            planning = import_module("migrations.versions.0401_product_planning_findings")
            planning.downgrade()

            def rows(table: str) -> dict[str, tuple[str, str | None]]:
                return {
                    r[0]: (r[1], r[2])
                    for r in c.execute(
                        text(
                            "SELECT conname,pg_get_constraintdef(oid),"
                            "obj_description(oid,'pg_constraint') "
                            f"FROM pg_constraint WHERE conrelid='cehub_ai.{table}'::regclass"
                        )
                    )
                }

            def canonical(table: str, definition: str) -> str:
                for _ in range(2):
                    c.execute(
                        text(
                            f"ALTER TABLE cehub_ai.{table} ADD CONSTRAINT metadata_check "
                            + definition
                        )
                    )
                    definition = c.execute(
                        text(
                            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                            f"WHERE conrelid='cehub_ai.{table}'::regclass "
                            "AND conname='metadata_check'"
                        )
                    ).scalar_one()
                    c.execute(text(f"ALTER TABLE cehub_ai.{table} DROP CONSTRAINT metadata_check"))
                return definition

            original = {table: rows(table) for table in ["findings", "finding_quality_controls"]}
            migration.downgrade()
            for table, names in [
                ("findings", migration.BRANCHES),
                ("finding_quality_controls", ["type_allowed"]),
            ]:
                current = rows(table)
                for name in names:
                    full = f"ck_{table}_{name}"
                    prior = json.loads(original[table][full][1] or "{}")
                    assert canonical(table, current[full][0]) == canonical(
                        table, prior["definition"]
                    )
                    assert current[full][1] == prior["comment"]
            migration.upgrade()
            for table, names in [
                ("findings", migration.BRANCHES),
                ("finding_quality_controls", ["type_allowed"]),
            ]:
                current = rows(table)
                for name in names:
                    full = f"ck_{table}_{name}"
                    assert canonical(table, current[full][0]) == canonical(
                        table, original[table][full][0]
                    )
            planning.upgrade()
            inheritance.upgrade()
            rfq.upgrade()
            for table in ["findings", "finding_quality_controls"]:
                current = rows(table)
                for constraint in getattr(tables, table).constraints:
                    if isinstance(constraint, CheckConstraint) and str(constraint.name) in current:
                        assert canonical(table, f"CHECK ({constraint.sqltext})") == canonical(
                            table, current[str(constraint.name)][0]
                        )
            for table in ["opportunities", "experiments"]:
                assert not c.execute(
                    text(
                        f"SELECT has_table_privilege('pdos_agent','cehub_product.{table}',"
                        "'INSERT,UPDATE,DELETE')"
                    )
                ).scalar_one()
                assert (
                    c.execute(
                        text(
                            "SELECT count(*) FROM pg_constraint "
                            f"WHERE conrelid='cehub_product.{table}'::regclass AND conname IN "
                            f"('fk_{table}_source_finding','uq_{table}_source_finding_position','ck_{table}_finding_position')"
                        )
                    ).scalar_one()
                    == 3
                )
    finally:
        engine.dispose()
