"""Back up this worktree's marked local environment and restore it into a new marked one (D211).

Local drill tool only. It reads the identity files written by local_environment.py,
workflow_environment.py and agent_runtime_environment.py, checks every container's
id, label and marker before touching it, and never accepts a URL from the command
line. A restore always creates new containers with a new marker; it never writes
into an existing environment. No credential is printed or written to the backup.

  backup                     write .local/backups/<time>-<marker8>/ (dumps, roles, manifest)
  restore BACKUP             create .local/restores/<marker8>/ and new containers, then verify
  verify BACKUP RESTORE      recount the restored databases against the backup manifest
  audit-outbound RESTORE     list in-flight outbound items in the restored business database
  serve-temporal RESTORE     run the local Temporal dev server on the restored history file
  destroy RESTORE            remove only that restore's containers and private files

Production backups use the cloud services (RDS automated backup and point-in-time
recovery, OSS versioning, KMS key protection); see docs/runbooks/backup-and-restore.md.
"""

import argparse
import hashlib
import json
import os
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
BACKUPS = LOCAL / "backups"
RESTORES = LOCAL / "restores"
BUSINESS_IMAGE = "pgvector/pgvector:0.8.6-pg16-bookworm"
STATE_IMAGE = "postgres:16"
# Ports that belong to other environments: the old shared joint-test database, other
# projects, and the comprehensive preview clone (64387). A restore never binds them.
PROTECTED_PORTS = {57432, 55432, 55433, 55434, 55435, 57439, 57441, 64387}
MANIFEST_VERSION = "pdos-local-backup/v1"
GUARD = "environment_guard"


# ---------------------------------------------------------------- pure helpers


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def private_dir(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=False)
    path.chmod(0o700)
    return path


def private_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    path.chmod(0o600)


def filter_roles(sql_text: str, bootstrap_role: str) -> str:
    """Keep roles and memberships, drop the container's own bootstrap superuser.

    The input is ``pg_dumpall --roles-only --no-role-passwords``; it carries no
    password. The bootstrap superuser already exists in a new container.
    """
    kept = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"CREATE ROLE {bootstrap_role};") or stripped.startswith(
            f"ALTER ROLE {bootstrap_role} WITH"
        ):
            continue
        if stripped.startswith(("\\restrict", "\\unrestrict")):
            # pg_dumpall 16.10+ wraps output in psql-only meta commands.
            continue
        kept.append(line)
    return "\n".join(kept) + "\n"


def login_roles(sql_text: str) -> list[str]:
    """Names of LOGIN roles in a roles-only dump, excluding superusers."""
    names = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("ALTER ROLE ") or " WITH " not in stripped:
            continue
        name, options = stripped[len("ALTER ROLE ") :].split(" WITH ", 1)
        flags = options.rstrip(";").split()
        if "LOGIN" in flags and "SUPERUSER" not in flags:
            names.append(name.strip('"'))
    return sorted(names)


def compare_tables(expected: dict, actual: dict) -> list[dict]:
    """Differences between two {table: {"rows": n, "digest": hex}} maps."""
    problems = []
    for table in sorted(set(expected) | set(actual)):
        left, right = expected.get(table), actual.get(table)
        if left is None or right is None:
            problems.append(
                {"table": table, "problem": "missing", "expected": left, "actual": right}
            )
        elif left != right:
            problems.append(
                {"table": table, "problem": "changed", "expected": left, "actual": right}
            )
    return problems


def check_port(port: int) -> int:
    if port in PROTECTED_PORTS:
        raise RuntimeError("Allocated port overlaps a protected environment")
    return port


def verify_files(directory: Path, manifest: dict) -> None:
    for name, expected in manifest["files"].items():
        path = directory / name
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"Backup file missing: {name}")
        if sha256_file(path) != expected:
            raise RuntimeError(f"Backup file checksum mismatch: {name}")


# ---------------------------------------------------------------- docker and postgres


def docker(*args, **options):
    result = subprocess.run(["docker", *args], capture_output=True, text=True, **options)
    if result.returncode:
        raise RuntimeError("Docker operation failed; private arguments withheld")
    return result.stdout.strip()


def inspect(container: str) -> dict:
    return json.loads(docker("inspect", container))[0]


def check_container(container: str, container_id: str, label: str, marker: str) -> dict:
    info = inspect(container)
    if info["Id"] != container_id or info["Config"]["Labels"].get(label) != marker:
        raise RuntimeError("Container identity or marker mismatch; refusing to operate")
    return info


def exec_to_file(container: str, command: list[str], destination: Path) -> None:
    with destination.open("xb") as handle:
        result = subprocess.run(
            ["docker", "exec", container, *command], stdout=handle, stderr=subprocess.PIPE
        )
    destination.chmod(0o600)
    if result.returncode:
        raise RuntimeError(f"{command[0]} failed inside the marked container")


def exec_from_file(container: str, command: list[str], source: Path) -> None:
    with source.open("rb") as handle:
        result = subprocess.run(
            ["docker", "exec", "-i", container, *command],
            stdin=handle,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    if result.returncode:
        tail = result.stderr.decode(errors="replace").strip().splitlines()[-3:]
        raise RuntimeError(f"{command[0]} failed inside the restore container: {tail}")


def connect(url: str, **options):
    import psycopg

    return psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://", 1), **options)


def wait_ready(url: str) -> None:
    import psycopg

    for _ in range(80):
        try:
            with connect(url, connect_timeout=1):
                return
        except psycopg.OperationalError:
            time.sleep(0.5)
    raise RuntimeError("Restore container did not become ready")


def table_inventory(connection, *, digests: bool = True) -> dict:
    """Exact row count and an order-independent content digest for every public table."""
    from psycopg import sql

    tables = [
        row[0]
        for row in connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename<>%s "
            "ORDER BY tablename",
            (GUARD,),
        )
    ]
    result = {}
    for table in tables:
        identifier = sql.Identifier(table)
        if digests:
            rows, digest = connection.execute(
                sql.SQL(
                    "SELECT count(*), "
                    "md5(COALESCE(string_agg(t::text, E'\\n' ORDER BY t::text),'')) "
                    "FROM public.{} t"
                ).format(identifier)
            ).fetchone()
            result[table] = {"rows": rows, "digest": digest}
        else:
            rows = connection.execute(
                sql.SQL("SELECT count(*) FROM public.{}").format(identifier)
            ).fetchone()[0]
            result[table] = {"rows": rows}
    return result


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


# ---------------------------------------------------------------- source environment


def source_stores() -> list[dict]:
    """Every database of this worktree's marked environment, identity checked."""
    sys.path.insert(0, str(ROOT / "tools"))
    import local_environment

    business = local_environment.verified(local_environment.read_state())
    stores = [
        {
            "name": "business",
            "container": business["container"],
            "container_id": business["container_id"],
            "label": "pdos.next.marker",
            "marker": business["marker"],
            "superuser": "postgres",
            "database": "pdos_test",
            "url": business["admin_url"],
            "image": BUSINESS_IMAGE,
            "guard": "uuid",
        }
    ]
    workflows = LOCAL / "workflows.json"
    if workflows.exists():
        import workflow_environment

        state = workflow_environment.read_verified(ignore_native=True)
        base = state["bootstrap_url"].rsplit("/", 1)[0]
        for name, database in (
            ("checkpoints", "pdos_checkpoints"),
            ("temporal", "pdos_temporal"),
            ("temporal_visibility", "pdos_visibility"),
        ):
            stores.append(
                {
                    "name": name,
                    "container": state["db_container"],
                    "container_id": state["db_container_id"],
                    "label": "pdos.next.marker",
                    "marker": state["marker"],
                    "superuser": "postgres",
                    "database": database,
                    "url": f"{base}/{database}",
                    "image": STATE_IMAGE,
                    "guard": "uuid",
                    # With the native dev server these two databases are empty by design.
                    "temporal_persistence": state.get("storage_mode", "postgresql"),
                }
            )
    runtime = LOCAL / "agent-runtime" / "environment.json"
    if runtime.exists():
        value = json.loads(runtime.read_text())
        check_container(
            value["container"], value["container_id"], "pdos.agent-runtime", value["marker"]
        )
        stores.append(
            {
                "name": "agent_runtime",
                "container": value["container"],
                "container_id": value["container_id"],
                "label": "pdos.agent-runtime",
                "marker": value["marker"],
                "superuser": "pdos_runtime",
                "database": "pdos_agent_runtime",
                "url": value["environment"]["PDOS_AGENT_RUNTIME_DATABASE_URL"],
                "image": BUSINESS_IMAGE,
                "guard": "text",
            }
        )
    return stores


def check_guard(connection, marker: str) -> None:
    actual = connection.execute(f"SELECT marker FROM {GUARD}").fetchone()[0]
    if str(actual) != marker:
        raise RuntimeError("Database marker mismatch; refusing to operate")


def backup_store(store: dict, directory: Path, *, digests: bool) -> dict:
    check_container(store["container"], store["container_id"], store["label"], store["marker"])
    dump = directory / f"{store['name']}.dump"
    with connect(store["url"]) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        check_guard(connection, store["marker"])
        # pg_dump reads the exact snapshot the inventory below counts.
        snapshot = connection.execute("SELECT pg_export_snapshot()").fetchone()[0]
        inventory = table_inventory(connection, digests=digests)
        alembic = None
        if "alembic_version" in inventory:
            alembic = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        server_version = connection.execute("SHOW server_version").fetchone()[0]
        exec_to_file(
            store["container"],
            [
                "pg_dump",
                "-U",
                store["superuser"],
                "-d",
                store["database"],
                "--format=custom",
                "--snapshot",
                snapshot,
                f"--exclude-table=public.{GUARD}",
            ],
            dump,
        )
    return {
        "database": store["database"],
        "image": store["image"],
        "superuser": store["superuser"],
        "guard": store["guard"],
        "server_version": server_version,
        "alembic_version": alembic,
        "tables": inventory,
        "temporal_persistence": store.get("temporal_persistence"),
    }


def backup(digests: bool = True, objects: Path | None = None) -> Path:
    """Dump every marked store; ``objects`` overrides the object root (.local/objects)."""
    stores = source_stores()
    business_marker = stores[0]["marker"]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    directory = private_dir(BACKUPS / f"{stamp}-{business_marker[:8]}")
    manifest = {
        "version": MANIFEST_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "source_markers": sorted({store["marker"] for store in stores}),
        "databases": {},
        "roles": {},
        "files": {},
        "kms": {
            "included": False,
            "reason": "Local profile has no KMS. Production keys stay in Alibaba Cloud KMS; "
            "only key references and the KMS recovery procedure are part of a backup.",
        },
    }
    containers = {}
    for store in stores:
        containers.setdefault(store["container"], store)
    for container, store in containers.items():
        roles = directory / f"roles-{store['name']}.sql"
        exec_to_file(
            container,
            ["pg_dumpall", "-U", store["superuser"], "--roles-only", "--no-role-passwords"],
            roles,
        )
        manifest["roles"][store["name"]] = roles.name
    for store in stores:
        manifest["databases"][store["name"]] = backup_store(store, directory, digests=digests)
    temporal = LOCAL / "temporal.sqlite"
    if temporal.exists():
        target = directory / "temporal.sqlite"
        # SQLite's online backup API copies a consistent image while the server runs.
        with (
            sqlite3.connect(f"file:{temporal}?mode=ro", uri=True) as source,
            sqlite3.connect(target) as copy,
        ):
            source.backup(copy)
        target.chmod(0o600)
        manifest["temporal_sqlite"] = target.name
    objects = LOCAL / "objects" if objects is None else objects
    if not objects.is_absolute() and objects != LOCAL / "objects":
        raise RuntimeError("Object root must be an absolute path")
    if objects.is_symlink():
        raise RuntimeError("Object root must not be a symlink")
    inventory = {}
    if objects.is_dir():
        archive = directory / "objects.tar"
        with tarfile.open(archive, "x") as tar:
            for path in sorted(objects.rglob("*")):
                if path.is_symlink():
                    raise RuntimeError("Object store contains a symlink; refusing to archive")
                if path.is_file():
                    name = str(path.relative_to(objects))
                    inventory[name] = sha256_file(path)
                    tar.add(path, arcname=name, recursive=False)
        archive.chmod(0o600)
        manifest["objects"] = {"archive": archive.name, "files": inventory}
    for path in sorted(directory.iterdir()):
        manifest["files"][path.name] = sha256_file(path)
    private_json(directory / "manifest.json", manifest)
    print(f"Backup written: {directory.relative_to(ROOT)}")
    print(
        json.dumps(
            {
                name: {
                    "tables": len(db["tables"]),
                    "rows": sum(t["rows"] for t in db["tables"].values()),
                }
                for name, db in manifest["databases"].items()
            },
            sort_keys=True,
        )
    )
    return directory


# ---------------------------------------------------------------- restore


def load_manifest(directory: Path) -> dict:
    directory = directory.resolve()
    if BACKUPS.resolve() not in directory.parents:
        raise RuntimeError("Restore only from this worktree's .local/backups")
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("version") != MANIFEST_VERSION:
        raise RuntimeError("Unknown backup manifest version")
    verify_files(directory, manifest)
    return manifest


def start_container(name: str, image: str, marker: str, source_marker: str, env: dict) -> dict:
    flags = []
    for key in env:
        flags += ["-e", key]
    container_id = docker(
        "run",
        "-d",
        "--pull",
        "never",
        "--name",
        name,
        "--label",
        f"pdos.next.marker={marker}",
        "--label",
        f"pdos.next.restored-from={source_marker}",
        *flags,
        "-p",
        "127.0.0.1::5432",
        image,
        env={**os.environ, **env},
    )
    info = inspect(name)
    binding = info["NetworkSettings"]["Ports"]["5432/tcp"][0]
    if binding["HostIp"] != "127.0.0.1":
        docker("rm", "-f", name)
        raise RuntimeError("Restore container is not bound to loopback")
    try:
        port = check_port(int(binding["HostPort"]))
    except RuntimeError:
        docker("rm", "-f", name)
        raise
    return {"container": name, "container_id": container_id, "port": port}


def create_guard(connection, kind: str, marker: str, readers=()) -> None:
    from psycopg import sql

    column = "uuid PRIMARY KEY" if kind == "uuid" else "text NOT NULL"
    connection.execute(f"CREATE TABLE {GUARD}(marker {column})")
    connection.execute(
        f"INSERT INTO {GUARD} VALUES (%s)", (UUID(marker) if kind == "uuid" else marker,)
    )
    for role in readers:
        connection.execute(
            sql.SQL("GRANT SELECT ON {} TO {}").format(sql.Identifier(GUARD), sql.Identifier(role))
        )


def apply_roles(url: str, roles_sql: str, bootstrap_role: str) -> dict:
    """Recreate roles without passwords, then give each LOGIN role a fresh one."""
    from psycopg import sql

    passwords = {}
    with connect(url, autocommit=True) as connection:
        connection.execute(filter_roles(roles_sql, bootstrap_role))
        for role in login_roles(roles_sql):
            passwords[role] = secrets.token_hex(20)
            connection.execute(
                sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(passwords[role])
                )
            )
    return passwords


def restore_database(container: str, superuser: str, database: str, dump: Path) -> None:
    exec_from_file(
        container,
        [
            "pg_restore",
            "-U",
            superuser,
            "-d",
            database,
            "--exit-on-error",
            "--single-transaction",
        ],
        dump,
    )


def restore(backup_dir: Path) -> Path:
    from psycopg import sql

    backup_dir = backup_dir.resolve()
    manifest = load_manifest(backup_dir)
    databases = manifest["databases"]
    marker = str(uuid4())
    directory = private_dir(RESTORES / marker[:8])
    source_marker = manifest["source_markers"][0]
    state = {
        "purpose": "restore-drill",
        "marker": marker,
        "restored_from": str(backup_dir.relative_to(ROOT)),
        "restored_at": datetime.now(UTC).isoformat(),
        "containers": [],
    }
    # Persist identity first so a failed restore can still be destroyed.
    private_json(directory / "restore.json", state)

    # Business database: same image, roles, guard and grants as local_environment.create.
    password = secrets.token_hex(20)
    business = start_container(
        f"pdos-next-restore-{marker[:8]}",
        BUSINESS_IMAGE,
        marker,
        source_marker,
        {"POSTGRES_DB": "pdos_test", "POSTGRES_USER": "postgres", "POSTGRES_PASSWORD": password},
    )
    state["containers"].append({**business, "label": "pdos.next.marker"})
    private_json(directory / "restore.json", state)
    admin = f"postgresql+psycopg://postgres:{password}@127.0.0.1:{business['port']}/pdos_test"
    wait_ready(admin)
    roles = (backup_dir / manifest["roles"]["business"]).read_text()
    passwords = apply_roles(admin, roles, "postgres")
    with connect(admin, autocommit=True) as connection:
        create_guard(connection, "uuid", marker, readers=("pdos_next_app", "pdos_next_dispatch"))
    restore_database(business["container"], "postgres", "pdos_test", backup_dir / "business.dump")
    runtime = {
        "purpose": "restore-drill",
        "container": business["container"],
        "container_id": business["container_id"],
        "port": business["port"],
        "marker": marker,
        "admin_url": admin,
        "app_url": f"postgresql+psycopg://pdos_next_app:{passwords['pdos_next_app']}"
        f"@127.0.0.1:{business['port']}/pdos_test",
        "auth_url": f"postgresql+psycopg://pdos_next_auth:{passwords['pdos_next_auth']}"
        f"@127.0.0.1:{business['port']}/pdos_test",
        "dispatch_url": f"postgresql+psycopg://pdos_next_dispatch:{passwords['pdos_next_dispatch']}"
        f"@127.0.0.1:{business['port']}/pdos_test",
    }
    private_json(directory / "runtime.json", runtime)

    # Temporal persistence, visibility and LangGraph checkpoints share one state container.
    state_names = [
        name for name in ("checkpoints", "temporal", "temporal_visibility") if name in databases
    ]
    if state_names:
        state_password = secrets.token_hex(20)
        holder = start_container(
            f"pdos-next-restore-{marker[:8]}-state",
            STATE_IMAGE,
            marker,
            source_marker,
            {"POSTGRES_PASSWORD": state_password},
        )
        state["containers"].append({**holder, "label": "pdos.next.marker"})
        private_json(directory / "restore.json", state)
        bootstrap = f"postgresql://postgres:{state_password}@127.0.0.1:{holder['port']}/postgres"
        wait_ready(bootstrap)
        state_passwords = apply_roles(
            bootstrap, (backup_dir / manifest["roles"]["checkpoints"]).read_text(), "postgres"
        )
        owners = {
            "checkpoints": "pdos_checkpoint",
            "temporal": "pdos_temporal",
            "temporal_visibility": "pdos_temporal",
        }
        with connect(bootstrap, autocommit=True) as connection:
            create_guard(connection, "uuid", marker)
            for name in state_names:
                connection.execute(
                    sql.SQL("CREATE DATABASE {} OWNER {}").format(
                        sql.Identifier(databases[name]["database"]), sql.Identifier(owners[name])
                    )
                )
                connection.execute(
                    sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(
                        sql.Identifier(databases[name]["database"])
                    )
                )
        base = bootstrap.rsplit("/", 1)[0]
        for name in state_names:
            with connect(f"{base}/{databases[name]['database']}", autocommit=True) as connection:
                create_guard(connection, "uuid", marker, readers=(owners[name],))
                connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            restore_database(
                holder["container"],
                "postgres",
                databases[name]["database"],
                backup_dir / f"{name}.dump",
            )
        workflows = {
            "marker": marker,
            "db_container": holder["container"],
            "db_container_id": holder["container_id"],
            "db_port": holder["port"],
            "bootstrap_url": bootstrap,
            "checkpoint_url": f"postgresql+psycopg://pdos_checkpoint:{state_passwords['pdos_checkpoint']}"
            f"@127.0.0.1:{holder['port']}/pdos_checkpoints",
            "temporal_password": state_passwords.get("pdos_temporal"),
            "server_port": 0,
        }
        private_json(directory / "workflows.json", workflows)

    if "agent_runtime" in databases:
        runtime_password = secrets.token_urlsafe(32)
        holder = start_container(
            f"pdos-next-restore-{marker[:8]}-agent",
            BUSINESS_IMAGE,
            marker,
            source_marker,
            {
                "POSTGRES_DB": "pdos_agent_runtime",
                "POSTGRES_USER": "pdos_runtime",
                "POSTGRES_PASSWORD": runtime_password,
            },
        )
        state["containers"].append({**holder, "label": "pdos.next.marker"})
        private_json(directory / "restore.json", state)
        url = f"postgresql://pdos_runtime:{runtime_password}@127.0.0.1:{holder['port']}/pdos_agent_runtime"
        wait_ready(url)
        apply_roles(
            url, (backup_dir / manifest["roles"]["agent_runtime"]).read_text(), "pdos_runtime"
        )
        with connect(url, autocommit=True) as connection:
            create_guard(connection, "text", marker)
        restore_database(
            holder["container"],
            "pdos_runtime",
            "pdos_agent_runtime",
            backup_dir / "agent_runtime.dump",
        )
        private_json(
            directory / "agent-runtime.json",
            {
                "container": holder["container"],
                "container_id": holder["container_id"],
                "marker": marker,
                "port": holder["port"],
                "environment": {
                    "PDOS_AGENT_RUNTIME_DATABASE_URL": url,
                    "PDOS_AGENT_RUNTIME_DB_MARKER": marker,
                },
            },
        )

    if manifest.get("temporal_sqlite"):
        target = directory / "temporal.sqlite"
        shutil.copyfile(backup_dir / manifest["temporal_sqlite"], target)
        target.chmod(0o600)
    if manifest.get("objects"):
        objects = private_dir(directory / "objects")
        with tarfile.open(backup_dir / manifest["objects"]["archive"]) as tar:
            tar.extractall(objects, filter="data")
        for name, expected in manifest["objects"]["files"].items():
            if sha256_file(objects / name) != expected:
                raise RuntimeError(f"Restored object checksum mismatch: {name}")
    state["completed_at"] = datetime.now(UTC).isoformat()
    private_json(directory / "restore.json", state)
    report = verify(backup_dir, directory)
    print(f"Restored into new marked environment: {directory.relative_to(ROOT)}")
    print(json.dumps(report["summary"], sort_keys=True))
    return directory


def restore_urls(directory: Path) -> dict:
    """Admin URL per restored database, after checking each container and marker."""
    state = json.loads((directory / "restore.json").read_text())
    for item in state["containers"]:
        check_container(item["container"], item["container_id"], item["label"], state["marker"])
    urls = {"business": json.loads((directory / "runtime.json").read_text())["admin_url"]}
    workflows = directory / "workflows.json"
    if workflows.exists():
        base = json.loads(workflows.read_text())["bootstrap_url"].rsplit("/", 1)[0]
        urls.update(
            checkpoints=f"{base}/pdos_checkpoints",
            temporal=f"{base}/pdos_temporal",
            temporal_visibility=f"{base}/pdos_visibility",
        )
    runtime = directory / "agent-runtime.json"
    if runtime.exists():
        urls["agent_runtime"] = json.loads(runtime.read_text())["environment"][
            "PDOS_AGENT_RUNTIME_DATABASE_URL"
        ]
    return {"state": state, "urls": urls}


def verify(backup_dir: Path, directory: Path) -> dict:
    manifest = load_manifest(backup_dir.resolve())
    restored = restore_urls(directory.resolve())
    marker = restored["state"]["marker"]
    report = {"databases": {}, "summary": {}}
    for name, expected in manifest["databases"].items():
        digests = all("digest" in row for row in expected["tables"].values())
        with connect(restored["urls"][name]) as connection:
            check_guard(connection, marker)
            actual = table_inventory(connection, digests=digests)
            alembic = None
            if "alembic_version" in actual:
                alembic = connection.execute("SELECT version_num FROM alembic_version").fetchone()[
                    0
                ]
        problems = compare_tables(expected["tables"], actual)
        if alembic != expected["alembic_version"]:
            problems.append(
                {
                    "table": "alembic_version",
                    "problem": "head",
                    "expected": expected["alembic_version"],
                    "actual": alembic,
                }
            )
        report["databases"][name] = {
            "tables": len(actual),
            "rows": sum(r["rows"] for r in actual.values()),
            "problems": problems,
        }
        report["summary"][name] = "match" if not problems else f"{len(problems)} differences"
    if manifest.get("objects"):
        objects = directory / "objects"
        missing = [
            n
            for n, h in manifest["objects"]["files"].items()
            if not (objects / n).is_file() or sha256_file(objects / n) != h
        ]
        report["summary"]["objects"] = "match" if not missing else f"{len(missing)} differences"
    if manifest.get("temporal_sqlite"):
        same = (
            sha256_file(directory / "temporal.sqlite")
            == manifest["files"][manifest["temporal_sqlite"]]
        )
        report["summary"]["temporal_sqlite"] = "match" if same else "changed after restore"
    private_json(directory / "verify.json", report)
    return report


# ---------------------------------------------------------------- after a restore

# In-flight outbound work that must be checked against the external side before any
# worker or channel starts on a restored database. Counts and identifiers only.
OUTBOUND_CHECKS = (
    ("outbox_events", "delivered_at IS NULL", "domain events not yet delivered; redelivered once"),
    (
        "dingtalk_deliveries",
        "state IN ('planned','sending','unknown')",
        "DingTalk sends not confirmed",
    ),
    (
        "dingtalk_summary_deliveries",
        "state IN ('planned','sending','unknown')",
        "DingTalk summaries not confirmed",
    ),
    (
        "external_handoff_currents",
        "(projection->>'delivery_unknown')::boolean",
        "handoff send result unknown",
    ),
    (
        "agent_tool_calls",
        "state IN ('started','unknown')",
        "tool calls started or with unknown outcome",
    ),
    ("model_invocations", "status IN ('started','unknown')", "model calls not finished"),
    (
        "agent_runs",
        "state NOT IN ('completed','partial','cancelled','failed')",
        "小Pai runs not finished",
    ),
)


def audit_outbound(directory: Path) -> dict:
    restored = restore_urls(directory.resolve())
    result = {}
    with connect(restored["urls"]["business"]) as connection:
        check_guard(connection, restored["state"]["marker"])
        for table, predicate, meaning in OUTBOUND_CHECKS:
            exists = connection.execute("SELECT to_regclass(%s)", (f"public.{table}",)).fetchone()[
                0
            ]
            if exists is None:
                result[table] = {"meaning": meaning, "skipped": "table absent"}
                continue
            columns = {
                row[0]
                for row in connection.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=%s",
                    (table,),
                )
            }
            needed = {"projection"} if "projection->>" in predicate else set()
            needed |= {word for word in ("state", "status", "delivered_at") if word in predicate}
            if not needed <= columns:
                result[table] = {
                    "meaning": meaning,
                    "skipped": f"columns {sorted(needed - columns)} absent",
                }
                continue
            rows = connection.execute(
                f"SELECT id FROM public.{table} WHERE {predicate} ORDER BY id LIMIT 200"
            ).fetchall()
            count = connection.execute(
                f"SELECT count(*) FROM public.{table} WHERE {predicate}"
            ).fetchone()[0]
            result[table] = {"meaning": meaning, "count": count, "ids": [str(r[0]) for r in rows]}
    private_json(directory / "outbound-audit.json", result)
    return result


def serve_temporal(directory: Path) -> None:
    directory = directory.resolve()
    restore_urls(directory)
    binary = LOCAL / "tools" / "temporal"
    history = directory / "temporal.sqlite"
    if not binary.is_file() or not history.is_file():
        raise RuntimeError("Local Temporal binary or restored history file missing")
    port = check_port(free_port())
    state = json.loads((directory / "restore.json").read_text())
    state["temporal_port"] = port
    state["temporal_pid"] = os.getpid()
    private_json(directory / "restore.json", state)
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
            str(history),
        ],
    )


def destroy(directory: Path) -> None:
    directory = directory.resolve()
    if RESTORES.resolve() not in directory.parents:
        raise RuntimeError("Destroy only this worktree's .local/restores entries")
    state = json.loads((directory / "restore.json").read_text())
    for item in state["containers"]:
        check_container(item["container"], item["container_id"], item["label"], state["marker"])
    for item in state["containers"]:
        docker("rm", "-f", "-v", item["container"])
    shutil.rmtree(directory)
    print("Removed only this restore's marked containers and private files.")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="action", required=True)
    make = sub.add_parser("backup")
    make.add_argument("--counts-only", action="store_true", help="skip per-table content digests")
    make.add_argument("--objects", type=Path, help="absolute object root (default .local/objects)")
    for name in ("restore",):
        sub.add_parser(name).add_argument("backup", type=Path)
    check = sub.add_parser("verify")
    check.add_argument("backup", type=Path)
    check.add_argument("restore", type=Path)
    for name in ("audit-outbound", "serve-temporal", "destroy"):
        sub.add_parser(name).add_argument("restore", type=Path)
    args = parser.parse_args(argv)
    if args.action == "backup":
        backup(digests=not args.counts_only, objects=args.objects)
    elif args.action == "restore":
        restore(args.backup)
    elif args.action == "verify":
        print(json.dumps(verify(args.backup, args.restore)["summary"], sort_keys=True))
    elif args.action == "audit-outbound":
        print(json.dumps(audit_outbound(args.restore), ensure_ascii=False, indent=2))
    elif args.action == "serve-temporal":
        serve_temporal(args.restore)
    elif args.action == "destroy":
        destroy(args.restore)


if __name__ == "__main__":
    main()
