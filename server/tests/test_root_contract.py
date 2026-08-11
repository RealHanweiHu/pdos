from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REQUIRED_ROOT_COMMANDS = {"setup", "dev", "test", "lint", "type", "typecheck", "build"}
REQUIRED_S0_GATE_COMMANDS = {
    "infra-up",
    "db-migrate-test",
    "production-preflight",
    "smoke-app",
    "smoke-production",
    "verify-s0-1",
    "verify-sprint-0",
}


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


def test_internal_api_address_is_never_exposed_as_a_public_browser_variable() -> None:
    for template_name in (".env.example", ".env.production.example"):
        template = (REPOSITORY_ROOT / template_name).read_text()

        assert "PDOS_API_INTERNAL_URL=" in template
        assert "NEXT_PUBLIC_PDOS_API" not in template


def test_runtime_smoke_uses_the_fail_closed_test_database() -> None:
    smoke_script = (REPOSITORY_ROOT / "scripts" / "smoke-app.sh").read_text()

    assert "configured_test_database_url" in smoke_script
    assert 'DATABASE_URL="$test_database_url"' in smoke_script
