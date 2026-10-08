"""Root-only exact guard repair; preserve every retained row and old assertion."""

import hashlib
import json
import subprocess
import sys

from local_environment import ROOT, SERVER, environment, read_state, verified
from pdos_next.database import engine_for
from sqlalchemy import text
from wave16_migrate import history

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave16-20261002"


def main():
    if sys.argv[1:] != ["run"]:
        raise RuntimeError("Explicit Root guard-repair checkpoint required")
    commands = subprocess.check_output(["ps", "-axo", "command"], text=True)
    if any(
        str(SERVER / ".venv/bin/python") in value
        and (" -m pytest " in value or " -m uvicorn " in value)
        for value in commands.splitlines()
    ):
        raise RuntimeError("Public API and PG checks must be stopped before repair")
    state = verified(read_state())
    if state["port"] != 62513 or state["marker"] != "916f950f-2d2b-405d-b809-c15db75dc20c":
        raise RuntimeError("Unexpected marked repair target")
    engine = engine_for(state["admin_url"])
    with engine.connect() as c:
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "next_0024"
        names = (
            c.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                    "AND tablename NOT IN ('alembic_version','environment_guard') "
                    "ORDER BY tablename"
                )
            )
            .scalars()
            .all()
        )
        assert len(names) == 106
        before = history(c, names)
        functions = c.execute(
            text("SELECT proname,prosrc FROM pg_proc WHERE pronamespace='public'::regnamespace")
        ).all()
        old = {name: hashlib.sha256(body.encode()).hexdigest() for name, body in functions}
    with (ROOT / ".local/pre-wave16-next_0024.dump").open("xb") as output:
        (ROOT / ".local/pre-wave16-next_0024.dump").chmod(0o600)
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
    for index, args in enumerate(
        (("upgrade", "next_0025"), ("downgrade", "next_0024"), ("upgrade", "next_0025"), ("check",))
    ):
        verified(read_state())
        with (REPORT / f"guard-repair-{index}.log").open("x") as output:
            result = subprocess.run(
                [sys.executable, "-m", "alembic", *args],
                cwd=SERVER,
                env=environment(state),
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        steps.append({"step": args, "exit_code": result.returncode})
        if result.returncode:
            raise RuntimeError("Guard repair checkpoint failed; raw diagnostics retained")
    verified(read_state())
    with engine.connect() as c:
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "next_0025"
        after = history(c, names)
        functions = c.execute(
            text("SELECT proname,prosrc FROM pg_proc WHERE pronamespace='public'::regnamespace")
        ).all()
        new = {name: hashlib.sha256(body.encode()).hexdigest() for name, body in functions}
    changed = [name for name in old if old[name] != new.get(name)]
    assert (
        before == after
        and changed == ["require_quality_followup_atom"]
        and old.keys() == new.keys()
    )
    with (REPORT / "guard-repair-result.json").open("x") as output:
        json.dump(
            {
                "passed": True,
                "head": "next_0025",
                "steps": steps,
                "retained_tables": len(names),
                "all_retained_rows_unchanged": before == after,
                "only_changed_function": changed,
                "before_function_sha256": old[changed[0]],
                "after_function_sha256": new[changed[0]],
                "no_data_restore_or_deletion": True,
                "scope": "Three extraction-parenthesis repairs only; original head24 retained",
            },
            output,
            indent=2,
        )
    print(
        "Head25 up/down/up/schema passed; all 106 table rows preserved; only exact guard repaired"
    )


if __name__ == "__main__":
    main()
