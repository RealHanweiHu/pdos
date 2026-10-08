"""Explicit synthetic candidate duty/qualification only on the marked local target."""

# Import the exact local harness before its server modules.
# ruff: noqa: I001
import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from local_environment import ROOT, read_state, verified
from wave16_closeout import private_json
from wave17_migrate import target
from pdos_next.api import create_app
from pdos_next.contracts import Command
from pdos_next.database import engine_for, tenant_session
from pdos_next.domain.professional_authority.schemas import FactInput
from pdos_next.domain.professional_authority.service import configure_local_synthetic
from pdos_next.domain.quality_execution.models import QualityIssueVersion
from pdos_next.models import Product
from pdos_next.original_store import OriginalStore
from pdos_next.professional_import import import_professional_fact
from pdos_next.security_bootstrap import local_runtime
from pdos_next.service import Context, execute
from sqlalchemy import select, text

OPERATION = "quality.capa.verification.candidate.record"
PLAN = ROOT / ".local/wave17-candidate-demo.json"


def save(plan):
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    PLAN.chmod(0o600)


async def main():
    state = target()
    assert state == verified(read_state())
    seed = private_json(ROOT / ".local/wave15-seed.json")
    ids = private_json(ROOT / ".local/wave16-saved-ids.json")
    tenant, actor, pid = (UUID(seed[k]) for k in ("tenant_id", "actor_id", "product_id"))
    assert seed["marker"] == state["marker"]
    assert str(tenant) == state["preview_tenant_id"] and str(pid) == state["preview_product_id"]
    ctx = Context(tenant, actor, actor)
    engine, auth = engine_for(state["app_url"]), engine_for(state["auth_url"])
    os.environ["PDOS_FILE_SECURITY_PROFILE"] = "local-synthetic-v1"
    store = OriginalStore(ROOT / ".local/objects")
    runtime = await local_runtime(store)
    assert runtime is not None
    try:
        create_app(
            engine,
            auth,
            object_store=store,
            security_runtime=runtime,
            lifecycle_enabled=True,
            professional_synthetic_scope={"tenant_id": str(tenant), "product_id": str(pid)},
            operational_synthetic_profile=private_json(
                ROOT / ".local/operational-synthetic-profile.json"
            ),
            test_resource_synthetic_profile=private_json(
                ROOT / ".local/test-resource-synthetic-profile.json"
            ),
            quality_synthetic_profile=private_json(ROOT / ".local/quality-synthetic-profile.json"),
            quality_followup_synthetic_profile=private_json(
                ROOT / ".local/quality-followup-synthetic-profile.json"
            ),
        )
        with engine_for(state["admin_url"]).connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "next_0026"
        with tenant_session(engine, tenant) as s:
            issue = s.scalar(
                select(QualityIssueVersion).where(
                    QualityIssueVersion.id == UUID(ids["complete_v6"]),
                    QualityIssueVersion.tenant_id == tenant,
                    QualityIssueVersion.product_id == pid,
                )
            )
            assert (
                issue is not None
                and issue.revision == 6
                and issue.status == "awaiting_verification"
            )
            project, purpose = issue.project_id, issue.purpose
        if PLAN.exists():
            plan = private_json(PLAN)
            assert plan["marker"] == state["marker"] and plan["operation"] == OPERATION
            assert plan["purpose"] == purpose and plan["project_id"] == str(project)
        else:
            at = datetime.now(UTC)
            setup_id = str(uuid4())
            publication = json.dumps(
                {
                    "nature": "synthetic",
                    "operation": OPERATION,
                    "role": "quality",
                    "subject_id": str(actor),
                    "project_id": str(project),
                    "purpose": purpose,
                    "issued_at": at.isoformat(),
                    "valid_from": (at - timedelta(minutes=1)).isoformat(),
                    "valid_until": (at + timedelta(days=2)).isoformat(),
                    "limitation": (
                        "Explicit isolated local synthetic candidate collection only; "
                        "no production, effectiveness, review or closure authority"
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            plan = {
                "marker": state["marker"],
                "setup_id": setup_id,
                "operation": OPERATION,
                "project_id": str(project),
                "purpose": purpose,
                "source": publication,
                "issued_at": at.isoformat(),
                "valid_from": (at - timedelta(minutes=1)).isoformat(),
                "valid_until": (at + timedelta(days=2)).isoformat(),
                "artifact_command_id": str(uuid4()),
                "artifact_key": f"wave17:{setup_id}:source",
                "facts": {
                    kind: {"command_id": str(uuid4()), "key": f"wave17:{setup_id}:{kind}"}
                    for kind in ("duty", "qualification")
                },
            }
            save(plan)
        assert datetime.fromisoformat(plan["valid_until"]) > datetime.now(UTC)
        with tenant_session(engine, tenant) as s:
            product = s.get(Product, pid)
            result = execute(
                s,
                ctx,
                Command(
                    command_id=UUID(plan["artifact_command_id"]),
                    idempotency_key=plan["artifact_key"],
                    operation="evidence.artifact.register",
                    product_id=pid,
                    expected_revision=product.revision,
                    payload={
                        "title": "本地合成 · 候选收集职责及资格演练",
                        "source_label": "Explicit local synthetic; no production qualification",
                        "content": plan["source"],
                        "visibility": "private",
                    },
                ),
            )
            assert result["subject_type"] == "artifact" and result["subject_revision"] == 1
        plan["artifact_receipt"] = result
        save(plan)
        issuer = configure_local_synthetic(engine, tenant_id=tenant, product_id=pid, enabled=True)
        for kind, item in plan["facts"].items():
            payload = FactInput(
                product_id=pid,
                project_id=project,
                subject_id=actor,
                external_id=item["key"],
                kind=kind,
                role="quality",
                operations=[OPERATION],
                purposes=[purpose],
                valid_from=plan["valid_from"],
                valid_until=plan["valid_until"],
                approval={
                    "system": "explicit-local-synthetic-wave17",
                    "external_id": item["key"],
                    "version": "v1",
                    "approved_by": "具名本地合成签发；无生产资格",
                    "issued_at": plan["issued_at"],
                },
                sources=[
                    {
                        "artifact_id": result["subject_id"],
                        "expected_revision": 1,
                        "line": 1,
                        "quote": plan["source"],
                    }
                ],
                reason="独立新增候选收集合成职责/资格系列，保留既有系列，不授独立复核、有效性或关闭",
            )
            with tenant_session(engine, tenant) as s:
                receipt = import_professional_fact(
                    s,
                    ctx,
                    issuer,
                    payload,
                    request_key=item["key"],
                    command_id=UUID(item["command_id"]),
                )
                assert receipt["subject_type"] == "professional_authority_fact"
                assert receipt["result"]["nature"] == "synthetic"
            item["payload"] = payload.model_dump(mode="json")
            item["receipt"] = receipt
            save(plan)
        print(
            "Marked local candidate-only synthetic duty and qualification "
            "saved with unique receipts."
        )
    finally:
        await runtime.scanner.close()


if __name__ == "__main__":
    asyncio.run(main())
