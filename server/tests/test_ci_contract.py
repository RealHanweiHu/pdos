from pathlib import Path

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
    assert "make type" in commands
    assert "make test" in commands
    assert "make build" in commands
    assert "scripts.migrate_test" in commands
    assert "CREATE EXTENSION IF NOT EXISTS vector" in commands
    assert "PDOS_LLM_API_KEY" not in workflow_path.read_text()
