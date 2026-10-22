"""Read-only interface capture and owned candidate hashing; no credentials/environment files."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
EVIDENCE = Path(__file__).resolve().parent
CONSUMED = [
    "AGENTS.md", "pdos-next/web/AGENTS.md", "tasks/ai-native-integrated-todo.md",
    "docs/design/2026-10-02-pdos-next-execution-plan.md",
    "docs/design/2026-10-02-pdos-complete-target-architecture-v1.md",
    "docs/design/2026-08-09-ui-baseline.md",
    "docs/design/2026-09-20-ai-direct-write-tier-policy.md",
    "pdos-next/server/pdos_next/providers/types.py",
    "pdos-next/server/pdos_next/providers/client.py",
    "pdos-next/server/pdos_next/model_gateway/ports.py",
    "pdos-next/server/pdos_next/model_gateway/claim.py",
    "pdos-next/server/pdos_next/models.py", "pdos-next/server/pdos_next/service.py",
    "pdos-next/server/pdos_next/errors.py", "pdos-next/server/pyproject.toml",
    "pdos-next/web/package.json", "pdos-next/web/tsconfig.json",
    "pdos-next/web/src/components/ui/button.tsx", "pdos-next/web/src/lib/utils.ts",
    "pdos-next/web/node_modules/next/dist/docs/01-app/01-getting-started/05-server-and-client-components.md",
]
OWNED = [
    "pdos-next/server/pdos_next/model_configuration",
    "pdos-next/server/pdos_next/schemas/model_configuration",
    "pdos-next/server/tests/model_configuration",
    "pdos-next/web/src/components/model_configuration",
]


def capture(paths):
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in paths}


if __name__ == "__main__":
    import sys
    mode = sys.argv[1]
    if mode == "consume":
        result = capture(CONSUMED)
        (EVIDENCE / "consumed-initial.json").write_text(json.dumps(result, indent=2) + "\n")
    elif mode == "freeze":
        files = sorted(str(path.relative_to(ROOT)) for directory in OWNED
                       for path in (ROOT / directory).rglob("*") if path.is_file()
                       and "__pycache__" not in path.parts)
        result = capture(files)
        candidate = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
        (EVIDENCE / "candidate.json").write_text(json.dumps(
            {"candidate_sha256": candidate, "files": result}, indent=2) + "\n")
        print(candidate)
    elif mode == "drift":
        initial = json.loads((EVIDENCE / "consumed-initial.json").read_text())
        current = capture(CONSUMED)
        changed = [path for path in CONSUMED if initial[path] != current[path]]
        (EVIDENCE / "consumed-final.json").write_text(json.dumps(current, indent=2) + "\n")
        (EVIDENCE / "drift.json").write_text(json.dumps({"changed": changed}, indent=2) + "\n")
        print(json.dumps({"changed": changed}))
