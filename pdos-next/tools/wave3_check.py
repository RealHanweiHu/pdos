"""Third candidate on the verified own test databases; earlier evidence is retained."""

import json
import subprocess
import sys

from local_environment import ROOT, SERVER, environment, read_state, verified
from pdos_next.database import engine_for
from sqlalchemy import text
from workflow_environment import read_verified, state_environment

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave3-20261002"
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
    backup = ROOT / ".local/pre-wave3-next_0004.dump"
    with engine_for(state["admin_url"]).connect() as connection:
        head = connection.scalar(text("SELECT version_num FROM alembic_version"))
        new_table = connection.scalar(text("SELECT to_regclass('public.bom_revisions')"))
    if head != "next_0004" or new_table:
        raise RuntimeError("Migration roundtrip requires unchanged 0004 and no Wave3 data")
    if action == "migrate":
        with backup.open("xb") as output:
            backup.chmod(0o600)
            run(
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
                output,
            )
    elif not backup.is_file() or not backup.stat().st_size:
        raise RuntimeError("Resume requires the retained pre-migration backup")
    with (REPORT / "migration-roundtrip.log").open("x" if action == "migrate" else "a") as log:
        for direction, target in [
            ("upgrade", "head"),
            ("downgrade", "next_0004"),
            ("upgrade", "head"),
        ]:
            run([sys.executable, "-m", "alembic", direction, target], log)
            log.write(f"{direction} {target}: passed\n")
        run([sys.executable, "-m", "alembic", "check"], log)
    print("Own marked database: backup, 0005 forward/back/forward and schema match passed")
elif action in {"schema", "check"}:
    name = (
        "schema-match.log"
        if action == "schema"
        else ("scoped-tests.log" if len(sys.argv) > 2 else "postgres-tests.log")
    )
    paths = sys.argv[2:]
    if action == "check" and not paths:
        # New independently owned draft packages may appear concurrently in this checkout.
        # Run the prior integrated candidate plus this slice, not their unfinished queues.
        previous = json.loads(
            (REPORT.parent / "pdos-next-wave2-20261002/candidate.json").read_text()
        )
        paths = sorted(
            {
                path.removeprefix("pdos-next/server/")
                for path in previous["source_files"]
                if path.startswith("pdos-next/server/tests/")
                and path.rsplit("/", 1)[-1].startswith("test_")
                and path.endswith(".py")
            }
            | {
                "tests/test_configurations.py",
                "tests/test_builds.py",
                "tests/test_build_readiness.py",
            }
        )
        (REPORT / "integrated-test-selection.json").write_text(json.dumps(paths, indent=2) + "\n")
    argv = (
        [sys.executable, "-m", "alembic", "check"]
        if action == "schema"
        else [sys.executable, "-m", "pytest", "-q", *paths]
    )
    with (REPORT / name).open("w") as log:
        result = subprocess.run(argv, cwd=SERVER, env=env, stdout=log, stderr=subprocess.STDOUT)
    print((REPORT / name).read_text())
    raise SystemExit(result.returncode)
else:
    raise RuntimeError("Unknown candidate action")
