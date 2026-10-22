"""Local synthetic professional front-stage evidence, confined to the marked instance."""

import hashlib
import json
import sys
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
from local_environment import ROOT, read_state, verified
from pdos_next.contracts import Command
from pdos_next.database import engine_for, tenant_session
from pdos_next.domain.professional_authority.service import configure_local_synthetic
from pdos_next.models import Artifact, Audit, Outbox, Product, Receipt
from pdos_next.professional_import import import_professional_fact
from pdos_next.service import Context, execute
from sqlalchemy import func, select, text

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave10-20261002"
state = verified(read_state())
engine = engine_for(state["app_url"])
tenant, product_id = UUID(state["preview_tenant_id"]), UUID(state["preview_product_id"])
action = sys.argv[1]
with httpx.Client(
    base_url="http://127.0.0.1:8898",
    trust_env=False,
    timeout=120,
    headers={"Authorization": "Bearer " + state["preview_token"]},
) as client:

    def read(resource):
        response = client.get(f"/v1/products/{product_id}/{resource}")
        if response.status_code != 200:
            raise RuntimeError(f"Own synthetic {resource} unavailable ({response.status_code})")
        return response.json()

    if action == "seed-authority":
        preparation = next(row for row in read("verification")["preparations"] if row["is_current"])
        project_id = UUID(preparation["project_id"])
        source_text = (
            "第十波本地合成品质职责与人员资格事实，仅用于独立临时实例的专业验证前段。"
            "不代表真实任命、认证、测试授权或生产资格。"
        )
        issuer = configure_local_synthetic(
            engine,
            tenant_id=tenant,
            product_id=product_id,
            enabled=True,
        )
        receipts = []
        with tenant_session(engine, tenant) as session:
            product = session.get(Product, product_id)
            ctx = Context(tenant, product.owner_id, product.owner_id)
            source = execute(
                session,
                ctx,
                Command(
                    command_id=uuid4(),
                    idempotency_key="wave10-synthetic-authority-source",
                    operation="evidence.artifact.register",
                    product_id=product_id,
                    expected_revision=product.revision,
                    payload={
                        "title": "第十波本地合成专业资格依据",
                        "content": source_text,
                        "source_label": "显式本地合成签发；不授真实资格",
                        "visibility": "private",
                    },
                ),
            )
            artifact = session.get(Artifact, UUID(source["subject_id"]))
            reference = {
                "artifact_id": str(artifact.id),
                "expected_revision": artifact.revision,
                "line": 1,
                "quote": source_text,
            }
            for kind in ("duty", "qualification"):
                payload = {
                    "product_id": str(product_id),
                    "project_id": str(project_id),
                    "subject_id": str(ctx.requester_id),
                    "external_id": f"wave10-synthetic-{kind}",
                    "kind": kind,
                    "role": "quality",
                    "operations": [
                        "verification.request.create",
                        "verification.method.prepare",
                        "verification.schedule.propose",
                    ],
                    "purposes": [preparation["purpose"]],
                    "state": "active",
                    "valid_from": (artifact.created_at - timedelta(minutes=1)).isoformat(),
                    "valid_until": (artifact.created_at + timedelta(days=6)).isoformat(),
                    "approval": {
                        "system": "explicit-local-synthetic-exercise",
                        "external_id": f"wave10-synthetic-{kind}",
                        "version": "v1",
                        "approved_by": "本地合成签发人",
                        "issued_at": artifact.created_at.isoformat(),
                    },
                    "sources": [reference],
                    "reason": "仅在已核对的独立临时实例验证专业前段",
                }
                receipts.append(
                    import_professional_fact(
                        session,
                        ctx,
                        issuer,
                        payload,
                        request_key=f"wave10-synthetic-{kind}",
                        command_id=uuid4(),
                    )
                )
        result = {
            "nature": "synthetic",
            "project_id": str(project_id),
            "preparation_id": preparation["id"],
            "receipt_ids": [r["id"] for r in receipts],
        }
        (REPORT / "synthetic-authority-seed.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
        print(
            "Synthetic duty and qualification imported through trusted transactional host; "
            "no real authority granted."
        )
    elif action == "readback":
        professional, preparation = read("verification-professional"), read("verification")
        prior = json.loads(
            (REPORT.parent / "pdos-next-wave7-20261002/actual-preview.json").read_text()
        )
        assert preparation == prior["verification"], (
            "Professional front must not rewrite preparation or sample history"
        )
        build_prior = json.loads(
            (REPORT.parent / "pdos-next-wave3-20261002/actual-preview.json").read_text()
        )["build"]
        assert (
            next(row for row in read("builds")["items"] if row["id"] == build_prior["id"])
            == build_prior
        )
        versions = sorted(professional["requests"], key=lambda row: row["revision"])
        assert len(versions) == 3 and [row["revision"] for row in versions] == [1, 2, 3]
        first, method, window = versions
        assert len({row["request_id"] for row in versions}) == 1
        assert len({row["first_requested_at"] for row in versions}) == 1
        assert len({row["preparation_id"] for row in versions}) == 1
        assert [row["operation"] for row in versions] == [
            "verification.request.create",
            "verification.method.prepare",
            "verification.schedule.propose",
        ]
        assert len(method["method_assessments"]) == len(first["items"])
        assert all(row["status"] == "unknown" for row in method["method_assessments"])
        assert method["method_assessments"] == window["method_assessments"]
        assert len(window["window_proposals"]) == 1
        for row in versions:
            assert row["zero_occupancy"] is True and row["physical_timeline_empty"] is True
            assert row["document_gaps"] and row["coverage_gaps"] and not row["documents_ready"]
            assert all(
                value is None
                for key, value in row["request_snapshot"]["timeline"].items()
                if key != "request_created"
            )
        assert read("model-calls")["items"] == []
        with tenant_session(engine, tenant) as session:
            receipts = session.scalars(
                select(Receipt).where(
                    Receipt.product_id == product_id,
                    Receipt.operation.in_([row["operation"] for row in versions]),
                )
            ).all()
            assert len(receipts) == 3
            for receipt in receipts:
                for model in (Audit, Outbox):
                    assert (
                        session.scalar(
                            select(func.count())
                            .select_from(model)
                            .where(model.receipt_id == receipt.id)
                        )
                        == 1
                    )
        with engine_for(state["admin_url"]).connect() as connection:
            head = connection.scalar(text("SELECT version_num FROM alembic_version"))
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
            assert all(
                not connection.scalar(
                    text("SELECT has_table_privilege('pdos_agent', :name, 'INSERT,UPDATE,DELETE')"),
                    {"name": name},
                )
                for name in tables
            )
        result = {
            "professional": professional,
            "schema_head": head,
            "business_tables": len(tables),
            "agent_direct_writes": 0,
            "model_calls": 0,
            "same_preparation_and_build": True,
            "one_receipt_audit_outbox_per_action": True,
            "preparation_digest": hashlib.sha256(
                json.dumps(preparation, sort_keys=True).encode()
            ).hexdigest(),
        }
        (REPORT / "actual-preview.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
        print(
            "Actual synthetic request → per-item review → tentative window read back; "
            "historical preparation and Build preserved."
        )
    else:
        raise RuntimeError("Unknown Wave10 evidence action")
