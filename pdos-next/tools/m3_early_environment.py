"""Provision/verify only M3's own labelled synthetic PostgreSQL, never the S0 or M2 DB."""

import argparse
import json
import re
import secrets
import subprocess
import sys
import time
from uuid import UUID, uuid4

import local_environment as local
import psycopg
from psycopg import sql

REPORT = local.ROOT.parent / "docs/reports/evidence/pdos-next-m3-20261008/review-followup"
local.STATE = local.ROOT / ".local/m3-followup-runtime.json"


def state():
    current = local.verified(local.read_state())
    if current.get("purpose") != "m3-early-g0":
        raise RuntimeError("This tool requires its own M3 fixture identity")
    return current


def run(arguments, name):
    current = state()
    env = local.environment(current)
    env["PYTHONPATH"] = (
        str(local.ROOT.parent / "packages/pdos-agent-runtime/src") + ":" + str(local.SERVER)
    )
    try:
        result = subprocess.run(
            [str(local.SERVER / ".venv/bin/python"), *arguments],
            cwd=local.SERVER,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        output, code = result.stdout + result.stderr, result.returncode
    except subprocess.TimeoutExpired as error:
        chunks = [error.stdout or b"", error.stderr or b""]
        output = "\n".join(c.decode() if isinstance(c, bytes) else c for c in chunks)
        output += "\nBounded private fixture check timed out after 180 seconds.\n"
        code = 124
    output = re.sub(r"postgresql(?:\+psycopg)?://[^\s'\"]+", "[REDACTED_DSN]", output)
    for value in current.values():
        if isinstance(value, str) and value in output and ("://" in value or len(value) > 60):
            output = output.replace(value, "[PRIVATE]")
    REPORT.mkdir(parents=True, exist_ok=True)
    path = REPORT / name
    if path.exists():
        path = path.with_name(f"{path.stem}-{time.time_ns()}{path.suffix}")
    path.write_text(output)
    print(f"{path.name}: exit {code}; M3 private target verified; credentials withheld")
    return code


def create():
    if local.STATE.exists():
        current = state()
        print(f"M3 private fixture verified at 127.0.0.1:{current['port']}/pdos_test")
        return
    marker = str(uuid4())
    password = secrets.token_hex(24)
    owner_password = secrets.token_hex(24)
    credentials = {
        role: secrets.token_hex(24)
        for role in ("pdos_next_app", "pdos_next_auth", "pdos_next_dispatch")
    }
    name = "pdos-next-m3-owner-" + marker[:8]
    container_id = local.docker(
        "run",
        "-d",
        "--name",
        name,
        "--label",
        f"pdos.next.marker={marker}",
        "-e",
        "POSTGRES_DB=pdos_test",
        "-e",
        "POSTGRES_USER=postgres",
        "-e",
        f"POSTGRES_PASSWORD={password}",
        "-p",
        "127.0.0.1::5432",
        "pgvector/pgvector:0.8.6-pg16-bookworm",
    )
    info = json.loads(local.docker("inspect", name))[0]
    port = int(info["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"])
    current = {
        "container": name,
        "container_id": container_id,
        "marker": marker,
        "port": port,
        "purpose": "m3-early-g0",
        "bootstrap_url": f"postgresql+psycopg://postgres:{password}@127.0.0.1:{port}/pdos_test",
        "admin_url": f"postgresql+psycopg://pdos_next_owner:{owner_password}@127.0.0.1:{port}/pdos_test",
    }
    for kind, role in (
        ("app", "pdos_next_app"),
        ("auth", "pdos_next_auth"),
        ("dispatch", "pdos_next_dispatch"),
    ):
        current[kind + "_url"] = (
            f"postgresql+psycopg://{role}:{credentials[role]}@127.0.0.1:{port}/pdos_test"
        )
    local.save(current)
    connection = None
    for _ in range(40):
        try:
            connection = psycopg.connect(
                current["bootstrap_url"].replace("+psycopg", ""), connect_timeout=1
            )
            break
        except psycopg.OperationalError:
            time.sleep(0.5)
    if connection is None:
        raise RuntimeError("Saved M3 fixture did not become ready")
    with connection:
        if connection.execute("SELECT current_database()").fetchone()[0] != "pdos_test":
            raise RuntimeError("Wrong database")
        for role, secret in credentials.items():
            connection.execute(
                sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(secret)
                )
            )
        connection.execute("CREATE ROLE pdos_agent NOLOGIN NOSUPERUSER NOBYPASSRLS")
        connection.execute(
            sql.SQL(
                "CREATE ROLE pdos_next_owner LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE PASSWORD {}"
            ).format(sql.Literal(owner_password))
        )
        connection.execute("ALTER DATABASE pdos_test OWNER TO pdos_next_owner")
        connection.execute("ALTER SCHEMA public OWNER TO pdos_next_owner")
        connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
        connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        connection.execute("CREATE TABLE environment_guard(marker uuid PRIMARY KEY)")
        connection.execute("INSERT INTO environment_guard VALUES(%s)", (UUID(marker),))
        connection.execute("ALTER TABLE environment_guard OWNER TO pdos_next_owner")
        connection.execute("GRANT SELECT ON environment_guard TO pdos_next_app,pdos_next_dispatch")
    state()
    migrate()


def migrate():
    current = state()
    # Use the reviewed actual B7 head, including the source/dispatch supplement.
    for head in ("s0_0424", "s0_0719"):
        if run(["-m", "alembic", "upgrade", head], "base-migration.log"):
            raise RuntimeError("M3 private baseline migration failed; inspect redacted log")
    # Trusted migration/definer owner is a separate role, never inherited by runtime roles.
    # FORCE RLS needs an explicit internal policy; ownership itself is not an exemption.
    from owner_policy import configure

    with psycopg.connect(current["admin_url"].replace("+psycopg", "")) as connection:
        configure(connection)
    print(
        f"M3 non-superuser fixture: 127.0.0.1:{current['port']}/pdos_test; "
        f"marker={current['marker']}"
    )


def install():
    current = state()
    sys.path.insert(0, str(local.SERVER))
    from migrations.candidates.m3_preproject import statements
    from pdos_next.database import engine_for
    from sqlalchemy import text

    engine = engine_for(current["admin_url"])
    with engine.begin() as connection:
        if connection.scalar(text("SELECT to_regclass('proposals')")):
            raise RuntimeError("M3 candidate already installed; no schema overwrite")
        for statement in statements():
            connection.execute(text(statement))
    engine.dispose()
    print("M3 owned candidate tables and guarded G0 functions installed on private fixture only")


def close():
    current = state()
    destination = local.ROOT / ".local/m3-early-backups"
    destination.mkdir(mode=0o700, exist_ok=True)
    backup = destination / f"g0-{time.time_ns()}.dump"
    result = subprocess.run(
        ["docker", "exec", current["container"], "pg_dump", "-U", "postgres", "-Fc", "pdos_test"],
        capture_output=True,
    )
    if result.returncode or not result.stdout:
        raise RuntimeError("Private M3 backup failed; fixture stays running")
    backup.write_bytes(result.stdout)
    backup.chmod(0o600)
    local.docker("stop", current["container"])
    (REPORT / "environment-closeout.json").write_text(
        json.dumps(
            {
                "purpose": current["purpose"],
                "marker": current["marker"],
                "port": current["port"],
                "backup_bytes": backup.stat().st_size,
                "container_stopped": True,
                "fixture_retained": True,
                "other_environments_touched": False,
            },
            indent=2,
        )
        + "\n"
    )
    print("M3 private synthetic fixture backed up and stopped; data retained")


def refresh_security():
    """Refresh only this unversioned candidate's guards on its own synthetic fixture."""
    current = state()
    from migrations.candidates.m3_preproject import ATOMIC_GUARDS, SECURITY, statements
    from pdos_next.database import engine_for
    from pdos_next.domain.preproject.models import PreparedCandidate
    from sqlalchemy import text
    from sqlalchemy.schema import CreateIndex, CreateTable

    engine = engine_for(current["admin_url"])
    with engine.begin() as connection:
        connection.execute(text("DROP FUNCTION IF EXISTS m3_effective_audience(uuid,uuid,uuid)"))
        if not connection.scalar(text("SELECT to_regclass('proposal_prepared_candidates')")):
            connection.execute(CreateTable(PreparedCandidate.__table__))
            for index in PreparedCandidate.__table__.indexes:
                connection.execute(CreateIndex(index))
            connection.execute(
                text(
                    "CREATE TRIGGER m3_append BEFORE UPDATE OR DELETE "
                    "ON proposal_prepared_candidates "
                    "FOR EACH ROW EXECUTE FUNCTION m3_append_only()"
                )
            )
        if not connection.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
                "WHERE table_name='proposal_item_versions' AND column_name='prepared_candidate_id')"
            )
        ):
            connection.execute(
                text(
                    "ALTER TABLE proposal_item_versions ADD COLUMN prepared_candidate_id uuid, "
                    "ADD FOREIGN KEY(tenant_id,prepared_candidate_id) "
                    "REFERENCES proposal_prepared_candidates(tenant_id,id)"
                )
            )
        for function in re.findall(r"CREATE FUNCTION m3_.*?\$\$;", SECURITY + ATOMIC_GUARDS, re.S):
            connection.execute(
                text(function.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))
            )
        for function in re.findall(r"CREATE OR REPLACE FUNCTION .*?\$\$;", SECURITY, re.S):
            connection.execute(text(function))
        for statement in statements():
            for policy in re.findall(r"CREATE POLICY m3_.*?;", statement, re.S):
                name, table = re.match(r"CREATE POLICY (\w+) ON (\w+)", policy).groups()
                existing = connection.scalar(
                    text(
                        "SELECT EXISTS(SELECT 1 FROM pg_policies "
                        "WHERE tablename=:t AND policyname=:p)"
                    ),
                    {"t": table, "p": name},
                )
                if existing:
                    policy = re.sub(
                        r" FOR (INSERT|UPDATE|DELETE|SELECT)",
                        "",
                        policy.replace("CREATE POLICY", "ALTER POLICY", 1),
                    )
                connection.execute(text(policy))
            if statement.startswith("ALTER POLICY"):
                connection.execute(text(statement))
            for grant in re.findall(r"GRANT EXECUTE ON FUNCTION m3_.*?;", statement, re.S):
                connection.execute(text(grant))
        for (signature,) in connection.execute(
            text(
                "SELECT oid::regprocedure::text FROM pg_proc "
                "WHERE pronamespace='public'::regnamespace AND proname LIKE 'm3_%'"
            )
        ):
            connection.execute(text(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC,pdos_agent"))
    engine.dispose()
    print("M3 candidate security refreshed on its labelled synthetic fixture only")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=("create", "migrate", "install", "test", "close", "refresh-security")
    )
    args = parser.parse_args()
    if args.action == "test":
        raise SystemExit(run(["-m", "pytest", "-q", "tests/preproject"], "g0-tests.log"))
    {
        "create": create,
        "migrate": migrate,
        "install": install,
        "close": close,
        "refresh-security": refresh_security,
    }[args.action]()
