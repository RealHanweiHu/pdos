"""Restart task-owned actual Temporal/worker; prove queued work and history survive."""

import asyncio
import base64
import json
import os
import signal
import subprocess
import sys
import time
from uuid import uuid4

import httpx
from local_environment import ROOT, read_state, verified
from temporalio.client import Client
from workflow_environment import read_verified

state, flow = verified(read_state()), read_verified()
report_dir = ROOT.parent / "docs/reports/evidence/pdos-next-wave1-20261002"
prior = json.loads((report_dir / "temporal-http.json").read_text())
result = {"synthetic_only": True, "model_calls": 0}


async def description():
    client = await Client.connect(f"127.0.0.1:{flow['server_port']}", namespace="pdos-next")
    value = await client.get_workflow_handle(
        f"pdos-source:{state['preview_tenant_id']}:{prior['work_id']}"
    ).describe()
    return value.run_id


before_run = asyncio.run(description())
processes = subprocess.check_output(["ps", "-axo", "pid=,command="], text=True).splitlines()
workers = [
    int(line.split()[0])
    for line in processes
    if line.strip().endswith("/pdos-next/server/.venv/bin/python -m pdos_next.workflows.worker")
]
if len(workers) != 1:
    raise RuntimeError("No unambiguous own worker")
worker_pid = workers[0]
cwd = subprocess.check_output(["lsof", "-a", "-p", str(worker_pid), "-d", "cwd", "-Fn"], text=True)
if "n" + str(ROOT / "server") + "\n" not in cwd:
    raise RuntimeError("Refuse unrelated worker")
os.kill(worker_pid, signal.SIGTERM)
os.kill(flow["native_pid"], signal.SIGTERM)
for _ in range(40):
    if subprocess.run(["ps", "-p", str(flow["native_pid"])], capture_output=True).returncode:
        break
    time.sleep(0.1)
else:
    raise RuntimeError("Own Temporal did not stop")

with httpx.Client(
    base_url="http://127.0.0.1:8898",
    trust_env=False,
    timeout=10,
    headers={"Authorization": "Bearer " + state["preview_token"]},
) as client:
    body = {
        "title": "重启期间合成原件",
        "filename": "restart.txt",
        "source_label": "恢复联验合成输入",
        "visibility": "private",
        "expected_revision": 1,
        "idempotency_key": str(uuid4()),
        "content_base64": base64.b64encode(
            b"Synthetic restart fixture\nTarget is unknown\n"
        ).decode(),
    }
    receipt = client.post(f"/v1/products/{prior['product_id']}/originals", json=body)
    receipt.raise_for_status()
    original = receipt.json()["subject_id"]
    response = client.post(
        f"/v1/work-requests/{prior['work_id']}/resume", json={"idempotency_key": str(uuid4())}
    )
    response.raise_for_status()
    native_log = (ROOT / ".local/temporal-native-restart.log").open("w")
    native_log.close()
    (ROOT / ".local/temporal-native-restart.log").chmod(0o600)
    with (ROOT / ".local/temporal-native-restart.log").open("a") as log:
        subprocess.Popen(
            [sys.executable, str(ROOT / "tools/workflow_environment.py"), "serve-native"],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    for _ in range(50):
        try:
            flow = read_verified()
            check = subprocess.run(
                [sys.executable, str(ROOT / "tools/workflow_environment.py"), "health"],
                capture_output=True,
                timeout=8,
            )
            if not check.returncode:
                break
        except (RuntimeError, subprocess.TimeoutExpired):
            pass
        time.sleep(0.3)
    else:
        raise RuntimeError("Restarted Temporal unavailable")
    worker_log = ROOT / ".local/worker-restart.log"
    worker_log.touch(mode=0o600)
    with worker_log.open("a") as log:
        subprocess.Popen(
            [sys.executable, str(ROOT / "tools/workflow_environment.py"), "worker"],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        value = client.get(f"/v1/products/{prior['product_id']}/workspace").json()
        item = next(o for o in value["originals"] if o["id"] == original)
        if item["status"] == "parsed":
            break
        time.sleep(0.3)
    else:
        raise RuntimeError("Queued original did not recover")
    result.update(
        queued_upload_survived=True,
        source_count_one=sum(s["original_id"] == original for s in value["sources"]) == 1,
        model_unavailable_preserved=next(w for w in value["works"] if w["id"] == prior["work_id"])[
            "error_code"
        ]
        == "MODEL_UNAVAILABLE",
        temporal_same_run=asyncio.run(description()) == before_run,
    )
    assert all(
        result[k]
        for k in (
            "queued_upload_survived",
            "source_count_one",
            "model_unavailable_preserved",
            "temporal_same_run",
        )
    )
(report_dir / "temporal-restart.json").write_text(json.dumps(result, indent=2) + "\n")
print(
    "Actual Temporal+worker restart: same run/history, queued original once, zero model calls"
)
