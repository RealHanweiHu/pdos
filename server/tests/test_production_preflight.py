from pathlib import Path

import pytest

from app.deployment.preflight import (
    UnsafeProductionConfigurationError,
    validate_production_environment,
    validate_production_environment_file,
)
from scripts.apply_agent_runtime_security import (
    UnsafeSecurityApplyError,
    _production_connection_info,
)
from scripts.check_production_env import main as production_preflight_main

VALID_ENVIRONMENT = {
    "APP_PORT": "3002",
    "DATABASE_URL": (
        "postgresql://pdos_app:production-password@"
        "pgm-2ze135h6045td5ujvo.pg.rds.aliyuncs.com:5432/pdos"
        "?sslmode=verify-full&sslrootcert=/app/certs/ApsaraDB-CA-Chain.pem"
    ),
    "PDOS_WORKER_DATABASE_URL": (
        "postgresql://pdos_worker:production-worker-password@"
        "pgm-2ze135h6045td5ujvo.pg.rds.aliyuncs.com:5432/pdos"
        "?sslmode=verify-full&sslrootcert=/app/certs/ApsaraDB-CA-Chain.pem"
    ),
    "PDOS_AGENT_DATABASE_URL": (
        "postgresql://pdos_agent:production-agent-password@"
        "pgm-2ze135h6045td5ujvo.pg.rds.aliyuncs.com:5432/pdos"
        "?sslmode=verify-full&sslrootcert=/app/certs/ApsaraDB-CA-Chain.pem"
    ),
    "JWT_SECRET": "production-only-jwt-secret-that-is-32-bytes",
    "PDOS_API_INTERNAL_URL": "http://api:8000",
    "PDOS_IMAGE_TAG": "cdfcab4",
    "S3_ACCESS_KEY_ID": "production-oss-key-id",
    "S3_BUCKET": "pdos-files",
    "S3_ENDPOINT": "https://oss-cn-beijing.aliyuncs.com",
    "S3_FORCE_PATH_STYLE": "false",
    "S3_REGION": "cn-beijing",
    "S3_SECRET_ACCESS_KEY": "production-oss-secret",
}


def test_valid_production_environment_passes_without_returning_secrets() -> None:
    validate_production_environment(VALID_ENVIRONMENT)


def test_enabled_dingtalk_delivery_requires_complete_callback_configuration() -> None:
    enabled = {
        **VALID_ENVIRONMENT,
        "PDOS_DINGTALK_DELIVERY_ENABLED": "true",
        "PDOS_DINGTALK_CLIENT_ID": "ding-client",
        "PDOS_DINGTALK_CLIENT_SECRET": "ding-client-secret",
        "PDOS_DINGTALK_CALLBACK_TOKEN": "ding-callback-token",
        "PDOS_DINGTALK_CALLBACK_AES_KEY": "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
        "PDOS_DINGTALK_CARD_CALLBACK_SECRET": "ding-card-callback-secret",
        "PDOS_PUBLIC_BASE_URL": "https://pdos.beepump.net",
    }
    validate_production_environment(enabled)
    for missing in (
        "PDOS_DINGTALK_CLIENT_SECRET",
        "PDOS_DINGTALK_CALLBACK_TOKEN",
        "PDOS_DINGTALK_CALLBACK_AES_KEY",
        "PDOS_DINGTALK_CARD_CALLBACK_SECRET",
    ):
        with pytest.raises(UnsafeProductionConfigurationError):
            validate_production_environment({**enabled, missing: ""})
    with pytest.raises(UnsafeProductionConfigurationError):
        validate_production_environment(
            {**enabled, "PDOS_PUBLIC_BASE_URL": "https://attacker.example"}
        )
    with pytest.raises(UnsafeProductionConfigurationError):
        validate_production_environment(
            {**VALID_ENVIRONMENT, "PDOS_DINGTALK_DELIVERY_ENABLED": "yes"}
        )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("APP_PORT", "3000"),
        ("DATABASE_URL", "postgresql://pdos_app:secret@localhost:5432/pdos"),
        ("JWT_SECRET", "too-short"),
        ("PDOS_API_INTERNAL_URL", "http://127.0.0.1:8000"),
        ("PDOS_IMAGE_TAG", "latest"),
        (
            "PDOS_WORKER_DATABASE_URL",
            "postgresql://pdos_app:secret@localhost:5432/pdos",
        ),
        (
            "PDOS_AGENT_DATABASE_URL",
            "postgresql://pdos_worker:secret@localhost:5432/pdos",
        ),
        ("S3_ACCESS_KEY_ID", "minioadmin"),
        ("S3_BUCKET", "<bucket>"),
        ("S3_FORCE_PATH_STYLE", "true"),
        ("S3_REGION", "nowhere"),
        ("S3_SECRET_ACCESS_KEY", "minioadmin"),
    ],
)
def test_unsafe_production_values_fail_closed(key: str, value: str) -> None:
    with pytest.raises(UnsafeProductionConfigurationError):
        validate_production_environment({**VALID_ENVIRONMENT, key: value})


@pytest.mark.parametrize(
    "database_url",
    [
        VALID_ENVIRONMENT["DATABASE_URL"].replace("/pdos?", "/cehub?"),
        VALID_ENVIRONMENT["DATABASE_URL"].replace("pdos_app:", "ce_hub:"),
        VALID_ENVIRONMENT["DATABASE_URL"].replace("production-password", "pdos"),
        VALID_ENVIRONMENT["DATABASE_URL"].replace("sslmode=verify-full", "sslmode=require"),
        VALID_ENVIRONMENT["DATABASE_URL"].replace(
            "/app/certs/ApsaraDB-CA-Chain.pem", "/tmp/untrusted.pem"
        ),
    ],
)
def test_wrong_database_scope_or_tls_fails_closed(database_url: str) -> None:
    with pytest.raises(UnsafeProductionConfigurationError):
        validate_production_environment({**VALID_ENVIRONMENT, "DATABASE_URL": database_url})


@pytest.mark.parametrize(
    ("key", "wrong_username"),
    [
        ("PDOS_WORKER_DATABASE_URL", "pdos_app"),
        ("PDOS_AGENT_DATABASE_URL", "pdos_worker"),
    ],
)
def test_runtime_database_roles_fail_closed(key: str, wrong_username: str) -> None:
    value = VALID_ENVIRONMENT[key]
    expected_username = "pdos_worker" if key == "PDOS_WORKER_DATABASE_URL" else "pdos_agent"
    with pytest.raises(UnsafeProductionConfigurationError):
        validate_production_environment(
            {**VALID_ENVIRONMENT, key: value.replace(expected_username, wrong_username)}
        )


def test_production_environment_file_must_be_owner_only(tmp_path: Path) -> None:
    environment_file = tmp_path / ".env.production"
    environment_file.write_text(
        "\n".join(f"{key}={value}" for key, value in VALID_ENVIRONMENT.items())
    )
    environment_file.chmod(0o644)

    with pytest.raises(UnsafeProductionConfigurationError):
        validate_production_environment_file(environment_file)

    environment_file.chmod(0o600)
    validate_production_environment_file(environment_file)


def test_container_preflight_validates_injected_environment_without_echoing_values(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for key, value in VALID_ENVIRONMENT.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("sys.argv", ["check_production_env", "--from-environment"])

    assert production_preflight_main() == 0

    output = capsys.readouterr().out
    assert "preflight passed" in output
    assert VALID_ENVIRONMENT["JWT_SECRET"] not in output
    assert VALID_ENVIRONMENT["DATABASE_URL"] not in output


@pytest.mark.parametrize(
    "database_url",
    [
        VALID_ENVIRONMENT["DATABASE_URL"].replace("pdos_app:", "pdos_agent:"),
        VALID_ENVIRONMENT["DATABASE_URL"].replace("/pdos?", "/pdos_test?"),
        VALID_ENVIRONMENT["DATABASE_URL"].replace(
            "pgm-2ze135h6045td5ujvo.pg.rds.aliyuncs.com", "localhost"
        ),
        VALID_ENVIRONMENT["DATABASE_URL"].replace("sslmode=verify-full", "sslmode=require"),
    ],
)
def test_runtime_security_helper_rejects_non_production_database_scope(
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)

    with pytest.raises(UnsafeSecurityApplyError):
        _production_connection_info()


def test_runtime_security_helper_normalizes_only_an_approved_production_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", VALID_ENVIRONMENT["DATABASE_URL"])

    connection_info = _production_connection_info()

    assert connection_info.startswith("postgresql://pdos_app:")
    assert "sslmode=verify-full" in connection_info
