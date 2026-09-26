"""Validated runtime configuration loaded lazily from the environment."""

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    webhook_delivery_enabled: bool = Field(
        default=False, validation_alias="PDOS_WEBHOOK_DELIVERY_ENABLED"
    )
    webhook_encryption_key: SecretStr | None = Field(
        default=None, validation_alias="PDOS_WEBHOOK_ENCRYPTION_KEY"
    )

    open_api_enabled: bool = Field(default=False, validation_alias="PDOS_OPEN_API_ENABLED")

    model_config = SettingsConfigDict(
        env_file=REPOSITORY_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str = Field(validation_alias="DATABASE_URL")
    jwt_secret: SecretStr = Field(validation_alias="JWT_SECRET")
    jwt_issuer: str = Field(default="pdos-api", validation_alias="JWT_ISSUER")
    jwt_audience: str = Field(default="pdos-web", validation_alias="JWT_AUDIENCE")
    jwt_access_token_minutes: int = Field(
        default=30,
        ge=1,
        le=1440,
        validation_alias="JWT_ACCESS_TOKEN_MINUTES",
    )
    s3_endpoint: str = Field(default="http://localhost:9000", validation_alias="S3_ENDPOINT")
    s3_region: str = Field(default="us-east-1", validation_alias="S3_REGION")
    s3_bucket: str = Field(default="pdos-files", validation_alias="S3_BUCKET")
    s3_access_key_id: SecretStr = Field(
        default=SecretStr("minioadmin"), validation_alias="S3_ACCESS_KEY_ID"
    )
    s3_secret_access_key: SecretStr = Field(
        default=SecretStr("minioadmin"), validation_alias="S3_SECRET_ACCESS_KEY"
    )
    s3_force_path_style: bool = Field(default=True, validation_alias="S3_FORCE_PATH_STYLE")
    research_search_endpoint: str | None = Field(
        default=None, validation_alias="PDOS_RESEARCH_SEARCH_ENDPOINT"
    )
    capture_recognition_enabled: bool = Field(
        default=False, validation_alias="PDOS_CAPTURE_RECOGNITION_ENABLED"
    )
    capture_tesseract_path: str | None = Field(
        default=None, validation_alias="PDOS_CAPTURE_TESSERACT_PATH"
    )
    capture_tessdata_dir: str | None = Field(
        default=None, validation_alias="PDOS_CAPTURE_TESSDATA_DIR"
    )
    capture_tessdata_sha256: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{64}$", validation_alias="PDOS_CAPTURE_TESSDATA_SHA256"
    )
    capture_whisper_dir: str | None = Field(
        default=None, validation_alias="PDOS_CAPTURE_WHISPER_DIR"
    )
    capture_whisper_sha256: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{64}$", validation_alias="PDOS_CAPTURE_WHISPER_SHA256"
    )
    knowledge_reuse_enabled: bool = Field(
        default=False, validation_alias="PDOS_KNOWLEDGE_REUSE_ENABLED"
    )
    knowledge_candidates_enabled: bool = Field(
        default=False, validation_alias="PDOS_KNOWLEDGE_CANDIDATES_ENABLED"
    )
    meeting_generation_enabled: bool = Field(
        default=False, validation_alias="PDOS_MEETING_GENERATION_ENABLED"
    )
    meeting_generation_scan_seconds: float = Field(
        default=60,
        ge=1,
        le=3600,
        allow_inf_nan=False,
        validation_alias="PDOS_MEETING_GENERATION_SCAN_SECONDS",
    )
    supplier_notice_matching_enabled: bool = Field(
        default=False, validation_alias="PDOS_SUPPLIER_NOTICE_MATCHING_ENABLED"
    )
    research_subscriptions_enabled: bool = Field(
        default=False, validation_alias="PDOS_RESEARCH_SUBSCRIPTIONS_ENABLED"
    )
    schedule_propagation_enabled: bool = Field(
        default=False, validation_alias="PDOS_SCHEDULE_PROPAGATION_ENABLED"
    )
    schedule_propagation_scan_seconds: float = Field(
        default=60,
        ge=1,
        le=3600,
        allow_inf_nan=False,
        validation_alias="PDOS_SCHEDULE_PROPAGATION_SCAN_SECONDS",
    )
    finding_auto_archive_enabled: bool = Field(
        default=True, validation_alias="PDOS_FINDING_AUTO_ARCHIVE_ENABLED"
    )
    reminder_scan_seconds: float = Field(
        default=60,
        ge=1,
        le=3600,
        allow_inf_nan=False,
        validation_alias="PDOS_REMINDER_SCAN_SECONDS",
    )
    reminder_daily_dm_cap: int = Field(
        default=50,
        ge=1,
        le=1000,
        validation_alias="PDOS_REMINDER_DAILY_DM_CAP",
    )
    reminder_quiet_hours: str = Field(
        default="21:00-08:00",
        pattern=r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$",
        validation_alias="PDOS_REMINDER_QUIET_HOURS",
    )
    dingtalk_client_id: str | None = Field(
        default=None,
        validation_alias="PDOS_DINGTALK_CLIENT_ID",
    )
    dingtalk_client_secret: SecretStr | None = Field(
        default=None,
        validation_alias="PDOS_DINGTALK_CLIENT_SECRET",
    )
    dingtalk_callback_token: SecretStr | None = Field(
        default=None,
        validation_alias="PDOS_DINGTALK_CALLBACK_TOKEN",
    )
    dingtalk_callback_aes_key: SecretStr | None = Field(
        default=None,
        validation_alias="PDOS_DINGTALK_CALLBACK_AES_KEY",
    )
    dingtalk_card_callback_secret: SecretStr | None = Field(
        default=None,
        validation_alias="PDOS_DINGTALK_CARD_CALLBACK_SECRET",
    )
    public_base_url: str = Field(
        default="http://localhost:3000",
        validation_alias="PDOS_PUBLIC_BASE_URL",
    )
    tencent_meeting_enabled: bool = Field(
        default=False, validation_alias="PDOS_TENCENT_MEETING_ENABLED"
    )
    tencent_meeting_tenant_id: UUID | None = Field(
        default=None, validation_alias="PDOS_TENCENT_MEETING_TENANT_ID"
    )
    tencent_meeting_app_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9._:-]{1,256}$",
        validation_alias="PDOS_TENCENT_MEETING_APP_ID",
    )
    tencent_meeting_sdk_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9._:-]{1,256}$",
        validation_alias="PDOS_TENCENT_MEETING_SDK_ID",
    )
    tencent_meeting_key_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9._:-]{1,256}$",
        validation_alias="PDOS_TENCENT_MEETING_KEY_ID",
    )
    tencent_meeting_secret: SecretStr | None = Field(
        default=None, validation_alias="PDOS_TENCENT_MEETING_SECRET"
    )

    dingtalk_conference_enabled: bool = Field(
        default=False,
        validation_alias="PDOS_DINGTALK_CONFERENCE_ENABLED",
    )

    dingtalk_delivery_enabled: bool = Field(
        default=False,
        validation_alias="PDOS_DINGTALK_DELIVERY_ENABLED",
    )

    @field_validator("research_search_endpoint", mode="before")
    @classmethod
    def validate_research_search_endpoint(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.port not in {None, 80, 443}
        ):
            raise ValueError(
                "research search endpoint must be a credential-free public HT"
                "TP(S) URL without query or fragment"
            )
        return value

    @field_validator("jwt_secret")
    @classmethod
    def require_strong_jwt_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().encode("utf-8")) < 32:
            message = "JWT_SECRET must contain at least 32 bytes"
            raise ValueError(message)
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
