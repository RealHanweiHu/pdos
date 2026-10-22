"""Root-owned bounded quality/change checks on the task's verified database."""

import ast
import concurrent.futures
import json
import subprocess
import sys
import time

from local_environment import ROOT, SERVER, environment, read_state, verified

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave15-20261002"


def nodes(path):
    return [
        f"{path}::{node.name}"
        for node in ast.parse((SERVER / path).read_text()).body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]


def run(key, selected):
    state = verified(read_state())
    start = time.monotonic()
    with (REPORT / (key + ".log")).open("x") as output:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-rA", "--tb=short", *selected],
            cwd=SERVER,
            env=environment(state),
            stdout=output,
            stderr=subprocess.STDOUT,
        )
    value = dict(
        nodes=selected, exit_code=result.returncode, seconds=round(time.monotonic() - start, 2)
    )
    print(key, result.returncode, flush=True)
    return key, value


mode = sys.argv[1]
if mode == "pure":
    selected = [
        f"tests/{package}/{file}"
        for package in ("quality_execution", "change_execution")
        for file in ("test_pure.py", "test_evidence.py", "test_native_evidence.py")
        if (SERVER / f"tests/{package}/{file}").exists()
    ]
    groups = {"root-pure": selected}
elif mode in {"pg", "priority"}:
    selected = nodes("tests/quality_execution/test_transactions.py")
    if mode == "priority":
        selected = [
            node
            for node in selected
            if node.endswith(
                (
                    "test_definite_fail_create_triage_containment_capa_retains_test_and_unknown_conclusions",
                    "test_outbox_failure_rolls_back_issue_version_pointer_and_common_confirmation",
                )
            )
        ]
        assert len(selected) == 2
    selected += nodes("tests/change_execution/test_transactions.py")
    groups = {f"{mode}-{i:02}": [node] for i, node in enumerate(selected)}
else:
    raise ValueError("Explicit check selection required")
with (REPORT / (mode + "-selection.json")).open("x") as output:
    output.write(json.dumps(groups, indent=2) + "\n")
results = {}
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    pending = [pool.submit(run, key, selected) for key, selected in groups.items()]
    for future in concurrent.futures.as_completed(pending):
        key, value = future.result()
        results[key] = value
        (REPORT / (mode + "-result.json")).write_text(json.dumps(results, indent=2) + "\n")
if any(value["exit_code"] for value in results.values()):
    raise SystemExit(1)
