"""Internal immutable evidence for actual model budget admission and settlement."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai.model_catalog import ProtocolKind, ProviderName

Nonnegative = Annotated[int, Field(strict=True, ge=0)]
Positive = Annotated[int, Field(strict=True, gt=0)]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class BudgetRequestBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_call_id: UUID
    structured_attempt: Annotated[int, Field(strict=True, ge=1, le=3)]
    request_digest: Digest
    provider: ProviderName
    model: Annotated[str, Field(min_length=1)]
    protocol: ProtocolKind
    qualification_ref: Annotated[str, Field(min_length=1)]
    meter_version: Annotated[str, Field(min_length=1)]
    qualified_window: Positive
    qualified_output_limit: Positive
    output_parameter: Literal["max_tokens", "max_completion_tokens"]
    output_limit: Positive


class BudgetUsageEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_digest: Digest
    input_tokens: Nonnegative
    output_tokens: Nonnegative
    cache_read_tokens: Nonnegative = 0
    cache_creation_tokens: Nonnegative = 0
    request_id: str | None = None
    model_version: str | None = None
    error_code: str | None = None

    @property
    def evidence_ref(self) -> str:
        body = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return "provider-usage.v1:sha256:" + sha256(body.encode()).hexdigest()

    @model_validator(mode="after")
    def cache_is_a_breakdown(self) -> Self:
        if self.cache_read_tokens + self.cache_creation_tokens > self.input_tokens:
            raise ValueError("cache breakdown exceeds normalized input")
        return self
