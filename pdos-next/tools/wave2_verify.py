"""Read actual local preview outcomes and retain task-owned synthetic backups."""

import hashlib
import json
import subprocess
from uuid import UUID

import httpx
from local_environment import ROOT, read_state, verified
from pdos_next.database import engine_for, tenant_session
from pdos_next.models import Audit, Grant, Outbox, Principal, Receipt
from pdos_next.workflows.checkpoints import verified_checkpoint_url
from sqlalchemy import func, select, text
from workflow_environment import read_verified

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave2-20261002"
state = verified(read_state())
workflows = read_verified()
import os  # noqa: E402

from workflow_environment import state_environment  # noqa: E402

os.environ.update(state_environment(workflows))
verified_checkpoint_url(workflows["checkpoint_url"])
product = state["preview_product_id"]
with httpx.Client(
    base_url="http://127.0.0.1:8898",
    trust_env=False,
    headers={"Authorization": "Bearer " + state["preview_token"]},
) as client:

    def read(path):
        response = client.get(path)
        if response.status_code != 200:
            raise RuntimeError("Local preview result unavailable")
        return response.json()

    definitions = read(f"/v1/products/{product}/definitions")["items"]
    variants = read(f"/v1/products/{product}/variants")["items"]
    projects = read(f"/v1/products/{product}/projects")["items"]
    calls = read(f"/v1/products/{product}/model-calls")["items"]
    project = next(item for item in projects if item["name"] == "合成研发项目 · 工程与NPI")
    variant = next(item for item in variants if item["name"] == "合成地区配置 · A")
    assert project["definition"]["revision"] == 2 and definitions[0]["revision"] == 3
    assert len(project["tasks"]) == len(project["work_packages"]) == 2
    assert project["plan"]["revision"] == 1 and project["revision"] == 2
    assert project["timeline"]["baseline"] is project["timeline"]["commitment"] is None
    assert project["timeline"]["actual"] is None
    npi = next(task for task in project["plan"]["forecast"]["tasks"] if task["discipline"] == "npi")
    assert npi["duration_min_minutes"] is npi["duration_max_minutes"] is None
    assert npi["earliest_finish"] is npi["latest_finish"] is None
    assert [item["revision"] for item in variant["revisions"]] == [2, 1]
    assert [item["parent_revision"] for item in variant["revisions"]] == [3, 2]
    assert variant["revisions"][0]["choices"][0]["selection"] == "child"
    assert calls == []
    compare = read(
        f"/v1/products/{product}/variants/{variant['id']}/compare"
        f"?parent_definition_id={definitions[0]['id']}"
    )

tenant = UUID(state["preview_tenant_id"])
with tenant_session(engine_for(state["app_url"]), tenant) as session:
    receipts = session.scalars(
        select(Receipt).where(
            Receipt.product_id == UUID(product),
            Receipt.operation.in_(
                {
                    "project.create",
                    "work.plan.propose",
                    "work.plan.apply",
                    "product.variant.derive",
                    "product.variant.rebase",
                }
            ),
        )
    ).all()
    assert len(receipts) == 5
    receipt_ids = [str(row.id) for row in receipts]
    for receipt in receipts:
        assert (
            session.scalar(
                select(func.count()).select_from(Audit).where(Audit.receipt_id == receipt.id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count()).select_from(Outbox).where(Outbox.receipt_id == receipt.id)
            )
            == 1
        )
    owner = session.get(Principal, receipts[0].requester_id)
    grant = session.scalar(
        select(Grant).where(Grant.product_id == UUID(product), Grant.principal_id == owner.id)
    )
    assert grant.can_write
with engine_for(state["admin_url"]).connect() as connection:
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "next_0004"
    business_tables = (
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
            text(
                "SELECT has_table_privilege('pdos_agent', :name, 'INSERT') "
                "OR has_table_privilege('pdos_agent', :name, 'UPDATE') "
                "OR has_table_privilege('pdos_agent', :name, 'DELETE')"
            ),
            {"name": name},
        )
        for name in business_tables
    )

backups = []
for container, database, name in [
    (state["container"], "pdos_test", "wave2-business.dump"),
    (workflows["db_container"], "pdos_checkpoints", "wave2-checkpoints.dump"),
]:
    path = ROOT / ".local" / name
    if not path.exists():
        with path.open("xb") as output:
            path.chmod(0o600)
            result = subprocess.run(
                ["docker", "exec", container, "pg_dump", "-U", "postgres", "-d", database, "-Fc"],
                stdout=output,
                stderr=subprocess.DEVNULL,
            )
        if result.returncode:
            raise RuntimeError("Own synthetic backup failed")
    if path.stat().st_size == 0 or path.stat().st_mode & 0o077:
        raise RuntimeError("Retained own backup invalid or not private")
    backups.append(
        {
            "path": str(path.relative_to(ROOT)),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    )

report = {
    "product_id": product,
    "project": project,
    "variant": variant,
    "post_rebase_compare": compare,
    "receipt_ids": receipt_ids,
    "audit_outbox_per_receipt": 1,
    "own_preview_model_calls": 0,
    "schema_head": "next_0004",
    "agent_business_writes": 0,
    "database_port": state["port"],
    "marker": state["marker"],
    "backups": backups,
}
(REPORT / "actual-preview.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print(
    "Actual synthetic preview: fixed definition, two variant versions, "
    "first plan and 5 receipt groups verified"
)
