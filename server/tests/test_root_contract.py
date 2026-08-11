from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REQUIRED_ROOT_COMMANDS = {"setup", "dev", "test", "lint", "type", "typecheck", "build"}
REQUIRED_S0_GATE_COMMANDS = {"infra-up", "db-migrate-test", "smoke-app", "verify-s0-1"}


def test_root_makefile_exposes_the_required_command_contract() -> None:
    makefile = (REPOSITORY_ROOT / "Makefile").read_text()
    declared_targets = {
        line.partition(":")[0]
        for line in makefile.splitlines()
        if line and not line.startswith(("\t", "#", ".")) and ":" in line
    }

    assert declared_targets >= REQUIRED_ROOT_COMMANDS
    assert declared_targets >= REQUIRED_S0_GATE_COMMANDS


def test_llm_key_is_optional_in_the_development_template() -> None:
    template = (REPOSITORY_ROOT / ".env.example").read_text()

    assert "PDOS_LLM_API_KEY=\n" in template
