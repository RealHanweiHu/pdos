"""Read back the browser-created synthetic cost history in our marked environment."""

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

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave6-20261002"
state = verified(read_state())
product_id = state["preview_product_id"]
previous = json.loads((REPORT.parent / "pdos-next-wave3-20261002/actual-preview.json").read_text())
prior_supply = json.loads(
    (REPORT.parent / "pdos-next-wave5-20261002/actual-preview.json").read_text()
)
with httpx.Client(
    base_url="http://127.0.0.1:8898", trust_env=False,
    headers={"Authorization": "Bearer " + state["preview_token"]},
) as client:
    def read(resource):
        response = client.get(f"/v1/products/{product_id}/{resource}")
        if response.status_code != 200:
            raise RuntimeError("Own synthetic preview read unavailable")
        return response.json()

    build = next(row for row in read("builds")["items"] if row["id"] == previous["build"]["id"])
    assert build == previous["build"], "Costs must not rewrite the fixed plan or preparation"
    costs = read("costs")
    inputs = sorted(
        [row for row in costs["inputs"] if row["build_id"] == build["id"]],
        key=lambda row: int(row["revision"]),
    )
    assert len(inputs) == 2 and [row["revision"] for row in inputs] == [1, 2]
    assert inputs[0]["freshness"] == "historical"
    assert inputs[1]["freshness"] == "current"
    assert inputs[1]["previous_input_id"] == inputs[0]["id"]
    assert inputs[1]["comparison"]["deltas"]
    assert costs["current_by_build"][build["id"]]["input_id"] == inputs[1]["id"]
    estimates = sorted(
        [row for row in costs["estimates"] if row["build_id"] == build["id"]],
        key=lambda row: row["created_at"],
    )
    assert len(estimates) == 2
    for estimate, subtotal in zip(estimates, ["220", "316.8"], strict=True):
        result = estimate["result"]
        assert result["complete_in_selected_scope"] is False
        assert result["build_candidate"] is None and result["per_product_candidate"] is None
        assert result["currency"] == "CNY"
        assert Decimal(result["known_build_subtotal"]) == Decimal(subtotal)
        assert Decimal(result["input_snapshot"]["basis"]["build"]["quantity"]) == 10
        motor = next(line for line in result["lines"] if line["line_id"] == "material:motor")
        housing = next(line for line in result["lines"] if line["line_id"] == "material:housing")
        assert Decimal(motor["quantity_for_build"]) == 22
        assert housing["quantity_for_build"] is None and housing["build_candidate"] is None
    last = estimates[-1]["result"]
    assert Decimal(last["known_nre_subtotal"]) == 1000
    assert last["input_snapshot"]["scope"]["nre_policy"] == "separate"
    rate = last["input_snapshot"]["rates"][0]
    assert Decimal(rate["rate"]) == Decimal("7.2") and rate["purpose"] == "budget"
    assert rate["ref"]["captured_at"].startswith("2026-10-02T12:00:00")
    assert rate["from_currency"] == "USD" and rate["to_currency"] == "CNY"
    assert {row["freshness"] for row in estimates} == {"current", "requires_recalculation"}
    assert all(row["applied_input_id"] for row in costs["captures"])
    supply = read("supply")
    for key in ("snapshots", "kits"):
        assert {row["id"] for row in supply[key]} == {
            row["id"] for row in prior_supply["supply"][key]
        }
    assert len(read("build-execution")["samples"]) == 2
    assert read("model-calls")["items"] == []

operations = {"cost.inputs.record", "cost.estimate.compute"}
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
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "next_0008"
    tables = connection.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
        "AND tablename NOT IN ('alembic_version','environment_guard')"
    )).scalars().all()
    for name in tables:
        assert not connection.scalar(text(
            "SELECT has_table_privilege('pdos_agent', :name, 'INSERT,UPDATE,DELETE')"
        ), {"name": name})
backup = ROOT / ".local/wave6-business.dump"
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
    "product_id": product_id, "schema_head": "next_0008", "business_marker": state["marker"],
    "business_port": state["port"], "business_table_count": len(tables),
    "plan_and_readiness_unchanged": True, "sample_and_supply_history_preserved": True,
    "costs": costs, "receipt_ids": receipt_ids, "audit_and_outbox_each_once": True,
    "model_calls": 0, "agent_business_write_privileges": 0,
    "backups": {path.name: {"bytes": path.stat().st_size,
                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                           "mode": oct(path.stat().st_mode & 0o777)}
                for path in [ROOT / ".local/pre-wave6-next_0007.dump", backup]},
    "limitations": (
        "Synthetic selected-scope cost candidates only. Missing housing cost retained. "
        "No purchase, actual financial cost, approval, proven savings or model call."
    ),
}
(REPORT / "actual-preview.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print("Synthetic costs: known CNY220→316.8, NRE1000 separate, complete total unknown")
