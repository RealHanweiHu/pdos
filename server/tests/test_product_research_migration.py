"""Research Finding migration constraints match metadata and roll back without history."""

from importlib import import_module

from sqlalchemy import CheckConstraint, create_engine, text

from app.db.schema import tables
from app.db.url import psycopg_database_url
from tests.migration_fixtures import rollback_migration_operations
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


def test_research_finding_constraints_roundtrip(isolated_test_run_database: str) -> None:
    migration = import_module("migrations.versions.0398_product_research_findings")
    engine = create_engine(psycopg_database_url(isolated_test_run_database))
    try:
        with rollback_migration_operations(engine) as c:
            inheritance = import_module("migrations.versions.0402_definition_inheritance")
            inheritance.downgrade()
            planning = import_module("migrations.versions.0401_product_planning_findings")
            planning.downgrade()
            discovery = import_module("migrations.versions.0400_product_discovery_findings")
            discovery.downgrade()
            evidence = import_module("migrations.versions.0399_product_evidence_findings")
            evidence.downgrade()
            query = (
                "SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint WHERE "
                "conrelid='cehub_ai.findings'::regclass AND conname IN "
                "('ck_findings_scope','ck_findings_type_allowed','ck_findings_evidence_event_ids_array','ck_findings_apply_lifecycle_consistent')"
            )

            def canonical(definition: str) -> str:
                for _ in range(2):
                    c.execute(
                        text(
                            "ALTER TABLE cehub_ai.findings ADD CONSTRAINT metadata_check "
                            + definition
                        )
                    )
                    definition = c.execute(
                        text(
                            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE "
                            "conrelid='cehub_ai.findings'::regclass AND conname='metadata_check'"
                        )
                    ).scalar_one()
                    c.execute(text("ALTER TABLE cehub_ai.findings DROP CONSTRAINT metadata_check"))
                return definition

            quality_query = (
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE "
                "conrelid='cehub_ai.finding_quality_controls'::regclass AND "
                "conname='ck_finding_quality_controls_type_allowed'"
            )
            quality_before = c.execute(text(quality_query)).scalar_one()
            original = {row[0]: row[1] for row in c.execute(text(query))}
            previous: dict[str, str] = {
                row[0]: row[1]
                for row in c.execute(
                    text(
                        query.replace(
                            "pg_get_constraintdef(oid)", "obj_description(oid,'pg_constraint')"
                        )
                    )
                )
            }
            migration.downgrade()
            assert {
                k: canonical(v)
                for k, v in {row[0]: row[1] for row in c.execute(text(query))}.items()
            } == {k: canonical(v) for k, v in previous.items()}
            migration.upgrade()
            assert {
                k: canonical(v)
                for k, v in {row[0]: row[1] for row in c.execute(text(query))}.items()
            } == {k: canonical(v) for k, v in original.items()}
            assert canonical(c.execute(text(quality_query)).scalar_one()) == canonical(
                quality_before
            )
            evidence.upgrade()
            discovery.upgrade()
            planning.upgrade()
            inheritance.upgrade()
            original = {row[0]: row[1] for row in c.execute(text(query))}
            quality_before = c.execute(text(quality_query)).scalar_one()
            for constraint in tables.finding_quality_controls.constraints:
                if (
                    isinstance(constraint, CheckConstraint)
                    and constraint.name == "ck_finding_quality_controls_type_allowed"
                ):
                    # Same columns allow parsing both type predicates on findings.
                    assert canonical(f"CHECK ({constraint.sqltext})") == canonical(quality_before)
            for constraint in tables.findings.constraints:
                if isinstance(constraint, CheckConstraint) and str(constraint.name) in original:
                    assert canonical(f"CHECK ({constraint.sqltext})") == canonical(
                        original[str(constraint.name)]
                    )
            assert not c.execute(
                text(
                    "SELECT "
                    "has_table_privilege('pdos_agent','cehub_product.research_tasks','INSERT,UPDATE,DELETE')"
                )
            ).scalar_one()
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM pg_constraint WHERE "
                        "conrelid='cehub_product.research_tasks'::regclass AND conname IN "
                        "('fk_research_tasks_source_finding','uq_research_tasks_source_finding')"
                    )
                ).scalar_one()
                == 2
            )
    finally:
        engine.dispose()
