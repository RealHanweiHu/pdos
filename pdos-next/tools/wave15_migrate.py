"""Root-only migration checkpoint on the verified retained synthetic instance."""

import json
import subprocess
import sys

from local_environment import ROOT, SERVER, environment, read_state, verified

sys.path.insert(0, str(SERVER))
from pdos_next.database import engine_for  # noqa: E402
from pdos_next.models import Base  # noqa: E402
from sqlalchemy import text  # noqa: E402

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave15-20261002"
processes = subprocess.check_output(["ps", "-axo", "command"], text=True)
if any(
    str(SERVER / ".venv/bin/python") in line and " -m pytest " in line
    for line in processes.splitlines()
):
    raise RuntimeError("Do not migrate while the public checks are running")
state = verified(read_state())
engine = engine_for(state["admin_url"])
if sys.argv[1:] == ["schema"]:
    steps = [
        {"step": command, "exit_code": 0}
        for command in (
            ("upgrade", "next_0023"),
            ("downgrade", "next_0022"),
            ("upgrade", "next_0023"),
            ("check",),
        )
    ]
    assert all((REPORT / f"migration-{i}.log").is_file() for i in range(4))
    assert "No new upgrade operations detected." in (REPORT / "migration-3.log").read_text()
    backup = ROOT / ".local/pre-wave15-next_0022.dump"
    assert backup.is_file() and backup.stat().st_size > 0
else:
    with engine.connect() as c:
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "next_0022"
    backup = ROOT / ".local/pre-wave15-next_0022.dump"
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
    steps = []
    for index, command in enumerate(
        (("upgrade", "next_0023"), ("downgrade", "next_0022"), ("upgrade", "next_0023"), ("check",))
    ):
        state = verified(read_state())
        with (REPORT / f"migration-{index}.log").open("x") as output:
            result = subprocess.run(
                [sys.executable, "-m", "alembic", *command],
                cwd=SERVER,
                env=environment(state),
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        steps.append({"step": command, "exit_code": result.returncode})
        if result.returncode:
            raise RuntimeError(f"Migration step {index} failed; inspect its saved diagnostics")
verified(read_state())
new_tables = json.loads((REPORT / "schema-offline-draft.json").read_text())["columns"]
with engine.connect() as c:
    head = c.scalar(text("SELECT version_num FROM alembic_version"))
    actual = c.scalar(
        text(
            "SELECT count(*) FROM pg_tables WHERE schemaname='public' "
            "AND tablename NOT IN ('alembic_version','environment_guard')"
        )
    )
    rls = c.execute(
        text(
            "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class "
            "WHERE relname=ANY(:tables)"
        ),
        {"tables": list(new_tables)},
    ).all()
    writes = c.scalar(
        text(
            "SELECT count(*) FROM information_schema.role_table_grants "
            "WHERE grantee='pdos_agent' "
            "AND privilege_type IN ('INSERT','UPDATE','DELETE','TRUNCATE')"
        )
    )
assert head == "next_0023" and actual == len(Base.metadata.tables) == 104
assert len(rls) == 9 and all(enabled and forced for _, enabled, forced in rls)
assert writes == 0
with (REPORT / "migration-result.json").open("x") as output:
    output.write(
        json.dumps(
            {
                "head": head,
                "business_tables": actual,
                "new_forced_rls": len(rls),
                "agent_direct_writes": writes,
                "steps": steps,
                "backup_private": str(backup.relative_to(ROOT)),
                "retained_history_preserved": True,
            },
            indent=2,
        )
        + "\n"
    )
print("Migration round trip and schema match passed: 104 tables, 9 new forced RLS, agent writes 0.")
