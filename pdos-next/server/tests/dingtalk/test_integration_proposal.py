"""Static migration and composition checks; no claim of executed PostgreSQL DDL."""

import ast
from pathlib import Path

from migrations.candidates.dingtalk import BASE_DOWN_SQL, EMPTY_HISTORY_SQL, TRANSFER_TABLES_SQL
from migrations.candidates.dingtalk_lifecycle import PREVIOUS_FUNCTIONS

SERVER = Path(__file__).resolve().parents[2]


def assignment(path, name):
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"Missing static assignment: {name}")


def test_native_predecessor_pins_are_actual_839_definitions_unchanged_by_841():
    native = assignment(SERVER / "migrations/schema_s0_0839.py", "NATIVE_FUNCTIONS")
    next_layer = assignment(SERVER / "migrations/schema_s0_0841.py", "NATIVE_FUNCTIONS")
    assert len(PREVIOUS_FUNCTIONS) == 2
    for signature, definition in PREVIOUS_FUNCTIONS.items():
        assert definition == native[signature]
        assert signature not in next_layer


def test_proposal_literals_are_reviewable_ascii_without_blanket_lint_exemption():
    for name in ("dingtalk.py", "dingtalk_lifecycle.py"):
        source = (SERVER / "migrations/candidates" / name).read_text()
        assert source.isascii()
        assert "noqa" not in source
        assert max(map(len, source.splitlines())) <= 100
        for token in ast.walk(ast.parse(source)):
            if isinstance(token, ast.Constant) and isinstance(token.value, str):
                # The AST joins adjacent literals; static parsing must still succeed.
                assert "\x00" not in token.value


def test_downgrade_metadata_acl_cleanup_precedes_role_drop_and_history_is_fenced():
    lock, fence = EMPTY_HISTORY_SQL
    tables = [sql.split("public.")[1].split()[0] for sql in TRANSFER_TABLES_SQL]
    assert len(set(tables)) == 6
    assert "ACCESS EXCLUSIVE" in lock
    assert all(f"public.{table}" in lock and f"public.{table}" in fence for table in tables)
    assert "RAISE EXCEPTION" in fence
    combined = "\n".join(BASE_DOWN_SQL)
    role_drop = combined.index("DROP ROLE pdos_next_dingtalk_maintenance")
    for table in (
        "agent_runs", "agent_tool_calls", "agent_run_events", "principals", "tenant_administrators"
    ):
        revokes = [
            sql for sql in BASE_DOWN_SQL
            if "REVOKE SELECT(" in sql and f"ON public.{table} " in sql
        ]
        assert len(revokes) == 1
        assert combined.index(revokes[0]) < role_drop
