"""Read back browser-created synthetic supply history in our marked environment."""

import hashlib
import json
import subprocess
from decimal import Decimal
from uuid import UUID

import httpx
from local_environment import ROOT, read_state, verified
from pdos_next.database import engine_for, tenant_session
from pdos_next.models import Audit, Outbox, Receipt
from sqlalchemy import func, select, text

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave5-20261002"
state = verified(read_state())
product_id = state["preview_product_id"]
prior = json.loads((REPORT.parent / "pdos-next-wave3-20261002/actual-preview.json").read_text())
with httpx.Client(
    base_url="http://127.0.0.1:8898", trust_env=False,
    headers={"Authorization": "Bearer " + state["preview_token"]},
) as client:
    def read(resource):
        response = client.get(f"/v1/products/{product_id}/{resource}")
        if response.status_code != 200:
            raise RuntimeError("Own synthetic preview read unavailable")
        return response.json()

    build = next(row for row in read("builds")["items"] if row["id"] == prior["build"]["id"])
    assert build == prior["build"], "Supply must not rewrite fixed plan or preparation"
    supply = read("supply")
    snapshots = sorted(
        [row for row in supply["snapshots"] if row["build_id"] == build["id"]],
        key=lambda row: int(row["revision"]),
    )
    assert len(snapshots) == 2
    for row, quantity in zip(snapshots, ["12", "15"], strict=True):
        assert row["scope_complete"] is False
        assert len(row["pools"]) == 1
        assert Decimal(row["pools"][0]["quantity"]) == Decimal(quantity)
        assert row["pools"][0]["quality"] == "unknown"
        assert row["pools"][0]["availability"] == "unknown"
        commitments = [record for record in row["records"] if record["record_kind"] == "commitment"]
        assert len(commitments) == 1 and Decimal(commitments[0]["quantity"]) == 100
    assert snapshots[0]["freshness"] == "historical"
    assert snapshots[1]["freshness"] == "current"
    assert snapshots[1]["reconciliation"]["before_snapshot_id"] == snapshots[0]["id"]
    assert snapshots[1]["reconciliation"]["deltas"]
    assert supply["current_by_build"][build["id"]]["snapshot_id"] == snapshots[1]["id"]
    kits = [row for row in supply["kits"] if row["build_id"] == build["id"]]
    assert len(kits) == 2
    for row in kits:
        result = row["result"]
        assert result["secured_ready"] is None and result["potential_ready"] is None
        assert result["input_snapshot"]["supply_scope_complete"] is False
        demands = {line["demand"]["item_id"]: line["demand"] for line in result["lines"]}
        assert Decimal(demands["motor"]["required_quantity"]) == 22
        assert demands["housing"]["required_quantity"] is None
    assert {row["freshness"] for row in kits} == {"current", "requires_recalculation"}
    assert all(row["applied_snapshot_id"] for row in supply["captures"])
    assert len(read("build-execution")["samples"]) == 2
    assert read("model-calls")["items"] == []

operations = {"supply.snapshot.record", "supply.kit.compute"}
with tenant_session(engine_for(state["app_url"]), UUID(state["preview_tenant_id"])) as session:
    receipts = session.scalars(select(Receipt).where(
        Receipt.product_id == UUID(product_id), Receipt.operation.in_(operations),
    )).all()
    assert len(receipts) == 4
    for operation in operations:
        assert sum(row.operation == operation for row in receipts) == 2
    for receipt in receipts:
        for model in (Audit, Outbox):
            assert session.scalar(select(func.count()).select_from(model).where(
                model.receipt_id == receipt.id,
            )) == 1
    receipt_ids = [str(row.id) for row in receipts]
with engine_for(state["admin_url"]).connect() as connection:
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "next_0007"
    tables = connection.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
        "AND tablename NOT IN ('alembic_version','environment_guard')"
    )).scalars().all()
    for name in tables:
        assert not connection.scalar(text(
            "SELECT has_table_privilege('pdos_agent', :name, 'INSERT,UPDATE,DELETE')"
        ), {"name": name})
backup = ROOT / ".local/wave5-business.dump"
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
    "product_id": product_id, "schema_head": "next_0007", "business_marker": state["marker"],
    "business_port": state["port"], "business_table_count": len(tables),
    "plan_and_readiness_unchanged": True, "sample_identities_preserved": True,
    "supply": supply, "receipt_ids": receipt_ids, "audit_and_outbox_each_once": True,
    "model_calls": 0, "agent_business_write_privileges": 0,
    "backups": {path.name: {"bytes": path.stat().st_size,
                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                           "mode": oct(path.stat().st_mode & 0o777)}
                for path in [ROOT / ".local/pre-wave5-next_0006.dump", backup]},
    "limitations": (
        "Synthetic observations only; incomplete stock/reservations and unknown quality. "
        "No start, release, real qualification, or costing claim."
    ),
}
(REPORT / "actual-preview.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print("Synthetic supply: 12→15 observed, 100 committed separately, need22/unknown retained")
