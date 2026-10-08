"""Read completed evidence and frozen files; never starts tests or opens a database."""

import hashlib
import json
import re

from local_environment import ROOT

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave14-20261002"
LOGS = (
    "regression-professional",
    "regression-build",
    "regression-handoff",
    "regression-pure",
    "regression-launch-recheck",
    "regression-mock-recheck",
    "regression-narrow-port-recheck",
    "launch-result-clock-recheck",
    *(f"new-pg-{n:02}" for n in range(10, 15)),
    "retained-deviation-recheck",
    *(f"results-authority-recheck-{n:02}" for n in (1, 4, 7, 8, 9)),
    *(f"results-pass-sample-recheck-{n:02}" for n in range(1, 4)),
    "result-operation-count-recheck",
    "concurrent-source-cas-recheck",
)
passed, failed, unfinished, rows = set(), set(), [], {}
for name in LOGS:
    path = REPORT / (name + ".log")
    content = path.read_text() if path.exists() else ""
    successes = set(re.findall(r"^PASSED (tests/[^\n]+)$", content, re.M))
    failures = set(re.findall(r"^(?:FAILED|ERROR) (tests/[^\n]+?)(?: - .*)?$", content, re.M))
    if not re.search(r"\d+ (?:passed|failed|error)(?:s)?(?:,| in )", content):
        unfinished.append(name)
    passed.update(successes)
    failed.update(failures)
    rows[name] = {"passed": sorted(successes), "failed": sorted(failures)}
manifest = json.loads((REPORT / "candidate-final-v6-source.json").read_text())
changed = [
    name
    for name, value in manifest["files"].items()
    if not (ROOT.parent / name).is_file()
    or hashlib.sha256((ROOT.parent / name).read_bytes()).hexdigest() != value
]
external = None
note = REPORT / "parallel-frontend-change.json"
if note.exists():
    external = json.loads(note.read_text())
    backup = ROOT.parent / external["verified_original_copy"]
    if hashlib.sha256(backup.read_bytes()).hexdigest() != manifest["files"][external["path"]]:
        raise RuntimeError("Parallel owner backup does not equal the frozen Wave14 entry")
    # This preserves the original candidate, not a claim that a later UI passed.
    separate = json.loads((REPORT / "parallel-frontend-source-delta-v2.json").read_text())
    if separate["owner_thread"] != external["owner_thread"]:
        raise RuntimeError("Separate frontend ownership could not be verified")
    for name, hashes in separate["files"].items():
        if manifest["files"][name] != hashes["original_sha256"]:
            raise RuntimeError("Separate frontend record altered its original candidate")
    external["subsequent_changes"] = separate
    changed = [name for name in changed if name not in separate["files"]]
value = {
    "status": "pending" if unfinished else "completed",
    "deduplicated_passed": len(passed),
    "unreplaced_failed": sorted(failed - passed),
    "unfinished": unfinished,
    "frozen_paths": len(manifest["files"]),
    "changed_covered_files": changed,
    "later_parallel_frontend_change": external,
    "selected_logs": rows,
    "source_manifest": "candidate-final-v6-source.json",
    "scope": "impact selection and exact repairs across preserved candidates; not formal Exit",
}
print(json.dumps({k: v for k, v in value.items() if k != "selected_logs"}, indent=2))
if not unfinished:
    if changed or failed - passed or len(passed) != 429:
        raise RuntimeError("Final evidence selection does not satisfy its explicit closure")
    with (REPORT / "final-check-selection.json").open("x") as output:
        output.write(json.dumps(value, indent=2) + "\n")
