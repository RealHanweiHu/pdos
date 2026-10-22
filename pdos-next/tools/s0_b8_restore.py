"""Exercise restoration only in B8's independently marked synthetic database."""

import asyncio
import json
import subprocess
from hashlib import sha256
from uuid import UUID, uuid4

import s0_b8_environment as checkpoint
from fastapi.testclient import TestClient
from pdos_next.api import create_app
from pdos_next.database import engine_for
from pdos_next.dispatch.outbox import dispatch_once
from pdos_next.models import Artifact
from pdos_next.workflows.transport import TemporalSender
from sqlalchemy import select, text


def checked(response):
    assert response.status_code == 200, f"HTTP {response.status_code}"
    return response.json()


def snapshot(current):
    checkpoint.state()
    engine = engine_for(current["admin_url"])
    result = {}
    with engine.connect() as connection:
        names = connection.scalars(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                "AND tablename<>'environment_guard' ORDER BY tablename"
            )
        ).all()
        for name in names:
            quoted = connection.dialect.identifier_preparer.quote(name)
            count, fingerprint = connection.execute(
                text(
                    f"SELECT count(*), md5(coalesce(string_agg(row_hash,'' ORDER BY row_hash),'')) "
                    f"FROM (SELECT md5(row_to_json(t)::text) row_hash FROM public.{quoted} t) rows"
                )
            ).one()
            result[name] = {"rows": count, "sha256": sha256(fingerprint.encode()).hexdigest()}
    engine.dispose()
    return result


def docker(current, *arguments, input=None):
    checkpoint.state()
    result = subprocess.run(
        ["docker", "exec", "-i", current["container"], *arguments],
        input=input,
        capture_output=True,
    )
    if result.returncode:
        private = checkpoint.local.ROOT / ".local/s0-b8-backups"
        private.mkdir(mode=0o700, exist_ok=True)
        diagnostic = private / ("failure-" + str(uuid4()) + ".log")
        diagnostic.write_bytes(result.stderr)
        diagnostic.chmod(0o600)
        raise RuntimeError("B8 restore command failed; private command output retained locally")
    return result.stdout


class NoWorkflowClient:
    async def start_workflow(self, *args, **kwargs):
        raise AssertionError("This metadata-only fixture must not start a workflow")


def deliver(current):
    checkpoint.state()
    engine = engine_for(current["dispatch_url"])
    observed = []
    route = TemporalSender(NoWorkflowClient(), task_queue="s0-b8-metadata-only")

    async def sender(envelope):
        observed.append({"event_id": envelope.event_id, "event_type": envelope.event_type})
        return await route(envelope)

    result = asyncio.run(dispatch_once(engine, UUID(current["preview_tenant_id"]), sender))
    engine.dispose()
    assert result["unknown"] == 0
    return {**result, "events": observed}


def run():
    current = checkpoint.state()
    report = checkpoint.REPORT
    if (report / "backup-restore.json").exists():
        raise RuntimeError("Preserve completed recovery evidence")
    app_engine, auth_engine = engine_for(current["app_url"]), engine_for(current["auth_url"])
    app = create_app(app_engine, auth_engine, workflow_enabled=False)
    headers = {"Authorization": "Bearer " + current["preview_token"]}
    category, product = current["preview_category_id"], current["preview_product_id"]
    admin = engine_for(current["admin_url"])
    with admin.connect() as connection:
        head = connection.scalar(text("SELECT version_num FROM alembic_version"))
        artifact = connection.execute(
            select(Artifact.id, Artifact.revision)
            .where(
                Artifact.tenant_id == UUID(current["preview_tenant_id"]),
                Artifact.product_id == UUID(product),
                Artifact.content.contains("额定压力：150 PSI，条件待确认。"),
            )
            .order_by(Artifact.created_at, Artifact.id)
        ).first()
        assert artifact
    admin.dispose()
    command = {
        "command_id": str(uuid4()),
        "idempotency_key": "b8-recovery:" + str(uuid4()),
        "category_id": category,
        "product_id": product,
        "operation": "evidence.claim.record",
        "expected_revision": 1,
        "source_read_set": [
            {"artifact_id": str(artifact.id), "expected_revision": artifact.revision}
        ],
        "payload": {
            "artifact_id": str(artifact.id),
            "line": 2,
            "quote": "额定压力：150 PSI，条件待确认。",
            "statement": "B8 合成恢复样例：150 PSI，条件待确认。" + str(uuid4()),
            "visibility": "private",
        },
    }
    with TestClient(app) as client:
        receipt = checked(
            client.post(f"/v1/categories/{category}/commands", headers=headers, json=command)
        )
        second = {
            **command,
            "command_id": str(uuid4()),
            "idempotency_key": "b8-recovery:" + str(uuid4()),
            "payload": {**command["payload"], "statement": "第二条合成恢复事件：" + str(uuid4())},
        }
        checked(client.post(f"/v1/categories/{category}/commands", headers=headers, json=second))
        before = snapshot(current)
        private = checkpoint.local.ROOT / ".local/s0-b8-backups"
        private.mkdir(mode=0o700, exist_ok=True)
        attempt = str(uuid4())
        archive = private / ("candidate-" + head + "-" + attempt + ".dump")
        remote = "/tmp/s0-b8-candidate-" + head + "-" + attempt + ".dump"
        context = private / ("context-" + attempt + ".json")
        context.write_text(json.dumps({"command": command, "receipt": receipt, "before": before}))
        context.chmod(0o600)
        docker(
            current,
            "pg_dump",
            "-U",
            "postgres",
            "-d",
            "pdos_test",
            "-Fc",
            "--exclude-table=public.environment_guard",
            "--exclude-table=public.alembic_version",
            "-f",
            remote,
        )
        subprocess.run(
            ["docker", "cp", f"{current['container']}:{remote}", str(archive)],
            capture_output=True,
            check=True,
        )
        archive.chmod(0o600)
        listing = docker(current, "pg_restore", "--list", remote)
        # Retain the existing public schema and marker table. All business objects
        # restore as the ordinary NOLOGIN owner; no CASCADE or database replacement.
        retained = []
        for line in listing.splitlines(keepends=True):
            if b" SCHEMA - public " in line:
                retained.append(b";" + line)
            else:
                retained.append(line)
        toc = b"".join(retained)
        (private / "restore.list").write_bytes(toc)
        (private / "restore.list").chmod(0o600)
        docker(current, "tee", "/tmp/s0-b8-restore.list", input=toc)
        original_delivery = deliver(current)
        assert original_delivery["delivered"] >= 2
        docker(
            current,
            "pg_restore",
            "-U",
            "postgres",
            "-d",
            "pdos_test",
            "--exit-on-error",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--role=pdos_next_owner",
            "--use-list=/tmp/s0-b8-restore.list",
            remote,
        )
        restored = snapshot(current)
        assert restored == before, "Restored business fingerprints differ"
        checkpoint.audit()
        replay = checked(
            client.post(f"/v1/categories/{category}/commands", headers=headers, json=command)
        )
        assert replay["id"] == receipt["id"]
        assert snapshot(current) == before, "Original receipt replay changed persisted state"
        restored_delivery = deliver(current)
        assert restored_delivery["events"] == original_delivery["events"]
        assert restored_delivery["delivered"] == original_delivery["delivered"]
        assert deliver(current) == {"delivered": 0, "unknown": 0, "events": []}
    output = {
        "head": head,
        "database": "pdos_test",
        "port": current["port"],
        "marker": current["marker"],
        "synthetic_only": True,
        "llm_calls": 0,
        "archive_sha256": sha256(archive.read_bytes()).hexdigest(),
        "table_fingerprints_restored": before,
        "original_receipt_recovered_without_state_change": True,
        "ordinary_owner_restore": True,
        "event_replay": restored_delivery,
        "event_scope": (
            "Actual dispatcher role and Temporal routing; metadata-only events are "
            "acknowledged as ignored. No workflow or external side effects claimed."
        ),
    }
    (report / "backup-restore.json").write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n"
    )
    app_engine.dispose()
    auth_engine.dispose()
    print(
        f"B8 restore passed: {len(before)} table fingerprints, original receipt, "
        f"{restored_delivery['delivered']} metadata event replays; ordinary owner"
    )


if __name__ == "__main__":
    run()
