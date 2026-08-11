from pathlib import Path

import pytest

from app.deployment.preflight import (
    UnsafeProductionConfigurationError,
    validate_production_environment,
    validate_production_environment_file,
)

VALID_ENVIRONMENT = {
    "APP_PORT": "3002",
    "DATABASE_URL": (
        "postgresql://pdos_app:production-password@"
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


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("APP_PORT", "3000"),
        ("DATABASE_URL", "postgresql://pdos_app:secret@localhost:5432/pdos"),
        ("JWT_SECRET", "too-short"),
        ("PDOS_API_INTERNAL_URL", "http://127.0.0.1:8000"),
        ("PDOS_IMAGE_TAG", "latest"),
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
