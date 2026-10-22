"""B8 owns only its separately labelled empty-chain/restore/browser fixture."""

import argparse
import json
import subprocess
import sys

import local_environment as local
from sqlalchemy import text

REPORT = local.ROOT.parent / "docs/reports/evidence/pdos-next-s0-20261008/final-candidate"
local.STATE = local.ROOT / ".local/s0-b8-runtime.json"
local.REPORT = REPORT / "environment"


def state():
    current = local.verified(local.read_state())
    if current.get("purpose") != "s0-b8-checkpoint":
        raise RuntimeError("B8 requires its own explicitly labelled fixture")
    return current


def create():
    if local.STATE.exists():
        state()
        return
    try:
        local.create()
    finally:
        if local.STATE.exists():
            current = local.verified(local.read_state())
            current["purpose"] = "s0-b8-checkpoint"
            local.save(current)
    current = local.verified(local.read_state())
    current["purpose"] = "s0-b8-checkpoint"
    local.save(current)
    audit()


def resume_empty():
    current = state()
    from pdos_next.database import engine_for

    with engine_for(current["admin_url"]).connect() as connection:
        if connection.scalar(text("SELECT count(*) FROM principals")) != 0:
            raise RuntimeError("Empty-chain recovery must not downgrade seeded business rows")
    with (REPORT / "empty-chain-fixed-roundtrip.log").open("w") as log:
        for direction, target in (("downgrade", "base"), ("upgrade", "head")):
            subprocess.run(
                [sys.executable, "-m", "alembic", direction, target],
                cwd=local.SERVER,
                env=local.environment(current),
                stdout=log,
                stderr=log,
                check=True,
            )
            log.write(f"{direction} {target}: passed\n")
    local.seed(current)
    audit()


def audit(current=None, *, destination=None):
    current = state() if current is None else local.verified(current)
    from pdos_next.database import engine_for

    engine = engine_for(current["admin_url"])
    with engine.connect() as connection:
        version = connection.scalar(text("SELECT version_num FROM alembic_version"))
        functions = connection.execute(
            text(
                "SELECT p.oid::regprocedure::text,r.rolname,r.rolsuper,r.rolbypassrls,p.proconfig "
                "FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner "
                "WHERE p.pronamespace='public'::regnamespace AND p.prosecdef ORDER BY 1"
            )
        ).all()
        tables = connection.execute(
            text(
                "SELECT c.relname,r.rolname,c.relrowsecurity,c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_roles r ON r.oid=c.relowner "
                "WHERE c.relnamespace='public'::regnamespace AND c.relkind IN ('r','p') "
                "AND c.relname NOT IN ('environment_guard','alembic_version') ORDER BY c.relname"
            )
        ).all()
        assert all(
            r[1] == "pdos_next_owner"
            and not r[2]
            and not r[3]
            and r[4] == ["search_path=pg_catalog, public, pg_temp"]
            for r in functions
        )
        assert all(r[1] == "pdos_next_owner" for r in tables)
        assert {r[0] for r in tables if not r[2] or not r[3]} == {"login_sessions"}
        login_privileges = connection.execute(
            text(
                "SELECT r.rolname,has_table_privilege(r.rolname,'login_sessions','SELECT'),"
                "has_table_privilege(r.rolname,'login_sessions','INSERT'),"
                "has_table_privilege(r.rolname,'login_sessions','UPDATE'),"
                "has_table_privilege(r.rolname,'login_sessions','DELETE') FROM pg_roles r "
                "WHERE r.rolname IN ('pdos_next_app','pdos_next_auth','pdos_next_dispatch',"
                "'pdos_agent') ORDER BY 1"
            )
        ).all()
        assert len(login_privileges) == 4 and all(
            tuple(row[1:]) == (row[0] == "pdos_next_auth", False, False, False)
            for row in login_privileges
        )
        assert not connection.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname IN ('pdos_next_app',"
                "'pdos_next_auth','pdos_next_dispatch','pdos_agent') "
                "AND pg_has_role(rolname,'pdos_next_owner','MEMBER'))"
            )
        )
        assert not connection.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM pg_class c "
                "WHERE c.relnamespace='public'::regnamespace "
                "AND c.relkind IN ('r','p') AND (has_table_privilege('pdos_agent',c.oid,'INSERT') "
                "OR has_table_privilege('pdos_agent',c.oid,'UPDATE') "
                "OR has_table_privilege('pdos_agent',c.oid,'DELETE')))"
            )
        )
        connection.execute(text("SET LOCAL ROLE pdos_next_owner"))
        assert connection.scalar(text("SELECT current_user")) == "pdos_next_owner"
        assert connection.scalar(text("SELECT count(*) FROM principals")) >= 1
    output = {
        "head": version,
        "database": "pdos_test",
        "port": current["port"],
        "marker": current["marker"],
        "ordinary_owner_read_passed": True,
        "agent_direct_dml": False,
        "runtime_owner_membership": False,
        "authentication_root": {
            "table": "login_sessions",
            "reason": "Hashed session lookup before tenant binding; auth SELECT only",
            "role_privileges": [list(row) for row in login_privileges],
        },
        "functions": [list(r) for r in functions],
        "tables": [list(r) for r in tables],
    }
    REPORT.mkdir(parents=True, exist_ok=True)
    target = destination or REPORT / "ordinary-owner-audit.json"
    with target.open("x" if destination is not None else "w") as stream:
        json.dump(output, stream, indent=2)
        stream.write("\n")
    engine.dispose()
    print(f"B8 ordinary-owner audit: {version}, {len(tables)} tables, {len(functions)} definers")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("create", "audit", "resume-empty"))
    arguments = parser.parse_args()
    {"create": create, "audit": audit, "resume-empty": resume_empty}[arguments.action]()
