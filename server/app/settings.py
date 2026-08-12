"""Validated runtime configuration loaded lazily from the environment."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
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
