"""Actual synthetic API/worker readback on the task's verified local environment."""

import base64
import hashlib
import json
import subprocess
import sys
from collections import Counter
from uuid import UUID

import httpx
from local_environment import ROOT, read_state, verified
from pdos_next.database import engine_for, tenant_session
from pdos_next.models import (
    Artifact,
    Audit,
    Base,
    OriginalScanResult,
    Outbox,
    Receipt,
    UploadedOriginal,
)
from pdos_next.original_store import OriginalStore
from pdos_next.originals import object_reference
from sqlalchemy import func, select, text

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave8-20261002"
state = verified(read_state())
product_id = state["preview_product_id"]
prefix = f"/v1/products/{product_id}"
with httpx.Client(
    base_url="http://127.0.0.1:8898",
    trust_env=False,
    headers={"Authorization": "Bearer " + state["preview_token"]},
    timeout=20,
) as client:

    def read(resource):
        response = client.get(f"{prefix}/{resource}")
        if response.status_code != 200:
            raise RuntimeError("Own synthetic preview read unavailable")
        return response.json()

    action = sys.argv[1]
    if action == "seed-risk":
        # Standard non-executable antivirus test marker; no real malicious file.
        marker = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
        response = client.post(
            f"{prefix}/originals",
            json={
                "filename": "wave8-antivirus-test.txt",
                "title": "合成防病毒标记 · 禁止作为业务来源",
                "source_label": "仅EICAR标准检测演练，无真实业务资料",
                "visibility": "private",
                "content_base64": base64.b64encode(marker).decode(),
                "expected_revision": read("workspace")["product"]["revision"],
                "idempotency_key": "wave8-antivirus-marker-20261002",
            },
        )
        if response.status_code != 200:
            raise RuntimeError("Synthetic antivirus-marker upload unavailable")
        (REPORT / "risk-upload-receipt.json").write_text(
            json.dumps(response.json(), indent=2) + "\n"
        )
        print("Own synthetic antivirus marker saved; scan result remains independently verified.")
        raise SystemExit(0)
    if action != "readback":
        raise RuntimeError("Unknown readback action")
    workspace = read("workspace")
    originals = {row["title"]: row for row in workspace["originals"]}
    good = originals["wave8-source.txt"]
    bad = originals["合成防病毒标记 · 禁止作为业务来源"]
    assert good["security"]["source_state"] == "withdrawn"
    assert good["status"] == "parsed" and good["artifact_id"]
    assert good["security"]["scan"]["status"] == "clean"
    assert good["security"]["state"] == "stale"
    assert good["security"]["lifecycle"]["journal_state"] == "registered"
    assert bad["security"]["state"] == "quarantined" and bad["status"] == "uploaded"
    assert bad["security"]["scan"]["status"] == "infected" and bad["artifact_id"] is None
    for row in (good, bad):
        assert not row["security"]["capabilities"]["download"]
        assert client.get(f"{prefix}/originals/{row['id']}/download").status_code == 409
        assert row["security"]["lifecycle"]["physical_actions_available"] is False
        assert row["security"]["lifecycle"]["disposition"] == "active"
    for name in ("browser-synthetic.txt", "browser-synthetic.pdf", "browser-synthetic.xlsx"):
        old = originals[name]
        assert old["security"]["state"] == "clean" and old["status"] == "parsed"
        downloaded = client.get(f"{prefix}/originals/{old['id']}/download")
        assert downloaded.status_code == 200
        assert hashlib.sha256(downloaded.content).hexdigest() == old["content_hash"]
        assert old["security"]["lifecycle"]["journal_state"] == "unknown"
    prior3 = json.loads(
        (REPORT.parent / "pdos-next-wave3-20261002/actual-preview.json").read_text()
    )
    build = next(row for row in read("builds")["items"] if row["id"] == prior3["build"]["id"])
    assert build == prior3["build"]
    prior7 = json.loads(
        (REPORT.parent / "pdos-next-wave7-20261002/actual-preview.json").read_text()
    )
    verification = read("verification")
    assert verification == prior7["verification"]

engine = engine_for(state["app_url"])
with tenant_session(engine, UUID(state["preview_tenant_id"])) as s:
    store = OriginalStore(ROOT / ".local/objects")
    for row in (good, bad):
        original = s.get(UploadedOriginal, UUID(row["id"]))
        assert (
            hashlib.sha256(store.read_original(object_reference(original))).hexdigest()
            == row["content_hash"]
        )
        assert store.inspect(original.id).registration_state == "registered"
    source = s.get(Artifact, UUID(good["artifact_id"]))
    assert source.status == "withdrawn" and source.revision == 2
    receipt_rows = list(s.scalars(select(Receipt).where(Receipt.product_id == UUID(product_id))))
    wave8_receipts = [
        r
        for r in receipt_rows
        if r.operation
        in {
            "evidence.original.scan.request",
            "evidence.original.scan.record",
            "evidence.original.withdraw",
        }
    ]
    for receipt in wave8_receipts:
        assert (
            s.scalar(select(func.count()).select_from(Audit).where(Audit.receipt_id == receipt.id))
            == 1
        )
        assert (
            s.scalar(
                select(func.count()).select_from(Outbox).where(Outbox.receipt_id == receipt.id)
            )
            == 1
        )
    scan_results = list(s.scalars(select(OriginalScanResult)))
    assert len(scan_results) == 5
    result_counts = dict(Counter(row.status for row in scan_results))
    assert result_counts == {"clean": 4, "infected": 1}
    receipt_ids = [str(r.id) for r in wave8_receipts]
    assert s.scalar(text("SELECT count(*) FROM model_invocations")) == 0
with engine_for(state["admin_url"]).connect() as connection:
    head = connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert head == "next_0010"
    tables = (
        connection.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                "AND tablename NOT IN ('alembic_version','environment_guard')"
            )
        )
        .scalars()
        .all()
    )
    assert set(tables) == set(Base.metadata.tables)
    privileges = sum(
        bool(
            connection.scalar(
                text("SELECT has_table_privilege('pdos_agent', :name, 'INSERT,UPDATE,DELETE')"),
                {"name": name},
            )
        )
        for name in tables
    )
    assert privileges == 0

backup = ROOT / ".local/wave8-business.dump"
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
        stderr=subprocess.DEVNULL,
        check=True,
    )
result = {
    "schema_head": head,
    "business_marker": state["marker"],
    "business_port": state["port"],
    "originals": list(originals.values()),
    "legacy_scans_and_exact_downloads": 3,
    "actual_scanner_results": result_counts,
    "new_clean_original_parsed_then_named_withdrawn": True,
    "infected_original_never_parsed_or_downloaded": True,
    "withdrawn_bytes_and_history_retained": True,
    "audit_and_outbox_each_once": True,
    "wave8_receipts": receipt_ids,
    "plan_unchanged": True,
    "verification_unchanged": True,
    "model_calls": 0,
    "agent_business_write_privileges": privileges,
    "business_table_count": len(tables),
    "backup_bytes": backup.stat().st_size,
    "limitations": [
        "Local synthetic profile, not production qualification",
        "Legacy journal coverage remains unknown",
        "Physical lifecycle actions/OCR/S3 runtime are not completed",
        "No real model or business egress",
    ],
}
(REPORT / "actual-preview.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print("Five actual scans, named withdrawal, exact retained bytes and prior history verified.")
