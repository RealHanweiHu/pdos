"""Root freezes and builds the Wave17 frontend once on its final source candidate."""

import hashlib
import json
import os
import subprocess
import sys

from local_environment import ROOT

WEB = ROOT / "web"
REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave17-20261003"
ignored = {"node_modules", ".next", ".local"}
tag = sys.argv[1] if len(sys.argv) == 2 else ""
if len(sys.argv) > 2 or (tag and (not tag.startswith("v") or not tag[1:].isdigit())):
    raise RuntimeError("Frontend candidate tag requires an explicit numbered revision")
suffix = "-" + tag if tag else ""
files = {
    str(path.relative_to(ROOT.parent)): hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted(WEB.rglob("*"))
    if path.is_file() and not ignored.intersection(path.parts) and path.suffix != ".tsbuildinfo"
}
with (REPORT / ("web-candidate-source" + suffix + ".json")).open("x") as output:
    json.dump(
        {"files": files, "scope": "Wave17 actual public BFF, parent followup and candidate panel"}, output, indent=2
    )
    output.write("\n")
results = []
for name, command in (("lint", ["pnpm", "lint"]), ("build", ["pnpm", "build"])):
    with (REPORT / f"web{suffix}-{name}.log").open("x") as output:
        result = subprocess.run(
            command, cwd=WEB, env=os.environ.copy(), stdout=output, stderr=subprocess.STDOUT
        )
    results.append({"check": name, "exit_code": result.returncode})
    if result.returncode:
        raise RuntimeError(f"Frontend {name} failed; inspect retained diagnostics")
changed = [
    name
    for name, sha in files.items()
    if hashlib.sha256((ROOT.parent / name).read_bytes()).hexdigest() != sha
]
with (REPORT / ("web-build-result" + suffix + ".json")).open("x") as output:
    json.dump(
        {"files": len(files), "checks": results, "source_stable": not changed, "changed": changed},
        output,
        indent=2,
    )
    output.write("\n")
if changed:
    raise RuntimeError("Frontend sources changed while building the frozen candidate")
print("Wave17 frozen frontend lint/build/typecheck passed")
