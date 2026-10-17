"""Frozen migration dispatch and exact lifecycle changes; no database execution."""

import ast
import re
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from migrations import schema_s0_0777 as frozen
from migrations.versions import s0_0777_manufacturing_publication as migration

SERVER = Path(__file__).resolve().parents[2]
TABLES = (
    "manufacturing_baseline_publications",
    "manufacturing_publication_currents",
    "manufacturing_publication_documents",
)
NODES = "m3_lifecycle_nodes(uuid,uuid,uuid[])"
SOURCES = "m3_lifecycle_source_links(uuid,uuid,text,jsonb)"
ROWS = "m3_lifecycle_row_links(uuid,uuid,text,jsonb)"


class OfflineConnection:
    """Only migration IO results are substituted; SQL itself is never executed."""

    def __init__(self, functions=None):
        self.functions = dict(functions or frozen.PREVIOUS_FUNCTIONS)
        self.owner = (False,) * 5
        self.runtime_inherits = False
        self.statements = []
        self.function_reads = []
        self.reject_history = False

    def execute(self, statement):
        assert "FROM pg_roles" in str(statement)
        return SimpleNamespace(one_or_none=lambda: self.owner)

    def scalar(self, statement, parameters=None):
        if parameters is None:
            assert "pg_has_role" in str(statement)
            return self.runtime_inherits
        assert str(statement) == "SELECT pg_get_functiondef(to_regprocedure(:signature))"
        signature = parameters["signature"].removeprefix("public.")
        self.function_reads.append(signature)
        return self.functions.get(signature)

    def exec_driver_sql(self, statement, *, execution_options):
        assert execution_options == {"no_parameters": True}
        assert not text(statement)._bindparams
        self.statements.append(statement)
        if self.reject_history and "Publication business history is retained" in statement:
            raise RuntimeError("explicit retained-history IO substitute")


def bind(monkeypatch, connection):
    roles = []
    monkeypatch.setattr(
        migration,
        "op",
        SimpleNamespace(get_bind=lambda: connection, execute=lambda sql: roles.append(sql)),
    )
    return roles


def test_new_revision_is_a_single_successor_of_the_real_0776_chain():
    config = Config(str(SERVER / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER / "migrations"))
    config.set_main_option("path_separator", "os")
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("s0_0777")
    assert revision.down_revision == frozen.PREDECESSOR_HEAD == "s0_0776"
    assert scripts.get_revision(revision.down_revision) is not None
    assert migration.branch_labels is None and migration.depends_on is None


def test_historical_sql_is_literal_and_has_no_live_registry_or_orm_imports():
    path = SERVER / "migrations/schema_s0_0777.py"
    parsed = ast.parse(path.read_text())
    assert not any(
        isinstance(node, (ast.Import, ast.ImportFrom, ast.Call)) for node in ast.walk(parsed)
    )
    assignments = {
        node.targets[0].id: node.value
        for node in parsed.body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
    }
    assert ast.literal_eval(assignments["INSTALL_SQL"]) == frozen.INSTALL_SQL
    assert ast.literal_eval(assignments["UNINSTALL_SQL"]) == frozen.UNINSTALL_SQL
    assert len(frozen.STORAGE_SOURCE_SHA256) == len(frozen.PUBLIC_FUNCTION_CONTEXT_SHA256) == 64
    assert set(frozen.PREVIOUS_FUNCTIONS) == {NODES, SOURCES, ROWS}
    assert {
        signature: sha256(sql.encode()).hexdigest()
        for signature, sql in frozen.PREVIOUS_FUNCTIONS.items()
    } == frozen.PREVIOUS_FUNCTION_SHA256


def test_frozen_storage_preserves_the_reviewed_ddl_and_reciprocal_guard_contract():
    creates = [sql for sql in frozen.INSTALL_SQL if sql.lstrip().startswith("CREATE TABLE ")]
    assert [re.search(r"CREATE TABLE (\w+)", sql)[1] for sql in creates] == list(TABLES)
    ddl = creates[0]
    assert "proof_expires_at TIMESTAMP WITH TIME ZONE" in ddl
    assert "DEFERRABLE INITIALLY DEFERRED" in ddl
    assert "qualification'='unknown'" in ddl and "manufacturing_release'='null'::jsonb" in ddl
    assert any(
        "publication_proof_target AFTER UPDATE ON public.confirmations" in sql
        for sql in frozen.INSTALL_SQL
    )
    assert any(
        "publication_member_atom AFTER INSERT ON public.request_keys" in sql
        for sql in frozen.INSTALL_SQL
    )
    assert frozen.DOWNGRADE_SQL[: len(frozen.UNINSTALL_SQL)] == frozen.UNINSTALL_SQL
    assert frozen.UNINSTALL_SQL[0].startswith("LOCK TABLE ")
    assert "downgrade refused" in frozen.UNINSTALL_SQL[1]
    assert not any("CASCADE" in sql for sql in frozen.UNINSTALL_SQL)


def test_nullable_deadline_adds_only_publication_and_preserves_the_0770_t2_set():
    before, after = frozen.PREVIOUS_CONFIRMATION_DEADLINE, frozen.CONFIRMATION_DEADLINE
    addition = "'npi.manufacturing_baseline.publish',"
    assert after.count(addition) == 1 and after.replace(addition, "", 1) == before
    assert "'ai.skill.qualify'" in before and "'mcp.connector.allow'" in before
    assert before.startswith("expires_at IS NOT NULL OR operation IN (")
    assert frozen.DEADLINE_UPGRADE_SQL[-1].endswith(f"CHECK ({after})")
    assert frozen.DEADLINE_DOWNGRADE_SQL[-1].endswith(f"CHECK ({before})")


def test_lifecycle_enumeration_adds_exact_new_tables_and_keeps_old_frontier_and_native_behavior():
    before, after = frozen.PREVIOUS_FUNCTIONS[NODES], frozen.PUBLICATION_FUNCTIONS[NODES]
    addition = ",".join(repr(name) for name in TABLES)
    full = re.search(r"THEN ARRAY\[([^\]]+)\] ELSE ARRAY\[", before)
    assert full
    expected = before.replace(full[1], full[1] + "," + addition, 1)
    anchor = "IF identities IS NULL AND name<>ALL(ARRAY["
    expected = expected.replace(anchor, anchor + addition + ",", 1)
    assert after == expected
    # New types use their explicit typed edges, not the arbitrary legacy UUID path.
    assert f"name<>ALL(ARRAY[{addition}," in after
    assert after.partition("] ELSE ARRAY[")[2] == expected.partition("] ELSE ARRAY[")[2]


def test_lifecycle_new_source_and_host_edges_are_exact_and_do_not_scan_declarations():
    source_cases = (
        "  WHEN 'manufacturing_baseline_publications' THEN "
        "ARRAY['baseline_id','process_id','previous_id']\n"
        "  WHEN 'manufacturing_publication_currents' THEN ARRAY['version_id']\n"
        "  WHEN 'manufacturing_publication_documents' THEN ARRAY['document_id','process_id']\n"
    )
    row_cases = """  WHEN 'manufacturing_baseline_publications' THEN ARRAY['project_id']
  WHEN 'manufacturing_publication_currents' THEN ARRAY['series_id']
  WHEN 'manufacturing_publication_documents' THEN ARRAY['publication_id']
"""
    for signature, addition in ((SOURCES, source_cases), (ROWS, row_cases)):
        before, after = (
            frozen.PREVIOUS_FUNCTIONS[signature],
            frozen.PUBLICATION_FUNCTIONS[signature],
        )
        assert addition in after
        restored = after.replace(addition, "", 1)
        if signature == SOURCES:
            start = restored.index(" -- Publication's exact saved read set")
            end = restored.index(
                " -- These stored fields are validated Reference containers.", start
            )
            typed = restored[start:end]
            assert "payload->'required_source_read_set'" in typed
            assert "item->>'artifact_id'" in typed
            assert "payload->'body'" not in typed and "payload->'semantic'" not in typed
            assert "lifecycle_payload_links(payload)" not in typed
            restored = restored[:start] + restored[end:]
        assert restored == before
    for before in frozen.PREVIOUS_FUNCTIONS.values():
        assert before in frozen.DOWNGRADE_SQL


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_migration_runs_frozen_driver_sql_under_only_the_ordinary_owner(monkeypatch, direction):
    expected = frozen.PREVIOUS_FUNCTIONS if direction == "upgrade" else frozen.PUBLICATION_FUNCTIONS
    connection = OfflineConnection(expected)
    roles = bind(monkeypatch, connection)
    getattr(migration, direction)()
    assert roles == ["SET LOCAL ROLE pdos_next_owner", "SET LOCAL ROLE NONE"]
    assert connection.function_reads == list(expected)
    assert tuple(connection.statements) == (
        frozen.SCHEMA_SQL if direction == "upgrade" else frozen.DOWNGRADE_SQL
    )


@pytest.mark.parametrize(
    "fault", ["missing", "super", "bypass", "create_role", "create_db", "login", "runtime"]
)
def test_unsafe_or_runtime_inherited_owner_never_executes_ddl(monkeypatch, fault):
    connection = OfflineConnection()
    if fault == "missing":
        connection.owner = None
    elif fault == "runtime":
        connection.runtime_inherits = True
    else:
        names = ("super", "bypass", "create_role", "create_db", "login")
        connection.owner = tuple(name == fault for name in names)
    roles = bind(monkeypatch, connection)
    with pytest.raises(RuntimeError):
        migration.upgrade()
    assert not connection.statements and not roles and not connection.function_reads


def test_unreviewed_current_function_is_rejected_before_any_ddl(monkeypatch):
    connection = OfflineConnection()
    connection.functions[SOURCES] = connection.functions[SOURCES].replace(
        "RETURN links", "RETURN '{}'::uuid[]"
    )
    bind(monkeypatch, connection)
    with pytest.raises(RuntimeError, match="reviewed function"):
        migration.upgrade()
    assert not connection.statements


def test_retained_business_history_refusal_precedes_every_drop_and_function_restore(monkeypatch):
    connection = OfflineConnection(frozen.PUBLICATION_FUNCTIONS)
    connection.reject_history = True
    bind(monkeypatch, connection)
    with pytest.raises(RuntimeError, match="retained-history"):
        migration.downgrade()
    assert connection.statements == list(frozen.UNINSTALL_SQL[:2])
