"""Frozen successor coverage; installed PostgreSQL is checked separately."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from migrations import schema_s0_0778 as previous
from migrations import schema_s0_0779 as frozen
from migrations import schema_s0_0780 as correction
from migrations.versions import s0_0779_release_packages as migration
from migrations.versions import s0_0780_release_read_set_grouping as repaired_migration
from pdos_next.domain.release import storage_schema


def test_single_monotonic_successor_keeps_actual_predecessor_definitions():
    server = Path(__file__).resolve().parents[2]
    config = Config(str(server / "alembic.ini"))
    config.set_main_option("script_location", str(server / "migrations"))
    config.set_main_option("path_separator", "os")
    scripts = ScriptDirectory.from_config(config)
    assert len(scripts.get_heads()) == 1
    assert migration.down_revision == "s0_0778"
    assert repaired_migration.down_revision == "s0_0779"
    assert scripts.get_revision("s0_0779").nextrev == frozenset({"s0_0780"})
    assert frozen.PREVIOUS_FUNCTIONS == previous.NATIVE_FUNCTIONS


def test_frozen_storage_matches_reviewed_generator_without_runtime_import_on_migration():
    # 0779 stays byte-for-byte frozen after installation. 0780 explicitly
    # corrects the two JSON operand groups rather than rewriting that history.
    generated = tuple(
        statement.replace(
            "(command->'source_read_set') @> v.required_source_read_set",
            "command->'source_read_set' @> v.required_source_read_set",
        ).replace(
            "v.required_source_read_set @> (command->'source_read_set')",
            "v.required_source_read_set @> command->'source_read_set'",
        )
        for statement in storage_schema.upgrade_sql()
    )
    assert tuple(frozen.SCHEMA_SQL[: len(generated)]) == generated
    assert tuple(frozen.SCHEMA_SQL[len(generated) :]) == tuple(frozen.RELEASE_FUNCTIONS.values())
    down = storage_schema.downgrade_sql()
    assert frozen.DOWNGRADE_SQL[:2] == down[:2]
    assert frozen.DOWNGRADE_SQL[2:5] == tuple(frozen.PREVIOUS_FUNCTIONS.values())
    assert frozen.DOWNGRADE_SQL[5:] == down[2:]


def test_correction_changes_only_the_two_operator_groups_and_preserves_history():
    original = correction.PREVIOUS_DEFINITION
    assert correction.REPLACEMENT_DEFINITION == original.replace(
        "command->'source_read_set' @> v.required_source_read_set",
        "(command->'source_read_set') @> v.required_source_read_set",
    ).replace(
        "v.required_source_read_set @> command->'source_read_set'",
        "v.required_source_read_set @> (command->'source_read_set')",
    )
    assert correction.FUNCTION == "assert_release_common(uuid,uuid,text)"
    assert "CREATE OR REPLACE FUNCTION" in correction.REPLACEMENT_DEFINITION


def test_lifecycle_uses_selected_fixed_object_refs_without_free_text_uuid_scans():
    nodes = frozen.RELEASE_FUNCTIONS["m3_lifecycle_nodes(uuid,uuid,uuid[])"]
    for table in ("release_packages", "release_package_currents", "release_decisions"):
        assert nodes.count("'" + table + "'") == 3
    sources = frozen.RELEASE_FUNCTIONS["m3_lifecycle_source_links(uuid,uuid,text,jsonb)"]
    assert "payload#>'{body,objects}'" in sources
    assert "container=item->'ref'" in sources
    assert "payload->'reason'" not in sources
