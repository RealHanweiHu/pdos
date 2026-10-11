"""Hash the S0 backend, joined runtime and exact fixtures without private state."""

from hashlib import sha256
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]


def snapshot():
    paths = set()
    for name in (
        "pdos-next/server/pdos_next",
        "pdos-next/server/migrations",
        "pdos-next/server/tests",
        "pdos-next/tools",
        "packages/pdos-agent-runtime/src",
    ):
        paths.update(
            path for path in (REPOSITORY / name).rglob("*.py") if "preproject" not in path.parts
        )
    paths.update((REPOSITORY / "pdos-next/server/pdos_next/skill_packages").glob("*.md"))
    paths.update((REPOSITORY / "pdos-next/contracts").glob("*.json"))
    paths.add(REPOSITORY / "pdos-next/server/pdos_next/security_runtime/parser-image.json")
    return {
        str(path.relative_to(REPOSITORY)): sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }
