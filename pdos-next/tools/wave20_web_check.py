"""Root-only frozen web checkpoint; no API, credentials or business commands."""

import hashlib
import json
import os
import subprocess
import sys

from local_environment import ROOT

WEB = ROOT / "web"
REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave20-20261003"
tag = sys.argv[1] if len(sys.argv) > 1 else "v1"
assert tag.startswith("v") and tag[1:].isdigit()
previous = REPORT.parent / "pdos-next-wave19-20261003/candidate-source-v2.json"
paths = set(json.loads(previous.read_text())["web_files"])
paths.update(str(p.relative_to(ROOT.parent)) for p in (WEB / "src").rglob("*") if p.is_file())
files = {
    name: hashlib.sha256((ROOT.parent / name).read_bytes()).hexdigest() for name in sorted(paths)
}
with (REPORT / f"web-candidate-source-{tag}.json").open("x") as output:
    json.dump(
        {"files": files, "scope": "all current src plus retained ten web config entries"},
        output,
        indent=2,
    )
    output.write("\n")
results = []
for name, args in (
    ("lint", ["pnpm", "lint"]),
    ("build", ["pnpm", "build"]),
    ("typecheck", ["pnpm", "exec", "tsc", "--noEmit"]),
):
    with (REPORT / f"web-{name}-{tag}.log").open("x") as output:
        result = subprocess.run(
            args, cwd=WEB, env=os.environ.copy(), stdout=output, stderr=subprocess.STDOUT
        )
    results.append({"check": name, "exit_code": result.returncode})
    if result.returncode:
        raise RuntimeError(f"Frozen web {name} failed; retained diagnostics describe the failure")
changed = [
    name
    for name, sha in files.items()
    if hashlib.sha256((ROOT.parent / name).read_bytes()).hexdigest() != sha
]
with (REPORT / f"web-build-result-{tag}.json").open("x") as output:
    json.dump(
        {"files": len(files), "checks": results, "source_stable": not changed, "changed": changed},
        output,
        indent=2,
    )
    output.write("\n")
if changed:
    raise RuntimeError("Web sources changed during this checkpoint")
print("Frozen web lint/build/typecheck passed")
