"""Freeze and build the integrated frontend once, without business mutations."""

import hashlib
import json
import os
import subprocess
import sys

from local_environment import ROOT

WEB = ROOT / "web"
REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave15-20261002"
tag = "" if len(sys.argv) == 1 else "-" + sys.argv[1]
if tag not in {"", "-v2"}:
    raise ValueError("Explicit frontend candidate required")
ignored = {"node_modules", ".next", ".local"}
files = {
    str(path.relative_to(ROOT.parent)): hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted(WEB.rglob("*"))
    if path.is_file() and not ignored.intersection(path.parts) and path.suffix != ".tsbuildinfo"
}
with (REPORT / f"web-candidate{tag}-source.json").open("x") as output:
    output.write(
        json.dumps(
            {
                "files": files,
                "scope": "Completed parallel navigation plus actual quality/change entry and BFF",
            },
            indent=2,
        )
        + "\n"
    )
results = []
for name, command in (("lint", ["pnpm", "lint"]), ("build", ["pnpm", "build"])):
    with (REPORT / f"web{tag}-{name}.log").open("x") as output:
        result = subprocess.run(
            command, cwd=WEB, env=os.environ.copy(), stdout=output, stderr=subprocess.STDOUT
        )
    results.append({"check": name, "exit_code": result.returncode})
    if result.returncode:
        raise RuntimeError(f"Frontend {name} failed; inspect saved diagnostics")
changed = [
    name
    for name, sha in files.items()
    if hashlib.sha256((ROOT.parent / name).read_bytes()).hexdigest() != sha
]
assert not changed, "Do not claim that a changed frontend passed the frozen build"
with (REPORT / f"web{tag}-build-result.json").open("x") as output:
    output.write(
        json.dumps({"files": len(files), "checks": results, "source_stable": True}, indent=2) + "\n"
    )
print("Integrated frontend lint, build and TypeScript check passed on its frozen source.")
