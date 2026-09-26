import json
from pathlib import Path

import pytest
import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_ci_enforces_quality_and_isolated_migration_gates() -> None:
    workflow_path = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
    workflow = yaml.load(workflow_path.read_text(), Loader=yaml.BaseLoader)
    quality = workflow["jobs"]["quality"]
    commands = "\n".join(step.get("run", "") for step in quality["steps"])

    assert set(workflow["on"]) == {"pull_request", "push"}
    assert quality["services"]["postgres"]["image"] == ("pgvector/pgvector:0.8.6-pg16-bookworm")
    assert quality["env"]["TEST_DATABASE_URL"].endswith("/pdos_test")
    assert "make lint" in commands
    assert "make audit-dependencies" in commands
    assert "make type" in commands
    assert "make test" in commands
    assert "make sprint2-removal-drill" in commands
    assert "make sprint2-redteam" in commands
    assert "make build" in commands
    assert "make smoke-app" in commands
    assert "scripts.migrate_test" in commands
    assert "CREATE EXTENSION IF NOT EXISTS vector" in commands
    assert "PDOS_LLM_API_KEY" not in workflow_path.read_text()


def test_dependency_audit_is_a_fail_closed_make_gate() -> None:
    makefile = (REPOSITORY_ROOT / "Makefile").read_text()
    audit = (REPOSITORY_ROOT / "server" / "scripts" / "audit_dependencies.py").read_text()

    assert "audit-dependencies:" in makefile
    assert "check: audit-dependencies" in makefile
    assert "https://api.osv.dev/v1/querybatch" in audit
    assert "MAX_RESPONSE_BYTES" in audit
    assert "DEPENDENCY_AUDIT_NETWORK_ERROR" in audit
    assert "DEPENDENCY_AUDIT_RESPONSE_INVALID" in audit


def test_web_typecheck_generates_route_types_in_a_clean_checkout() -> None:
    package_path = REPOSITORY_ROOT / "web" / "package.json"
    scripts = json.loads(package_path.read_text())["scripts"]

    assert scripts["typecheck"] == "next typegen && tsc --noEmit"


def test_runtime_cannot_mutate_the_golden_trust_root(tmp_path: Path) -> None:
    from scripts.probe_minimax_input_metering import candidate_evidence_path

    runtime_roots = [
        REPOSITORY_ROOT / "server" / "app",
        REPOSITORY_ROOT / "server" / "scripts",
    ]
    disallowed = []
    for root in runtime_roots:
        for path in root.rglob("*.py"):
            source = path.read_text()
            if "golden" in source.lower() and any(
                token in source for token in ("write_text(", "write_bytes(", 'open("w')
            ):
                disallowed.append(path.relative_to(REPOSITORY_ROOT))

    assert disallowed == []
    trusted = REPOSITORY_ROOT / "server/golden"
    alias = tmp_path / "trusted-alias"
    alias.symlink_to(trusted, target_is_directory=True)
    for output in (trusted / "candidate.json", alias / "candidate.json"):
        with pytest.raises(ValueError, match="golden trust root"):
            candidate_evidence_path(output)
    assert candidate_evidence_path(tmp_path / "candidate.json") == tmp_path / "candidate.json"
