"""Retained initial Root attempt; final recovery is in the Wave25 checkpoint.

The old ordinal-order predicate below belongs to the preserved failed attempt.
Use migration-final-checkpoint-v1.json for the adopted named-schema verification.
"""

# ruff: noqa: E501 -- retain exact SQL statements from the recorded attempt.

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime

from local_environment import ROOT, SERVER, environment
from pdos_next.database import engine_for
from pdos_next.lifecycle_catalog import COVERED_COLUMNS
from pdos_next.models import Base
from sqlalchemy import text
from wave16_migrate import history
from wave17_ddl_rollback_observation import catalog
from wave17_migrate import target

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave25-20261003"
NEW = (
    "change_order_records",
    "change_approval_records",
    "change_implementation_captures",
    "change_implementation_records",
    "controlled_change_policy_facts",
    "controlled_change_policy_currents",
    "controlled_change_selection_facts",
    "controlled_change_selection_currents",
    "manufacturing_preparation_versions",
    "manufacturing_preparation_currents",
    "manufacturing_baseline_document_links",
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stop_verified(pid, suffix):
    command = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="], text=True).strip()
    expected = str(SERVER / ".venv/bin/python") + " -m " + suffix
    if not command.startswith(expected):
        raise RuntimeError("Runtime process identity changed")
    cwd = subprocess.check_output(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], text=True)
    if f"n{SERVER}\n" not in cwd:
        raise RuntimeError("Runtime working directory changed")
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        probe = subprocess.run(
            ["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True
        )
        if probe.returncode or not probe.stdout.strip() or probe.stdout.strip().startswith("Z"):
            return
        time.sleep(0.1)
    raise RuntimeError("Verified process did not stop; migration refused")


def main():
    if sys.argv[1:] != ["run"]:
        raise RuntimeError("Explicit Root migration checkpoint required")
    out = REPORT / "migration-roundtrip-v1.json"
    if out.exists():
        raise RuntimeError("Original checkpoint evidence must not be overwritten")
    state = target()
    source = json.loads((REPORT / "actual-runtime-source-v1.json").read_text())["files"]
    frozen = {
        **source,
        **json.loads((REPORT / "migration-allocation-v1.json").read_text())["migrations"],
    }
    assert all(sha(ROOT / p) == v for p, v in frozen.items())
    for name in ("wave22-shared-retest.json", "wave22-followup-control.json"):
        requests = json.loads((ROOT / ".local" / name).read_text())["requests"]
        if any(v.get("state") not in {"saved", "rejected"} for v in requests.values()):
            raise RuntimeError("Pending original request must be resolved before runtime reload")
    engine = engine_for(state["admin_url"])
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "next_0026"
    result = {
        "status": "RUNNING",
        "marker": state["marker"],
        "target": "127.0.0.1:62513/pdos_test",
        "steps": [],
        "business_fact_writes": 0,
        "model_calls": 0,
        "source_sha256": frozen,
    }
    try:
        stop_verified(51981, "uvicorn pdos_next.asgi:app")
        stop_verified(86504, "pdos_next.workflows.worker")
        result["verified_runtime_paused"] = [51981, 86504]
        with engine.connect() as connection:
            names = (
                connection.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT IN ('alembic_version','environment_guard') ORDER BY tablename"
                    )
                )
                .scalars()
                .all()
            )
            assert len(names) == 111 and not set(NEW).intersection(names)
            before = history(connection, names)
            before_catalog = catalog(connection)
        with (REPORT / "migration-retained-before-v1.json").open("x") as output:
            json.dump(before, output, indent=2)
            output.write("\n")
        backup = ROOT / ".local/pre-wave25-next_0026.dump"
        with backup.open("xb") as output:
            backup.chmod(0o600)
            subprocess.run(
                [
                    "docker",
                    "exec",
                    state["container"],
                    "pg_dump",
                    "-U",
                    "postgres",
                    "-d",
                    "pdos_test",
                    "-Fc",
                ],
                stdout=output,
                check=True,
            )
        result["backup"] = {
            "bytes": backup.stat().st_size,
            "sha256": sha(backup),
            "mode": "0600",
            "path": str(backup),
        }
        for i, (args, expected) in enumerate(
            (
                (("upgrade", "next_0027"), "next_0027"),
                (("upgrade", "next_0028"), "next_0028"),
                (("downgrade", "next_0026"), "next_0026"),
                (("upgrade", "next_0028"), "next_0028"),
                (("check",), "next_0028"),
            )
        ):
            state = target()
            assert all(sha(ROOT / p) == v for p, v in frozen.items())
            log = REPORT / f"migration-step-{i}-v1.log"
            with log.open("x") as output:
                process = subprocess.run(
                    [sys.executable, "-m", "alembic", *args],
                    cwd=SERVER,
                    env=environment(state),
                    stdout=output,
                    stderr=subprocess.STDOUT,
                )
            result["steps"].append(
                {
                    "args": args,
                    "exit_code": process.returncode,
                    "log": log.name,
                    "log_sha256": sha(log),
                }
            )
            if process.returncode:
                raise RuntimeError(f"Migration step {i} failed; raw diagnostics retained")
            with engine.connect() as connection:
                assert (
                    connection.scalar(text("SELECT version_num FROM alembic_version")) == expected
                )
                assert history(connection, names) == before
                if expected == "next_0026":
                    assert catalog(connection) == before_catalog
                    result["downgrade_original_catalog_exact"] = True
        with engine.connect() as connection:
            actual = connection.execute(
                text(
                    "SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='public' AND table_name NOT IN ('alembic_version','environment_guard') ORDER BY table_name,ordinal_position"
                )
            ).all()
            columns = {}
            for name, column in actual:
                columns.setdefault(name, []).append(column)
            assert set(columns) == set(Base.metadata.tables) == set(COVERED_COLUMNS)
            assert len(columns) == 122
            for name, table in Base.metadata.tables.items():
                assert tuple(table.c.keys()) == tuple(columns[name]) == COVERED_COLUMNS[name]
                for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                    assert not connection.scalar(
                        text("SELECT has_table_privilege('pdos_agent',:name,:privilege)"),
                        {"name": name, "privilege": privilege},
                    )
            for name in NEW:
                assert connection.scalar(
                    text(
                        "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid=to_regclass(:name)"
                    ),
                    {"name": name},
                )
                assert (
                    connection.scalar(
                        text(
                            "SELECT count(*) FROM pg_trigger WHERE tgrelid=to_regclass(:name) AND tgname='lifecycle_reference' AND tgenabled='O'"
                        ),
                        {"name": name},
                    )
                    == 1
                )
                assert connection.scalar(text(f'SELECT count(*) FROM "{name}"')) == 0
        result.update(
            status="PASS",
            head="next_0028",
            public_tables=122,
            retained_tables=111,
            all_retained_rows_unchanged=True,
            runtime_catalog_database_columns_match=True,
            new_tables_force_rls=11,
            all_registered_tables_agent_direct_writes=0,
            formal_approval_or_manufacturing_fact_published=False,
        )
    except Exception as error:
        result.update(status="FAIL", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        result["source_stable"] = all(sha(ROOT / p) == v for p, v in frozen.items())
        result["observed_at"] = datetime.now(UTC).isoformat()
        with out.open("x") as output:
            json.dump(result, output, indent=2)
            output.write("\n")
    print(
        "Actual 26→27→28→26→28/schema: PASS; all 111 retained tables preserved; 122 registered tables."
    )


if __name__ == "__main__":
    main()
