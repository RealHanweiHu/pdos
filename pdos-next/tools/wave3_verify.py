"""Read the actual browser-created Wave3 synthetic loop and retain own backups."""

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

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave3-20261002"
state = verified(read_state())
product_id = state["preview_product_id"]

with httpx.Client(
    base_url="http://127.0.0.1:8898",
    trust_env=False,
    headers={"Authorization": "Bearer " + state["preview_token"]},
) as client:

    def read(resource):
        response = client.get(f"/v1/products/{product_id}/{resource}")
        if response.status_code != 200:
            raise RuntimeError("Own preview resource unavailable")
        return response.json()

    configurations = read("configurations")
    builds = read("builds")
    projects = read("projects")
    calls = read("model-calls")
    build = next(row for row in builds["items"] if row["name"] == "合成原型试制 · 第1轮")
    engineering = build["engineering_configuration"]
    process = build["manufacturing_configuration"]
    project = next(row for row in projects["items"] if row["id"] == build["project_id"])
    assert project["definition"]["id"] == engineering["definition_id"]
    assert process["engineering_configuration_id"] == engineering["id"]
    assert engineering["status"] == process["status"] == "draft"
    assert build["status"] == "planned" and Decimal(build["planned_quantity"]) == 10
    assert build["source_status"] == "current" and build["readiness"]["is_current"]
    result = build["readiness"]["result"]
    assert result["ready"] is None and result["hard_blocking"] is True
    known = [row for row in result["demands"] if row["required_quantity"] is not None]
    unknown = [row for row in result["demands"] if row["required_quantity"] is None]
    assert len(known) == len(unknown) == 1
    assert Decimal(known[0]["required_quantity"]) == 22
    assert not result["coverage"]["input_snapshot"]["supply_scope_complete"]
    assert result["coverage"]["input_snapshot"]["pools"] == []
    assert (
        result["input_snapshot"]["build"]["metadata"]["verification_objectives"]
        == (build["verification_objectives"])
    )
    assert calls["items"] == []

operations = {
    "engineering.bom.revise",
    "engineering.configuration.create",
    "npi.process.revise",
    "build.create",
    "build.readiness.compute",
}
with tenant_session(engine_for(state["app_url"]), UUID(state["preview_tenant_id"])) as session:
    receipts = session.scalars(
        select(Receipt).where(
            Receipt.product_id == UUID(product_id),
            Receipt.operation.in_(operations),
        )
    ).all()
    assert len(receipts) == 5 and {row.operation for row in receipts} == operations
    for row in receipts:
        for model in (Audit, Outbox):
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.receipt_id == row.id)
                )
                == 1
            )
    receipt_ids = [str(row.id) for row in receipts]

with engine_for(state["admin_url"]).connect() as connection:
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "next_0005"
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
    assert not any(
        connection.scalar(
            text("SELECT has_table_privilege('pdos_agent', :name, 'INSERT,UPDATE,DELETE')"),
            {"name": name},
        )
        for name in tables
    )

backup = ROOT / ".local/wave3-business.dump"
if not backup.exists():
    with backup.open("xb") as output:
        backup.chmod(0o600)
        saved = subprocess.run(
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
        )
        if saved.returncode:
            raise RuntimeError("Own database backup failed")
backups = {
    path.name: {
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "mode": oct(path.stat().st_mode & 0o777),
    }
    for path in [ROOT / ".local/pre-wave3-next_0004.dump", backup]
}
result = {
    "product_id": product_id,
    "schema_head": "next_0005",
    "business_port": state["port"],
    "business_marker": state["marker"],
    "business_table_count": len(tables),
    "build": build,
    "configuration_counts": {
        key: len(configurations[key]) for key in ("boms", "engineering", "processes")
    },
    "receipt_ids": receipt_ids,
    "audit_and_outbox_each_once": True,
    "model_calls": 0,
    "agent_business_write_privileges": 0,
    "backups": backups,
}
(REPORT / "actual-preview.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print(
    "Actual own preview: fixed configurations, Build, "
    "22 known/1 unknown demand, five receipts verified"
)
