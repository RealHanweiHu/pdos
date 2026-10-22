"""Second candidate only; preserve earlier evidence and private migration backup."""

import subprocess
import sys

from local_environment import ROOT, SERVER, environment, read_state, verified
from workflow_environment import read_verified, state_environment

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave2-20261002"
REPORT.mkdir(parents=True, exist_ok=True)
state = verified(read_state())
workflows = read_verified()
env = {**environment(state), **state_environment(workflows),
       "CHECKPOINT_DATABASE_URL": workflows["checkpoint_url"]}
action = sys.argv[1]


def run(argv, log):
    result = subprocess.run(argv, cwd=SERVER, env=env, stdout=log, stderr=subprocess.STDOUT)
    log.flush()
    if result.returncode:
        raise SystemExit(result.returncode)


if action in {"migrate", "resume-migrate"}:
    backup = ROOT / ".local/pre-wave2-next_0003.dump"
    if backup.exists() and action == "migrate":
        raise RuntimeError("Existing migration backup retained; do not overwrite")
    if action == "migrate":
        with backup.open("xb") as output:
            backup.chmod(0o600)
            run(["docker", "exec", state["container"], "pg_dump", "-U", "postgres",
                 "-d", "pdos_test", "-Fc"], output)
    else:
        from pdos_next.database import engine_for
        from sqlalchemy import text

        with engine_for(state["admin_url"]).connect() as connection:
            head = connection.scalar(text("SELECT version_num FROM alembic_version"))
            exists = connection.scalar(text("SELECT to_regclass('public.projects')"))
        if not backup.exists() or head != "next_0003" or exists:
            raise RuntimeError("Resume requires retained pre-backup and rolled-back 0003 schema")
    with (REPORT / "migration-roundtrip.log").open("x" if action == "migrate" else "a") as log:
        for direction, target in [("upgrade", "head"), ("downgrade", "next_0003"),
                                  ("upgrade", "head")]:
            run([sys.executable, "-m", "alembic", direction, target], log)
            log.write(f"{direction} {target}: passed\n")
        run([sys.executable, "-m", "alembic", "check"], log)
    print("Own marked database: backup, 0004 forward/back/forward and schema match passed")
elif action in {"schema", "check"}:
    name = "schema-match.log" if action == "schema" else "postgres-tests.log"
    argv = ([sys.executable, "-m", "alembic", "check"] if action == "schema"
            else [sys.executable, "-m", "pytest", "-q", *sys.argv[2:]])
    with (REPORT / name).open("w") as log:
        result = subprocess.run(argv, cwd=SERVER, env=env, stdout=log, stderr=subprocess.STDOUT)
    print((REPORT / name).read_text())
    raise SystemExit(result.returncode)
else:
    raise RuntimeError("Unknown candidate action")
