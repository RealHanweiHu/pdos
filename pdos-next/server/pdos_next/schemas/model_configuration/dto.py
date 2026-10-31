"""Closed HTTP DTOs. No identity, secret reference, policy facts or permits in input."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from pdos_next.providers.types import OpenAIResponseMode, ProviderRoute


class ClosedDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)


class ModelMetadata(ClosedDTO):
    protocol: Literal["openai-compatible", "anthropic-native"]
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=200)
    model_version: str = Field(min_length=1, max_length=200)
    max_output_tokens: int = Field(default=2048, ge=1, le=32768)
    context_window_tokens: int | None = Field(default=None, strict=True, ge=1024, le=10_000_000)
    openai_output_parameter: Literal["max_tokens", "max_completion_tokens"] = (
        "max_completion_tokens"
    )
    openai_response_mode: OpenAIResponseMode = "auto"
    streaming: bool = True
    connection_id: UUID | None = Field(default=None, strict=False)
    timeout_seconds: float = Field(default=30.0, ge=1, le=90, allow_inf_nan=False)
    response_bytes: int = Field(default=1_048_576, ge=1024, le=2_097_152)

    @field_validator("model", "model_version")
    @classmethod
    def public_identifier(cls, value):
        # Bounded metadata, never free text or credential storage.
        import re

        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_.@/-]{0,199}", value):
            raise ValueError("A public model identifier is required")
        return value

    @model_validator(mode="after")
    def route_boundary(self):
        # Validation only. This marker is never returned as a runtime route/credential.
        self.route(SecretStr("validation-only"), "metadata-validation")
        return self

    def route(self, credential: SecretStr, provider_version: str) -> ProviderRoute:
        return ProviderRoute(
            protocol=self.protocol,
            base_url=self.base_url,
            model=self.model,
            api_key=credential,
            version=provider_version,
            max_output_tokens=self.max_output_tokens,
            context_window_tokens=self.context_window_tokens,
            openai_output_parameter=self.openai_output_parameter,
            openai_response_mode=self.openai_response_mode,
            streaming=self.streaming,
            connection_id=self.connection_id,
            timeout_seconds=self.timeout_seconds,
            response_bytes=self.response_bytes,
        )

    def binding_metadata(self):
        """New default options must not invalidate previously saved configurations."""
        value = self.model_dump(mode="json")
        if self.context_window_tokens is None:
            value.pop("context_window_tokens")
        if self.openai_response_mode == "auto":
            value.pop("openai_response_mode")
        if self.streaming:
            value.pop("streaming")
        if self.connection_id is None:
            value.pop("connection_id")
        return value


class SaveConfiguration(ClosedDTO):
    expected_revision: int = Field(ge=0)
    metadata: ModelMetadata
    enabled: bool = False


class ConfigurationReading(ClosedDTO):
    revision: int
    version_id: UUID
    provider_version: str
    metadata: ModelMetadata
    enabled: bool
    credential_status: Literal["bound", "missing", "changed", "unavailable"]
    credential_display: Literal["已绑定 ••••", "未绑定", "需重新绑定", "暂不可核对"]
    created_at: datetime
    requires_requalification: Literal[True] = True


class SavePreview(ClosedDTO):
    expected_revision: int
    next_revision: int
    metadata: ModelMetadata
    enabled: bool
    credential_status: Literal["bound", "missing", "changed", "unavailable"]
    digest: str
    expires_at: datetime
    requires_requalification: Literal[True] = True
