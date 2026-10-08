"""HTTP→Outbox→actual Temporal→activities→domain replay, synthetic local only."""

import asyncio
import base64
import json
import time
from uuid import uuid4

import httpx
from local_environment import ROOT, read_state, verified
from temporalio.client import Client
from workflow_environment import read_verified

state, flow = verified(read_state()), read_verified()
headers = {"Authorization": "Bearer " + state["preview_token"]}
report = ROOT.parent / "docs/reports/evidence/pdos-next-wave1-20261002/temporal-http.json"
result = {"synthetic_only": True, "model_calls": 0, "temporal_storage": flow["storage_mode"]}


def wait_for(client, path, predicate):
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        response = client.get(path)
        response.raise_for_status()
        value = response.json()
        if predicate(value):
            return value
        time.sleep(0.3)
    raise RuntimeError("Durable domain result did not arrive")


async def verify_history(product, original, work):
    temporal = await Client.connect(f"127.0.0.1:{flow['server_port']}", namespace="pdos-next")
    parse = temporal.get_workflow_handle(f"pdos-parse:{state['preview_tenant_id']}:{original}")
    outcome = await parse.result()
    assert outcome["status"] == "parsed"
    handle = temporal.get_workflow_handle(f"pdos-source:{state['preview_tenant_id']}:{work}")
    description = await handle.describe()
    result["parse_workflow_status"] = "COMPLETED"
    result["waiting_workflow_status"] = description.status.name
    result["work_id"] = work
    result["product_id"] = product
    result["original_id"] = original


with httpx.Client(
    base_url="http://127.0.0.1:8898", headers=headers, timeout=15, trust_env=False
) as client:
    response = client.post(
        "/v1/products",
        json={
            "name": "并行执行联验 · 合成",
            "purpose": "验证文件处理、产品定义和可恢复工作。仅使用合成材料。",
            "idempotency_key": str(uuid4()),
        },
    )
    response.raise_for_status()
    product = response.json()["subject_id"]
    path = f"/v1/products/{product}/workspace"
    raw = (
        "合成客户资料（仅演练）\n额定压力：150 PSI，条件待确认。\n"
        "噪声目标：未知，测量条件待确认。\n"
    ).encode()
    upload = {
        "title": "合成原件联验",
        "filename": "synthetic.txt",
        "source_label": "本地合成测试",
        "content_base64": base64.b64encode(raw).decode(),
        "visibility": "private",
        "expected_revision": 1,
        "idempotency_key": str(uuid4()),
    }
    response = client.post(f"/v1/products/{product}/originals", json=upload)
    response.raise_for_status()
    receipt = response.json()
    replay = client.post(f"/v1/products/{product}/originals", json=upload)
    assert replay.json()["id"] == receipt["id"]
    original = receipt["subject_id"]
    workspace = wait_for(
        client,
        path,
        lambda v: any(o["id"] == original and o["status"] == "parsed" for o in v["originals"]),
    )
    source = workspace["sources"][0]
    download = client.get(f"/v1/products/{product}/originals/{original}/download")
    assert download.content == raw and "attachment" in download.headers["Content-Disposition"]
    ref = {
        "artifact_id": source["id"],
        "expected_revision": source["revision"],
        "line": 2,
        "quote": source["content"].splitlines()[1],
    }
    payload = {
        "title": "合成产品定义",
        "purpose": "资料驱动的合成规格演练",
        "use_cases": ["客户资料核对"],
        "unknowns": ["噪声目标及测量条件待确认"],
        "sources": [ref],
        "change_reason": "由本地合成原件建立首版",
        "specs": [
            {
                "key": "pressure",
                "parameter": "额定压力",
                "value_type": "number",
                "availability": "known",
                "value": "150",
                "unit": "PSI",
                "reason": "合成原文引用，条件尚待确认",
                "sources": [ref],
            },
            {
                "key": "noise",
                "parameter": "噪声目标",
                "value_type": "number",
                "availability": "unknown",
                "reason": "尚无目标与测量条件",
                "sources": [ref],
            },
        ],
    }
    command = {
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "operation": "product.definition.draft",
        "product_id": product,
        "expected_revision": 1,
        "source_read_set": [{"artifact_id": source["id"], "expected_revision": 1}],
        "payload": payload,
    }
    response = client.post("/v1/commands", json=command)
    response.raise_for_status()
    assert client.post("/v1/commands", json=command).json()["id"] == response.json()["id"]
    definitions = client.get(f"/v1/products/{product}/definitions").json()["items"]
    assert (
        len(definitions) == 1
        and next(s for s in definitions[0]["specs"] if s["key"] == "noise")["availability"]
        == "unknown"
    )
    command.update(
        command_id=str(uuid4()),
        idempotency_key=str(uuid4()),
        operation="ai.work.start",
        payload={
            "goal": "整理合成原件事实",
            "artifact_id": source["id"],
            "source_revision": 1,
            "max_actions": 1,
        },
    )
    response = client.post("/v1/commands", json=command)
    response.raise_for_status()
    work = response.json()["subject_id"]
    workspace = wait_for(
        client,
        path,
        lambda v: any(w["id"] == work and w["status"] == "waiting_input" for w in v["works"]),
    )
    assert workspace["works"][0]["error_code"] == "MODEL_UNAVAILABLE"
    resume_body = {"idempotency_key": str(uuid4())}
    response = client.post(f"/v1/work-requests/{work}/resume", json=resume_body)
    response.raise_for_status()
    assert (
        client.post(f"/v1/work-requests/{work}/resume", json=resume_body).json()["id"]
        == response.json()["id"]
    )
    result.update(
        upload_download_exact=True,
        upload_replay_one_receipt=True,
        definition_replay_one_revision=True,
        unknown_spec_unfilled=True,
        resume_replay_one_event=True,
    )
    asyncio.run(verify_history(product, original, work))
report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print(
    "Synthetic HTTP/download/definition/Temporal/replay passed"
)
