"""Create/check/serve/destroy only this task's marked synthetic local environment."""

import json
import os
import secrets
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
STATE = ROOT / ".local" / "runtime.json"
REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-g0-20261002"
sys.path.insert(0, str(SERVER))

from pdos_next.contracts import Command  # noqa: E402
from pdos_next.database import engine_for, tenant_session  # noqa: E402
from pdos_next.models import Category, Grant, LoginSession, Principal, Product, now  # noqa: E402
from pdos_next.service import Context, digest, execute  # noqa: E402


def docker(*args):
    result = subprocess.run(["docker", *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Docker operation failed; private arguments withheld")
    return result.stdout.strip()


def read_state():
    state = json.loads(STATE.read_text())
    info = json.loads(docker("inspect", state["container"]))[0]
    if (
        info["Id"] != state["container_id"]
        or info["Config"]["Labels"].get("pdos.next.marker") != state["marker"]
    ):
        raise RuntimeError("Container identity or marker mismatch")
    binding = info["NetworkSettings"]["Ports"]["5432/tcp"][0]
    if binding["HostIp"] != "127.0.0.1" or int(binding["HostPort"]) != state["port"]:
        raise RuntimeError("Container endpoint changed")
    return state


def environment(state):
    return {
        **os.environ,
        "DATABASE_URL": state["app_url"],
        "AUTH_DATABASE_URL": state["auth_url"],
        "DISPATCH_DATABASE_URL": state["dispatch_url"],
        "MIGRATION_DATABASE_URL": state["admin_url"],
        "TEST_DATABASE_URL": state["admin_url"],
        "TEST_DATABASE_MARKER": state["marker"],
        "TEST_DATABASE_PORT": str(state["port"]),
        "PYTHONPATH": str(SERVER),
    }


def save(state):
    STATE.parent.mkdir(mode=0o700, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2) + "\n")
    STATE.chmod(0o600)


def verified(state):
    from pdos_next.safety import verify_test_target

    os.environ.update(environment(state))
    verify_test_target(engine_for(state["admin_url"]))
    return state


def seed(state):
    verified(state)
    admin = engine_for(state["admin_url"])
    tenant, person = uuid4(), uuid4()
    token = secrets.token_urlsafe(32)
    with Session(admin) as s, s.begin():
        s.add(Principal(id=person, tenant_id=tenant, name="合成产品经理", kind="human"))
        s.flush()
        s.add(
            LoginSession(
                tenant_id=tenant,
                principal_id=person,
                token_hash=digest(token),
                expires_at=now() + timedelta(days=7),
            )
        )
        category = Category(
            id=uuid4(), tenant_id=tenant, name="汽车充气泵", purpose="合成品类范围", owner_id=person
        )
        s.add(category)
        s.flush()
        product = Product(
            id=uuid4(),
            tenant_id=tenant,
            category_id=category.id,
            name="合成资料演练",
            purpose="验证来源记录与工作恢复，不代表真实产品定义。",
            owner_id=person,
        )
        s.add(product)
        s.flush()
        s.add(
            Grant(
                tenant_id=tenant,
                category_id=category.id,
                principal_id=person,
                can_write=True,
                expires_at=now() + timedelta(days=7),
            )
        )
        product_id, category_id = product.id, category.id
    with tenant_session(
        engine_for(state["app_url"]),
        tenant,
        actor_id=person,
        requester_id=person,
        category_id=category_id,
    ) as s:
        execute(
            s,
            Context(tenant, person, person, category_id=category_id),
            Command(
                command_id=uuid4(),
                idempotency_key=f"preview-source:{uuid4()}",
                operation="evidence.artifact.register",
                category_id=category_id,
                product_id=product_id,
                expected_revision=1,
                payload={
                    "title": "合成客户输入 · 练习资料",
                    "source_label": "本地合成样例",
                    "content": (
                        "合成客户输入（仅演练）\n额定压力：150 PSI，条件待确认。\n"
                        "目标噪声：未知，需要定义测试条件。\n客户承认：尚未取得。\n"
                    ),
                    "visibility": "private",
                },
            ),
        )
    state["preview_category_id"] = str(category_id)
    state["preview_token"] = token
    state["preview_product_id"] = str(product_id)
    state["preview_tenant_id"] = str(tenant)
    save(state)


def create():
    if STATE.exists():
        state = verified(read_state())
        print(f"Existing task environment verified: 127.0.0.1:{state['port']}/pdos_test")
        return
    marker = str(uuid4())
    name = f"pdos-next-test-20261002-{marker[:8]}"
    password = secrets.token_hex(20)
    app_password, auth_password, dispatch_password = (secrets.token_hex(20) for _ in range(3))
    container_id = docker(
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
    info = json.loads(docker("inspect", name))[0]
    port = int(info["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"])
    if port in {57432, 55432, 55433, 55434, 55435, 57439, 57441}:
        docker("rm", "-f", name)
        raise RuntimeError("Allocated port overlaps a protected environment")
    state = {
        "container": name,
        "container_id": container_id,
        "port": port,
        "marker": marker,
        "admin_url": f"postgresql+psycopg://postgres:{password}@127.0.0.1:{port}/pdos_test",
        "app_url": f"postgresql+psycopg://pdos_next_app:{app_password}@127.0.0.1:{port}/pdos_test",
        "auth_url": f"postgresql+psycopg://pdos_next_auth:{auth_password}@127.0.0.1:{port}/pdos_test",
        "dispatch_url": f"postgresql+psycopg://pdos_next_dispatch:{dispatch_password}@127.0.0.1:{port}/pdos_test",
    }
    # Preserve interrupted bootstrap state to avoid creating another container.
    save(state)
    conn = None
    for _ in range(40):
        try:
            conn = psycopg.connect(state["admin_url"].replace("+psycopg", ""), connect_timeout=1)
            break
        except psycopg.OperationalError:
            time.sleep(0.5)
    if conn is None:
        raise RuntimeError("New task container did not become ready; saved state retained")
    with conn:
        if conn.execute("SELECT current_database()").fetchone()[0] != "pdos_test":
            raise RuntimeError("Unexpected database")
        for role, role_password in [
            ("pdos_next_app", app_password),
            ("pdos_next_auth", auth_password),
            ("pdos_next_dispatch", dispatch_password),
        ]:
            conn.execute(
                sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(role_password)
                )
            )
        conn.execute("CREATE ROLE pdos_agent NOLOGIN NOSUPERUSER NOBYPASSRLS")
        conn.execute(
            "CREATE ROLE pdos_next_owner NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB"
        )
        conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        conn.execute("CREATE TABLE environment_guard(marker uuid PRIMARY KEY)")
        conn.execute("INSERT INTO environment_guard VALUES (%s)", (UUID(marker),))
        conn.execute("GRANT SELECT ON environment_guard TO pdos_next_app,pdos_next_dispatch")
    verified(state)
    bootstrap_report = REPORT.parent / f"pdos-next-bootstrap-{marker[:8]}"
    bootstrap_report.mkdir(parents=True, exist_ok=True)
    with (bootstrap_report / "migration-roundtrip.log").open("x") as log:
        for target in ["head", "base", "head"]:
            direction = "downgrade" if target == "base" else "upgrade"
            subprocess.run(
                [sys.executable, "-m", "alembic", direction, target],
                cwd=SERVER,
                env=environment(state),
                check=True,
                stdout=log,
                stderr=log,
            )
            log.write(f"{direction} {target}: passed\n")
            log.flush()
    seed(state)
    print(f"Created synthetic task database: 127.0.0.1:{port}/pdos_test; marker={marker}")
    print(
        "Independent app/auth/agent roles and migration up/down/up verified. "
        "No old databases accessed."
    )


def local_profile_environment(directory, state):
    """Read only explicit host files; a list supersedes the retained single file."""
    result = {}
    for family, stem, single_suffix in (
        ("PROFESSIONAL", "professional", "SCOPE"),
        ("OPERATIONAL", "operational", "PROFILE"),
        ("TEST_RESOURCE", "test-resource", "PROFILE"),
        ("QUALITY", "quality", "PROFILE"),
        ("QUALITY_FOLLOWUP", "quality-followup", "PROFILE"),
        ("CAPA_FACTS", "capa-facts", "PROFILE"),
    ):
        single_key = f"PDOS_{family}_SYNTHETIC_{single_suffix}"
        plural_key = f"PDOS_{family}_SYNTHETIC_PROFILES"
        plural = directory / f"{stem}-synthetic-profiles.json"
        result[single_key] = result[plural_key] = "null"
        if plural.exists():
            value = json.loads(plural.read_text())
            if (
                type(value) is not list
                or not value
                or any(type(item) is not dict for item in value)
            ):
                raise RuntimeError(f"Invalid nonempty {family} host profile list of mappings")
            result[plural_key] = json.dumps(value)
        elif family == "PROFESSIONAL":
            result[single_key] = json.dumps(
                {
                    "tenant_id": state["preview_tenant_id"],
                    "product_id": state["preview_product_id"],
                }
            )
        else:
            single = directory / f"{stem}-synthetic-profile.json"
            if single.exists():
                result[single_key] = single.read_text()
    return result


def main():
    action = sys.argv[1]
    if action == "create":
        create()
        return
    state = verified(read_state())
    env = environment(state)
    if action in {"migrate", "check"}:
        raise RuntimeError("Use wave1_check.py; historical G0 evidence is immutable")
    if action == "serve-api":
        from workflow_environment import read_verified, state_environment

        env.update(state_environment(read_verified()))
        env.update(local_profile_environment(ROOT / ".local", state))
        os.chdir(SERVER)
        os.execve(
            sys.executable,
            [
                sys.executable,
                "-m",
                "uvicorn",
                "pdos_next.asgi:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8898",
            ],
            env,
        )
    if action == "serve-web":
        # Optional account name: serve the browser as one acceptance login
        # (tools/acceptance_account.py) instead of the seeded preview person.
        account = sys.argv[2] if len(sys.argv) > 2 else None
        tokens = state.get("acceptance_tokens", {})
        if account is not None and account not in tokens:
            raise SystemExit(
                f"No acceptance token named {account!r} in this environment; "
                "create one with tools/acceptance_account.py create."
            )
        env.update(
            PDOS_NEXT_API_URL="http://127.0.0.1:8898",
            PDOS_NEXT_LOCAL_SESSION=(
                state["preview_token"] if account is None else tokens[account]
            ),
        )
        subprocess.run(
            ["pnpm", "start", "--hostname", "127.0.0.1", "--port", "3028"],
            cwd=ROOT / "web",
            env=env,
            check=True,
        )
    if action == "destroy":
        # Container identity, endpoint, and DB marker were all checked above.
        docker("rm", "-f", state["container"])
        STATE.unlink()
        print("Removed only this task's marked synthetic container; credentials removed.")


if __name__ == "__main__":
    main()
