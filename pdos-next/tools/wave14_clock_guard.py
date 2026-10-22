"""Root-owned monotonic clock repair; run only after isolated public PG checks stop."""

import copy
import json
import subprocess
import sys
from uuid import UUID

from local_environment import ROOT, SERVER, environment, read_state, verified

sys.path.insert(0, str(SERVER))
from pdos_next.database import engine_for  # noqa: E402
from pdos_next.domain.verification_front.models import FormalVerificationRequest  # noqa: E402
from pdos_next.service import digest  # noqa: E402
from sqlalchemy import insert, select, text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave14-20261002"
processes = subprocess.check_output(["ps", "-axo", "command"], text=True)
if any(str(SERVER / ".venv/bin/python") in line and " -m pytest " in line
       for line in processes.splitlines()):
    raise RuntimeError("Public PostgreSQL checks still running; do not migrate concurrently")
state = verified(read_state())
engine = engine_for(state["admin_url"])
with engine.connect() as connection:
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "next_0021"

backup = ROOT / ".local/pre-wave14-next_0021-before-clock-guard.dump"
assert not backup.exists()
with backup.open("xb") as output:
    backup.chmod(0o600)
    subprocess.run(
        ["docker", "exec", state["container"], "pg_dump", "-U", "postgres",
         "-d", "pdos_test", "-Fc"],
        stdout=output, check=True,
    )

for index, command in enumerate((
    ["upgrade", "next_0022"], ["downgrade", "next_0021"],
    ["upgrade", "next_0022"], ["check"],
)):
    verified(read_state())
    with (REPORT / f"clock-guard-migration-{index}.log").open("x") as output:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *command], cwd=SERVER,
            env=environment(state), stdout=output, stderr=subprocess.STDOUT,
        )
    if result.returncode:
        raise RuntimeError(f"Clock migration step {index} failed; inspect saved diagnostics")

verified(read_state())
cases = []
with Session(engine) as session, session.begin():
    row = session.scalar(select(FormalVerificationRequest).where(
        FormalVerificationRequest.request_id == UUID("8ab2f1ad-716d-404b-8a69-013c2a2015d7"),
        FormalVerificationRequest.operation == "test.run.start",
    ))
    assert row is not None
    before = row.snapshot_sha256
    original = {column.name: copy.deepcopy(getattr(row, column.name))
                for column in FormalVerificationRequest.__table__.columns}
    for name in ("preliminary_result", "final_result", "disposed", "missing_preliminary"):
        values = copy.deepcopy(original)
        timeline = values["request_snapshot"]["timeline"]
        if name == "missing_preliminary":
            timeline.pop("preliminary_result")
        else:
            timeline[name] = copy.deepcopy(timeline["actual_start"])
        values["snapshot_sha256"] = digest(values["request_snapshot"])
        try:
            with session.begin_nested():
                session.execute(insert(FormalVerificationRequest).values(**values))
        except IntegrityError as error:
            constraint = error.orig.diag.constraint_name
            assert constraint == "ck_test_start_no_result_clocks", constraint
            cases.append({"case": name, "constraint": constraint, "rolled_back": True})
        else:
            raise AssertionError("Forged clock was accepted")
    session.expire(row)
    assert row.snapshot_sha256 == before
    assert session.scalar(text("SELECT version_num FROM alembic_version")) == "next_0022"

(REPORT / "clock-guard-migration-result.json").write_text(json.dumps({
    "head": "next_0022", "roundtrip": "0021 -> 0022 -> 0021 -> 0022",
    "schema_check": "passed", "backup_private": str(backup.relative_to(ROOT)),
    "actual_constraint_cases": cases, "original_start_sha256_unchanged": True,
    "nature": ("Owned isolated target; duplicate existing Start insertion is rejected at "
               "CHECK before uniqueness; savepoint rolls each probe back."),
}, indent=2) + "\n")
print("Clock guard migration roundtrip, schema and four rollback-only constraint probes passed.")
