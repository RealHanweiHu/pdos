"""Read back browser-created preparation versions on our marked synthetic environment."""

import hashlib
import json
import subprocess
from uuid import UUID

import httpx
from local_environment import ROOT, read_state, verified
from pdos_next.database import engine_for, tenant_session
from pdos_next.models import Audit, Outbox, Receipt
from sqlalchemy import func, select, text

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave7-20261002"
state = verified(read_state())
product_id = state["preview_product_id"]
prior = {
    wave: json.loads((REPORT.parent / f"pdos-next-wave{wave}-20261002/actual-preview.json")
                     .read_text())
    for wave in (3, 4, 5, 6)
}
with httpx.Client(
    base_url="http://127.0.0.1:8898", trust_env=False,
    headers={"Authorization": "Bearer " + state["preview_token"]},
) as client:
    def read(resource):
        response = client.get(f"/v1/products/{product_id}/{resource}")
        if response.status_code != 200:
            raise RuntimeError("Own synthetic preview read unavailable")
        return response.json()

    build = next(row for row in read("builds")["items"] if row["id"] == prior[3]["build"]["id"])
    assert build == prior[3]["build"], "Preparation must not rewrite the fixed plan"
    verification = read("verification")
    versions = sorted(verification["preparations"], key=lambda row: row["revision"])
    assert len(versions) == 2 and [row["revision"] for row in versions] == [1, 2]
    first, latest = versions
    assert first["request_id"] == latest["request_id"]
    assert latest["previous_preparation_id"] == first["id"]
    assert latest["previous_revision"] == 1
    assert not first["is_current"] and latest["is_current"]
    assert verification["current_by_request"][latest["request_id"]] == {
        "preparation_id": latest["id"], "revision": 2,
    }
    assert first["first_prepared_at"] == latest["first_prepared_at"]
    assert first["expected_at"].startswith("2026-10-05T16:00:00")
    assert latest["expected_at"].startswith("2026-10-06T16:00:00")
    assert all(row["expected_timezone"] == "America/Los_Angeles" for row in versions)
    for row in versions:
        assert row["build_id"] == build["id"] and row["build_revision"] == build["revision"]
        assert row["status"] == "prepared" and row["request_state"] == "draft"
        snapshot = row["request_snapshot"]
        assert all(snapshot[key] == [] for key in (
            "samples", "acceptances", "offered_coverage", "returns",
        ))
        assert snapshot["timeline"]["request_created"]["source"]["kind"] == "command"
        assert all(value is None for key, value in snapshot["timeline"].items()
                   if key != "request_created")
        assert row["document_gaps"] and row["coverage_gaps"]
        assert row["method_applicability"] == row["qualification_status"] == "unknown"
        assert row["reference_samples_are_accepted"] is False
        assert all(value is False for key, value in row["capabilities"].items()
                   if key != "preparation_record")
    pressure1 = next(item for item in first["items"] if item["feature"] == "合成压力检查")
    pressure2 = next(item for item in latest["items"] if item["feature"] == "合成压力检查")
    assert pressure1["drawing"] is pressure1["method"] is None
    assert pressure2["drawing"]["line"] == 3 and pressure2["method"]["line"] == 4
    assert len(first["document_gaps"]) - len(latest["document_gaps"]) == 2
    assert first["coverage_gaps"] == latest["coverage_gaps"]
    assert verification["runs"] == []
    assert len(verification["reference_samples"]) == 2
    assert {row["availability"] for row in verification["reference_samples"]} <= {"unknown", "hold"}
    execution = read("build-execution")
    assert verification["reference_samples"] == execution["samples"]
    assert {row["id"] for row in execution["samples"]} == {
        row["id"] for row in prior[4]["samples"]
    }
    for resource, keys, wave in (("supply", ("snapshots", "kits"), 5),
                                 ("costs", ("inputs", "estimates"), 6)):
        current = read(resource)
        for key in keys:
            assert {row["id"] for row in current[key]} == {
                row["id"] for row in prior[wave][resource][key]
            }
    assert read("model-calls")["items"] == []

with tenant_session(engine_for(state["app_url"]), UUID(state["preview_tenant_id"])) as session:
    receipts = session.scalars(select(Receipt).where(
        Receipt.product_id == UUID(product_id),
        Receipt.operation == "verification.preparation.record",
    )).all()
    assert len(receipts) == 2
    for receipt in receipts:
        for model in (Audit, Outbox):
            assert session.scalar(select(func.count()).select_from(model).where(
                model.receipt_id == receipt.id,
            )) == 1
    receipt_ids = [str(row.id) for row in receipts]
with engine_for(state["admin_url"]).connect() as connection:
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "next_0009"
    tables = connection.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
        "AND tablename NOT IN ('alembic_version','environment_guard')"
    )).scalars().all()
    for name in tables:
        assert not connection.scalar(text(
            "SELECT has_table_privilege('pdos_agent', :name, 'INSERT,UPDATE,DELETE')"
        ), {"name": name})
backup = ROOT / ".local/wave7-business.dump"
if not backup.exists():
    with backup.open("xb") as output:
        backup.chmod(0o600)
        saved = subprocess.run(
            ["docker", "exec", state["container"], "pg_dump", "-U", "postgres",
             "-d", "pdos_test", "-Fc"], stdout=output, stderr=subprocess.DEVNULL,
        )
        if saved.returncode:
            raise RuntimeError("Own synthetic environment backup failed")
result = {
    "product_id": product_id, "schema_head": "next_0009", "business_marker": state["marker"],
    "business_port": state["port"], "business_table_count": len(tables),
    "plan_unchanged": True, "sample_supply_and_cost_history_preserved": True,
    "verification": verification, "receipt_ids": receipt_ids, "audit_and_outbox_each_once": True,
    "model_calls": 0, "agent_business_write_privileges": 0,
    "backups": {path.name: {"bytes": path.stat().st_size,
                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                           "mode": oct(path.stat().st_mode & 0o777)}
                for path in [ROOT / ".local/pre-wave7-next_0008.dump", backup]},
    "limitations": "Synthetic human preparation versions only; no qualification, acceptance, "
                   "reservation, physical readiness, TestRun, measurements or formal Exit.",
}
(REPORT / "actual-preview.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print("Synthetic preparation v1→v2: two source gaps resolved; physical clocks and TestRuns absent")
