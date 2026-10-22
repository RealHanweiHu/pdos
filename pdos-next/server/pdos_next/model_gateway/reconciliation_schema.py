"""Typed, bounded T1 accounting input; no identity, source text or credentials."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pdos_next.providers.types import ProviderUsage


class NormalizedUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    input_tokens: int = Field(ge=0, le=2_147_483_647, strict=True)
    output_tokens: int = Field(ge=0, le=2_147_483_647, strict=True)
    cache_read_tokens: int = Field(default=0, ge=0, strict=True)
    cache_creation_tokens: int = Field(default=0, ge=0, strict=True)

    @model_validator(mode="after")
    def bounded_totals(self):
        if self.input_tokens + self.output_tokens > 2_147_483_647:
            raise ValueError("Normalized usage exceeds the accounting bound")
        if self.cache_read_tokens + self.cache_creation_tokens > self.input_tokens:
            raise ValueError("Cache tokens must be part of total input tokens")
        return self

    def provider_usage(self):
        return ProviderUsage(**self.model_dump())


class ReconciliationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    call_id: UUID
    expected_revision: int = Field(ge=1, strict=True)
    resolution: Literal["known", "unknown"]
    usage: NormalizedUsage | None = None
    request_id: str | None = Field(
        default=None, min_length=1, max_length=200, pattern=r"^[A-Za-z0-9:_.-]+$"
    )
    reason_code: Literal["provider_usage_verified", "provider_usage_unavailable"]
    evidence_ref: str = Field(
        min_length=3, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9:_.-]+$"
    )
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)

    @model_validator(mode="after")
    def exact_resolution(self):
        if self.resolution == "known":
            if self.usage is None or self.reason_code != "provider_usage_verified":
                raise ValueError("Known fees require verified normalized usage")
        elif self.usage is not None or self.reason_code != "provider_usage_unavailable":
            raise ValueError("Unknown fees retain the original reservation")
        return self
