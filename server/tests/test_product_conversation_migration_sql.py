"""Offline migration construction and original project guard preservation; no database."""

import ast
from importlib import import_module
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def literal(filename: str, name: str) -> str:
    module = ast.parse((VERSIONS / filename).read_text())
    return next(
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
    )


def original_function(sql: str, name: str) -> str:
    marker = sql.index("FUNCTION cehub_ai." + name)
    start = sql.rfind("CREATE", 0, marker)
    end = sql.index("END $$;", marker) + len("END $$;")
    return sql[start:end].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION")


def test_downgrade_restores_actual_project_shared_and_eml_guards() -> None:
    migration = import_module("migrations.versions.0412_product_conversations")
    shared = literal("0395_xiaopai_delegations.py", "GUARDS")
    attachments = literal("0177_conversation_attachments.py", "GUARDS")
    expected = "\n".join(
        [
            original_function(shared, name)
            for name in (
                "guard_private_conversation",
                "guard_conversation_message",
                "guard_conversation_attachment",
            )
        ]
        + [
            original_function(attachments, name)
            for name in ("guard_message_attachment", "guard_attachment_request")
        ]
    )
    assert expected == migration.OLD_GUARDS


def test_offline_operations_do_not_import_application_or_delete_history() -> None:
    migration = import_module("migrations.versions.0412_product_conversations")
    assert migration.down_revision == "0411_plan_lineage_aliases"
    source = ast.parse((VERSIONS / "0412_product_conversations.py").read_text())
    assert all(
        not isinstance(node, ast.ImportFrom) or node.module == "alembic" for node in source.body
    )
    for operation in (migration.upgrade, migration.downgrade):
        buffer = StringIO()
        context = MigrationContext.configure(
            dialect_name="postgresql", opts={"as_sql": True, "output_buffer": buffer}
        )
        with Operations.context(context):
            operation()
        emitted = buffer.getvalue()
        assert emitted
        assert "DELETE FROM" not in emitted.upper()
        assert "TRUNCATE" not in emitted.upper()
    # The preservation check must execute before any restoring/dropping DDL.
    calls: list[str] = []
    with patch.object(migration.op, "execute", side_effect=calls.append):
        migration.downgrade()
    assert "scope_kind<>'project'" in calls[0]
    assert "action='product_work'" in calls[0]
    assert calls[1] == migration.OLD_GUARDS


def test_pm_null_scope_guards_do_not_replace_unrelated_run_or_project_actor_guards() -> None:
    migration = import_module("migrations.versions.0412_product_conversations")
    assert "CREATE OR REPLACE FUNCTION cehub_ai.conversation_actor_allowed" not in migration.GUARDS
    assert "guard_conversation_meeting_planning_run" not in migration.GUARDS
    assert "guard_conversation_change_run" not in migration.GUARDS
    assert "NEW.project_id<>OLD.project_id" not in migration.GUARDS
    assert "project_id=NEW.project_id" not in migration.GUARDS
    assert "NEW.project_id IS NULL" in migration.GUARDS
    assert "source->'selection'=m.product_work_request->'selection'" in migration.GUARDS
    assert "source->>'actor_id'=m.author_user_id::text" in migration.GUARDS


def test_new_checks_and_strict_parent_constraints_match_metadata_offline() -> None:
    import re

    from sqlalchemy import CheckConstraint
    from sqlalchemy.dialects.postgresql import dialect
    from sqlalchemy.schema import AddConstraint

    from app.db.schema import tables

    migration = import_module("migrations.versions.0412_product_conversations")
    normalized_ddl = re.sub(r"\s+", "", migration.DDL)
    for table, names in (
        (
            tables.conversations,
            {
                "ck_conversations_typed_scope",
                "uq_conversation_typed_scope",
                "fk_conversations_market_space",
                "fk_conversations_product_line",
            },
        ),
        (
            tables.conversation_messages,
            {
                # The product_request CHECK is extended at 0413; its latest
                # metadata correspondence and exact 0412 restoration are
                # verified in test_conversation_matrix_migration_sql.py.
                "ck_conversation_messages_action_allowed",
                "ck_conversation_messages_action_source",
                "uq_conversation_message_typed_scope",
                "fk_conversation_messages_typed_conversation",
            },
        ),
        (
            tables.conversation_attachments,
            {
                "uq_conversation_attachment_typed_scope",
                "fk_conversation_attachments_typed_conversation",
            },
        ),
        (
            tables.conversation_attachment_requests,
            {"fk_conversation_attachment_requests_typed_attachment"},
        ),
        (
            tables.conversation_message_attachments,
            {
                "fk_conversation_message_attachments_typed_message",
                "fk_conversation_message_attachments_typed_attachment",
            },
        ),
    ):
        assert table.c.project_id.nullable
        matched = {
            str(constraint.name)
            for constraint in table.constraints
            if str(constraint.name) in names
        }
        assert names == matched
        for constraint in table.constraints:
            if str(constraint.name) not in names:
                continue
            compiled = str(AddConstraint(constraint).compile(dialect=dialect()))
            # Compare each ADD clause independently of a multi-clause ALTER TABLE.
            clause = compiled.split(" ADD ", 1)[1]
            assert re.sub(r"\s+", "", clause) in normalized_ddl
            if isinstance(constraint, CheckConstraint):
                assert str(constraint.sqltext)
