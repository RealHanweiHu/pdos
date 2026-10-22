"""Exact Wave15 v4 graph pair, retaining the failed v3 expiry evidence."""

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


candidate = REPORT / "backend-candidate-v4-source.json"
frozen = json.loads(candidate.read_text())
assert len(frozen["files"]) == 303
assert all(sha(ROOT.parent / p) == value for p, value in frozen["files"].items())
original = json.loads((REPORT / "pg-result.json").read_text())
assert len(original) == 13
assert {key for key, value in original.items() if value["exit_code"]} == {"pg-02", "pg-11", "pg-12"}
prior = json.loads((REPORT / "backend-candidate-v3-delta.json").read_text())
assert len(prior["rechecks"]) == 2
assert sorted(entry["exit_code"] for entry in prior["rechecks"]) == [0, 1]
for entry in prior["rechecks"]:
    assert all(sha(REPORT / entry[field]) == entry[field.replace("_file", "_sha256")]
               for field in ("selection_file", "result_file", "log_file"))
state = verified(read_state())
assert state["port"] == 62513


def run(number):
    group = f"pg-{number}"
    nodes = original[group]["nodes"]
    stem = f"graph-speed-recheck-v4-{group.replace('-', '')}"
    selection_name = stem + "-selection.json"
    result_name = stem + "-result.json"
    binding = dict(nodes=nodes, candidate=candidate.name, candidate_sha256=sha(candidate))
    write(selection_name, binding)
    checked = verified(read_state())
    start = time.monotonic()
    with (REPORT / (stem + ".log")).open("x") as output:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-rA", "--tb=short", *nodes],
            cwd=SERVER, env=environment(checked), stdout=output, stderr=subprocess.STDOUT,
        )
    stable = all(sha(ROOT.parent / path) == value for path, value in frozen["files"].items())
    write(result_name, {**binding, "exit_code": result.returncode,
                       "seconds": round(time.monotonic() - start, 2), "source_stable": stable})
    print(group, result.returncode, "source_stable", stable, flush=True)
    return dict(nodes=nodes, selection_file=selection_name,
                selection_sha256=sha(REPORT / selection_name),
                result_file=result_name, result_sha256=sha(REPORT / result_name),
                log_file=stem + ".log", log_sha256=sha(REPORT / (stem + ".log")),
                exit_code=result.returncode, source_stable=stable)


with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(run, ("11", "12")))
previous = REPORT / "backend-candidate-v3-source.json"
difference = json.loads((REPORT / "backend-candidate-v4-source-difference.json").read_text())
write("backend-candidate-v4-delta.json", dict(
    previous_manifest=previous.name, current_manifest=candidate.name,
    previous_manifest_sha256=sha(previous), current_manifest_sha256=sha(candidate),
    changes=difference["changes"], rechecks=results,
    supersedes_exact_graph_stage=dict(record="backend-candidate-v3-delta.json",
                                     sha256=sha(REPORT / "backend-candidate-v3-delta.json")),
    unaffected_checks="Original complete scoped v1 PG, v2 merge; v3 pass/fail retained. "
                      "v4 checks only the exact affected graph pair; no v4 whole-tree joint claim.",
))
raise SystemExit(int(any(value["exit_code"] or not value["source_stable"] for value in results)))
