"""Create/check the independent local Agent state service, never a business database."""

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import psycopg
from pdos_agent_runtime.bootstrap import install

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / ".local" / "agent-runtime"
CONFIG = DIRECTORY / "environment.json"
IMAGE = "pgvector/pgvector:0.8.6-pg16-bookworm"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def private_write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value))
    path.chmod(0o600)


def inspect_container(value: dict) -> None:
    container = json.loads(
        subprocess.check_output(["docker", "inspect", value["container"]], text=True)
    )[0]
    if (
        container["Id"] != value["container_id"]
        or container["Config"]["Labels"].get("pdos.agent-runtime") != value["marker"]
        or container["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"] != str(value["port"])
    ):
        raise RuntimeError("Local runtime identity changed; refusing to operate")


def initialize() -> dict:
    if CONFIG.exists():
        if CONFIG.stat().st_mode & 0o077:
            raise RuntimeError("Private local runtime configuration permissions changed")
        value = json.loads(CONFIG.read_text())
        inspect_container(value)
        return value
    binary = shutil.which("temporal")
    if binary is None:
        candidate = ROOT / "pdos-next" / ".local" / "tools" / "temporal"
        if candidate.is_file():
            binary = str(candidate)
    if binary is None:
        raise RuntimeError("The local Temporal CLI is required; no runtime fallback is allowed")
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    DIRECTORY.chmod(0o700)
    port, temporal_port = free_port(), free_port()
    password, marker = secrets.token_urlsafe(32), str(uuid4())
    container_name = "pdos-agent-state-" + marker[:8]
    if subprocess.run(
        ["docker", "image", "inspect", IMAGE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ).returncode:
        raise RuntimeError("The configured PostgreSQL image must be installed before local startup")
    try:
        container_id = subprocess.check_output(
            [
                "docker",
                "run",
                "-d",
                "--pull",
                "never",
                "--name",
                container_name,
                "--restart",
                "unless-stopped",
                "--label",
                "pdos.agent-runtime=" + marker,
                "-e",
                "POSTGRES_DB=pdos_agent_runtime",
                "-e",
                "POSTGRES_USER=pdos_runtime",
                "-e",
                "POSTGRES_PASSWORD",
                "-p",
                f"127.0.0.1:{port}:5432",
                "-v",
                container_name + ":/var/lib/postgresql/data",
                IMAGE,
            ],
            text=True,
            env={**os.environ, "POSTGRES_PASSWORD": password},
        ).strip()
    except subprocess.CalledProcessError:
        raise RuntimeError("Independent local Agent PostgreSQL could not start") from None
    url = f"postgresql://pdos_runtime:{password}@127.0.0.1:{port}/pdos_agent_runtime"
    value = {
        "container": container_name,
        "container_id": container_id,
        "marker": marker,
        "port": port,
        "temporal_binary": binary,
        "temporal_port": temporal_port,
        "development_profile": True,
        "environment": {
            "PDOS_AGENT_RUNTIME_DATABASE_URL": url,
            "PDOS_AGENT_RUNTIME_DB_MARKER": marker,
            "PDOS_TEMPORAL_ADDRESS": f"127.0.0.1:{temporal_port}",
            "PDOS_TEMPORAL_NAMESPACE": "pdos-agent-local",
        },
    }
    # Persist identity before initialization so a failed startup cannot create duplicates.
    private_write(CONFIG, value)
    for _ in range(80):
        try:
            connection = psycopg.connect(url, connect_timeout=1)
            break
        except psycopg.OperationalError:
            time.sleep(0.25)
    else:
        raise RuntimeError("Independent Agent PostgreSQL startup timeout")
    with connection:
        connection.execute("CREATE TABLE environment_guard(marker text NOT NULL)")
        connection.execute("INSERT INTO environment_guard VALUES(%s)", (marker,))
    install(url, realm="pdos", marker=marker)
    return value


def temporal_running(value: dict) -> bool:
    pid = value.get("temporal_pid")
    if not pid:
        return False
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True
    )
    return result.returncode == 0 and str(DIRECTORY / "temporal.sqlite") in result.stdout


def start(value: dict) -> None:
    if temporal_running(value):
        return
    with (DIRECTORY / "temporal.log").open("ab") as log:
        process = subprocess.Popen(
            [
                value["temporal_binary"],
                "server",
                "start-dev",
                "--headless",
                "--ip",
                "127.0.0.1",
                "--port",
                str(value["temporal_port"]),
                "--namespace",
                "pdos-agent-local",
                "--db-filename",
                str(DIRECTORY / "temporal.sqlite"),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    value["temporal_pid"] = process.pid
    private_write(CONFIG, value)
    for _ in range(80):
        if process.poll() is not None:
            raise RuntimeError("Local Temporal startup failed; inspect the private runtime log")
        try:
            with socket.create_connection(("127.0.0.1", value["temporal_port"]), timeout=0.25):
                return
        except OSError:
            time.sleep(0.25)
    raise RuntimeError("Local Temporal startup timeout")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "status"))
    action = parser.parse_args().action
    if action == "status" and not CONFIG.exists():
        print(json.dumps({"configured": False}))
        return
    value = initialize()
    if action == "start":
        start(value)
    print(
        json.dumps(
            {
                "database": "pdos_agent_runtime",
                "database_port": value["port"],
                "temporal_port": value["temporal_port"],
                "temporal_running": temporal_running(value),
                "profile": "local-development",
                "configuration": str(CONFIG),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
