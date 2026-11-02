"""Independent local Temporal/checkpoint storage; no access to legacy environments."""

import asyncio
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from datetime import timedelta
from uuid import UUID

import psycopg
from local_environment import ROOT, SERVER, docker, read_state, verified
from psycopg import sql

STATE = ROOT / ".local/workflows.json"
sys.path.insert(0, str(SERVER))


def save(value):
    STATE.write_text(json.dumps(value, indent=2) + "\n")
    STATE.chmod(0o600)


def state_environment(value):
    return {
        "PDOS_STATE_DB_PORT": str(value["db_port"]),
        "PDOS_STATE_DB_MARKER": value["marker"],
        "PDOS_CHECKPOINT_DATABASE_URL": value["checkpoint_url"],
        "PDOS_TEMPORAL_ADDRESS": f"127.0.0.1:{value['server_port']}",
        "PDOS_TEMPORAL_NAMESPACE": "pdos-next",
        "PDOS_OBJECT_ROOT": str(ROOT / ".local/objects"),
        "PDOS_WORKFLOWS_ENABLED": "1",
        "PDOS_FILE_SECURITY_PROFILE": "local-synthetic-v1",
        "PDOS_OBJECT_LIFECYCLE_PROFILE": "local-synthetic-v1",
    }


def read_verified(*, ignore_native=False):
    parent = verified(read_state())
    value = json.loads(STATE.read_text())
    if value["marker"] != parent["marker"]:
        raise RuntimeError("Independent workflow marker mismatch")
    info = json.loads(docker("inspect", value["db_container"]))[0]
    port = info["NetworkSettings"]["Ports"]["5432/tcp"][0]
    if (
        info["Id"] != value["db_container_id"]
        or info["Config"]["Labels"].get("pdos.next.marker") != value["marker"]
        or port["HostIp"] != "127.0.0.1"
        or int(port["HostPort"]) != value["db_port"]
    ):
        raise RuntimeError("Workflow DB identity changed")
    with psycopg.connect(value["bootstrap_url"], connect_timeout=3) as connection:
        if (
            connection.execute("SELECT current_database()").fetchone()[0] != "postgres"
            or str(connection.execute("SELECT marker FROM environment_guard").fetchone()[0])
            != value["marker"]
        ):
            raise RuntimeError("Workflow bootstrap target mismatch")
    if value.get("server_container"):
        info = json.loads(docker("inspect", value["server_container"]))[0]
        binding = info["NetworkSettings"]["Ports"]["7233/tcp"][0]
        if (
            info["Id"] != value["server_container_id"]
            or info["Config"]["Labels"].get("pdos.next.marker") != value["marker"]
            or binding["HostIp"] != "127.0.0.1"
            or int(binding["HostPort"]) != value["server_port"]
        ):
            raise RuntimeError("Temporal instance identity changed")
    if value.get("native_binary_sha256"):
        binary = ROOT / ".local/tools/temporal"
        if hashlib.sha256(binary.read_bytes()).hexdigest() != value["native_binary_sha256"]:
            raise RuntimeError("Verified local Temporal binary changed")
    if value.get("native_pid") and not ignore_native:
        result = subprocess.run(
            ["ps", "-p", str(value["native_pid"]), "-o", "args="], capture_output=True, text=True
        )
        if (
            result.returncode
            or str(ROOT / ".local/tools/temporal") not in result.stdout
            or str(ROOT / ".local/temporal.sqlite") not in result.stdout
        ):
            raise RuntimeError("Independent native Temporal process unavailable")
    return value


def serve_native():
    # Development fallback uses actual Temporal history in its own private SQLite file.
    # It is explicitly excluded from production PostgreSQL acceptance.
    value = read_verified(ignore_native=True)
    binary = ROOT / ".local/tools/temporal"
    if not binary.is_file():
        raise RuntimeError("Official Temporal local binary missing")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", value.get("server_port", 0)))
        port = listener.getsockname()[1]
    value.update(
        server_port=port,
        native_pid=os.getpid(),
        native_binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        storage_mode="local-sqlite-development",
    )
    save(value)
    os.umask(0o077)
    os.execv(
        str(binary),
        [
            str(binary),
            "server",
            "start-dev",
            "--headless",
            "--ip",
            "127.0.0.1",
            "--port",
            str(port),
            "--namespace",
            "pdos-next",
            "--db-filename",
            str(ROOT / ".local/temporal.sqlite"),
        ],
    )


def create_database():
    parent = verified(read_state())
    if STATE.exists():
        value = read_verified()
        print(f"Independent state DB verified on loopback:{value['db_port']}")
        return
    marker = parent["marker"]
    password, temporal_password, checkpoint_password = (secrets.token_hex(20) for _ in range(3))
    network = f"pdos-next-state-{marker[:8]}"
    network_id = docker("network", "create", "--label", f"pdos.next.marker={marker}", network)
    name = network + "-pg"
    identity = docker(
        "run",
        "-d",
        "--name",
        name,
        "--label",
        f"pdos.next.marker={marker}",
        "--network",
        network,
        "--network-alias",
        "state-db",
        "-p",
        "127.0.0.1::5432",
        "-e",
        f"POSTGRES_PASSWORD={password}",
        "postgres:16",
    )
    info = json.loads(docker("inspect", name))[0]
    port = int(info["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"])
    if port in {parent["port"], 55432, 57432, 57439, 57441}:
        raise RuntimeError("State DB overlaps a protected endpoint")
    value = {
        "marker": marker,
        "network": network,
        "network_id": network_id,
        "db_container": name,
        "db_container_id": identity,
        "db_port": port,
        "bootstrap_url": f"postgresql://postgres:{password}@127.0.0.1:{port}/postgres",
        "temporal_password": temporal_password,
        "checkpoint_url": (
            f"postgresql+psycopg://pdos_checkpoint:{checkpoint_password}"
            f"@127.0.0.1:{port}/pdos_checkpoints"
        ),
        "server_port": 0,
    }
    save(value)
    connection = None
    for _ in range(40):
        try:
            connection = psycopg.connect(value["bootstrap_url"], autocommit=True, connect_timeout=1)
            break
        except psycopg.OperationalError:
            time.sleep(0.5)
    if connection is None:
        raise RuntimeError("State DB did not become available; bootstrap state retained")
    with connection:
        if connection.execute("SELECT current_database()").fetchone()[0] != "postgres":
            raise RuntimeError("Unexpected fresh state DB")
        connection.execute("CREATE TABLE environment_guard(marker uuid PRIMARY KEY)")
        connection.execute("INSERT INTO environment_guard VALUES (%s)", (UUID(marker),))
        for role, credential in [
            ("pdos_temporal", temporal_password),
            ("pdos_checkpoint", checkpoint_password),
        ]:
            connection.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB PASSWORD {}"
                ).format(sql.Identifier(role), sql.Literal(credential))
            )
        for database, owner in [
            ("pdos_temporal", "pdos_temporal"),
            ("pdos_visibility", "pdos_temporal"),
            ("pdos_checkpoints", "pdos_checkpoint"),
        ]:
            connection.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(database), sql.Identifier(owner)
                )
            )
            connection.execute(
                sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(
                    sql.Identifier(database)
                )
            )
    for database, owner in [
        ("pdos_temporal", "pdos_temporal"),
        ("pdos_visibility", "pdos_temporal"),
        ("pdos_checkpoints", "pdos_checkpoint"),
    ]:
        target = value["bootstrap_url"].rsplit("/", 1)[0] + "/" + database
        with psycopg.connect(target, autocommit=True) as c:
            c.execute("CREATE TABLE environment_guard(marker uuid PRIMARY KEY)")
            c.execute("INSERT INTO environment_guard VALUES (%s)", (UUID(marker),))
            c.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            c.execute(
                sql.SQL("GRANT SELECT ON environment_guard TO {}").format(sql.Identifier(owner))
            )
    os.environ.update(state_environment(value))
    from langgraph.checkpoint.postgres import PostgresSaver
    from pdos_next.workflows.checkpoints import verified_checkpoint_url

    with PostgresSaver.from_conn_string(verified_checkpoint_url(value["checkpoint_url"])) as saver:
        saver.setup()
    read_verified()
    print(f"Created separate Temporal/visibility/checkpoint databases on loopback:{port}")


def create_server():
    value = read_verified()
    if value.get("server_container"):
        print(f"Temporal instance verified on loopback:{value['server_port']}")
        return
    name = value["network"] + "-temporal"
    identity = docker(
        "run",
        "-d",
        "--name",
        name,
        "--label",
        f"pdos.next.marker={value['marker']}",
        "--network",
        value["network"],
        "-p",
        "127.0.0.1::7233",
        "-e",
        "DB=postgres12",
        "-e",
        "POSTGRES_SEEDS=state-db",
        "-e",
        "DB_PORT=5432",
        "-e",
        "POSTGRES_USER=pdos_temporal",
        "-e",
        f"POSTGRES_PWD={value['temporal_password']}",
        "-e",
        "DBNAME=pdos_temporal",
        "-e",
        "VISIBILITY_DBNAME=pdos_visibility",
        "-e",
        "SKIP_DB_CREATE=true",
        "-e",
        "DEFAULT_NAMESPACE=pdos-next",
        "-e",
        "DEFAULT_NAMESPACE_RETENTION=72h",
        "temporalio/auto-setup:1.29.1",
    )
    info = json.loads(docker("inspect", name))[0]
    value.update(
        server_container=name,
        server_container_id=identity,
        server_port=int(info["NetworkSettings"]["Ports"]["7233/tcp"][0]["HostPort"]),
    )
    save(value)
    print(f"Started independent local Temporal on loopback:{value['server_port']}")


async def health():
    value = read_verified()
    from temporalio.client import Client

    client = await Client.connect(f"127.0.0.1:{value['server_port']}", namespace="pdos-next")
    from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest

    response = await client.workflow_service.describe_namespace(
        DescribeNamespaceRequest(namespace="pdos-next"),
        timeout=timedelta(seconds=5),
    )
    print(f"Temporal namespace verified: {response.namespace_info.name}")


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "create-db":
        create_database()
    elif action == "create-server":
        create_server()
    elif action == "serve-native":
        serve_native()
    elif action == "health":
        asyncio.run(health())
    elif action == "worker":
        from local_environment import environment

        parent, value = verified(read_state()), read_verified()
        env = {
            **environment(parent),
            **state_environment(value),
            "PDOS_WORKFLOW_TENANTS": parent["preview_tenant_id"],
        }
        os.chdir(SERVER)
        os.execve(sys.executable, [sys.executable, "-m", "pdos_next.workflows.worker"], env)
    else:
        raise RuntimeError("Unknown workflow environment action")
