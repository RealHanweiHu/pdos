"""Explicit synthetic launch exercise; every transaction verifies this task's marker."""

import json
import sys
from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
from local_environment import ROOT, read_state, verified
from pdos_next.contracts import Command
from pdos_next.database import engine_for, tenant_session
from pdos_next.domain.professional_authority.service import configure_local_synthetic
from pdos_next.models import now
from pdos_next.professional_import import import_professional_fact
from pdos_next.service import Context, execute
from sqlalchemy import text

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave13-20261002"
SEED = ROOT / ".local/wave13-seed.json"


def target():
    return verified(read_state())


state = target()
tenant, product = UUID(state["preview_tenant_id"]), UUID(state["preview_product_id"])
engine = engine_for(state["app_url"])
prior = json.loads((ROOT / ".local/wave12-seed.json").read_text())
actor = UUID(prior["actor_id"])
ctx = Context(tenant, actor, actor)


def session():
    target()
    return tenant_session(engine, tenant)


def save(path, value, *, private=False):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")
    if private:
        path.chmod(0o600)


def artifact(title, content, key):
    with session() as s:
        receipt = execute(
            s,
            ctx,
            Command(
                command_id=uuid4(),
                idempotency_key=key,
                operation="evidence.artifact.register",
                product_id=product,
                expected_revision=1,
                payload={
                    "title": title,
                    "content": content,
                    "source_label": "Explicit local synthetic launch, no real qualification",
                    "visibility": "private",
                },
            ),
        )
    return receipt["subject_id"]


def reference(identity, quote, line=1):
    return {"artifact_id": identity, "expected_revision": 1, "line": line, "quote": quote}


def command(operation, payload):
    return {
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "operation": operation,
        "product_id": str(product),
        "expected_revision": 1,
        "source_read_set": [],
        "payload": payload,
    }


def read(client, path):
    target()
    response = client.get(f"/v1/products/{product}/{path}")
    response.raise_for_status()
    return response.json()


def submit(client, data, label):
    target()
    inputs = client.post(f"/v1/products/{product}/verification-launch/inputs", json=data)
    if inputs.status_code != 200:
        save(REPORT / f"{label}-inputs-error.json", inputs.json())
    inputs.raise_for_status()
    body = inputs.json()
    save(REPORT / f"{label}-inputs.json", body)
    assert body["allowed"], "Fixed launch input is not allowed"
    complete = deepcopy(data)
    complete["source_read_set"] = body["required_source_read_set"]
    save(ROOT / f".local/wave13-{label}-command.json", complete, private=True)
    target()
    preview = client.post("/v1/commands/preview", json=complete)
    if preview.status_code != 200:
        save(REPORT / f"{label}-preview-error.json", preview.json())
    preview.raise_for_status()
    body = preview.json()
    confirmed = body["command"]
    public_preview = deepcopy(body)
    public_preview.pop("confirmation_token", None)
    public_preview["command"]["payload"].pop("confirmation_token", None)
    save(REPORT / f"{label}-preview.json", public_preview)
    save(ROOT / f".local/wave13-{label}-confirmed.json", confirmed, private=True)
    target()
    receipt = client.post("/v1/commands", json=confirmed)
    if receipt.status_code != 200:
        save(REPORT / f"{label}-execute-error.json", receipt.json())
    receipt.raise_for_status()
    save(REPORT / f"{label}-receipt.json", receipt.json())
    return receipt.json()


with httpx.Client(
    base_url="http://127.0.0.1:8898",
    trust_env=False,
    timeout=120,
    headers={"Authorization": "Bearer " + state["preview_token"]},
) as client:
    action = sys.argv[1]
    if action == "authority":
        if SEED.exists():
            raise RuntimeError("Wave13 journal already exists; use a specific continuation phase")
        seed = deepcopy(prior)
        seed["previous_wave12"] = {
            key: prior[key]
            for key in (
                "build_id",
                "request_id",
                "current_version_id",
                "revision",
                "actual",
                "lot",
                "samples",
            )
        }
        seed["phase"] = "readiness_events_saved"
        seed["handoff_receipts"] = []
        seed["readiness_receipts"] = []
        # Preserve every pre-existing physical/request row independently of later additions.
        baseline = {}
        with session() as s:
            for table in (
                "builds",
                "actual_configurations",
                "build_lots",
                "sample_units",
                "verification_preparations",
                "verification_formal_requests",
                "verification_actual_method_applicabilities",
                "verification_handoff_facts",
                "sample_readiness_facts",
                "build_starts",
                "operational_material_holds",
                "operational_resource_occupancies",
            ):
                rows = s.execute(text(f"SELECT id, to_jsonb(t)::text FROM {table} t")).all()
                from pdos_next.service import digest

                baseline[table] = {
                    str(identity): digest(json.loads(value)) for identity, value in rows
                }
        save(REPORT / "old-business-manifest.json", baseline)
        line = "第十三波具名品质职责与测试资格，仅本任务隔离环境的合成演练，不是工厂资格。"
        identity = artifact("第十三波 · 合成开测职责依据", line, "wave13-authority-source")
        ref = reference(identity, line)
        issuer = configure_local_synthetic(
            engine, tenant_id=tenant, product_id=product, enabled=True
        )
        at = now()
        receipts = []
        for kind in ("duty", "qualification"):
            key = f"wave13-quality-{kind}"
            with session() as s:
                receipts.append(
                    import_professional_fact(
                        s,
                        ctx,
                        issuer,
                        {
                            "product_id": str(product),
                            "project_id": seed["project_id"],
                            "subject_id": str(actor),
                            "external_id": key,
                            "kind": kind,
                            "role": "quality",
                            "operations": [
                                "test.run.plan",
                                "verification.schedule.promise",
                                "test.run.start",
                            ],
                            "purposes": [seed["purpose"]],
                            "state": "active",
                            "valid_from": (at - timedelta(minutes=1)).isoformat(),
                            "valid_until": (at + timedelta(days=1)).isoformat(),
                            "approval": {
                                "system": "explicit-local-synthetic-launch",
                                "external_id": key,
                                "version": "v1",
                                "approved_by": "本地合成签发人",
                                "issued_at": at.isoformat(),
                            },
                            "sources": [ref],
                            "reason": "只新增本波三项合成开测权限；旧履历需按当前资格重新核对",
                        },
                        request_key=key,
                        command_id=uuid4(),
                    )
                )
        seed["launch_authority_receipts"] = receipts
        seed["launch_authority_reference"] = ref
        save(SEED, seed, private=True)
        print("Saved finite synthetic launch authority and unchanged old-history manifest.")
    elif action == "resources":
        from pdos_next.domain.test_resources.schemas import TestResourceFactInput
        from pdos_next.domain.verification_front import service as front
        from pdos_next.domain.verification_handoff import service as handoff
        from pdos_next.domain.verification_launch.schemas import ExecutionPlan
        from pdos_next.domain.verification_launch.service import _binding
        from pdos_next.engines.planning.calendar import frozen_timezone
        from pdos_next.test_resource_bootstrap import configure_local_profile
        from pdos_next.test_resource_import import import_test_resource_fact

        seed = json.loads(SEED.read_text())
        assert seed["phase"] == "returned"
        configure_local_synthetic(engine, tenant_id=tenant, product_id=product, enabled=True)
        from pdos_next.operational_bootstrap import configure_local_profile as operational_profile

        operational_profile(
            engine, json.loads((ROOT / ".local/operational-synthetic-profile.json").read_text())
        )
        text_lines = [
            "SYN-W13-EQUIPMENT:固定合成设备，本次完整窗口可用，未授真实资格。",
            "SYN-W13-CALIBRATION:合成具名校准依据，不代表生产校准。",
        ]
        identity = artifact(
            "第十三波 · 固定合成设备与校准原件",
            "\n".join(text_lines),
            "wave13-test-resource-source",
        )
        equipment, calibration = (
            reference(identity, text_lines[0]),
            reference(identity, text_lines[1], 2),
        )
        at, run_id, equipment_id = now(), uuid4(), uuid4()
        window = {
            "start": at + timedelta(minutes=10),
            "finish": at + timedelta(hours=2),
            "original_timezone": "UTC",
        }
        plan = ExecutionPlan(
            window=window,
            executor_id=actor,
            equipment=equipment,
            calibration=calibration,
            environment="本地合成测试室",
            conditions="固定合成20°C，结果与处置尚未接入",
            resource_fact_id=uuid4(),
            expected_resource_fact_revision=1,
        )
        with session() as s:
            _, row = front._current(s, ctx, product, UUID(seed["request_id"]))
            request = front._snapshot(row)
            methods = {}
            from pdos_next.domain.verification.rules import accepted_coverage

            coverage = accepted_coverage(request)
            for c in coverage:
                _, method = handoff._method_pointer(
                    s, ctx, product, request.id, c.sample_id, c.item_id
                )
                methods[(c.sample_id, c.item_id)] = method
            binding = _binding(row, request, run_id, plan, methods)
        resources = []
        for kind, rid, facts in (
            ("equipment", equipment_id, ("acceptance", "calibration")),
            ("person", actor, ("qualification",)),
        ):
            ref = {"id": str(rid), "revision": 1, "kind": kind}
            resources.append(
                {
                    "resource": ref,
                    "purposes": [binding.purpose],
                    "operation_ids": ["test.run.start"],
                    "lifecycle": "active",
                    "facts": [
                        {
                            "kind": fact,
                            "purpose": binding.purpose,
                            "operation_id": "test.run.start",
                            "status": "accepted",
                            "valid_from": at - timedelta(days=1),
                            "valid_until": at + timedelta(days=1),
                            "named_decision_id": uuid4(),
                            "actor_id": actor,
                            "sources": [calibration if fact == "calibration" else equipment],
                        }
                        for fact in facts
                    ],
                    "maintenance": [],
                    "capacity": "1",
                    "calendar": {
                        "calendar_id": "SYN-W13-UTC",
                        "version": "1",
                        "timezone": "UTC",
                        "timezone_rules_sha256": frozen_timezone("UTC")[1],
                        "weekly": [
                            {"weekday": i, "intervals": [{"start_minute": 0, "end_minute": 1440}]}
                            for i in range(7)
                        ],
                    },
                    "calendar_sources": [equipment],
                    "external_occupancies_complete": True,
                    "sources": [equipment, calibration],
                }
            )
        data = TestResourceFactInput.model_validate(
            {
                "binding": binding,
                "external_id": f"SYN-W13-RUN-{run_id}",
                "valid_from": at - timedelta(minutes=1),
                "valid_until": at + timedelta(days=1),
                "resources": resources,
                "required_uses": [{"resource": r["resource"], "units": "1"} for r in resources],
                "requirements_sources": [seed["reference"]],
                "sources": [equipment, calibration, seed["reference"]],
                "reason": "服务器有限合成签发，绑定完整已接收A范围、方法、配置和完整设备/人员窗口",
            }
        )
        profile = {
            "tenant_id": str(tenant),
            "product_id": str(product),
            "decisions": [
                {
                    "binding": binding.model_dump(mode="json"),
                    "resource": r.resource.model_dump(mode="json"),
                    "decision": d.model_dump(mode="json"),
                }
                for r in data.resources
                for d in r.facts
            ],
        }
        save(ROOT / ".local/test-resource-synthetic-profile.json", profile, private=True)
        issuer = configure_local_profile(engine, profile)
        with session() as s:
            receipt = import_test_resource_fact(
                s,
                ctx,
                product,
                issuer,
                data,
                request_key=f"wave13-resources-{run_id}",
                command_id=uuid4(),
            )
        plan = plan.model_copy(update={"resource_fact_id": UUID(receipt["subject_id"])})
        seed.update(
            phase="launch_resources_saved",
            run_id=str(run_id),
            launch_plan=plan.model_dump(mode="json"),
            resource_receipt=receipt,
            launch_binding=binding.model_dump(mode="json"),
            launch_coverage=[c.model_dump(mode="json") for c in coverage],
        )
        save(SEED, seed, private=True)
        print(
            "Saved exact synthetic test facts and private finite verifier profile. "
            "Restart API to load it."
        )
    elif action in {"plan", "promise", "start-event", "start"}:
        seed = json.loads(SEED.read_text())
        view = read(client, f"verification-launch?build_id={seed['build_id']}")
        pointer = view["current_by_request"][seed["request_id"]]
        payload = {
            "request_id": seed["request_id"],
            "expected_request_revision": pointer["revision"],
            "sources": [seed["reference"]],
            "reason": "本地合成固定A范围开测，未接收B与缺项保持",
        }
        if action == "plan":
            assert seed["phase"] == "launch_resources_saved"
            payload.update(
                run_id=seed["run_id"],
                coverage=seed["launch_coverage"],
                execution_plan=seed["launch_plan"],
            )
            receipt = submit(client, command("test.run.plan", payload), "plan")
            seed.update(phase="run_planned", plan_receipt=receipt)
        elif action == "start-event":
            from datetime import datetime

            assert seed["phase"] == "run_promised"
            assert now() >= datetime.fromisoformat(
                seed["launch_plan"]["window"]["start"].replace("Z", "+00:00")
            )
            event = {
                "request_id": seed["request_id"],
                "run_id": seed["run_id"],
                "purpose": seed["purpose"],
                "operation": "test.run.start",
                "occurred_at": now().isoformat(),
                "executor_id": str(actor),
            }
            line = json.dumps(event, ensure_ascii=False, sort_keys=True)
            identity = artifact("第十三波 · 合成实际开测事件原值", line, "wave13-start-event")
            seed.update(
                phase="start_event_saved",
                start_event=event,
                start_reference=reference(identity, line),
            )
            print(
                "Recorded an explicit synthetic actual-start event; this has no launch side effect."
            )
        else:
            from datetime import datetime

            from pdos_next.domain.configurations.schemas import DefinitionReference
            from pdos_next.domain.verification_handoff.service import event_source

            run_pointer = view["current_by_run"][seed["run_id"]]
            run = next(v for v in view["runs"] if v["id"] == run_pointer["run_version_id"])
            payload.update(
                run_id=seed["run_id"],
                expected_run_revision=run_pointer["revision"],
                expected_plan_sha256=run["plan_sha256"],
            )
            if action == "promise":
                assert seed["phase"] == "run_planned"
                event = {
                    "request_id": seed["request_id"],
                    "run_id": seed["run_id"],
                    "purpose": seed["purpose"],
                    "operation": "verification.schedule.promise",
                    "occurred_at": datetime.fromisoformat(
                        seed["launch_plan"]["window"]["start"].replace("Z", "+00:00")
                    ).isoformat(),
                    "executor_id": str(actor),
                }
                line = json.dumps(event, ensure_ascii=False, sort_keys=True)
                identity = artifact("第十三波 · 合成具名承诺事件原值", line, "wave13-promise-event")
                ref = reference(identity, line)
                seed.update(promise_event=event, promise_reference=ref)
                operation = "verification.schedule.promise"
            else:
                assert seed["phase"] == "start_event_saved"
                event, ref, operation = (
                    seed["start_event"],
                    seed["start_reference"],
                    "test.run.start",
                )
            payload["sources"].append(ref)
            payload["at"] = {
                "occurred_at": event["occurred_at"],
                "original_timezone": "UTC",
                "source": event_source(DefinitionReference.model_validate(ref)).model_dump(
                    mode="json"
                ),
            }
            data = command(operation, payload)
            if action == "start" and "--prepare-only" in sys.argv:
                save(ROOT / ".local/wave13-start-ui-command.json", data, private=True)
                save(SEED, seed, private=True)
                print("Prepared exact actual-start input for the browser's one-confirmation flow.")
                sys.exit(0)
            receipt = submit(client, data, action)
            seed.update(
                phase="run_promised" if action == "promise" else "run_started",
                **{f"{action}_receipt": receipt},
            )
        save(SEED, seed, private=True)
        save(
            REPORT / f"after-{action}.json",
            read(client, f"verification-launch?build_id={seed['build_id']}"),
        )
        print(f"Synthetic launch phase {action} saved on the exact accepted-scope chain.")
    else:
        raise RuntimeError("Unsupported explicit Wave13 exercise phase")
