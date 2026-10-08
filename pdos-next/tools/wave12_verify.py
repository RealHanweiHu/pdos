"""Explicit synthetic handoff exercise on this task's verified isolated instance."""

import json
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
from local_environment import ROOT, read_state, verified

sys.path.insert(0, str(ROOT / "server/tests"))
from pdos_next.contracts import Command
from pdos_next.database import engine_for, tenant_session
from pdos_next.domain.professional_authority.service import configure_local_synthetic
from pdos_next.models import Product, now
from pdos_next.professional_import import import_professional_fact
from pdos_next.service import Context, execute
from test_build_execution import actual_command, allocation_command, output_command
from test_project_first_plan import accepted, cmd
from test_verification_execution import TEXT, reference
from test_verification_execution import payload as prep_payload

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave12-20261002"
SEED = ROOT / ".local/wave12-seed.json"
state = verified(read_state())
engine = engine_for(state["app_url"])
tenant, product_id = UUID(state["preview_tenant_id"]), UUID(state["preview_product_id"])
prior = json.loads((ROOT / ".local/wave11-seed.json").read_text())


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")
    path.chmod(0o600)


with tenant_session(engine, tenant) as session:
    actor = session.get(Product, product_id).owner_id
ctx = Context(tenant, actor, actor)
with httpx.Client(
    base_url="http://127.0.0.1:8898",
    trust_env=False,
    timeout=120,
    headers={"Authorization": "Bearer " + state["preview_token"]},
) as client:
    setup = SimpleNamespace(
        engine=engine,
        tenant=tenant,
        human=actor,
        product=product_id,
        ctx=ctx,
        client=client,
        headers=dict(client.headers),
    )

    def read(path):
        response = client.get(f"/v1/products/{product_id}/{path}")
        response.raise_for_status()
        return response.json()

    def confirmed(command, reads):
        command["source_read_set"] = reads
        return accepted(setup, command)[0]

    def artifact(title, content, key):
        with tenant_session(engine, tenant) as session:
            return execute(
                session,
                ctx,
                Command(
                    command_id=uuid4(),
                    idempotency_key=key,
                    operation="evidence.artifact.register",
                    product_id=product_id,
                    expected_revision=1,
                    payload={
                        "title": title,
                        "content": content,
                        "source_label": "Explicit local synthetic only",
                        "visibility": "private",
                    },
                ),
            )["subject_id"]

    action = sys.argv[1]
    if action == "seed":
        if SEED.exists():
            raise RuntimeError("Existing Wave12 checkpoint retained; resume an explicit phase")
        before = {
            key: read(key)
            for key in (
                "builds",
                "build-execution",
                "verification",
                "verification-professional",
                "build-start",
            )
        }
        save(REPORT / "prior-business.json", before)
        build = next(row for row in before["builds"]["items"] if row["id"] == prior["build_id"])
        source = artifact("第十二波 · 实物与品质合成资料", TEXT, "wave12-material")
        fixed = {row["artifact_id"]: row for row in build["required_source_read_set"]}
        fixed[source] = {"artifact_id": source, "expected_revision": 1}
        reads = list(fixed.values())
        # Actual identities are added to the existing started Build, not a second ledger.
        original_source = artifact(
            "第十二波 · 合成产出依据", "Synthetic requirement is unverified", "wave12-output-source"
        )
        fixed[original_source] = {"artifact_id": original_source, "expected_revision": 1}
        reads = list(fixed.values())
        work = {
            "source": original_source,
            "build": {"subject_id": build["id"]},
            "engineering": {"subject_id": build["engineering_configuration"]["id"]},
            "process": {"subject_id": build["manufacturing_configuration"]["id"]},
            "preparation_source": source,
        }
        actual = confirmed(actual_command(setup, work), reads)
        lot = confirmed(
            output_command(setup, work, actual, units=2, lot_label="SYN-W12-LOT"), reads
        )
        allocation = confirmed(
            allocation_command(
                setup,
                work,
                lot,
                samples=[
                    {"label": "SYN-W12-A", "cavity": "A", "availability": "unknown"},
                    {"label": "SYN-W12-B", "cavity": "B", "availability": "unknown"},
                ],
            ),
            reads,
        )
        samples = [
            s
            for s in read("build-execution")["samples"]
            if s["allocation_id"] == allocation["subject_id"]
        ]
        data = prep_payload(
            work, purpose=prior["scope"]["purpose"], title="第十二波 · 实物交接与部分接收（合成）"
        )
        data["items"][0]["method"] = reference(work, 2)
        data["items"][0]["criterion"] = {
            "lower": "9.5",
            "upper": "10.5",
            "source": reference(work, 2),
        }
        data["documents"][0]["source"] = reference(work, 3)
        receipt = confirmed(cmd(setup, "verification.preparation.record", data), reads)
        prep = next(
            row
            for row in read("verification")["preparations"]
            if row["id"] == receipt["subject_id"]
        )
        authority_text = (
            "第十二波本地合成制造和品质职责、资格；"
            "只演练固定用途实物就绪、实际配置方法及部分接收，不代表真实工厂资格。"
        )
        authority_source = artifact(
            "第十二波 · 合成职责依据", authority_text, "wave12-authority-source"
        )
        authority_ref = {
            "artifact_id": authority_source,
            "expected_revision": 1,
            "line": 1,
            "quote": authority_text,
        }
        issuer = configure_local_synthetic(
            engine, tenant_id=tenant, product_id=product_id, enabled=True
        )
        issued = now()
        facts = []
        with tenant_session(engine, tenant) as session:
            for role, operations in {
                "manufacturing": ["build.sample.readiness.record", "verification.handoff.offer"],
                "quality": [
                    "verification.request.create",
                    "verification.method.prepare",
                    "verification.schedule.propose",
                    "verification.actual_method.prepare",
                    "verification.handoff.accept",
                    "verification.handoff.return",
                ],
            }.items():
                for kind in ("duty", "qualification"):
                    key = f"wave12-{role}-{kind}"
                    facts.append(
                        import_professional_fact(
                            session,
                            ctx,
                            issuer,
                            {
                                "product_id": str(product_id),
                                "project_id": prior["project_id"],
                                "subject_id": str(actor),
                                "external_id": key,
                                "kind": kind,
                                "role": role,
                                "operations": operations,
                                "purposes": [prior["scope"]["purpose"]],
                                "state": "active",
                                "valid_from": (issued - timedelta(minutes=1)).isoformat(),
                                "valid_until": (issued + timedelta(days=1)).isoformat(),
                                "approval": {
                                    "system": "explicit-local-synthetic-exercise",
                                    "external_id": key,
                                    "version": "v1",
                                    "approved_by": "本地合成签发人",
                                    "issued_at": issued.isoformat(),
                                },
                                "sources": [authority_ref],
                                "reason": "仅本地合成样件交接验证",
                            },
                            request_key=key,
                            command_id=uuid4(),
                        )
                    )
        seed = {
            "phase": "materials_saved",
            "build_id": build["id"],
            "project_id": prior["project_id"],
            "purpose": prior["scope"]["purpose"],
            "actual": actual,
            "lot": lot,
            "samples": samples,
            "preparation": prep,
            "reference": reference(work, 2),
            "authority_reference": authority_ref,
            "facts": facts,
            "actor_id": str(actor),
        }
        save(SEED, seed)
        print(
            "Saved two samples and complete preparation on the existing started Build. "
            "Synthetic authority only."
        )
    elif action == "formal":
        seed = json.loads(SEED.read_text())
        assert seed["phase"] == "materials_saved"
        prep = next(
            row
            for row in read("verification-professional")["preparations"]
            if row["id"] == seed["preparation"]["id"]
        )
        command = cmd(
            setup,
            "verification.request.create",
            {
                "request_id": str(uuid4()),
                "preparation_id": prep["id"],
                "expected_preparation_revision": prep["revision"],
                "preparation_sha256": prep["sha256"],
                "reason": "以固定合成资料开始实物交接演练",
            },
        )
        command["source_read_set"] = prep["required_source_read_set"]
        response = client.post("/v1/commands", json=command)
        assert response.status_code == 200, response.text
        receipt = response.json()
        row = next(
            row
            for row in read("verification-professional")["requests"]
            if row["id"] == receipt["subject_id"]
        )
        seed.update(
            phase="formal_created",
            request_id=row["request_id"],
            current_version_id=row["id"],
            revision=row["revision"],
        )
        save(SEED, seed)
    elif action == "planned-method":
        seed = json.loads(SEED.read_text())
        assert seed["phase"] == "formal_created"
        row = next(
            row
            for row in read("verification-professional")["requests"]
            if row["id"] == seed["current_version_id"]
        )
        receipt = confirmed(
            cmd(
                setup,
                "verification.method.prepare",
                {
                    "request_id": row["request_id"],
                    "expected_request_revision": row["revision"],
                    "assessments": [
                        {
                            "item_id": item["id"],
                            "status": "applicable",
                            "conditions": [],
                            "reason": "仅演练固定计划方法，实际样件逐对另核",
                            "sources": [seed["reference"]],
                        }
                        for item in row["items"]
                    ],
                    "reason": "合成固定资料已齐，实际配置尚未核对",
                },
            ),
            row["required_source_read_set"],
        )
        seed.update(
            phase="planned_method_saved",
            current_version_id=receipt["subject_id"],
            revision=row["revision"] + 1,
        )
        save(SEED, seed)
    elif action == "readiness-events":
        seed = json.loads(SEED.read_text())
        assert seed["phase"] == "planned_method_saved"
        events = []
        for sample in sorted(seed["samples"], key=lambda row: row["label"]):
            event = {
                "sample_id": sample["id"],
                "lot_id": sample["lot_id"],
                "actual_configuration_id": sample["actual_configuration_id"],
                "build_id": seed["build_id"],
                "state": "ready" if sample["label"].endswith("A") else "hold",
                "purpose": seed["purpose"],
                "occurred_at": now().isoformat(),
            }
            line = json.dumps(event, ensure_ascii=False, sort_keys=True)
            source = artifact(
                f"第十二波 · {sample['label']} 合成实物事件", line, f"wave12-event-{sample['id']}"
            )
            ref = {"artifact_id": source, "expected_revision": 1, "line": 1, "quote": line}
            events.append({"sample": sample, "event": event, "reference": ref})
        seed.update(phase="readiness_events_saved", events=events)
        save(SEED, seed)
        save(REPORT / "readiness-events.json", events)
    elif action == "readiness":
        seed = json.loads(SEED.read_text())
        assert seed["phase"] == "readiness_events_saved"
        done = []
        for item in seed["events"]:
            sample, event, ref = item["sample"], item["event"], item["reference"]
            data = read(f"sample-handoff?build_id={seed['build_id']}")
            cap = data["capabilities_by_sample"][sample["id"]]
            command = cmd(
                setup,
                "build.sample.readiness.record",
                {
                    "sample_id": sample["id"],
                    "expected_sample_revision": sample["revision"],
                    "previous_readiness_id": None,
                    "expected_previous_revision": 0,
                    "state": event["state"],
                    "purpose": event["purpose"],
                    "occurred_at": event["occurred_at"],
                    "occurred_timezone": "UTC",
                    "event_source": ref,
                    "sources": [ref],
                    "reason": "合成样件A用途就绪；B暂缓，保留品质待核对缺项",
                },
            )
            reads = {v["artifact_id"]: v for v in cap["required_source_read_set"]}
            reads[ref["artifact_id"]] = {"artifact_id": ref["artifact_id"], "expected_revision": 1}
            command["source_read_set"] = list(reads.values())
            # Retain the original command identity before submitting.
            save(ROOT / f".local/wave12-readiness-{sample['id']}.json", command)
            done.append(confirmed(command, list(reads.values())))
        seed.update(phase="readiness_saved", readiness_receipts=done)
        save(SEED, seed)
        save(REPORT / "actual-readiness.json", read(f"sample-handoff?build_id={seed['build_id']}"))
    elif action == "next-round":
        from build_operational_facts.fixtures import fact_payload
        from pdos_next.domain.build_operational_facts.schemas import OperationalScope
        from pdos_next.models import BuildReadiness
        from pdos_next.operational_bootstrap import configure_local_profile
        from pdos_next.operational_import import import_operational_fact
        from test_builds import build_command

        seed = json.loads(SEED.read_text())
        if seed["phase"] == "readiness_saved":
            assert (
                datetime.fromisoformat(seed["scope"]["window"]["finish"].replace("Z", "+00:00"))
                < now()
            )
            seed.setdefault("expired_rounds", []).append(
                {
                    key: seed[key]
                    for key in (
                        "build_id",
                        "actual",
                        "lot",
                        "samples",
                        "preparation",
                        "request_id",
                        "current_version_id",
                        "revision",
                        "events",
                        "scope",
                        "readiness_receipts",
                    )
                }
            )
            seed["round_number"] = seed.get("round_number", 2) + 1
        else:
            assert seed["phase"] == "readiness_events_saved"
            seed["round_number"] = 2
        # New professional facts intentionally invalidate the old comprehensive authority
        # fingerprint. Keep that stopped history; use a successor Build under the new basis.
        seed.setdefault(
            "interrupted_round",
            {
                key: seed[key]
                for key in (
                    "build_id",
                    "actual",
                    "lot",
                    "samples",
                    "preparation",
                    "request_id",
                    "current_version_id",
                    "revision",
                    "events",
                )
            },
        )
        source = artifact(
            "第十二波 · 合成产出依据", "Synthetic requirement is unverified", "wave12-output-source"
        )
        old = next(row for row in read("builds")["items"] if row["id"] == seed["build_id"])
        config = {
            "source": source,
            "project": seed["project_id"],
            "engineering": {"subject_id": old["engineering_configuration"]["id"]},
            "process": {"subject_id": old["manufacturing_configuration"]["id"]},
        }
        fixed = {row["artifact_id"]: row for row in old["required_source_read_set"]}
        fixed[source] = {"artifact_id": source, "expected_revision": 1}
        receipt = confirmed(
            build_command(
                setup,
                config,
                name=f"第十二波 · 实物交接后续第{seed['round_number']}轮（合成）",
                previous_build_id=old["id"],
            ),
            list(fixed.values()),
        )
        build_id = receipt["subject_id"]
        command = cmd(
            setup, "build.readiness.compute", {"build_id": build_id, "expected_build_revision": 1}
        )
        command["source_read_set"] = list(fixed.values())
        response = client.post("/v1/commands", json=command)
        assert response.status_code == 200, response.text
        with tenant_session(engine, tenant) as session:
            config["result"] = session.get(
                BuildReadiness, UUID(response.json()["subject_id"])
            ).result
        at = now()
        scope = OperationalScope(
            purpose=seed["purpose"],
            quantity="10",
            unit="ea",
            site="SYN-INTERNAL-LAB",
            window={
                "start": at - timedelta(minutes=1),
                "finish": at + timedelta(hours=8),
                "original_timezone": "UTC",
            },
        )
        work = SimpleNamespace(
            setup=setup,
            config=config,
            at=at,
            build_id=build_id,
            scope=scope,
            resource_id=uuid4(),
            decision_ids={"acceptance": uuid4(), "calibration": uuid4()},
        )
        payload = fact_payload(work, pool_id=f"SYN-W12-FOLLOWUP-POOL-R{seed['round_number']}")
        binding = {
            "build_id": build_id,
            "build_revision": 1,
            "project_id": seed["project_id"],
            "scope": scope.model_dump(mode="json"),
            "engineering_configuration_id": config["engineering"]["subject_id"],
            "engineering_configuration_revision": 1,
            "manufacturing_configuration_id": config["process"]["subject_id"],
            "manufacturing_configuration_revision": 1,
        }
        profile_path = ROOT / ".local/operational-synthetic-profile.json"
        profile = json.loads(profile_path.read_text())
        profile["decisions"].extend(
            {
                "binding": binding,
                "resource": resource.resource.model_dump(mode="json"),
                "decision": decision.model_dump(mode="json"),
            }
            for resource in payload.resources
            for decision in resource.facts
        )
        save(profile_path, profile)
        issuer = configure_local_profile(engine, profile)
        with tenant_session(engine, tenant) as session:
            imported = import_operational_fact(
                session,
                ctx,
                issuer,
                payload.model_dump(mode="json"),
                request_key=f"wave12-followup-operational-{build_id}",
                command_id=uuid4(),
            )
        seed.update(
            phase="next_round_facts_saved",
            build_id=build_id,
            config=config,
            operational_receipt=imported,
            scope=scope.model_dump(mode="json"),
            at=at.isoformat(),
        )
        save(SEED, seed)
    elif action == "next-round-start":
        from datetime import datetime

        from build_start.test_transactions import (
            assessment_command,
            authorization_command,
            start_command,
        )
        from pdos_next.domain.build_operational_facts.schemas import OperationalScope
        from pdos_next.operational_bootstrap import configure_local_profile

        seed = json.loads(SEED.read_text())
        assert seed["phase"] == "next_round_facts_saved"
        configure_local_synthetic(engine, tenant_id=tenant, product_id=product_id, enabled=True)
        configure_local_profile(
            engine, json.loads((ROOT / ".local/operational-synthetic-profile.json").read_text())
        )
        work = SimpleNamespace(
            setup=setup,
            config=seed["config"],
            at=datetime.fromisoformat(seed["at"]),
            build_id=seed["build_id"],
            scope=OperationalScope.model_validate(seed["scope"]),
        )
        response = client.post("/v1/commands", json=assessment_command(work))
        assert response.status_code == 200, response.text
        work.assessment = next(
            row
            for row in read("build-start")["assessments"]
            if row["id"] == response.json()["subject_id"]
        )
        decisions = {}
        for role in ("engineering", "manufacturing"):
            command = authorization_command(work, role)
            until = (work.scope.window.finish + timedelta(minutes=20)).isoformat()
            command["payload"]["valid_until"] = until
            for item in command["payload"]["professional_assessments"]:
                item["valid_until"] = until
            data = read("build-start")
            cap = data["capabilities_by_build"][work.build_id]
            reads = {row["artifact_id"]: row for row in cap["required_source_read_set"]}
            reads.update(
                {
                    row["artifact_id"]: row
                    for row in cap["authority"][f"{role}_authorize"]["required_source_read_set"]
                }
            )
            receipt = confirmed(command, list(reads.values()))
            decisions[role] = next(
                row
                for row in read("build-start")["authorizations"]
                if row["id"] == receipt["subject_id"]
            )
        command = start_command(work, decisions["engineering"], decisions["manufacturing"])
        cap = read("build-start")["capabilities_by_build"][work.build_id]
        reads = {row["artifact_id"]: row for row in cap["required_source_read_set"]}
        for group in (
            command["source_read_set"],
            cap["authority"]["start"]["required_source_read_set"],
            *[v["required_source_read_set"] for v in decisions.values()],
        ):
            reads.update({row["artifact_id"]: row for row in group})
        receipt = confirmed(command, list(reads.values()))
        seed.update(
            phase="next_round_started",
            start=receipt,
            assessment=work.assessment,
            decisions=decisions,
        )
        save(SEED, seed)
    elif action == "next-round-materials":
        seed = json.loads(SEED.read_text())
        assert seed["phase"] == "next_round_started"
        work = {
            **seed["config"],
            "build": {"subject_id": seed["build_id"]},
            "preparation_source": seed["reference"]["artifact_id"],
        }
        build = next(row for row in read("builds")["items"] if row["id"] == seed["build_id"])
        reads = {row["artifact_id"]: row for row in build["required_source_read_set"]}
        for identity in (work["source"], work["preparation_source"]):
            reads[identity] = {"artifact_id": identity, "expected_revision": 1}
        actual = confirmed(
            actual_command(setup, work, observed_at=now().isoformat()), list(reads.values())
        )
        lot = confirmed(
            output_command(
                setup,
                work,
                actual,
                units=2,
                lot_label=f"SYN-W12-R{seed.get('round_number', 2)}-LOT",
                observation={
                    "system": "Synthetic next round",
                    "external_id": str(uuid4()),
                    "nature": "synthetic",
                    "occurred_at": now().isoformat(),
                },
            ),
            list(reads.values()),
        )
        receipt = confirmed(
            allocation_command(
                setup,
                work,
                lot,
                samples=[
                    {
                        "label": f"SYN-W12-R{seed.get('round_number', 2)}-A",
                        "cavity": "A",
                        "availability": "unknown",
                    },
                    {
                        "label": f"SYN-W12-R{seed.get('round_number', 2)}-B",
                        "cavity": "B",
                        "availability": "unknown",
                    },
                ],
            ),
            list(reads.values()),
        )
        samples = [
            row
            for row in read("build-execution")["samples"]
            if row["allocation_id"] == receipt["subject_id"]
        ]
        data = prep_payload(
            work, purpose=seed["purpose"], title="第十二波 · 后续轮次交样与部分接收（合成）"
        )
        data["items"][0].update(
            method=seed["reference"],
            criterion={"lower": "9.5", "upper": "10.5", "source": seed["reference"]},
        )
        data["documents"][0]["source"] = reference(work, 3)
        receipt = confirmed(
            cmd(setup, "verification.preparation.record", data), list(reads.values())
        )
        prep = next(
            row
            for row in read("verification")["preparations"]
            if row["id"] == receipt["subject_id"]
        )
        seed.update(
            phase="materials_saved", actual=actual, lot=lot, samples=samples, preparation=prep
        )
        save(SEED, seed)
    elif action in {"actual-method", "offer", "accept", "return"}:
        from pdos_next.domain.configurations.schemas import DefinitionReference
        from pdos_next.domain.verification_handoff.service import event_source

        seed = json.loads(SEED.read_text())
        expected = {
            "actual-method": "readiness_saved",
            "offer": "actual_method_saved",
            "accept": "offered",
            "return": "accepted",
        }
        assert seed["phase"] == expected[action]
        data = read(f"verification-handoff?build_id={seed['build_id']}")
        pointer = data["current_by_request"][seed["request_id"]]
        row = next(v for v in data["requests"] if v["id"] == pointer["request_version_id"])
        samples = sorted(
            [v for v in data["reference_samples"] if v["request_id"] == seed["request_id"]],
            key=lambda v: v["label"],
        )
        assert len(samples) == 2
        reads = {v["artifact_id"]: v for v in row["required_source_read_set"]}
        for sample in samples:
            reads.update({v["artifact_id"]: v for v in sample["required_source_read_set"]})
        reads[seed["reference"]["artifact_id"]] = {
            "artifact_id": seed["reference"]["artifact_id"],
            "expected_revision": 1,
        }
        payload = {
            "request_id": seed["request_id"],
            "expected_request_revision": row["revision"],
            "reason": "合成实物交接：只接收A，B继续暂缓并明确缺项责任",
            "sources": [seed["reference"]],
        }
        if action == "actual-method":
            operation = "verification.actual_method.prepare"
            payload["assessments"] = [
                {
                    "sample": sample["reference"],
                    "item_id": "dimension",
                    "expected_assessment_revision": 0,
                    "status": "applicable" if sample["label"].endswith("A") else "unknown",
                    "conditions": [],
                    "reason": "实际配置A方法核对；B适用性未知保留",
                    "sources": [seed["reference"]],
                }
                for sample in samples
            ]
        else:
            for method in data["actual_methods"]:
                if method["request_id"] == seed["request_id"]:
                    reads.update({v["artifact_id"]: v for v in method["required_source_read_set"]})
            operation = "verification.handoff." + action
            payload["at"] = {
                "occurred_at": now().isoformat(),
                "original_timezone": "UTC",
                "source": event_source(
                    DefinitionReference.model_validate(seed["reference"])
                ).model_dump(mode="json"),
            }
            covers = [{"sample_id": sample["id"], "item_id": "dimension"} for sample in samples]
            if action == "offer":
                payload.update(samples=[sample["reference"] for sample in samples], coverage=covers)
            elif action == "accept":
                payload.update(
                    coverage=covers[:1],
                    returned_coverage=covers[1:],
                    next_owner_id=seed["actor_id"],
                )
            else:
                payload.update(coverage=covers[1:], next_owner_id=seed["actor_id"])
        command = cmd(setup, operation, payload)
        receipt = confirmed(command, list(reads.values()))
        seed.update(
            phase={
                "actual-method": "actual_method_saved",
                "offer": "offered",
                "accept": "accepted",
                "return": "returned",
            }[action]
        )
        seed.setdefault("handoff_receipts", []).append(receipt)
        save(SEED, seed)
        save(
            REPORT / f"actual-{action}.json",
            read(f"verification-handoff?build_id={seed['build_id']}"),
        )
    else:
        raise RuntimeError("Unknown explicit exercise phase")
