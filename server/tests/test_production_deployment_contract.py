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

    assert set(services) == {"migrate", "api", "dispatcher", "executor", "web"}
    assert "ports" not in services["api"]
    assert "ports" not in services["migrate"]
    assert "ports" not in services["dispatcher"]
    assert "ports" not in services["executor"]
    assert "extra_hosts" not in services["api"]
    assert "extra_hosts" not in services["migrate"]
    assert "extra_hosts" not in services["dispatcher"]
    assert "extra_hosts" not in services["executor"]
    assert services["web"]["ports"] == ["127.0.0.1:${APP_PORT:-3002}:3000"]
    assert services["web"]["networks"] == {
        "default": {"aliases": ["pdos-web"]},
    }
    web_environment = cast(dict[str, str], services["web"]["environment"])
    assert web_environment["PDOS_API_INTERNAL_URL"] == "http://api:8000"


def test_production_startup_orders_migration_api_and_web() -> None:
    services = production_services()
    api_dependencies = cast(dict[str, dict[str, str]], services["api"]["depends_on"])
    dispatcher_dependencies = cast(dict[str, dict[str, str]], services["dispatcher"]["depends_on"])
    executor_dependencies = cast(dict[str, dict[str, str]], services["executor"]["depends_on"])
    web_dependencies = cast(dict[str, dict[str, str]], services["web"]["depends_on"])
    api_healthcheck = cast(dict[str, object], services["api"]["healthcheck"])
    web_healthcheck = cast(dict[str, object], services["web"]["healthcheck"])

    assert services["migrate"]["command"] == ["alembic", "upgrade", "head"]
    assert api_dependencies["migrate"]["condition"] == "service_completed_successfully"
    assert dispatcher_dependencies["migrate"]["condition"] == "service_completed_successfully"
    assert executor_dependencies["migrate"]["condition"] == "service_completed_successfully"
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


def test_production_dispatcher_and_executor_have_disjoint_runtime_credentials() -> None:
    services = production_services()
    dispatcher = services["dispatcher"]
    executor = services["executor"]
    dispatcher_environment = cast(dict[str, str], dispatcher["environment"])
    executor_environment = cast(dict[str, str], executor["environment"])
    dispatcher_healthcheck = cast(dict[str, object], dispatcher["healthcheck"])
    executor_healthcheck = cast(dict[str, object], executor["healthcheck"])

    assert dispatcher["command"] == ["python", "-m", "scripts.run_dispatcher"]
    assert executor["command"] == ["python", "-m", "scripts.run_executor"]
    assert dispatcher_environment["PDOS_WORKER_DATABASE_URL"] == (
        "${PDOS_WORKER_DATABASE_URL:?PDOS_WORKER_DATABASE_URL must be set}"
    )
    assert executor_environment["PDOS_AGENT_DATABASE_URL"] == (
        "${PDOS_AGENT_DATABASE_URL:?PDOS_AGENT_DATABASE_URL must be set}"
    )
    assert "DATABASE_URL" not in dispatcher_environment
    assert "DATABASE_URL" not in executor_environment
    assert "PDOS_AGENT_DATABASE_URL" not in dispatcher_environment
    assert "PDOS_WORKER_DATABASE_URL" not in executor_environment
    assert "PDOS_ALLOW_SHARED_RUNTIME_DATABASE_URL" not in dispatcher_environment
    assert "PDOS_ALLOW_SHARED_RUNTIME_DATABASE_URL" not in executor_environment
    assert not any(name.startswith("PDOS_LLM_") for name in dispatcher_environment)
    assert executor_environment["PDOS_LLM_API_KEY"] == "${PDOS_LLM_API_KEY:-}"
    assert "scripts.run_dispatcher" in str(dispatcher_healthcheck["test"])
    assert "scripts.run_executor" in str(executor_healthcheck["test"])


def test_production_images_run_as_non_root_and_web_uses_standalone_output() -> None:
    services = production_services()
    server_dockerfile = (REPOSITORY_ROOT / "server" / "Dockerfile").read_text()
    web_dockerfile = (REPOSITORY_ROOT / "web" / "Dockerfile").read_text()
    next_config = (REPOSITORY_ROOT / "web" / "next.config.ts").read_text()
    api_build = cast(dict[str, object], services["api"]["build"])
    api_build_args = cast(dict[str, str], api_build["args"])

    assert "USER pdos" in server_dockerfile
    assert "COPY server/golden ./golden" in server_dockerfile
    assert "COPY server/scripts ./scripts" in server_dockerfile
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
    assert "scripts/deploy-ecs.sh" in runbook
    assert "PDOS_DEPLOY_CONFIRM" in runbook
    assert "PDOS_ROLLBACK_CONFIRM" in runbook
    assert "重施加并验证 Agent 最小权限" in runbook


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
    assert 'PDOS_AGENT_DATABASE_URL="$agent_database_url"' in smoke_script
    assert 'PDOS_WORKER_DATABASE_URL="$worker_database_url"' in smoke_script
    assert 'username="pdos_agent"' in smoke_script
    assert 'username="pdos_worker"' in smoke_script
    assert "scripts.manage_test_agent_security" in smoke_script
    assert "content-security-policy" in smoke_script.lower()
    assert "strict-transport-security" in smoke_script.lower()
    assert "x-content-type-options" in smoke_script.lower()
    assert "make smoke-production" in workflow


def test_agent_database_security_runbook_keeps_production_actions_human_owned() -> None:
    runbook = (
        REPOSITORY_ROOT / "docs" / "runbooks" / "agent-runtime-database-security.md"
    ).read_text()

    assert "pdos_worker" in runbook
    assert "pdos_agent" in runbook
    assert "pdos_app" in runbook
    assert "人工" in runbook
    assert "幂等" in runbook
    assert "0 行" in runbook
    assert "permission denied" in runbook
    assert "agent-runtime-roles.sql" in runbook
    assert "agent-runtime.sql" in runbook
    assert "agent-runtime-revert.sql" in runbook
    assert "不得临时把 `pdos_app` 凭据交给 executor" in runbook


def test_ecs_deploy_entrypoint_is_staged_confirmed_and_observable() -> None:
    deploy_script = REPOSITORY_ROOT / "scripts" / "deploy-ecs.sh"
    source = deploy_script.read_text()

    assert deploy_script.stat().st_mode & 0o111
    assert "set -euo pipefail" in source
    assert "preflight|build|deploy|status|rollback" in source
    assert "PDOS_DEPLOY_CONFIRM" in source
    assert "mode 0600" in source
    assert "env -i" in source
    assert "PDOS_COMPOSE_IMAGE_TAG_OVERRIDE" in source
    assert "compose_config run --rm --no-deps migrate" in source
    assert "scripts.apply_agent_runtime_security" in source
    assert (
        source.index("compose_config run --rm --no-deps migrate")
        < source.index("scripts.apply_agent_runtime_security")
        < source.index("compose_config up -d --no-build --wait")
    )
    assert "http://127.0.0.1:${app_port}/api/session/status" in source
    assert "https://pdos.beepump.net/login" in source
    assert "docker compose logs" not in source
    assert "compose_config logs --since" in source
    assert "Traceback|fatal|panic|permission denied|connection refused" in source


def test_ecs_rollback_never_runs_an_old_migrator_or_downgrades_the_database() -> None:
    source = (REPOSITORY_ROOT / "scripts" / "deploy-ecs.sh").read_text()
    rollback = source[source.index("rollback_release()") : source.index('case "$action"')]

    assert "PDOS_ROLLBACK_CONFIRM" in rollback
    assert "PDOS_ROLLBACK_IMAGE_TAG" in rollback
    assert "--no-deps --no-build --wait api dispatcher executor" in rollback
    assert "--no-deps --no-build --wait web" in rollback
    assert "migrate" not in rollback
    assert "downgrade" not in rollback


def test_runtime_security_apply_helper_is_fail_closed_and_does_not_log_database_url() -> None:
    source = (
        REPOSITORY_ROOT / "server" / "scripts" / "apply_agent_runtime_security.py"
    ).read_text()

    assert "required environment variable is missing: DATABASE_URL" in source
    assert 'username != "pdos_app"' in source
    assert 'database != "pdos"' in source
    assert "prepare=False" in source
    assert "has_table_privilege" in source
    assert "Production Agent runtime security boundary applied" in source
    assert "print(database_url)" not in source
