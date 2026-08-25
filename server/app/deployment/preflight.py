"""Fail-closed validation before a production migration or deployment."""

from __future__ import annotations

import base64
import binascii
import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.ai.golden_suite import GoldenSuiteFileError, load_golden_suite
from app.ai.model_catalog import ModelCatalog, ProviderName
from app.ai.qualifications import GoldenQualificationFileError, load_golden_qualifications

EXPECTED_DATABASE_HOST = "pgm-2ze135h6045td5ujvo.pg.rds.aliyuncs.com"
EXPECTED_CA_PATH = "/app/certs/ApsaraDB-CA-Chain.pem"
EXPECTED_MINIMAX_BASE_URL = "https://api.minimaxi.com/v1"
EXPECTED_MINIMAX_MODEL = "MiniMax-M3"
SERVER_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_SUITE_PATH = SERVER_ROOT / "golden" / "model-gateway-v1.json"
MODEL_QUALIFICATIONS_PATH = SERVER_ROOT / "golden" / "model-qualifications.json"
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


def _optional_credential(values: Mapping[str, str | None], key: str) -> str | None:
    value = values.get(key)
    if value in {None, ""}:
        return None
    if value is None or value.strip() != value or "<" in value or ">" in value:
        raise UnsafeProductionConfigurationError(
            f"Production configuration {key} must be a non-placeholder value when set"
        )
    return value


def validate_production_model_activation(values: Mapping[str, str | None]) -> None:
    if _required(values, "PDOS_LLM_PROVIDER") != ProviderName.MINIMAX.value:
        raise UnsafeProductionConfigurationError(
            "Production AI provider must remain minimax for this release"
        )
    if _required(values, "PDOS_LLM_BASE_URL") != EXPECTED_MINIMAX_BASE_URL:
        raise UnsafeProductionConfigurationError(
            "Production MiniMax base URL must use the approved endpoint"
        )
    if _required(values, "PDOS_LLM_MODEL") != EXPECTED_MINIMAX_MODEL:
        raise UnsafeProductionConfigurationError(
            "Production AI default model must remain MiniMax-M3 for this release"
        )

    specific_base_url = values.get("PDOS_LLM_MINIMAX_BASE_URL")
    if specific_base_url and specific_base_url != EXPECTED_MINIMAX_BASE_URL:
        raise UnsafeProductionConfigurationError(
            "Production MiniMax provider base URL must use the approved endpoint"
        )
    specific_model = values.get("PDOS_LLM_MINIMAX_MODEL")
    if specific_model and specific_model != EXPECTED_MINIMAX_MODEL:
        raise UnsafeProductionConfigurationError(
            "Production MiniMax provider model must remain MiniMax-M3 for this release"
        )

    primary_key = _optional_credential(values, "PDOS_LLM_API_KEY")
    provider_key = _optional_credential(values, "PDOS_LLM_MINIMAX_API_KEY")
    if primary_key is None and provider_key is None:
        raise UnsafeProductionConfigurationError(
            "Production MiniMax M3 requires a server-side credential"
        )

    environment = {key: value for key, value in values.items() if value is not None}
    try:
        catalog = ModelCatalog.from_environment(environment)
        trusted_suite = load_golden_suite(GOLDEN_SUITE_PATH)
        qualifications = load_golden_qualifications(
            MODEL_QUALIFICATIONS_PATH,
            trusted_suite=trusted_suite,
        )
    except (GoldenQualificationFileError, GoldenSuiteFileError, ValueError) as error:
        raise UnsafeProductionConfigurationError(
            "Production MiniMax qualification inputs are invalid"
        ) from error
    eligible = {
        (candidate.provider, candidate.model)
        for candidate in catalog.eligible_models(qualifications)
    }
    if (ProviderName.MINIMAX, EXPECTED_MINIMAX_MODEL) not in eligible:
        raise UnsafeProductionConfigurationError(
            "Production MiniMax M3 must be configured and golden-qualified"
        )


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
    validate_production_model_activation(values)

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

    dingtalk_delivery = (values.get("PDOS_DINGTALK_DELIVERY_ENABLED") or "false").lower()
    if dingtalk_delivery not in {"true", "false"}:
        raise UnsafeProductionConfigurationError(
            "PDOS_DINGTALK_DELIVERY_ENABLED must be true or false"
        )
    if dingtalk_delivery == "true":
        dingtalk_values = {
            key: _required(values, key)
            for key in (
                "PDOS_DINGTALK_CLIENT_ID",
                "PDOS_DINGTALK_CLIENT_SECRET",
                "PDOS_DINGTALK_CALLBACK_TOKEN",
                "PDOS_DINGTALK_CALLBACK_AES_KEY",
                "PDOS_DINGTALK_CARD_CALLBACK_SECRET",
                "PDOS_PUBLIC_BASE_URL",
            )
        }
        if dingtalk_values["PDOS_PUBLIC_BASE_URL"] != "https://pdos.beepump.net":
            raise UnsafeProductionConfigurationError(
                "Production DingTalk callbacks must use the approved public origin"
            )
        aes_key = dingtalk_values["PDOS_DINGTALK_CALLBACK_AES_KEY"]
        try:
            decoded_aes_key = base64.b64decode(
                aes_key + "=" * (-len(aes_key) % 4),
                validate=True,
            )
        except (binascii.Error, ValueError) as error:
            raise UnsafeProductionConfigurationError(
                "Production DingTalk callback AES key is invalid"
            ) from error
        if len(decoded_aes_key) != 32:
            raise UnsafeProductionConfigurationError(
                "Production DingTalk callback AES key must decode to 32 bytes"
            )


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
