"""Read-only Wave11 business comparison on the explicitly marked local instance."""

import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import httpx
from sqlalchemy import func, select, text

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "pdos-next/tools"))
from local_environment import read_state, verified  # noqa: E402
from pdos_next.database import engine_for, tenant_session  # noqa: E402
from pdos_next.domain.build_operational_facts.models import (  # noqa: E402
    MaterialHold,
    ResourceOccupancy,
)
from pdos_next.models import Audit, Outbox, Receipt  # noqa: E402

REPORT = Path(__file__).resolve().parent
state = verified(read_state())
tenant = UUID(state["preview_tenant_id"])
product = UUID(state["preview_product_id"])
with httpx.Client(
    base_url="http://127.0.0.1:8898", trust_env=False, timeout=120,
    headers={"Authorization": "Bearer " + state["preview_token"]},
) as client:
    def read(resource):
        response = client.get(f"/v1/products/{product}/{resource}")
        response.raise_for_status()
        return response.json()

    prior = json.loads((REPORT / "prior-business.json").read_text())
    current = {key: read(key) for key in prior}
    for old in prior["builds"]["items"]:
        assert next(b for b in current["builds"]["items"] if b["id"] == old["id"]) == old
    assert current["verification"] == prior["verification"]
    for key in ("requests", "current_by_request", "preparations"):
        assert current["verification-professional"][key] == prior["verification-professional"][key]
    assert all(row["zero_occupancy"] for row in current["verification-professional"]["requests"])
    view = read("build-start")
    assert len(view["starts"]) == 1
    start = view["starts"][0]
    bid = start["build_id"]
    build = next(row for row in current["builds"]["items"] if row["id"] == bid)
    assert build["revision"] == start["build_revision"] == 1
    for field in ("engineering_configuration", "manufacturing_configuration"):
        assert build[field]["id"] == start[f"{field}_id"]
    assert build["project_id"] == start["project_id"]
    decisions = [r for r in view["authorizations"] if r["build_id"] == bid]
    assert len(decisions) == 2 and {r["role"] for r in decisions} == {"engineering", "manufacturing"}
    assert all(r["status"] == "approved" and r["is_current"] for r in decisions)
    assessment = next(row for row in view["assessments"] if row["id"] == start["assessment_id"])
    assert assessment["status"] == "UNKNOWN"
    assert start["execution_result"]["state"] == "READY_WITH_CONDITIONS"
    assert start["execution_result"]["nature"] == "synthetic"
    capability = view["capabilities_by_build"][bid]
    assert capability["execution_status"] == "executing"
    assert capability["execution_qualification"] == "limited_current"
    assert capability["stop_required"] is False and capability["start"] is False
    assert read("model-calls")["items"] == []

with tenant_session(engine_for(state["app_url"]), tenant) as session:
    holds = session.scalars(select(MaterialHold).where(MaterialHold.owner_execution_id == UUID(start["id"]))).all()
    occupancies = session.scalars(select(ResourceOccupancy).where(ResourceOccupancy.owner_execution_id == UUID(start["id"]))).all()
    assert len(holds) == len(occupancies) == 1
    assert holds[0].quantity == Decimal("22") and holds[0].unit == "ea"
    assert occupancies[0].units == Decimal("1")
    assert {str(row.id) for row in holds} == set(start["reservations"]["material_holds"])
    assert {str(row.id) for row in occupancies} == set(start["reservations"]["resource_reservations"])
    subjects = [UUID(row["id"]) for row in [assessment, *decisions, start]]
    receipts = session.scalars(select(Receipt).where(Receipt.product_id == product, Receipt.subject_id.in_(subjects))).all()
    assert len(receipts) == 4
    for receipt in receipts:
        for model in (Audit, Outbox):
            assert session.scalar(select(func.count()).select_from(model).where(model.receipt_id == receipt.id)) == 1

with engine_for(state["admin_url"]).connect() as connection:
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "next_0014"
    tables = connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT IN ('alembic_version','environment_guard')")).scalars().all()
    assert len(tables) == 76
    assert all(not connection.scalar(text("SELECT has_table_privilege('pdos_agent', :name, 'INSERT,UPDATE,DELETE')"), {"name": name}) for name in tables)
    new_tables = ["build_operational_facts", "build_operational_current", "operational_asset_sentinels", "operational_material_holds", "operational_resource_occupancies", "build_execution_assessments", "build_current_execution_assessments", "build_authorization_decisions", "build_current_authorizations", "build_starts"]
    rls = {name: list(connection.execute(text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid=to_regclass(:name)"), {"name": name}).one()) for name in new_tables}
    assert all(all(v) for v in rls.values())

summary = {
    "schema_head": "next_0014", "business_tables": len(tables), "agent_direct_writes": 0,
    "new_tables_forced_rls": rls, "model_calls": 0, "nature": "synthetic",
    "old_builds_unchanged": len(prior["builds"]["items"]),
    "old_preparation_samples_and_runs_unchanged": True,
    "old_request_versions_unchanged": len(prior["verification-professional"]["requests"]),
    "old_request_occupancy": 0, "fixed_build_id": bid, "plan_revision": build["revision"],
    "assessment_status_retained": assessment["status"], "named_approvals": len(decisions),
    "start_count": 1, "start_id": start["id"], "execution_state": "READY_WITH_CONDITIONS",
    "execution_qualification": "limited_current", "stop_required": False,
    "material_holds": 1, "material_quantity": "22", "material_unit": "ea",
    "resource_occupancies": 1, "resource_units": "1", "receipt_audit_outbox_each": 4,
    "prior_business_sha256": hashlib.sha256((REPORT / "prior-business.json").read_bytes()).hexdigest(),
}
(REPORT / "actual-build-start.json").write_text(json.dumps(view, ensure_ascii=False, indent=2) + "\n")
(REPORT / "actual-preview.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(summary, ensure_ascii=False))
