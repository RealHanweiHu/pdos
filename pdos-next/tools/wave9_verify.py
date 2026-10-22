"""Actual synthetic lifecycle readback; uses only this task's verified environment."""

import base64
import hashlib
import json
import sys
from uuid import UUID

import httpx
from local_environment import ROOT, read_state, verified
from pdos_next.contracts import UploadInput
from pdos_next.database import engine_for, tenant_session
from pdos_next.domain.original_lifecycle_execution.codec import decode_intent
from pdos_next.models import (
    Audit,
    Base,
    LifecycleIntentRecord,
    Outbox,
    Product,
    Receipt,
    UploadAttempt,
    UploadedOriginal,
)
from pdos_next.original_store import OriginalStore
from pdos_next.service import Context
from pdos_next.upload_lifecycle import exact_reference, named, reserve
from sqlalchemy import func, select, text

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave9-20261002"
state = verified(read_state())
engine = engine_for(state["app_url"])
tenant, product_id = UUID(state["preview_tenant_id"]), UUID(state["preview_product_id"])
store = OriginalStore(ROOT / ".local/objects")
action = sys.argv[1]
if action == "seed-interrupted":
    content = (
        b"Wave9 synthetic interrupted upload. Exact bytes must survive isolation and restoration.\n"
    )
    with tenant_session(engine, tenant) as s:
        product = s.get(Product, product_id)
        ctx = Context(tenant, product.owner_id, product.owner_id)
        data = UploadInput(
            title="第九波中断上传演练",
            filename="wave9-interrupted.txt",
            source_label="仅本地合成资料；模拟写完字节后未完成业务登记",
            visibility="private",
            content_base64=base64.b64encode(content).decode(),
            expected_revision=product.revision,
            idempotency_key="wave9-interrupted-20261002",
        )
        identity = reserve(s, ctx, product_id, data)
        if identity is None:
            raise RuntimeError("Synthetic upload has already registered")
    with tenant_session(engine, tenant) as s:
        named(s, ctx, product_id)
        attempt = s.get(UploadAttempt, identity)
        if attempt.status != "reserved":
            raise RuntimeError("Synthetic upload has already been closed")
        reference = store.put_scoped(
            content,
            media_type="text/plain",
            tenant_id=tenant,
            product_id=product_id,
            requester_id=ctx.requester_id,
            upload_id=identity,
        )
        assert reference == exact_reference(attempt.reference)
        assert s.get(UploadedOriginal, identity) is None
    journal = store.inspect(identity)
    assert journal.registration_state == "unknown" and journal.byte_status == "intact"
    result = {
        "object_id": str(identity),
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
        "registered": None,
        "upload_state": "reserved",
        "source": "explicit local synthetic interruption; no true business material",
    }
    (REPORT / "interrupted-upload.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    raise SystemExit(0)
if action != "readback":
    raise RuntimeError("Unknown Wave9 verification action")
seed = json.loads((REPORT / "interrupted-upload.json").read_text())
identity = UUID(seed["object_id"])
with httpx.Client(
    base_url="http://127.0.0.1:8898",
    trust_env=False,
    timeout=30,
    headers={"Authorization": "Bearer " + state["preview_token"]},
) as client:
    prefix = f"/v1/products/{product_id}"

    def read(resource):
        response = client.get(f"{prefix}/{resource}")
        assert response.status_code == 200, (resource, response.status_code)
        return response.json()

    inventory = read("original-lifecycle")
    item = next(row for row in inventory["items"] if row["id"] == str(identity))
    assert item["registered"] is False and item["upload_state"] == "abandoned"
    assert item["disposition"] == "active" and item["pending_intent_id"] is None
    assert item["coverage_complete"] and item["reference_count"] == 0
    assert {row["action"] for row in item["intents"]} == {"quarantine", "restore"}
    assert sorted(row["state"] for row in item["intents"]) == ["applied", "applied", "cancelled"]
    workspace = read("workspace")
    originals = {row["filename"]: row for row in workspace["originals"]}
    assert "wave9-interrupted.txt" not in originals
    downloads = {}
    for filename in ("browser-synthetic.txt", "browser-synthetic.pdf", "browser-synthetic.xlsx"):
        row = originals[filename]
        response = client.get(f"{prefix}/originals/{row['id']}/download")
        assert response.status_code == 200
        assert hashlib.sha256(response.content).hexdigest() == row["content_hash"]
        downloads[filename] = "exact original hash"
    for filename in ("wave8-source.txt", "wave8-antivirus-test.txt"):
        row = originals[filename]
        assert client.get(f"{prefix}/originals/{row['id']}/download").status_code == 409
    previous3 = json.loads(
        (REPORT.parent / "pdos-next-wave3-20261002/actual-preview.json").read_text()
    )
    previous7 = json.loads(
        (REPORT.parent / "pdos-next-wave7-20261002/actual-preview.json").read_text()
    )
    assert (
        next(row for row in read("builds")["items"] if row["id"] == previous3["build"]["id"])
        == previous3["build"]
    )
    assert read("verification") == previous7["verification"]
with tenant_session(engine, tenant) as s:
    product = s.get(Product, product_id)
    named(s, Context(tenant, product.owner_id, product.owner_id), product_id)
    attempt = s.get(UploadAttempt, identity)
    reference = exact_reference(attempt.reference)
    assert hashlib.sha256(store.read_original(reference)).hexdigest() == seed["content_sha256"]
    assert (
        hashlib.sha256((store.root / reference.server_storage_key).read_bytes()).hexdigest()
        == seed["content_sha256"]
    )
    intents = list(
        s.scalars(select(LifecycleIntentRecord).where(LifecycleIntentRecord.object_id == identity))
    )
    assert len(intents) == 3
    for row in intents:
        intent = decode_intent(row.document)
        if intent.state.value == "cancelled":
            assert intent.permit is None and intent.receipt is None
            continue
        assert intent.permit.attempt == 1 and intent.receipt.outcome.value == "applied"
    subjects = {identity, *(row.id for row in intents)}
    receipts = list(s.scalars(select(Receipt).where(Receipt.subject_id.in_(subjects))))
    for row in receipts:
        assert (
            s.scalar(select(func.count()).select_from(Audit).where(Audit.receipt_id == row.id)) == 1
        )
        event = s.scalar(select(Outbox).where(Outbox.receipt_id == row.id))
        assert event is not None and event.delivered_at is not None
    receipt_ids = [str(row.id) for row in receipts]
with engine_for(state["admin_url"]).connect() as c:
    head = c.scalar(text("SELECT version_num FROM alembic_version"))
    assert head == "next_0012"
    for table in Base.metadata.tables:
        assert not c.scalar(
            text("SELECT has_table_privilege('pdos_agent',:table,'INSERT,UPDATE,DELETE')"),
            {"table": table},
        )
    model_calls = c.scalar(
        text("SELECT count(*) FROM model_invocations WHERE tenant_id=:tenant"),
        {"tenant": tenant},
    )
    assert model_calls == 0
result = {
    "scope": "actual local synthetic API + worker + retained bytes; no production qualification",
    "head": head,
    "business_tables": len(Base.metadata.tables),
    "agent_business_writes": 0,
    "model_calls": model_calls,
    "model_call_scope": "actual preview tenant; unrelated isolated test fixtures excluded",
    "lifecycle": item,
    "receipt_ids": receipt_ids,
    "registered_original_downloads": downloads,
    "wave8_withdrawn_infected_still_blocked": True,
    "build_and_verification_unchanged": True,
    "exact_bytes_retained": True,
    "no_physical_move_or_purge": True,
}
(REPORT / "actual-preview.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print("Actual lifecycle, one-attempt effects, receipts, retained bytes and prior history verified.")
