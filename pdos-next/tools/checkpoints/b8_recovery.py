"""Restore the final schema while a real synthetic configuration/handoff chain exists.

Only the root invokes this in B8's explicitly marked isolated database. Business
rows and their immutable proofs restore; metadata events do not start workflows.
"""

# ruff: noqa: F401,F811 -- explicit imports register the existing fixture tree
import json

import pytest
import s0_b8_environment as checkpoint
import s0_b8_restore as recovery
from alembic.config import Config
from alembic.script import ScriptDirectory
from conftest import setup
from test_project_first_plan import post
from test_resource_dependency_execution import (
    engines,
    known_configuration,
    launch_work,
    operational_work,
    ready_work,
)
from verification_launch import fixtures as launch

CHAIN_TABLES = (
    "engineering_configurations",
    "process_revisions",
    "build_starts",
    "verification_handoff_facts",
    "verification_run_versions",
    "test_resource_reservations",
)


@pytest.mark.parametrize(
    "launch_work", [{"window_minutes": 45, "fact_minutes": 60}], indirect=True
)
def test_final_restore_keeps_configuration_to_handoff_and_started_run(launch_work, monkeypatch):
    config = Config(str(checkpoint.local.SERVER / "alembic.ini"))
    config.set_main_option("script_location", str(checkpoint.local.SERVER / "migrations"))
    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1
    expected_head = heads[0]
    work = launch_work
    receipt, prepared = launch.started(work, monkeypatch)
    before_view = launch.listing(work)
    assert launch.fixed_run(work, before_view)["status"] == "running"
    original_report = checkpoint.REPORT
    final_report = original_report / f"{expected_head.removeprefix('s0_')}-final-checkpoint"
    final_report.mkdir(parents=True, exist_ok=True)
    checkpoint.REPORT = final_report
    try:
        current = checkpoint.state()
        before = recovery.snapshot(current)
        assert before["alembic_version"]["rows"] == 1
        assert all(before[table]["rows"] > 0 for table in CHAIN_TABLES)
        recovery.run()
        evidence = json.loads((final_report / "backup-restore.json").read_text())
        assert evidence["head"] == expected_head
        assert all(
            evidence["table_fingerprints_restored"][table]["rows"] > 0 for table in CHAIN_TABLES
        )
        # Actual public reads still verify source bytes, current permission,
        # qualification and the exact saved resource proof after the restoration.
        before_replay = recovery.snapshot(current)
        after_view = launch.listing(work)
        assert launch.fixed_run(work, after_view)["status"] == "running"
        assert any(
            row["id"] == str(work.test_fact_id)
            and row["current"] is True
            and row["source_status"] == "current"
            for row in after_view["resource_facts"]
        )
        replay = post(work.quality, prepared)
        assert replay.status_code == 200 and replay.json()["id"] == receipt["id"], replay.text
        assert recovery.snapshot(current) == before_replay
        with (final_report / "configuration-handoff-recovery.json").open("x") as stream:
            json.dump(
                {
                    "head": evidence["head"],
                    "database": "pdos_test",
                    "port": current["port"],
                    "marker": current["marker"],
                    "synthetic_only": True,
                    "llm_calls": 0,
                    "chain_tables": {table: before[table] for table in CHAIN_TABLES},
                    "public_read_after_restore": True,
                    "original_start_receipt_recovered": True,
                    "read_and_replay_added_no_effects": True,
                    "source_store": (
                        "Existing synthetic source bytes retained and re-read; DB restore only"
                    ),
                    "event_scope": evidence["event_scope"],
                    "workflow_starts": 0,
                    "external_sends": 0,
                },
                stream,
                indent=2,
            )
            stream.write("\n")
    finally:
        checkpoint.REPORT = original_report
