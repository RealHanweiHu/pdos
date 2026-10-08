"""Run one candidate against explicitly verified task-owned local databases."""

import subprocess
import sys

from local_environment import ROOT, SERVER, environment, read_state, verified
from workflow_environment import read_verified, state_environment

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave1-20261002"
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


if action == "migrate":
    backup = ROOT / ".local/pre-wave1-next_0002.dump"
    if backup.exists():
        raise RuntimeError("Existing migration backup retained; do not overwrite")
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
    with (REPORT / "migration-roundtrip.log").open("x") as log:
        for direction, target in [
            ("upgrade", "head"),
            ("downgrade", "next_0002"),
            ("upgrade", "head"),
        ]:
            run([sys.executable, "-m", "alembic", direction, target], log)
            log.write(f"{direction} {target}: passed\n")
        run([sys.executable, "-m", "alembic", "check"], log)
    print("Independent marked database: backup, 0003 forward/back/forward and schema match passed")
elif action == "schema":
    with (REPORT / "schema-match.log").open("w") as log:
        run([sys.executable, "-m", "alembic", "check"], log)
    print((REPORT / "schema-match.log").read_text())
elif action == "check":
    with (REPORT / "postgres-tests.log").open("w") as log:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=SERVER,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    print((REPORT / "postgres-tests.log").read_text())
    raise SystemExit(result.returncode)
else:
    raise RuntimeError("Unknown candidate action")
