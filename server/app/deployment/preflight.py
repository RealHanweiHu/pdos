"""Fail-closed validation before a production migration or deployment."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

EXPECTED_DATABASE_HOST = "pgm-2ze135h6045td5ujvo.pg.rds.aliyuncs.com"
EXPECTED_CA_PATH = "/app/certs/ApsaraDB-CA-Chain.pem"
REQUIRED_VALUES = (
    "APP_PORT",
    "DATABASE_URL",
    "JWT_SECRET",
    "PDOS_API_INTERNAL_URL",
    "PDOS_IMAGE_TAG",
    "PDOS_WORKER_DATABASE_URL",
    "PDOS_AGENT_DATABASE_URL",
    "S3_ACCESS_KEY_ID",
    "S3_BUCKET",
    "S3_ENDPOINT",
    "S3_FORCE_PATH_STYLE",
    "S3_REGION",
    "S3_SECRET_ACCESS_KEY",
)


class UnsafeProductionConfigurationError(ValueError):
    """Raised before production tooling can touch an unsafe target."""


def _required(values: Mapping[str, str | None], key: str) -> str:
    value = values.get(key)
    if not value or value.strip() != value or "<" in value or ">" in value:
        message = f"Production configuration {key} must be set to a non-placeholder value"
        raise UnsafeProductionConfigurationError(message)
    return value


def validate_production_database_url(value: str, *, username: str) -> None:
    try:
        url = make_url(value)
    except ArgumentError as error:
        message = "Production DATABASE_URL must be a valid PostgreSQL URL"
        raise UnsafeProductionConfigurationError(message) from error

    if not url.drivername.startswith("postgresql"):
        raise UnsafeProductionConfigurationError("Production database must use PostgreSQL")
    if url.host != EXPECTED_DATABASE_HOST or url.port != 5432:
        raise UnsafeProductionConfigurationError("Production database host is not the approved RDS")
    if url.database != "pdos" or url.username != username or not url.password:
        raise UnsafeProductionConfigurationError(
            f"Production database must target pdos with the {username} account"
        )
    if url.password.lower() in {"password", "pdos", "secret"}:
        raise UnsafeProductionConfigurationError("Production database password is a known default")
    if url.query.get("sslmode") != "verify-full":
        raise UnsafeProductionConfigurationError("Production database TLS must verify the RDS host")
    if url.query.get("sslrootcert") != EXPECTED_CA_PATH:
        raise UnsafeProductionConfigurationError("Production database must use the bundled RDS CA")


def validate_production_environment(values: Mapping[str, str | None]) -> None:
    resolved = {key: _required(values, key) for key in REQUIRED_VALUES}
    validate_production_database_url(resolved["DATABASE_URL"], username="pdos_app")
    validate_production_database_url(resolved["PDOS_WORKER_DATABASE_URL"], username="pdos_worker")
    validate_production_database_url(resolved["PDOS_AGENT_DATABASE_URL"], username="pdos_agent")
    if (
        len(
            {
                resolved["DATABASE_URL"],
                resolved["PDOS_WORKER_DATABASE_URL"],
                resolved["PDOS_AGENT_DATABASE_URL"],
            }
        )
        != 3
    ):
        raise UnsafeProductionConfigurationError(
            "Production app, worker, and Agent database URLs must be distinct"
        )

    if len(resolved["JWT_SECRET"].encode("utf-8")) < 32:
        raise UnsafeProductionConfigurationError("Production JWT_SECRET must contain 32 bytes")
    if resolved["JWT_SECRET"] == "dev-only-change-this-secret-now-123":
        raise UnsafeProductionConfigurationError(
            "Development JWT_SECRET is forbidden in production"
        )
    if resolved["APP_PORT"] != "3002":
        raise UnsafeProductionConfigurationError("Production APP_PORT must remain 3002")
    if resolved["PDOS_API_INTERNAL_URL"] != "http://api:8000":
        raise UnsafeProductionConfigurationError("Production BFF must use the compose API address")
    if re.fullmatch(r"[0-9a-f]{7,40}", resolved["PDOS_IMAGE_TAG"]) is None:
        raise UnsafeProductionConfigurationError("PDOS_IMAGE_TAG must be a git commit SHA")

    s3_endpoint = urlparse(resolved["S3_ENDPOINT"])
    s3_hostname = s3_endpoint.hostname or ""
    s3_region = resolved["S3_REGION"]
    approved_oss_prefixes = (f"oss-{s3_region}.", f"oss-{s3_region}-internal.")
    if (
        re.fullmatch(r"cn-[a-z0-9-]+", s3_region) is None
        or s3_endpoint.scheme != "https"
        or not s3_hostname.endswith(".aliyuncs.com")
        or not s3_hostname.startswith(approved_oss_prefixes)
    ):
        raise UnsafeProductionConfigurationError("Production S3 endpoint must use Alibaba HTTPS")
    if resolved["S3_BUCKET"] != "pdos-files":
        raise UnsafeProductionConfigurationError("Production S3 bucket must be pdos-files")
    if resolved["S3_FORCE_PATH_STYLE"].lower() != "false":
        raise UnsafeProductionConfigurationError("Production OSS must not force path-style URLs")
    if (
        resolved["S3_ACCESS_KEY_ID"].lower() == "minioadmin"
        or len(resolved["S3_ACCESS_KEY_ID"]) < 8
        or resolved["S3_SECRET_ACCESS_KEY"].lower() == "minioadmin"
        or len(resolved["S3_SECRET_ACCESS_KEY"]) < 16
    ):
        raise UnsafeProductionConfigurationError("Local object-storage credentials are forbidden")


def validate_production_environment_file(path: Path) -> None:
    if not path.is_file() or path.is_symlink():
        raise UnsafeProductionConfigurationError(
            "Production environment file must be a regular file"
        )
    file_stat = path.stat()
    if file_stat.st_uid != os.getuid() or stat.S_IMODE(file_stat.st_mode) != 0o600:
        raise UnsafeProductionConfigurationError(
            "Production environment file must be owned by the deploy user with mode 0600"
        )
    validate_production_environment(dotenv_values(path, interpolate=False))
