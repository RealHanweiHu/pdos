"""Frozen monotonic policy migration, without a database connection."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from migrations import schema_s0_0779 as previous
from migrations import schema_s0_0781 as frozen
from migrations import schema_s0_0782 as deadline
from migrations.versions import s0_0781_release_policy as migration
from migrations.versions import s0_0782_release_decision_deadline as deadline_migration
from pdos_next.domain.release import policy_storage_schema as storage


def test_policy_has_one_monotonic_successor_and_exact_actual_lifecycle_predecessor():
    server = Path(__file__).resolve().parents[2]
    config = Config(str(server / "alembic.ini"))
    config.set_main_option("script_location", str(server / "migrations"))
    config.set_main_option("path_separator", "os")
    scripts = ScriptDirectory.from_config(config)
    assert len(scripts.get_heads()) == 1
    assert migration.down_revision == "s0_0780"
    assert scripts.get_revision("s0_0780").nextrev == frozenset({"s0_0781"})
    assert frozen.PREVIOUS_FUNCTIONS == previous.RELEASE_FUNCTIONS
    assert deadline_migration.down_revision == "s0_0781"
    assert scripts.get_revision("s0_0781").nextrev == frozenset({"s0_0782"})


def test_policy_frozen_sql_matches_reviewed_generator():
    up, down = storage.upgrade_sql(), storage.downgrade_sql()
    assert frozen.SCHEMA_SQL == (*up, *frozen.POLICY_FUNCTIONS.values())
    assert frozen.DOWNGRADE_SQL == (*down[:2], *frozen.PREVIOUS_FUNCTIONS.values(), *down[2:])


def test_lifecycle_edges_use_explicit_policy_references():
    nodes = frozen.POLICY_FUNCTIONS["m3_lifecycle_nodes(uuid,uuid,uuid[])"]
    for table in ("release_policy_facts", "release_policy_currents"):
        assert nodes.count("'" + table + "'") == 3
    links = frozen.POLICY_FUNCTIONS["m3_lifecycle_source_links(uuid,uuid,text,jsonb)"]
    assert "ARRAY['material','subject_config',key]" in links
    assert "payload->'reason'" not in links


def test_release_deadline_correction_adds_only_two_registered_t2_operations():
    assert deadline.REPLACEMENT_DEFINITION == deadline.PREVIOUS_DEFINITION.replace(
        "ARRAY[",
        "ARRAY['release.engineering.approve'::character varying, "
        "'release.manufacturing.approve'::character varying, ",
        1,
    )
    assert deadline.CONSTRAINT == "ck_confirmations_decision_deadline"
    assert "expires_at IS NOT NULL" in deadline.PREVIOUS_DEFINITION
    for name in ("release.engineering.approve", "release.manufacturing.approve"):
        assert name in deadline.APPLIED_DEFINITION
        assert name not in deadline.PREVIOUS_STATEMENT
