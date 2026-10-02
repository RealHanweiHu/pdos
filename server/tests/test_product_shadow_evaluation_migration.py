"""0407 preserves its actual historical constraints, comments and employee write boundary."""

import json
from collections.abc import Callable
from importlib import import_module

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, Connection, create_engine, text

from app.db.schema import tables
from app.db.url import psycopg_database_url
from tests.migration_fixtures import rollback_migration_operations
from tests.test_migrations import EXPECTED_HEAD, SERVER_ROOT
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database

ConstraintRows = dict[str, tuple[str, str | None]]
MachineSnapshot = tuple[str, str, str | None]
NormalizedConstraintRows = dict[str, tuple[str, str | None | MachineSnapshot]]
ObjectRows = dict[str, tuple[object, ...]]


def constraint_rows(connection: Connection) -> ConstraintRows:
    return {
        row[0]: (row[1], row[2])
        for row in connection.execute(
            text(
                "SELECT conname,pg_get_constraintdef(oid),obj_description(oid,'pg_constraint') "
                "FROM pg_constraint WHERE conrelid='cehub_ai.agent_runs'::regclass "
                "AND conname IN ('ck_agent_runs_scope','ck_agent_runs_event_bounds_consistent')"
            )
        )
    }


def function_rows(connection: Connection) -> ObjectRows:
    return {
        row[0]: tuple(row[1:])
        for row in connection.execute(
            text(
                "SELECT p.oid::regprocedure::text,pg_get_functiondef(p.oid),p.proacl::text,"
                "p.proowner::regrole::text,p.prosecdef,p.proconfig,"
                "obj_description(p.oid,'pg_proc') "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname='cehub_ai' AND p.proname IN "
                "('guard_product_evaluation_run','guard_market_matrix_run',"
                "'application_authorization_is_current')"
            )
        )
    }


def trigger_rows(connection: Connection) -> ObjectRows:
    return {
        row[0]: tuple(row[1:])
        for row in connection.execute(
            text(
                "SELECT tgname,pg_get_triggerdef(oid),tgenabled,obj_description(oid,'pg_trigger') "
                "FROM pg_trigger WHERE tgrelid='cehub_ai.agent_runs'::regclass "
                "AND tgname='guard_product_evaluation_run' AND NOT tgisinternal"
            )
        )
    }


def role_state(connection: Connection) -> tuple[object, ...]:
    state = tuple(
        connection.execute(
            text(
                "SELECT relowner::regrole::text,relacl::text,"
                "has_table_privilege('pdos_agent',oid,'INSERT'),"
                "has_table_privilege('pdos_agent',oid,'UPDATE'),"
                "has_table_privilege('pdos_agent',oid,'DELETE') "
                "FROM pg_class WHERE oid='cehub_product.product_definitions'::regclass"
            )
        ).one()
    )
    assert state[2:] == (False, False, False)
    return state


def test_empty_roundtrip_metadata_comments_and_role_boundary(
    isolated_test_run_database: str,
    record_property: Callable[[str, object], None],
) -> None:
    migration = import_module("migrations.versions.0407_product_shadow_evaluation")
    scripts = ScriptDirectory.from_config(Config(str(SERVER_ROOT / "alembic.ini")))
    assert scripts.get_heads() == [EXPECTED_HEAD]
    later = list(scripts.iterate_revisions(EXPECTED_HEAD, migration.revision))
    position = EXPECTED_HEAD
    for revision in later:
        assert revision.revision == position
        assert isinstance(revision.down_revision, str)
        assert not revision.dependencies and not revision.branch_labels
        position = revision.down_revision
    assert position == migration.revision
    historical_revision = scripts.get_revision(migration.revision)
    assert historical_revision is not None
    assert historical_revision.down_revision == migration.down_revision

    engine = create_engine(psycopg_database_url(isolated_test_run_database))
    try:
        with rollback_migration_operations(engine) as c:

            def canonical(value: str) -> str:
                for _ in range(2):
                    c.execute(
                        text(
                            "ALTER TABLE cehub_ai.agent_runs ADD CONSTRAINT eval_metadata_check "
                            + value
                        )
                    )
                    value = c.execute(
                        text(
                            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE "
                            "conrelid='cehub_ai.agent_runs'::regclass "
                            "AND conname='eval_metadata_check'"
                        )
                    ).scalar_one()
                    c.execute(
                        text("ALTER TABLE cehub_ai.agent_runs DROP CONSTRAINT eval_metadata_check")
                    )
                return value

            def normalized_comment(comment: str | None) -> str | None | MachineSnapshot:
                if comment is None:
                    return None
                try:
                    saved: object = json.loads(comment)
                except json.JSONDecodeError:
                    return comment
                if not isinstance(saved, dict) or saved.get("version") != migration.VERSION:
                    return comment
                assert set(saved) == {"version", "expression", "comment"}
                version, expression, original_comment = (
                    saved["version"],
                    saved["expression"],
                    saved["comment"],
                )
                assert isinstance(version, str) and isinstance(expression, str)
                assert original_comment is None or isinstance(original_comment, str)
                # Only 0407's machine-saved SQL is canonicalized; its original comment is raw.
                return version, canonical(expression), original_comment

            def normalized(rows: ConstraintRows) -> NormalizedConstraintRows:
                return {
                    name: (canonical(value), normalized_comment(comment))
                    for name, (value, comment) in rows.items()
                }

            head = constraint_rows(c)
            assert set(head) == {"ck_agent_runs_scope", "ck_agent_runs_event_bounds_consistent"}
            head_constraints = normalized(head)
            head_functions = function_rows(c)
            head_triggers = trigger_rows(c)
            head_role = role_state(c)
            # Current metadata describes the frozen head, not the schema at 0407.
            metadata_constraints = {
                str(constraint.name): constraint
                for constraint in tables.agent_runs.constraints
                if isinstance(constraint, CheckConstraint) and str(constraint.name) in head
            }
            assert set(metadata_constraints) == set(head)
            for name, constraint in metadata_constraints.items():
                assert canonical(f"CHECK ({constraint.sqltext})") == canonical(head[name][0])

            # Apply the real descending graph on this connection; never edit alembic_version.
            for revision in later:
                revision.module.downgrade()
            historical = constraint_rows(c)
            historical_constraints = normalized(historical)
            historical_functions = function_rows(c)
            historical_triggers = trigger_rows(c)
            assert set(historical) == set(head)
            assert role_state(c) == head_role
            expected_prior: ConstraintRows = {}
            for name, (_, comment) in historical.items():
                assert comment is not None
                saved: dict[str, object] = json.loads(comment)
                assert saved["version"] == migration.VERSION
                original_expression, original_comment = saved["expression"], saved["comment"]
                assert isinstance(original_expression, str)
                assert original_comment is None or isinstance(original_comment, str)
                expected_prior[name] = (original_expression, original_comment)

            migration.downgrade()
            prior = constraint_rows(c)
            prior_functions = function_rows(c)
            assert normalized(prior) == normalized(expected_prior)
            assert trigger_rows(c) == {}
            assert role_state(c) == head_role
            migration.upgrade()
            assert normalized(constraint_rows(c)) == historical_constraints
            assert function_rows(c) == historical_functions
            assert trigger_rows(c) == historical_triggers
            assert role_state(c) == head_role

            migration.downgrade()
            assert normalized(constraint_rows(c)) == normalized(prior)
            assert function_rows(c) == prior_functions
            assert trigger_rows(c) == {}
            assert role_state(c) == head_role
            migration.upgrade()
            assert normalized(constraint_rows(c)) == historical_constraints
            assert function_rows(c) == historical_functions
            assert trigger_rows(c) == historical_triggers
            assert role_state(c) == head_role

            for revision in reversed(later):
                revision.module.upgrade()
            replayed = constraint_rows(c)
            assert normalized(replayed) == head_constraints
            rendering_fields: list[str] = []
            for name, (_, comment) in replayed.items():
                original_comment = head[name][1]
                if comment != original_comment:
                    assert comment is not None and original_comment is not None
                    actual_snapshot: dict[str, object] = json.loads(comment)
                    original_snapshot: dict[str, object] = json.loads(original_comment)
                    assert actual_snapshot["expression"] != original_snapshot["expression"]
                    rendering_fields.append(f"{name}.comment.expression (0407)")
            record_property(
                "replayed_machine_snapshot_rendering_fields", json.dumps(rendering_fields)
            )
            assert function_rows(c) == head_functions
            assert trigger_rows(c) == head_triggers
            assert role_state(c) == head_role
            assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
                EXPECTED_HEAD
            )

        # The outer rollback restores original objects and raw comments, not only the version.
        with engine.connect() as c:
            assert constraint_rows(c) == head
            assert function_rows(c) == head_functions
            assert trigger_rows(c) == head_triggers
            assert role_state(c) == head_role
            assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
                EXPECTED_HEAD
            )
    finally:
        engine.dispose()
