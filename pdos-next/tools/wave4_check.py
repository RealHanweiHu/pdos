"""Wave4 checks on this task's guarded synthetic environment only."""

import json
import subprocess
import sys

from local_environment import ROOT, SERVER, environment, read_state, verified
from pdos_next.database import engine_for
from sqlalchemy import text
from workflow_environment import read_verified, state_environment

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave4-20261002"
REPORT.mkdir(parents=True, exist_ok=True)
state = verified(read_state())
workflows = read_verified()
env = {
    **environment(state),
    **state_environment(workflows),
    "CHECKPOINT_DATABASE_URL": workflows["checkpoint_url"],
}
action = sys.argv[1]


def run(argv, log):
    result = subprocess.run(argv, cwd=SERVER, env=env, stdout=log, stderr=subprocess.STDOUT)
    log.flush()
    if result.returncode:
        raise SystemExit(result.returncode)


if action in {"migrate", "resume-migrate"}:
    backup = ROOT / ".local/pre-wave4-next_0005.dump"
    with engine_for(state["admin_url"]).connect() as connection:
        head = connection.scalar(text("SELECT version_num FROM alembic_version"))
        new_table = connection.scalar(text("SELECT to_regclass('public.actual_configurations')"))
    if head != "next_0005" or new_table:
        raise RuntimeError("Roundtrip requires unchanged 0005 and no Wave4 objects/data")
    if action == "migrate":
        with backup.open("xb") as output:
            backup.chmod(0o600)
            run(
                [
                    "docker", "exec", state["container"], "pg_dump",
                    "-U", "postgres", "-d", "pdos_test", "-Fc",
                ],
                output,
            )
    elif not backup.is_file() or not backup.stat().st_size:
        raise RuntimeError("Resume requires retained pre-migration backup")
    with (REPORT / "migration-roundtrip.log").open("x" if action == "migrate" else "a") as log:
        for direction, target in [
            ("upgrade", "next_0006"),
            ("downgrade", "next_0005"),
            ("upgrade", "next_0006"),
        ]:
            run([sys.executable, "-m", "alembic", direction, target], log)
            log.write(f"{direction} {target}: passed\n")
        run([sys.executable, "-m", "alembic", "check"], log)
    print("Own marked database: retained backup, 0006 roundtrip and schema check passed")
elif action in {"schema", "check"}:
    paths = sys.argv[2:]
    name = "schema-match.log" if action == "schema" else (
        "scoped-tests.log" if paths else "postgres-tests.log"
    )
    if action == "check" and not paths:
        previous = json.loads(
            (REPORT.parent / "pdos-next-wave3-20261002/integrated-test-selection.json").read_text()
        )
        paths = sorted(set(previous) | {
            "tests/test_build_execution.py", "tests/test_build_comparison.py",
        })
        (REPORT / "integrated-test-selection.json").write_text(json.dumps(paths, indent=2) + "\n")
    argv = (
        [sys.executable, "-m", "alembic", "check"]
        if action == "schema" else [sys.executable, "-m", "pytest", "-q", *paths]
    )
    with (REPORT / name).open("w") as log:
        result = subprocess.run(argv, cwd=SERVER, env=env, stdout=log, stderr=subprocess.STDOUT)
    print((REPORT / name).read_text())
    raise SystemExit(result.returncode)
else:
    raise RuntimeError("Unknown Wave4 check action")
