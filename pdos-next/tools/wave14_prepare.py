"""Explicit synthetic result materials for the retained Wave13 Run, on its owned target."""

import base64
import hashlib
import json
import sys
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
from local_environment import ROOT, read_state, verified
from pdos_next.contracts import Command
from pdos_next.database import engine_for, tenant_session
from pdos_next.domain.professional_authority.service import configure_local_synthetic
from pdos_next.domain.verification_launch.models import VerificationRunVersion
from pdos_next.domain.verification_launch.service import _snapshot
from pdos_next.models import Product, now
from pdos_next.professional_import import import_professional_fact
from pdos_next.service import Context, execute
from sqlalchemy import select

SEED = ROOT / ".local/wave14-seed.json"
REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave14-20261002"
state = verified(read_state())
tenant, pid = UUID(state["preview_tenant_id"]), UUID(state["preview_product_id"])
engine = engine_for(state["app_url"])
prior = json.loads((ROOT / ".local/wave13-seed.json").read_text())


def save(value):
    SEED.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")
    SEED.chmod(0o600)


def artifact(ctx, title, content, key):
    verified(read_state())
    with tenant_session(engine, tenant) as session:
        return execute(
            session,
            ctx,
            Command(
                command_id=uuid4(),
                idempotency_key=key,
                operation="evidence.artifact.register",
                product_id=pid,
                expected_revision=1,
                payload={
                    "title": title,
                    "content": content,
                    "source_label": "Explicit local synthetic result exercise",
                    "visibility": "private",
                },
            ),
        )["subject_id"]


def checked(response):
    if not response.is_success:
        raise RuntimeError(f"Result request rejected ({response.status_code}): {response.text}")
    return response.json()


def listing(client, seed, name):
    data = checked(
        client.get(
            f"/v1/products/{pid}/verification-results", params={"build_id": seed["build_id"]}
        )
    )
    (REPORT / (name + ".json")).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return data


def current(data, seed):
    run_id = data["current_by_run"][seed["run_id"]]["run_version_id"]
    request_id = data["current_by_request"][seed["request_id"]]["request_version_id"]
    return (
        next(row for row in data["runs"] if row["id"] == run_id),
        next(row for row in data["requests"] if row["id"] == request_id),
    )


def apply_result(client, seed, phase, operation, payload):
    pending = seed.setdefault("commands", {}).get(phase)
    if pending is None:
        command = {
            "command_id": str(uuid4()),
            "idempotency_key": "wave14-" + phase,
            "operation": operation,
            "product_id": str(pid),
            "expected_revision": 1,
            "payload": payload,
        }
        inputs = checked(
            client.post(f"/v1/products/{pid}/verification-results/inputs", json=command)
        )
        if not inputs["allowed"]:
            raise RuntimeError("Result inputs unavailable: " + json.dumps(inputs["blockers"]))
        command["source_read_set"] = inputs["required_source_read_set"]
        if operation != "test.result.compute":
            prepared = checked(client.post("/v1/commands/preview", json=command))
            command = prepared["command"]
            # Confirmation and approval tokens stay in the private recovery state.
        seed["commands"][phase] = command
        save(seed)
        pending = command
    receipt = checked(client.post("/v1/commands", json=pending))
    seed.setdefault("receipts", {})[phase] = receipt
    seed["phase"] = phase
    save(seed)
    (REPORT / (phase + "-receipt.json")).write_text(json.dumps(receipt, indent=2) + "\n")
    print(
        {
            "phase": phase,
            "subject_type": receipt["subject_type"],
            "revision": receipt["subject_revision"],
        }
    )


class VerifiedClient(httpx.Client):
    def request(self, *args, **kwargs):
        verified(read_state())
        return super().request(*args, **kwargs)


verified(read_state())
with tenant_session(engine, tenant) as s:
    actor = s.get(Product, pid).owner_id
    row = s.scalar(
        select(VerificationRunVersion).where(
            VerificationRunVersion.run_id == UUID(prior["run_id"]),
            VerificationRunVersion.revision == 2,
        )
    )
    run, plan = _snapshot(row)
    original = {
        "version_id": str(row.id),
        "sha256": row.snapshot_sha256,
        "start_intent": row.intent_digest,
    }
ctx = Context(tenant, actor, actor)

with VerifiedClient(
    base_url="http://127.0.0.1:8898",
    trust_env=False,
    timeout=180,
    headers={"Authorization": "Bearer " + state["preview_token"]},
) as client:
    action = sys.argv[1]
    if action == "seed":
        if SEED.exists():
            raise RuntimeError("Existing Wave14 materials retained; use an explicit next phase")
        quality_text = "仅本隔离实例合成结果办理职责，覆盖原Run用途；不授真实专业资格或生产批准。"
        source = artifact(
            ctx, "第十四波 · 合成结果办理依据", quality_text, "wave14-authority-source"
        )
        reference = {
            "artifact_id": source,
            "expected_revision": 1,
            "line": 1,
            "quote": quality_text,
        }
        issuer = configure_local_synthetic(engine, tenant_id=tenant, product_id=pid, enabled=True)
        issued = now()
        for kind in ("duty", "qualification"):
            verified(read_state())
            with tenant_session(engine, tenant) as s:
                key = f"wave14-quality-{kind}"
                import_professional_fact(
                    s,
                    ctx,
                    issuer,
                    {
                        "product_id": str(pid),
                        "project_id": str(run.scope.project_id),
                        "subject_id": str(actor),
                        "external_id": key,
                        "kind": kind,
                        "role": "quality",
                        "operations": [
                            "test.results.import",
                            "test.result.compute",
                            "test.run.review",
                            "test.disposition.decide",
                        ],
                        "purposes": [prior["purpose"]],
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
                        "sources": [reference],
                        "reason": "仅本地合成结果与具名办理验证",
                    },
                    request_key=key,
                    command_id=uuid4(),
                )
        observations = []
        for coverage in run.coverage:
            item = next(v for v in run.items if v.id == coverage.item_id)
            sample = next(v for v in run.samples if v.id == coverage.sample_id)
            lower = (
                item.criterion.lower
                if item.criterion and item.criterion.lower is not None
                else Decimal(0)
            )
            upper = (
                item.criterion.upper
                if item.criterion and item.criterion.upper is not None
                else lower
            )
            value = format((lower + upper) / 2, "f")
            observations.append(
                {
                    "format": "pdos-measurement-jsonl-v1",
                    "run_id": str(run.id),
                    "sample_id": str(sample.id),
                    "sample_revision": sample.revision,
                    "actual_configuration": sample.actual_configuration.model_dump(mode="json"),
                    "cavity": sample.cavity,
                    "item_id": item.id,
                    "raw_value": "  " + value + "  ",
                    "unit": item.unit,
                    "conditions": plan.conditions,
                    "equipment": run.execution.equipment.model_dump(mode="json"),
                    "equipment_label": "本地合成固定设备",
                    "calibration": run.execution.calibration.model_dump(mode="json"),
                    "environment": plan.environment,
                    "method": item.method.model_dump(mode="json") if item.method else None,
                    "executor_id": str(plan.executor_id),
                    "observed_at": (
                        run.actual_start.occurred_at + timedelta(minutes=10)
                    ).isoformat(),
                    "observed_timezone": "UTC",
                    "note": "Synthetic native report; no instrument data",
                }
            )
        content = (
            "\n".join(
                json.dumps(v, ensure_ascii=False, separators=(",", ":")) for v in observations
            )
            + "\n"
        )
        raw_path = ROOT / ".local/wave14-synthetic-measurement.txt"
        raw_path.write_text(content)
        raw_path.chmod(0o600)
        upload = client.post(
            f"/v1/products/{pid}/originals",
            json={
                "idempotency_key": "wave14-native-report",
                "expected_revision": 1,
                "title": "第十四波 · 合成原生测量报告",
                "source_label": "Synthetic local report; not instrument data",
                "filename": "wave14-synthetic-measurement.txt",
                "content_base64": base64.b64encode(content.encode()).decode(),
                "visibility": "private",
            },
        )
        upload.raise_for_status()
        seed = {
            "phase": "materials_uploaded",
            "original_start": original,
            "request_id": str(run.request_id),
            "run_id": str(run.id),
            "build_id": str(run.build.id),
            "purpose": prior["purpose"],
            "actor_id": str(actor),
            "authority_reference": reference,
            "upload_receipt": upload.json(),
            "report_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "observations": observations,
            "events": {},
        }
        for operation, minutes, name in (
            ("test.results.import", 15, "partial"),
            ("test.run.end", 20, "end"),
            ("test.results.import", 25, "final"),
        ):
            occurred = run.actual_start.occurred_at + timedelta(minutes=minutes)
            value = {
                "request_id": str(run.request_id),
                "run_id": str(run.id),
                "purpose": prior["purpose"],
                "operation": operation,
                "occurred_at": occurred.isoformat(),
                "actor_id": str(actor),
            }
            text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            identity = artifact(
                ctx, "第十四波 · 合成" + name + "事实", text, "wave14-event-" + name
            )
            seed["events"][name] = {
                "at": {
                    "occurred_at": occurred.isoformat(),
                    "original_timezone": "UTC",
                    "source": {
                        "kind": "artifact",
                        "id": identity,
                        "revision": 1,
                        "position": "line:1;quote_sha256:"
                        + hashlib.sha256(text.encode()).hexdigest(),
                    },
                },
                "reference": {
                    "artifact_id": identity,
                    "expected_revision": 1,
                    "line": 1,
                    "quote": text,
                },
            }
        save(seed)
        print("Synthetic report and result duties saved. No result imported.")
    elif action == "read":
        response = client.get(
            f"/v1/products/{pid}/verification-results", params={"build_id": str(run.build.id)}
        )
        response.raise_for_status()
        data = response.json()
        (REPORT / "results-initial-get.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        )
        print(
            {
                key: len(value) if isinstance(value, list) else type(value).__name__
                for key, value in data.items()
            }
        )
    elif action in {"capture", "partial", "final", "compute", "professional-events"}:
        seed = json.loads(SEED.read_text())
        data = listing(client, seed, "before-" + action)
        fixed, request = current(data, seed)
        base = {
            "request_id": seed["request_id"],
            "expected_request_revision": request["revision"],
            "run_id": seed["run_id"],
            "expected_run_revision": fixed["revision"],
            "reason": "本地合成原件逐值返回，沿原请求与运行保存，不授真实资格或对外放行。",
        }
        if action == "capture":
            source = next(
                row
                for row in data["report_sources"]
                if row["original_sha256"] == seed["report_sha256"]
            )
            value = {
                "capture_key": "wave14-native-report-capture",
                "expected_product_revision": 1,
                **{k: v for k, v in base.items() if k != "reason"},
                "report_artifact_id": source["artifact_id"],
                "expected_report_revision": source["artifact_revision"],
                "selections": [
                    {"line": i + 1, "sample_id": row["sample_id"], "item_id": row["item_id"]}
                    for i, row in enumerate(seed["observations"])
                ],
                "reason": "选取合成原生报告的真实原件行号，原空格与缺项逐字保留。",
            }
            seed["capture_input"] = value
            save(seed)
            capture = checked(
                client.post(f"/v1/products/{pid}/verification-results/captures", json=value)
            )
            seed["capture"] = capture
            seed["phase"] = "capture_prepared"
            save(seed)
            (REPORT / "capture-response.json").write_text(
                json.dumps(capture, ensure_ascii=False, indent=2) + "\n"
            )
            print({"phase": seed["phase"], "id": capture["capture"]["id"]})
        elif action in {"partial", "final"}:
            event = seed["events"][action]
            payload = {
                **base,
                "final": action == "final",
                "at": event["at"],
                "sources": [event["reference"]],
            }
            if action == "partial":
                payload.update(
                    capture_id=seed["capture"]["capture"]["id"],
                    expected_capture_revision=1,
                    incomplete_reason="原值先返回，实际结束和最终返回分别凭独立来源确认。",
                    next_owner_id=str(actor),
                )
            else:
                payload.update(actual_end=seed["events"]["end"]["at"])
                payload["sources"].append(seed["events"]["end"]["reference"])
            apply_result(client, seed, action, "test.results.import", payload)
        elif action == "compute":
            apply_result(
                client,
                seed,
                action,
                "test.result.compute",
                {**base, "expected_basis_sha256": fixed["basis_sha256"]},
            )
        else:
            for operation, name, conclusion in (
                (
                    "test.run.review",
                    "review",
                    "合成报告原值已逐字核对；报告工况与原请求要求不同，固定判定仍不能确定。A局部范围与B/C、数量缺项保持，后续核对适用性，不授产品放行。",
                ),
                (
                    "test.disposition.decide",
                    "disposition",
                    "保存此合成运行的具名处置：保留结果与原占用，后续补齐B/C独立验证，不释放资源或外部交付。",
                ),
            ):
                if name in seed["events"]:
                    continue
                at = now()
                fact = {
                    "request_id": seed["request_id"],
                    "run_id": seed["run_id"],
                    "purpose": seed["purpose"],
                    "operation": operation,
                    "occurred_at": at.isoformat(),
                    "actor_id": str(actor),
                    "text": conclusion,
                    "basis_sha256": fixed["basis_sha256"],
                }
                text = json.dumps(fact, ensure_ascii=False, separators=(",", ":"))
                identity = artifact(
                    ctx, "第十四波 · 合成" + name + "具名事实", text, "wave14-event-" + name
                )
                seed["events"][name] = {
                    "text": conclusion,
                    "basis_sha256": fixed["basis_sha256"],
                    "at": {
                        "occurred_at": at.isoformat(),
                        "original_timezone": "UTC",
                        "source": {
                            "kind": "artifact",
                            "id": identity,
                            "revision": 1,
                            "position": "line:1;quote_sha256:"
                            + hashlib.sha256(text.encode()).hexdigest(),
                        },
                    },
                    "reference": {
                        "artifact_id": identity,
                        "expected_revision": 1,
                        "line": 1,
                        "quote": text,
                    },
                }
                save(seed)
            print(
                "Separate synthetic review and disposition sources prepared; no T2 action executed."
            )
        listing(client, seed, "after-" + action)
    else:
        raise RuntimeError("Unknown explicit material phase")
