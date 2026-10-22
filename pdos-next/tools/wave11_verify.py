"""Local synthetic Build lifecycle evidence; only root runs on the verified own instance."""

import json
import sys
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
from local_environment import ROOT, read_state, verified

sys.path.insert(0, str(ROOT / "server/tests"))
from build_operational_facts.fixtures import fact_payload  # noqa: E402
from pdos_next.contracts import Command  # noqa: E402
from pdos_next.database import engine_for, tenant_session  # noqa: E402
from pdos_next.domain.build_operational_facts.schemas import OperationalScope  # noqa: E402
from pdos_next.domain.professional_authority.service import configure_local_synthetic  # noqa: E402
from pdos_next.models import Artifact, BuildReadiness, Product, now  # noqa: E402
from pdos_next.operational_bootstrap import configure_local_profile  # noqa: E402
from pdos_next.operational_import import import_operational_fact  # noqa: E402
from pdos_next.professional_import import import_professional_fact  # noqa: E402
from pdos_next.service import Context, execute  # noqa: E402
from test_builds import accepted, build_command  # noqa: E402
from test_project_first_plan import cmd, post  # noqa: E402

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave11-20261002"
state = verified(read_state())
engine = engine_for(state["app_url"])
tenant, product_id = UUID(state["preview_tenant_id"]), UUID(state["preview_product_id"])
SEED = ROOT / ".local/wave11-seed.json"
PROFILE = ROOT / ".local/operational-synthetic-profile.json"
action = sys.argv[1]
with httpx.Client(
    base_url="http://127.0.0.1:8898",
    trust_env=False,
    timeout=120,
    headers={"Authorization": "Bearer " + state["preview_token"]},
) as client:
    with tenant_session(engine, tenant) as session:
        product = session.get(Product, product_id)
        actor = product.owner_id
    setup = SimpleNamespace(
        engine=engine,
        tenant=tenant,
        human=actor,
        product=product_id,
        ctx=Context(tenant, actor, actor),
        client=client,
        headers={"Authorization": "Bearer " + state["preview_token"]},
    )

    def save(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")
        path.chmod(0o600)

    def read(path):
        response = client.get(f"/v1/products/{product_id}/{path}")
        response.raise_for_status()
        return response.json()

    if action == "seed":
        if SEED.exists():
            raise RuntimeError(
                "Existing seed checkpoint retained; resume its next phase explicitly"
            )
        before = {key: read(key) for key in ("builds", "verification", "verification-professional")}
        save(REPORT / "prior-business.json", before)
        defined = read("definitions")["items"][0]
        source_text = "Synthetic requirement is unverified"
        with tenant_session(engine, tenant) as session:
            saved_source = execute(
                session,
                setup.ctx,
                Command(
                    command_id=uuid4(),
                    idempotency_key="wave11-fixed-input",
                    operation="evidence.artifact.register",
                    product_id=product_id,
                    expected_revision=1,
                    payload={
                        "title": "第十一波 · 内部试制合成输入",
                        "content": source_text,
                        "source_label": "明确合成输入",
                        "visibility": "private",
                    },
                ),
            )
        source = saved_source["subject_id"]
        reference = {"artifact_id": source, "expected_revision": 1, "line": 1, "quote": source_text}
        reads = {
            ref["artifact_id"]: {
                "artifact_id": ref["artifact_id"],
                "expected_revision": ref["expected_revision"],
            }
            for ref in defined["sources"]
        }
        reads[source] = {"artifact_id": source, "expected_revision": 1}
        fixed_reads = [reads[k] for k in sorted(reads)]

        def confirmed(operation, payload):
            command = cmd(setup, operation, payload)
            command["source_read_set"] = fixed_reads
            return accepted(setup, command)[0]

        projected = confirmed(
            "project.create",
            {
                "name": "第十一波 · 内部开工演练",
                "purpose": "Build and verify a synthetic design",
                "scope": "Internal synthetic manufacturing only",
                "definition_id": defined["id"],
                "expected_definition_revision": defined["revision"],
                "visibility": "private",
            },
        )
        project_id = projected["subject_id"]
        common = {
            "visibility": "private",
            "reason": "Explicit synthetic fixed scope",
            "sources": [reference],
        }
        bom = confirmed(
            "engineering.bom.revise",
            {
                **common,
                "name": "合成全已知物料清单",
                "lines": [
                    {
                        "key": "motor",
                        "part": {"name": "Synthetic motor"},
                        "quantity": "2",
                        "unit": "ea",
                        "loss_rate": "0.1",
                        "critical": True,
                    }
                ],
            },
        )
        eng = confirmed(
            "engineering.configuration.create",
            {
                **common,
                "name": "合成固定工程配置",
                "definition_id": defined["id"],
                "expected_definition_revision": defined["revision"],
                "bom_id": bom["subject_id"],
                "expected_bom_revision": 1,
            },
        )
        process = confirmed(
            "npi.process.revise",
            {
                **common,
                "name": "合成固定制造配置",
                "engineering_configuration_id": eng["subject_id"],
                "expected_engineering_revision": 1,
                "operations": [
                    {
                        "key": "assembly",
                        "name": "Synthetic assembly",
                        "kind": "assembly",
                        "bom_line_keys": ["motor"],
                    }
                ],
            },
        )
        config = {
            "source": source,
            "project": project_id,
            "bom": bom,
            "engineering": eng,
            "process": process,
            "reads": fixed_reads,
        }
        command = build_command(setup, config, name="第十一波 · 内部试制开工演练（合成）")
        command["source_read_set"] = fixed_reads
        built, _ = accepted(setup, command)
        command = cmd(
            setup,
            "build.readiness.compute",
            {"build_id": built["subject_id"], "expected_build_revision": 1},
        )
        command["source_read_set"] = fixed_reads
        computed = post(setup, command)
        assert computed.status_code == 200, computed.text
        with tenant_session(engine, tenant) as session:
            prep = session.get(BuildReadiness, UUID(computed.json()["subject_id"]))
            config.update(build_id=built["subject_id"], result=prep.result)
        at = now()
        scope = OperationalScope(
            purpose="Verify preparation",
            quantity="10",
            unit="ea",
            site="SYN-INTERNAL-LAB",
            window={
                "start": at - timedelta(minutes=5),
                "finish": at + timedelta(hours=6),
                "original_timezone": "UTC",
            },
        )
        work = SimpleNamespace(
            setup=setup,
            config=config,
            at=at,
            build_id=built["subject_id"],
            resource_id=uuid4(),
            decision_ids={"acceptance": uuid4(), "calibration": uuid4()},
            scope=scope,
        )
        payload = fact_payload(work)
        binding = {
            "build_id": work.build_id,
            "build_revision": 1,
            "project_id": project_id,
            "scope": scope.model_dump(mode="json"),
            "engineering_configuration_id": config["engineering"]["subject_id"],
            "engineering_configuration_revision": 1,
            "manufacturing_configuration_id": config["process"]["subject_id"],
            "manufacturing_configuration_revision": 1,
        }
        profile = {
            "tenant_id": str(tenant),
            "product_id": str(product_id),
            "decisions": [
                {
                    "binding": binding,
                    "resource": resource.resource.model_dump(mode="json"),
                    "decision": decision.model_dump(mode="json"),
                }
                for resource in payload.resources
                for decision in resource.facts
            ],
        }
        save(PROFILE, profile)
        seed = {
            "build_id": work.build_id,
            "project_id": project_id,
            "scope": scope.model_dump(mode="json"),
            "binding": binding,
            "payload": payload.model_dump(mode="json"),
            "phase": "plan_saved",
        }
        save(SEED, seed)
        print("Fixed synthetic plan saved; execute seed-facts next.")
    elif action == "seed-facts":
        seed = json.loads(SEED.read_text())
        assert seed["phase"] == "plan_saved"
        issuer = configure_local_profile(engine, json.loads(PROFILE.read_text()))
        professional = configure_local_synthetic(
            engine, tenant_id=tenant, product_id=product_id, enabled=True
        )
        with tenant_session(engine, tenant) as session:
            result = import_operational_fact(
                session,
                setup.ctx,
                issuer,
                seed["payload"],
                request_key="wave11-preview-operational-facts",
                command_id=uuid4(),
            )
            source_text = (
                "第十一波独立临时实例的合成工程与制造职责、人员资格和适用性演练。"
                "固定内部试制用途、已知物料和双配置；保留可追溯产出；偏离时停工重核；"
                "不授权测试、样件合格或外部交付。不代表真实工厂任命或生产资格。"
            )
            source = execute(
                session,
                setup.ctx,
                Command(
                    command_id=uuid4(),
                    idempotency_key="wave11-preview-professional-source",
                    operation="evidence.artifact.register",
                    product_id=product_id,
                    expected_revision=1,
                    payload={
                        "title": "第十一波 · 合成专业依据",
                        "content": source_text,
                        "source_label": "明确本地合成签发",
                        "visibility": "private",
                    },
                ),
            )
            artifact = session.get(Artifact, UUID(source["subject_id"]))
            reference = {
                "artifact_id": str(artifact.id),
                "expected_revision": 1,
                "line": 1,
                "quote": source_text,
            }
            receipts = []
            for role in ("engineering", "manufacturing"):
                for kind in ("duty", "qualification"):
                    item = {
                        "product_id": str(product_id),
                        "project_id": seed["project_id"],
                        "subject_id": str(actor),
                        "external_id": f"wave11-{role}-{kind}",
                        "kind": kind,
                        "role": role,
                        "operations": [f"build.{role}.authorize"]
                        + (["build.start"] if role == "manufacturing" else []),
                        "purposes": [seed["scope"]["purpose"]],
                        "state": "active",
                        "valid_from": (artifact.created_at - timedelta(minutes=1)).isoformat(),
                        "valid_until": (artifact.created_at + timedelta(days=1)).isoformat(),
                        "approval": {
                            "system": "explicit-local-synthetic-exercise",
                            "external_id": f"wave11-{role}-{kind}",
                            "version": "v1",
                            "approved_by": "本地合成签发人",
                            "issued_at": artifact.created_at.isoformat(),
                        },
                        "sources": [reference],
                        "reason": "独立本地范围的内部开工守卫演练",
                    }
                    receipts.append(
                        import_professional_fact(
                            session,
                            setup.ctx,
                            professional,
                            item,
                            request_key=f"wave11-{role}-{kind}",
                            command_id=uuid4(),
                        )
                    )
        seed.update(
            phase="facts_saved",
            operational_receipt=result,
            professional_receipts=receipts,
            professional_reference=reference,
        )
        save(SEED, seed)
        save(REPORT / "actual-seed.json", seed)
        print("Controlled synthetic facts and finite qualified-decision profile saved atomically.")
    elif action == "event":
        seed = json.loads(SEED.read_text())
        view = read("build-start")
        decisions = [v for v in view["authorizations"] if v["build_id"] == seed["build_id"]]
        assert len(decisions) == 2 and all(v["status"] == "approved" for v in decisions)
        at = now().isoformat()
        event = {
            "build_id": seed["build_id"],
            "occurred_at": at,
            "purpose": seed["scope"]["purpose"],
            "engineering_configuration_id": seed["binding"]["engineering_configuration_id"],
            "manufacturing_configuration_id": seed["binding"]["manufacturing_configuration_id"],
        }
        content = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        with tenant_session(engine, tenant) as session:
            source = execute(
                session,
                setup.ctx,
                Command(
                    command_id=uuid4(),
                    idempotency_key="wave11-preview-actual-event",
                    operation="evidence.artifact.register",
                    product_id=product_id,
                    expected_revision=1,
                    payload={
                        "title": "第十一波 · 合成实际开工事件",
                        "content": content,
                        "source_label": "本地合成事件，不代表生产实绩",
                        "visibility": "private",
                    },
                ),
            )
        seed.update(
            event_time=at,
            event_reference={
                "artifact_id": source["subject_id"],
                "expected_revision": 1,
                "line": 1,
                "quote": content,
            },
        )
        save(SEED, seed)
        save(REPORT / "actual-event.json", seed["event_reference"])
        print(
            json.dumps(
                {"event_time": at, "event_reference": seed["event_reference"]}, ensure_ascii=False
            )
        )
    elif action == "inspect":
        save(REPORT / "actual-build-start.json", read("build-start"))
        print("Current view saved without credentials.")
    else:
        raise RuntimeError("Unknown explicit phase")
