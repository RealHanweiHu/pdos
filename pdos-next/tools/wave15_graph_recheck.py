"""Root-owned exact affected-node checks, preserving original failure evidence."""

import concurrent.futures
import hashlib
import json
import subprocess
import sys
import time

from local_environment import ROOT, SERVER, environment, read_state, verified

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave15-20261002"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, value):
    with (REPORT / name).open("x") as output:
        json.dump(value, output, indent=2)
        output.write("\n")


candidate = REPORT / "backend-candidate-v3-source.json"
frozen = json.loads(candidate.read_text())
assert all(sha(ROOT.parent / p) == value for p, value in frozen["files"].items())
original = json.loads((REPORT / "pg-result.json").read_text())
assert len(original) == 13
assert {key for key, value in original.items() if value["exit_code"]} == {
    "pg-02", "pg-11", "pg-12"
}
state = verified(read_state())
assert state["port"] == 62513


def run(number):
    group = f"pg-{number}"
    nodes = original[group]["nodes"]
    key = f"graph-history-recheck-{group.replace('-', '')}"
    binding = dict(nodes=nodes, candidate=candidate.name, candidate_sha256=sha(candidate))
    selection_name = f"graph-history-recheck-selection-{group.replace('-', '')}.json"
    result_name = f"graph-history-recheck-result-{group.replace('-', '')}.json"
    write(selection_name, binding)
    checked = verified(read_state())
    start = time.monotonic()
    with (REPORT / (key + ".log")).open("x") as output:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-rA", "--tb=short", *nodes],
            cwd=SERVER, env=environment(checked), stdout=output, stderr=subprocess.STDOUT,
        )
    write(result_name, {**binding, "exit_code": result.returncode,
                        "seconds": round(time.monotonic() - start, 2)})
    print(group, result.returncode, flush=True)
    return {
        "nodes": nodes,
        "selection_file": selection_name,
        "selection_sha256": sha(REPORT / selection_name),
        "result_file": result_name,
        "result_sha256": sha(REPORT / result_name),
        "log_file": key + ".log",
        "log_sha256": sha(REPORT / (key + ".log")),
        "exit_code": result.returncode,
    }


with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(run, ("11", "12")))
previous = REPORT / "backend-candidate-v2-source.json"
difference = json.loads((REPORT / "backend-candidate-v3-source-difference.json").read_text())
write("backend-candidate-v3-delta.json", {
    "previous_manifest": previous.name, "current_manifest": candidate.name,
    "previous_manifest_sha256": sha(previous), "current_manifest_sha256": sha(candidate),
    "changes": difference["changes"], "rechecks": results,
    "unaffected_checks": "Original v1 full scoped PG selection, v2 affected merge pass, "
                         "and v3 exact graph affected nodes; no v3 full joint rerun claimed.",
})
raise SystemExit(int(any(value["exit_code"] for value in results)))
