from pathlib import Path
from typing import cast

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def production_services() -> dict[str, dict[str, object]]:
    document: object = yaml.safe_load((REPOSITORY_ROOT / "compose.production.yaml").read_text())
    assert isinstance(document, dict)
    services = document.get("services")
    assert isinstance(services, dict)
    return cast(dict[str, dict[str, object]], services)


def test_production_compose_exposes_only_the_web_service() -> None:
    services = production_services()

    assert set(services) == {"migrate", "api", "web"}
    assert "ports" not in services["api"]
    assert "ports" not in services["migrate"]
    assert "extra_hosts" not in services["api"]
    assert "extra_hosts" not in services["migrate"]
    assert services["web"]["ports"] == ["127.0.0.1:${APP_PORT:-3002}:3000"]
    assert services["web"]["networks"] == {
        "default": {"aliases": ["pdos-web"]},
    }
    web_environment = cast(dict[str, str], services["web"]["environment"])
    assert web_environment["PDOS_API_INTERNAL_URL"] == "http://api:8000"


def test_production_startup_orders_migration_api_and_web() -> None:
    services = production_services()
    api_dependencies = cast(dict[str, dict[str, str]], services["api"]["depends_on"])
    web_dependencies = cast(dict[str, dict[str, str]], services["web"]["depends_on"])
    api_healthcheck = cast(dict[str, object], services["api"]["healthcheck"])
    web_healthcheck = cast(dict[str, object], services["web"]["healthcheck"])

    assert services["migrate"]["command"] == ["alembic", "upgrade", "head"]
    assert api_dependencies["migrate"]["condition"] == "service_completed_successfully"
    assert web_dependencies["api"]["condition"] == "service_healthy"
    assert api_healthcheck["test"]
    assert web_healthcheck["test"]


def test_production_api_receives_only_server_side_model_configuration() -> None:
    api_environment = cast(dict[str, str], production_services()["api"]["environment"])

    assert api_environment["PDOS_LLM_PROVIDER"] == "${PDOS_LLM_PROVIDER:-minimax}"
    assert api_environment["PDOS_LLM_API_KEY"] == "${PDOS_LLM_API_KEY:-}"
    assert api_environment["PDOS_LLM_ANTHROPIC_API_KEY"] == ("${PDOS_LLM_ANTHROPIC_API_KEY:-}")
    assert api_environment["PDOS_AI_DAILY_TOKEN_BUDGET"] == (
        "${PDOS_AI_DAILY_TOKEN_BUDGET:-2000000}"
    )
    web_environment = cast(dict[str, str], production_services()["web"]["environment"])
    assert not any(name.startswith("PDOS_LLM_") for name in web_environment)


def test_production_images_run_as_non_root_and_web_uses_standalone_output() -> None:
    services = production_services()
    server_dockerfile = (REPOSITORY_ROOT / "server" / "Dockerfile").read_text()
    web_dockerfile = (REPOSITORY_ROOT / "web" / "Dockerfile").read_text()
    next_config = (REPOSITORY_ROOT / "web" / "next.config.ts").read_text()
    api_build = cast(dict[str, object], services["api"]["build"])
    api_build_args = cast(dict[str, str], api_build["args"])

    assert "USER pdos" in server_dockerfile
    assert "COPY server/golden ./golden" in server_dockerfile
    assert "USER nextjs" in web_dockerfile
    assert "ARG PYTHON_BASE_IMAGE=" in server_dockerfile
    assert "ARG UV_BASE_IMAGE=" in server_dockerfile
    assert "ARG UV_DEFAULT_INDEX=" in server_dockerfile
    assert "UV_DEFAULT_INDEX=${UV_DEFAULT_INDEX}" in server_dockerfile
    assert api_build_args["UV_DEFAULT_INDEX"] == (
        "${PDOS_UV_DEFAULT_INDEX:-https://pypi.org/simple}"
    )
    assert "ARG NODE_BASE_IMAGE=" in web_dockerfile
    assert server_dockerfile.count("@sha256:") == 2
    assert web_dockerfile.count("@sha256:") == 1
    assert 'output: "standalone"' in next_config
    for header in (
        "Content-Security-Policy",
        "Permissions-Policy",
        "Referrer-Policy",
        "Strict-Transport-Security",
        "X-Content-Type-Options",
        "X-Frame-Options",
    ):
        assert header in next_config
    assert "/app/certs/ApsaraDB-CA-Chain.pem" in server_dockerfile


def test_sprint_zero_runbook_has_preflight_smoke_and_rollback_gates() -> None:
    runbook = (REPOSITORY_ROOT / "docs" / "runbooks" / "sprint-0-ecs-smoke.md").read_text()

    assert "RDS" in runbook
    assert "OSS" in runbook
    assert "Nginx" in runbook
    assert "pdos.beepump.net" in runbook
    assert "pdos_default" in runbook
    assert "certbot" in runbook
    assert "回滚" in runbook
    assert "明确授权" in runbook
    assert "公开前" in runbook
    assert "SSH 端口转发" in runbook


def test_production_smoke_is_isolated_and_available_from_the_root_makefile() -> None:
    makefile = (REPOSITORY_ROOT / "Makefile").read_text()
    smoke_script = (REPOSITORY_ROOT / "scripts" / "smoke-production.sh").read_text()
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text()

    assert "smoke-production:" in makefile
    assert "verify-sprint-0:" in makefile
    assert "pdos-s0-production-smoke" in smoke_script
    assert "configured_test_database_url" in smoke_script
    assert "/api/session/status" in smoke_script
    assert "compose.production.yaml" in smoke_script
    assert "compose.production-smoke.yaml" in smoke_script
    assert "content-security-policy" in smoke_script.lower()
    assert "strict-transport-security" in smoke_script.lower()
    assert "x-content-type-options" in smoke_script.lower()
    assert "make smoke-production" in workflow
