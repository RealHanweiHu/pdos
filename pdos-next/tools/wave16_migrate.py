"""Root-only, empty-new-tables migration checkpoint on the retained test target."""

import hashlib
import json
import subprocess
import sys

from local_environment import ROOT, SERVER, environment, read_state, verified

sys.path.insert(0, str(SERVER))
from pdos_next.database import engine_for  # noqa: E402
from pdos_next.models import Base  # noqa: E402
from sqlalchemy import text  # noqa: E402

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave16-20261002"
MARKER = "916f950f-2d2b-405d-b809-c15db75dc20c"
TABLES = ("capa_remediation_links", "capa_verification_evidence")


def target():
    state = verified(read_state())
    if state["port"] != 62513 or state["marker"] != MARKER:
        raise RuntimeError("Wave16 requires the verified retained synthetic target")
    return state


def history(connection, names):
    # Database names come only from the actual fixed public catalog, not input.
    values = {}
    for name in names:
        keys = list(Base.metadata.tables[name].primary_key.columns)
        if not keys:
            raise RuntimeError("Retained history requires the real primary key")
        ordering = ", ".join(f'"{column.name}"' for column in keys)
        rows = connection.execute(
            text(f'SELECT to_jsonb(t)::text FROM "{name}" t ORDER BY {ordering}')
        ).scalars()
        digest = hashlib.sha256()
        count = 0
        for row in rows:
            digest.update(row.encode())
            digest.update(b"\n")
            count += 1
        values[name] = {"rows": count, "sha256": digest.hexdigest()}
    return values


def main():
    if sys.argv[1:] not in (["run"], ["retry"]):
        raise RuntimeError("Explicit Root migration checkpoint required")
    retry = sys.argv[1:] == ["retry"]
    tag = "-recovery1" if retry else ""
    processes = subprocess.check_output(["ps", "-axo", "command"], text=True)
    if any(
        str(SERVER / ".venv/bin/python") in line and " -m pytest " in line
        for line in processes.splitlines()
    ):
        raise RuntimeError("Public tests must finish before migration")
    state = target()
    engine = engine_for(state["admin_url"])
    with engine.connect() as connection:
        if connection.scalar(text("SELECT version_num FROM alembic_version")) != "next_0023":
            raise RuntimeError("Expected the actually verified next_0023 predecessor")
        names = (
            connection.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                    "AND tablename NOT IN ('alembic_version','environment_guard') "
                    "ORDER BY tablename"
                )
            )
            .scalars()
            .all()
        )
        if len(names) != 104 or set(names) & set(TABLES):
            raise RuntimeError("Unexpected predecessor table set")
        before = (
            json.loads((REPORT / "migration-retained-before.json").read_text())
            if retry
            else history(connection, names)
        )
        if set(before) != set(names):
            raise RuntimeError("Retained baseline does not match the actual predecessor tables")
        old_guard = connection.scalar(
            text("SELECT pg_get_functiondef('require_quality_change_atom()'::regprocedure)")
        )
    backup = ROOT / ".local/pre-wave16-next_0023.dump"
    if retry:
        if not backup.is_file() or not backup.stat().st_size or backup.stat().st_mode & 0o077:
            raise RuntimeError("Original private backup must be retained for recovery")
    else:
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
        with (REPORT / "migration-retained-before.json").open("x") as output:
            json.dump(before, output, indent=2)
            output.write("\n")
    steps = []
    for index, command in enumerate(
        (("upgrade", "next_0024"), ("downgrade", "next_0023"), ("upgrade", "next_0024"), ("check",))
    ):
        state = target()
        with (REPORT / f"migration{tag}-{index}.log").open("x") as output:
            result = subprocess.run(
                [sys.executable, "-m", "alembic", *command],
                cwd=SERVER,
                env=environment(state),
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        steps.append(
            {"step": command, "exit_code": result.returncode, "log": f"migration{tag}-{index}.log"}
        )
        if result.returncode:
            raise RuntimeError(f"Migration step {index} failed; saved diagnostics retained")
    target()
    with engine.connect() as connection:
        head = connection.scalar(text("SELECT version_num FROM alembic_version"))
        actual = connection.scalar(
            text(
                "SELECT count(*) FROM pg_tables WHERE schemaname='public' "
                "AND tablename NOT IN ('alembic_version','environment_guard')"
            )
        )
        after = history(connection, names)
        guard = connection.scalar(
            text("SELECT pg_get_functiondef('require_quality_change_atom()'::regprocedure)")
        )
        rls = connection.execute(
            text(
                "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class "
                "WHERE relname=ANY(:tables)"
            ),
            {"tables": list(TABLES)},
        ).all()
        agent_writes = connection.scalar(
            text(
                "SELECT count(*) FROM information_schema.role_table_grants "
                "WHERE grantee='pdos_agent' "
                "AND privilege_type IN ('INSERT','UPDATE','DELETE','TRUNCATE')"
            )
        )
        candidate_permissions = (
            connection.execute(
                text(
                    "SELECT privilege_type FROM information_schema.role_table_grants "
                    "WHERE grantee='pdos_next_app' AND table_name='capa_verification_evidence' "
                    "ORDER BY privilege_type"
                )
            )
            .scalars()
            .all()
        )
        links_permissions = (
            connection.execute(
                text(
                    "SELECT privilege_type FROM information_schema.role_table_grants "
                    "WHERE grantee='pdos_next_app' AND table_name='capa_remediation_links' "
                    "ORDER BY privilege_type"
                )
            )
            .scalars()
            .all()
        )
    passed = (
        head == "next_0024"
        and actual == len(Base.metadata.tables) == 106
        and before == after
        and old_guard == guard
        and agent_writes == 0
        and len(rls) == 2
        and all(enabled and forced for _, enabled, forced in rls)
        and candidate_permissions == ["SELECT"]
        and links_permissions == ["INSERT", "SELECT"]
    )
    with (REPORT / "migration-result.json").open("x") as output:
        json.dump(
            {
                "passed": passed,
                "head": head,
                "business_tables": actual,
                "metadata_tables": len(Base.metadata.tables),
                "steps": steps,
                "retained_tables": len(before),
                "retained_rows_unchanged": before == after,
                "old_quality_merge_change_guard_unchanged": old_guard == guard,
                "new_forced_rls": len(rls),
                "agent_direct_writes": agent_writes,
                "candidate_app_permissions": candidate_permissions,
                "link_app_permissions": links_permissions,
                "backup_private": str(backup.relative_to(ROOT)),
                "after": after,
            },
            output,
            indent=2,
        )
        output.write("\n")
    if not passed:
        raise RuntimeError("Migration/schema/retention checkpoint failed; inspect saved evidence")
    print("Wave16 migration round trip passed; 106 tables, two forced RLS, retained rows unchanged")


if __name__ == "__main__":
    main()
