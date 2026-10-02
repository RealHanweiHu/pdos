"""0397 database round-trip, same metadata constraints, no business-role writes granted."""

from importlib import import_module

from sqlalchemy import CheckConstraint, create_engine, text

from app.db.schema import tables
from app.db.url import psycopg_database_url
from tests.migration_fixtures import rollback_migration_operations
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database

migration = import_module("migrations.versions.0397_product_work_runs")


def test_empty_roundtrip_restores_actual_head_constraints_and_matches_metadata(
    isolated_test_run_database: str,
) -> None:
    engine = create_engine(psycopg_database_url(isolated_test_run_database))
    try:
        with rollback_migration_operations(engine) as c:
            evaluation = import_module("migrations.versions.0407_product_shadow_evaluation")
            evaluation.downgrade()
            rfq = import_module("migrations.versions.0404_product_rfq_requirements")
            rfq.downgrade()
            inheritance = import_module("migrations.versions.0402_definition_inheritance")
            inheritance.downgrade()
            planning = import_module("migrations.versions.0401_product_planning_findings")
            planning.downgrade()
            discovery = import_module("migrations.versions.0400_product_discovery_findings")
            discovery.downgrade()
            names = "conname IN ('ck_agent_runs_scope','ck_agent_runs_event_bounds_consistent')"
            query = (
                "SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid='cehub_ai.agent_runs'::regclass AND " + names
            )

            def canonical(definition: str) -> str:
                # PostgreSQL distributes array casts on reparse; normalize both sides equally.
                for _ in range(2):
                    c.execute(
                        text(
                            "ALTER TABLE cehub_ai.agent_runs ADD CONSTRAINT metadata_check "
                            + definition
                        )
                    )
                    definition = c.execute(
                        text(
                            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                            "WHERE conrelid='cehub_ai.agent_runs'::regclass "
                            "AND conname='metadata_check'"
                        )
                    ).scalar_one()
                    c.execute(
                        text("ALTER TABLE cehub_ai.agent_runs DROP CONSTRAINT metadata_check")
                    )
                return definition

            original = dict(c.execute(text(query)).all())
            preceding = dict(
                c.execute(
                    text(
                        query.replace(
                            "pg_get_constraintdef(oid)", "obj_description(oid,'pg_constraint')"
                        )
                    )
                ).all()
            )
            research = import_module("migrations.versions.0398_product_research_findings")
            evidence = import_module("migrations.versions.0399_product_evidence_findings")
            evidence.downgrade()
            research.downgrade()
            migration.downgrade()
            assert {k: canonical(v) for k, v in dict(c.execute(text(query)).all()).items()} == {
                k: canonical(v) for k, v in preceding.items()
            }
            migration.upgrade()
            research.upgrade()
            evidence.upgrade()
            discovery.upgrade()
            planning.upgrade()
            inheritance.upgrade()
            assert {k: canonical(v) for k, v in dict(c.execute(text(query)).all()).items()} == {
                k: canonical(v) for k, v in original.items()
            }
            # Let PostgreSQL parse metadata too, then compare canonical stored expressions.
            rfq.upgrade()
            evaluation.upgrade()
            original = dict(c.execute(text(query)).all())
            for constraint in tables.agent_runs.constraints:
                if isinstance(constraint, CheckConstraint) and str(constraint.name) in original:
                    assert canonical(f"CHECK ({constraint.sqltext})") == canonical(
                        original[str(constraint.name)]
                    )
            assert not c.execute(
                text(
                    "SELECT has_table_privilege('pdos_agent','cehub_product.market_spaces',"
                    "'INSERT,UPDATE,DELETE')"
                )
            ).scalar_one()
    finally:
        engine.dispose()
