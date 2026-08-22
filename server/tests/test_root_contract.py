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


def test_llm_templates_preconfigure_the_supported_provider_catalog() -> None:
    expected_presets = {
        "minimax | openai-compatible | https://api.minimaxi.com/v1 | MiniMax-M3",
        "deepseek | openai-compatible | https://api.deepseek.com | deepseek-v4-flash",
        "glm | openai-compatible | https://open.bigmodel.cn/api/paas/v4 | glm-5.2",
        "openai | openai-compatible | https://api.openai.com/v1 | gpt-5.1",
        "anthropic | native | SDK default | claude-sonnet-5",
        "openrouter | openai-compatible | https://openrouter.ai/api/v1 | openai/gpt-5.2",
        "opencode_go | openai-compatible | https://opencode.ai/zen/go/v1 | deepseek-v4-flash",
    }
    expected_optional_keys = {
        "PDOS_LLM_MINIMAX_API_KEY=",
        "PDOS_LLM_DEEPSEEK_API_KEY=",
        "PDOS_LLM_GLM_API_KEY=",
        "PDOS_LLM_OPENAI_API_KEY=",
        "ANTHROPIC_API_KEY=",
        "PDOS_LLM_OPENROUTER_API_KEY=",
        "PDOS_LLM_OPENCODE_GO_API_KEY=",
    }
    expected_provider_settings = {
        "PDOS_LLM_MINIMAX_BASE_URL=https://api.minimaxi.com/v1",
        "PDOS_LLM_MINIMAX_MODEL=MiniMax-M3",
        "PDOS_LLM_DEEPSEEK_BASE_URL=https://api.deepseek.com",
        "PDOS_LLM_DEEPSEEK_MODEL=deepseek-v4-flash",
        "PDOS_LLM_GLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4",
        "PDOS_LLM_GLM_MODEL=glm-5.2",
        "PDOS_LLM_OPENAI_BASE_URL=https://api.openai.com/v1",
        "PDOS_LLM_OPENAI_MODEL=gpt-5.1",
        "PDOS_LLM_ANTHROPIC_BASE_URL=https://api.anthropic.com",
        "PDOS_LLM_ANTHROPIC_MODEL=claude-sonnet-5",
        "PDOS_LLM_OPENROUTER_BASE_URL=https://openrouter.ai/api/v1",
        "PDOS_LLM_OPENROUTER_MODEL=openai/gpt-5.2",
        "PDOS_LLM_OPENCODE_GO_BASE_URL=https://opencode.ai/zen/go/v1",
        "PDOS_LLM_OPENCODE_GO_MODEL=deepseek-v4-flash",
    }

    for template_name in (".env.example", ".env.production.example"):
        template = (REPOSITORY_ROOT / template_name).read_text()

        assert "PDOS_LLM_PROVIDER=minimax\n" in template
        assert "PDOS_LLM_BASE_URL=https://api.minimaxi.com/v1\n" in template
        assert "PDOS_LLM_API_KEY=\n" in template
        assert "PDOS_LLM_MODEL=MiniMax-M3\n" in template
        assert all(preset in template for preset in expected_presets)
        assert all(f"{key}\n" in template for key in expected_optional_keys)
        assert all(f"{setting}\n" in template for setting in expected_provider_settings)


def test_internal_api_address_is_never_exposed_as_a_public_browser_variable() -> None:
    for template_name in (".env.example", ".env.production.example"):
        template = (REPOSITORY_ROOT / template_name).read_text()

        assert "PDOS_API_INTERNAL_URL=" in template
        assert "NEXT_PUBLIC_PDOS_API" not in template


def test_runtime_smoke_uses_the_fail_closed_test_database() -> None:
    smoke_script = (REPOSITORY_ROOT / "scripts" / "smoke-app.sh").read_text()

    assert "configured_test_database_url" in smoke_script
    assert 'DATABASE_URL="$test_database_url"' in smoke_script
