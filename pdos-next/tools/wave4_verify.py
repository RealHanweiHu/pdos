"""Verify the browser-created synthetic physical ledger without granting execution."""

import hashlib
import json
import subprocess
from uuid import UUID

import httpx
from local_environment import ROOT, read_state, verified
from pdos_next.database import engine_for, tenant_session
from pdos_next.models import Audit, Outbox, Receipt
from sqlalchemy import func, select, text

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave4-20261002"
state = verified(read_state())
product_id = state["preview_product_id"]
previous = json.loads(
    (REPORT.parent / "pdos-next-wave3-20261002/actual-preview.json").read_text()
)["build"]

with httpx.Client(
    base_url="http://127.0.0.1:8898", trust_env=False,
    headers={"Authorization": "Bearer " + state["preview_token"]},
) as client:

    def read(resource):
        response = client.get(f"/v1/products/{product_id}/{resource}")
        if response.status_code != 200:
            raise RuntimeError("Own preview read resource unavailable")
        return response.json()

    execution = read("build-execution")
    build = next(row for row in read("builds")["items"] if row["id"] == previous["id"])
    assert build == previous, "Observation must not rewrite the saved plan or readiness"
    lot = next(row for row in execution["lots"] if row["lot_label"] == "合成实物批次 · 第1轮")
    actual = next(
        row for row in execution["actual_configurations"]
        if row["id"] == lot["actual_configuration_id"]
    )
    samples = [row for row in execution["samples"] if row["lot_id"] == lot["id"]]
    allocations = [row for row in execution["allocations"] if row["lot_id"] == lot["id"]]
    assert lot["observed_unit_count"] == 3 and lot["identified_count"] == 2
    assert lot["remaining_unit_count"] == 1 and lot["unit"] == "台"
    assert len(allocations) == 1 and len(samples) == 2
    assert {row["label"] for row in samples} == {"PDOS-W4-S01", "PDOS-W4-S02"}
    assert {row["availability"] for row in samples} == {"unknown", "hold"}
    for row in samples:
        assert row["actual_configuration_id"] == actual["id"]
        assert row["build_id"] == build["id"]
        assert row["reservation"] is None and row["consumption"] is None
        assert row["source_status"] == "current"
    assert read("model-calls")["items"] == []

operations = {
    "build.configuration.actual.record", "build.output.record", "build.sample.allocate",
}
with tenant_session(engine_for(state["app_url"]), UUID(state["preview_tenant_id"])) as session:
    receipts = session.scalars(select(Receipt).where(
        Receipt.product_id == UUID(product_id), Receipt.operation.in_(operations),
    )).all()
    assert len(receipts) == 3 and {row.operation for row in receipts} == operations
    for receipt in receipts:
        for model in (Audit, Outbox):
            assert session.scalar(select(func.count()).select_from(model).where(
                model.receipt_id == receipt.id,
            )) == 1
    receipt_ids = [str(row.id) for row in receipts]

with engine_for(state["admin_url"]).connect() as connection:
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "next_0006"
    tables = connection.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
        "AND tablename NOT IN ('alembic_version','environment_guard')"
    )).scalars().all()
    for name in tables:
        assert not connection.scalar(text(
            "SELECT has_table_privilege('pdos_agent', :name, 'INSERT,UPDATE,DELETE')"
        ), {"name": name})

backup = ROOT / ".local/wave4-business.dump"
if not backup.exists():
    with backup.open("xb") as output:
        backup.chmod(0o600)
        saved = subprocess.run(
            ["docker", "exec", state["container"], "pg_dump", "-U", "postgres",
             "-d", "pdos_test", "-Fc"],
            stdout=output, stderr=subprocess.DEVNULL,
        )
        if saved.returncode:
            raise RuntimeError("Own database backup failed")
backups = {
    path.name: {"bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "mode": oct(path.stat().st_mode & 0o777)}
    for path in [ROOT / ".local/pre-wave4-next_0005.dump", backup]
}
result = {
    "product_id": product_id, "schema_head": "next_0006",
    "business_marker": state["marker"], "business_port": state["port"],
    "business_table_count": len(tables), "plan_and_readiness_unchanged": True,
    "actual_configuration": actual, "lot": lot, "samples": samples,
    "allocations": allocations, "receipt_ids": receipt_ids,
    "audit_and_outbox_each_once": True, "model_calls": 0,
    "agent_business_write_privileges": 0, "backups": backups,
    "limitations": "Recorded observations only; no start authorization or quality reception.",
}
(REPORT / "actual-preview.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print("Own synthetic physical ledger verified: 3 observed units, 2 identified, 1 remaining")
