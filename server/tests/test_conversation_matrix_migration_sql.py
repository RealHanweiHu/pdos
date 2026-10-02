"""Offline matrix guard construction and original work-guard preservation; no database."""

import ast
from importlib import import_module
from io import StringIO
from pathlib import Path
from typing import cast
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def literal(filename: str, name: str) -> str:
    module = ast.parse((VERSIONS / filename).read_text())
    value = next(
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
    )
    assert isinstance(value, str)
    return value


def function(sql: str, name: str) -> str:
    marker = sql.index("FUNCTION cehub_ai." + name)
    start = sql.rfind("CREATE", 0, marker)
    end = sql.index("END $$;", marker) + len("END $$;")
    return sql[start:end].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION")


def test_downgrade_snapshot_restores_all_three_actual_0412_guards() -> None:
    migration = import_module("migrations.versions.0413_conversation_matrix_runs")
    original = literal("0412_product_conversations.py", "GUARDS")
    expected = "\n".join(
        function(original, name)
        for name in (
            "guard_conversation_message",
            "guard_conversation_product_run",
            "guard_message_attachment",
        )
    )
    assert expected == migration.OLD_GUARDS
    legacy_run = function(original, "guard_conversation_product_run")
    marker = " IF jsonb_typeof(m.product_work_request->'selection'->'sources')"
    assert legacy_run[legacy_run.index(marker) :] in migration.GUARDS


def test_offline_operations_preserve_history_and_guard_before_restore() -> None:
    migration = import_module("migrations.versions.0413_conversation_matrix_runs")
    assert migration.down_revision == "0412_product_conversations"
    source = ast.parse((VERSIONS / "0413_conversation_matrix_runs.py").read_text())
    assert all(
        not isinstance(node, ast.ImportFrom) or node.module == "alembic" for node in source.body
    )
    for operation in (migration.upgrade, migration.downgrade):
        buffer = StringIO()
        context = MigrationContext.configure(
            dialect_name="postgresql",
            opts={"as_sql": True, "output_buffer": buffer},
        )
        with Operations.context(context):
            operation()
        output = buffer.getvalue()
        assert "FUNCTION cehub_ai.guard_conversation_product_run" in output
        assert "TRUNCATE" not in output.upper() and "DELETE FROM" not in output.upper()
        assert "GRANT " not in output.upper()
    calls: list[str] = []
    with patch.object(migration.op, "execute", side_effect=calls.append):
        migration.downgrade()
    assert calls[0] == migration.DOWNGRADE_PROTECTION
    assert "product_work_request->>'kind'='matrix'" in calls[0]
    assert "r.context_version='product-matrix-request-v1'" in calls[0]
    assert calls[1] == migration.OLD_GUARDS


def test_matrix_scope_unknown_kind_and_source_checks_fail_closed_on_sql_null() -> None:
    migration = import_module("migrations.versions.0413_conversation_matrix_runs")
    guard = function(migration.GUARDS, "guard_conversation_message")
    assert "ELSE 'work' END) IN ('work','matrix')) IS NOT TRUE" in guard
    assert "->>'product_line_id' IS DISTINCT FROM c.product_line_id::text" in guard
    assert "r.product_line_id IS NOT DISTINCT FROM c.product_line_id" in guard
    assert "(NEW.product_work_request->'selection')-ARRAY['record_id','roadmap_ids']" in guard
    assert "jsonb_array_length" in guard and ">8" in guard
    assert "count(DISTINCT value)" in guard
    assert "'^[0-9a-f]{8}-" in guard
    run = function(migration.GUARDS, "guard_conversation_product_run")
    assert "r.result_digest=source->>'record_result_digest')) IS NOT TRUE" in run
    for binding in (
        "source->>'actor_id'=m.author_user_id::text",
        "source->>'market_space_id'=c.market_space_id::text",
        "source->'selection'=m.product_work_request->'selection'",
        "source->>'digest'=m.product_work_request->>'expected_digest'",
    ):
        assert binding in run
    assert "Matrix requests cannot use private attachment bindings" in run
    attachment = function(migration.GUARDS, "guard_message_attachment")
    assert "m.product_work_request->>'kind'='matrix'" in attachment
    assert "Matrix requests cannot use private attachment bindings" in attachment
    matrix_rejection = attachment.index("Matrix requests cannot use private attachment bindings")
    assert matrix_rejection < attachment.index("c.next_sequence<>m.sequence")
    assert matrix_rejection < attachment.index("a.classification<>'internal'")
    assert attachment.count("Matrix requests cannot use private attachment bindings") == 1
    early = attachment[:matrix_rejection]
    for scoped_original in (
        "m.id IS NOT NULL AND a.id IS NOT NULL AND c.id IS NOT NULL",
        "c.project_id IS NOT DISTINCT FROM NEW.project_id",
        "m.project_id IS NOT DISTINCT FROM NEW.project_id",
        "a.project_id IS NOT DISTINCT FROM NEW.project_id",
        "tenant_id=NEW.tenant_id",
        "conversation_id=NEW.conversation_id",
    ):
        assert scoped_original in early


def test_current_request_check_matches_metadata_and_old_check_restores_0412() -> None:
    import re

    from sqlalchemy import CheckConstraint
    from sqlalchemy.dialects.postgresql import dialect
    from sqlalchemy.engine import Dialect
    from sqlalchemy.schema import AddConstraint

    from app.db.schema import tables

    migration = import_module("migrations.versions.0413_conversation_matrix_runs")
    constraint = next(
        c
        for c in tables.conversation_messages.constraints
        if isinstance(c, CheckConstraint)
        and str(c.name) == "ck_conversation_messages_product_request"
    )
    postgres_dialect = cast(type[Dialect], dialect)()
    compiled = str(AddConstraint(constraint).compile(dialect=postgres_dialect)).split(" ADD ", 1)[1]
    assert re.sub(r"\s+", "", compiled) in re.sub(r"\s+", "", migration.UPGRADE_DDL)
    assert str(constraint.sqltext) == migration.NEW_REQUEST_CHECK
    original = literal("0412_product_conversations.py", "DDL")
    assert "CHECK(" + migration.OLD_REQUEST_CHECK + ")" in original
    assert migration.OLD_REQUEST_CHECK in migration.DOWNGRADE_DDL
    assert "DROP CONSTRAINT ck_conversation_messages_product_request" in migration.UPGRADE_DDL
    assert "DROP CONSTRAINT ck_conversation_messages_product_request" in migration.DOWNGRADE_DDL
    for requirement in ("IS TRUE", "'kind'", "'matrix'", "'product_line_id'", "roadmap_ids"):
        assert requirement in migration.NEW_REQUEST_CHECK
