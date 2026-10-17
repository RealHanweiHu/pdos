"""Offline frozen native migration contracts; never an installed-PG claim."""

import ast
import re
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Engine

from migrations import schema_s0_0777 as predecessor
from migrations import schema_s0_0778 as frozen
from migrations.versions import s0_0778_native_pilot as migration
from pdos_next.domain.manufacturing_trials import native_storage_schema as storage

SERVER = Path(__file__).resolve().parents[2]
TABLES = ("native_pilot_runs", "native_pilot_currents", "native_pilot_observations")
NODES = "m3_lifecycle_nodes(uuid,uuid,uuid[])"
SOURCES = "m3_lifecycle_source_links(uuid,uuid,text,jsonb)"
ROWS = "m3_lifecycle_row_links(uuid,uuid,text,jsonb)"


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Native migration checks must never connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


class OfflineConnection:
    """Only role/function IO outcomes are replaced; actual SQL remains intact."""

    def __init__(self, functions=None):
        self.functions = dict(frozen.PREVIOUS_FUNCTIONS if functions is None else functions)
        self.owner = (False,) * 5
        self.runtime_inherits = False
        self.function_reads = []
        self.statements = []
        self.events = []
        self.reject_history = False

    def execute(self, statement):
        assert "FROM pg_roles" in str(statement)
        assert "rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,rolcanlogin" in str(statement)
        return SimpleNamespace(one_or_none=lambda: self.owner)

    def scalar(self, statement, parameters=None):
        if parameters is None:
            assert "pg_has_role(rolname,'pdos_next_owner','MEMBER')" in str(statement)
            return self.runtime_inherits
        assert str(statement) == "SELECT pg_get_functiondef(to_regprocedure(:signature))"
        signature = parameters["signature"].removeprefix("public.")
        self.function_reads.append(signature)
        self.events.append(("function", signature))
        return self.functions.get(signature)

    def exec_driver_sql(self, statement, *, execution_options):
        assert execution_options == {"no_parameters": True}
        assert not text(statement)._bindparams
        self.statements.append(statement)
        self.events.append(("sql", statement))
        if self.reject_history and "Native Pilot business history is retained" in statement:
            raise RuntimeError("explicit retained-history IO substitute")


def bind(monkeypatch, connection):
    roles = []

    def execute(sql):
        roles.append(sql)
        connection.events.append(("role", sql))

    monkeypatch.setattr(
        migration, "op", SimpleNamespace(get_bind=lambda: connection, execute=execute)
    )
    return roles


def test_native_revision_is_the_single_successor_of_the_frozen_0777_chain():
    config = Config(str(SERVER / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER / "migrations"))
    config.set_main_option("path_separator", "os")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_revision("s0_0778").down_revision == frozen.PREDECESSOR_HEAD == "s0_0777"
    assert scripts.get_revision("s0_0777").nextrev == frozenset({"s0_0778"})
    assert migration.branch_labels is None and migration.depends_on is None


def test_frozen_module_contains_literal_sql_and_the_actual_installer_source_sha():
    parsed = ast.parse((SERVER / "migrations/schema_s0_0778.py").read_text())
    assert not any(
        isinstance(node, (ast.Import, ast.ImportFrom, ast.Call)) for node in ast.walk(parsed)
    )
    assignments = {
        node.targets[0].id: node.value
        for node in parsed.body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
    }
    for name in ("INSTALL_SQL", "UNINSTALL_SQL", "PREVIOUS_FUNCTIONS", "NATIVE_FUNCTIONS"):
        assert ast.literal_eval(assignments[name]) == getattr(frozen, name)
    source = SERVER / "pdos_next/domain/manufacturing_trials/native_storage_schema.py"
    assert sha256(source.read_bytes()).hexdigest() == frozen.STORAGE_SOURCE_SHA256
    assert frozen.INSTALL_SQL == storage.install_sql()
    assert frozen.UNINSTALL_SQL == storage.uninstall_sql()
    assert frozen.PREVIOUS_FUNCTIONS == predecessor.PUBLICATION_FUNCTIONS
    assert set(frozen.NATIVE_FUNCTIONS) == {NODES, SOURCES, ROWS}
    assert frozen.SCHEMA_SQL == (*frozen.INSTALL_SQL, *frozen.NATIVE_FUNCTIONS.values())
    assert frozen.DOWNGRADE_SQL == (*frozen.UNINSTALL_SQL, *frozen.PREVIOUS_FUNCTIONS.values())


def test_frozen_ddl_installs_the_real_three_tables_before_the_current_observation_cycle():
    creates = [sql for sql in frozen.INSTALL_SQL if sql.lstrip().startswith("CREATE TABLE ")]
    assert [re.search(r"CREATE TABLE (\w+)", sql)[1] for sql in creates] == list(TABLES)
    last_table = max(frozen.INSTALL_SQL.index(sql) for sql in creates)
    cycle = next(
        sql
        for sql in frozen.INSTALL_SQL
        if "ADD CONSTRAINT fk_native_pilot_current_observation" in sql
    )
    assert frozen.INSTALL_SQL.index(cycle) > last_table
    assert "DEFERRABLE INITIALLY DEFERRED" in cycle
    assert frozen.UNINSTALL_SQL[0].startswith("LOCK TABLE ")
    assert "downgrade refused" in frozen.UNINSTALL_SQL[1]
    assert not any("CASCADE" in sql for sql in frozen.UNINSTALL_SQL)


def test_lifecycle_nodes_add_only_native_tables_to_full_and_targeted_typed_lookup():
    before, after = frozen.PREVIOUS_FUNCTIONS[NODES], frozen.NATIVE_FUNCTIONS[NODES]
    names = ",".join(repr(name) for name in TABLES)
    full = re.search(r"THEN ARRAY\[([^\]]+)\] ELSE ARRAY\[", before)
    assert full
    expected = before.replace(full[1], full[1] + "," + names, 1)
    frontier = "  'evidence_links','promotion_proofs'] END LOOP"
    assert frontier in expected
    expected = expected.replace(
        frontier, "  'evidence_links','promotion_proofs'," + names + "] END LOOP", 1
    )
    anchor = "IF identities IS NULL AND name<>ALL(ARRAY["
    expected = expected.replace(anchor, anchor + names + ",", 1)
    assert after == expected
    assert f"name<>ALL(ARRAY[{names}," in after


def test_lifecycle_native_links_use_real_columns_and_only_actual_owner_material_paths():
    sources = (
        "  WHEN 'native_pilot_runs' THEN ARRAY['build_id','lot_id','actual_configuration_id',"
        "'engineering_configuration_id','process_id','publication_id']\n"
        "  WHEN 'native_pilot_currents' THEN ARRAY['pilot_id','latest_observation_id']\n"
        "  WHEN 'native_pilot_observations' THEN ARRAY['pilot_id','previous_observation_id']\n"
    )
    rows = """  WHEN 'native_pilot_runs' THEN ARRAY['project_id']
  WHEN 'native_pilot_currents' THEN ARRAY['pilot_id']
  WHEN 'native_pilot_observations' THEN ARRAY['pilot_id']
"""
    for signature, addition in ((SOURCES, sources), (ROWS, rows)):
        before, after = frozen.PREVIOUS_FUNCTIONS[signature], frozen.NATIVE_FUNCTIONS[signature]
        assert addition in after
        restored = after.replace(addition, "", 1)
        if signature == SOURCES:
            expanded = (
                "IF table_name IN ('manufacturing_baseline_publications',"
                "'native_pilot_runs','native_pilot_observations') THEN"
            )
            assert expanded in restored
            restored = restored.replace(
                expanded, "IF table_name='manufacturing_baseline_publications' THEN", 1
            )
            start = restored.index(
                " IF table_name IN ('native_pilot_runs','native_pilot_observations') THEN"
            )
            end = restored.index(
                " -- These stored fields are validated Reference containers.", start
            )
            native = restored[start:end]
            assert set(re.findall(r"payload#>'\{([^}]+)\}'", native)) == {
                "material_snapshot,statistics,samples",
                "material_snapshot,statistics,issues",
                "material_snapshot,statistics,resource,fact",
            }
            assert "item->>'id'" in native
            assert "lifecycle_payload_links" not in native
            assert "jsonb_path_query" not in native
            assert "payload->'details'" not in native and "payload->'record'" not in native
            # The unchanged exact readset loop serves both native immutable rows.
            readset = restored[restored.index(" -- Publication's exact saved read set") : start]
            assert "payload->'required_source_read_set'" in readset
            assert "item->>'artifact_id'" in readset
            restored = restored[:start] + restored[end:]
        assert restored == before
    for before in frozen.PREVIOUS_FUNCTIONS.values():
        assert before in frozen.DOWNGRADE_SQL


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_migration_uses_only_the_ordinary_owner_and_exact_frozen_driver_order(
    monkeypatch, direction
):
    functions = frozen.PREVIOUS_FUNCTIONS if direction == "upgrade" else frozen.NATIVE_FUNCTIONS
    connection = OfflineConnection(functions)
    roles = bind(monkeypatch, connection)
    getattr(migration, direction)()
    assert roles == ["SET LOCAL ROLE pdos_next_owner", "SET LOCAL ROLE NONE"]
    assert connection.function_reads == list(functions)
    expected = frozen.SCHEMA_SQL if direction == "upgrade" else frozen.DOWNGRADE_SQL
    assert tuple(connection.statements) == expected
    assert connection.events == [
        ("role", "SET LOCAL ROLE pdos_next_owner"),
        *(("function", signature) for signature in functions),
        *(("sql", sql) for sql in expected),
        ("role", "SET LOCAL ROLE NONE"),
    ]


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
        connection.owner = tuple(
            name == fault for name in ("super", "bypass", "create_role", "create_db", "login")
        )
    roles = bind(monkeypatch, connection)
    with pytest.raises(RuntimeError):
        migration.upgrade()
    assert not connection.statements and not roles and not connection.function_reads


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_unreviewed_function_is_rejected_before_install_or_drop(monkeypatch, direction):
    expected = frozen.PREVIOUS_FUNCTIONS if direction == "upgrade" else frozen.NATIVE_FUNCTIONS
    connection = OfflineConnection(expected)
    connection.functions[SOURCES] += "\n-- unexpected function revision"
    roles = bind(monkeypatch, connection)
    with pytest.raises(RuntimeError, match="reviewed function"):
        getattr(migration, direction)()
    assert connection.statements == []
    assert roles == ["SET LOCAL ROLE pdos_next_owner"]


def test_retained_history_refusal_precedes_every_drop_and_lifecycle_restore(monkeypatch):
    connection = OfflineConnection(frozen.NATIVE_FUNCTIONS)
    connection.reject_history = True
    roles = bind(monkeypatch, connection)
    with pytest.raises(RuntimeError, match="retained-history"):
        migration.downgrade()
    assert connection.statements == list(frozen.UNINSTALL_SQL[:2])
    assert roles == ["SET LOCAL ROLE pdos_next_owner"]
