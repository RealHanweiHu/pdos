"""Independent embedding metadata; no chat credential or model routing fallback."""

import math
import re
from dataclasses import dataclass, field
from typing import Literal, Protocol
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from pdos_next.errors import DomainError
from pdos_next.model_configuration.ports import SecretBinding, SecretMaterial
from pdos_next.schema_base import StrictModel

CATEGORIES = frozenset({"public", "synthetic", "internal", "customer", "customer_original"})
MAX_BATCH = 16
MAX_CHARACTERS = 64_000


class EmbeddingMetadata(StrictModel):
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9:_.@/-]{0,159}$")
    model_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9:_.@/-]{0,159}$")
    dimensions: int = Field(strict=True, ge=1, le=2000)
    connection_id: UUID
    data_categories: list[
        Literal[
            "public",
            "synthetic",
            "internal",
            "customer",
            "customer_original",
        ]
    ]
    include_customer_original: bool = False

    @field_validator("base_url")
    @classmethod
    def endpoint(cls, value):
        endpoint = urlsplit(value)
        if (
            endpoint.scheme not in {"http", "https"}
            or not endpoint.hostname
            or endpoint.username
            or endpoint.password
            or endpoint.query
            or endpoint.fragment
            or (
                endpoint.scheme != "https"
                and endpoint.hostname
                not in {
                    "localhost",
                    "127.0.0.1",
                    "::1",
                }
            )
        ):
            raise ValueError("An explicit HTTPS or local embedding endpoint is required")
        return value.rstrip("/")

    @model_validator(mode="after")
    def categories(self):
        if not self.data_categories or len(set(self.data_categories)) != len(self.data_categories):
            raise ValueError("Choose explicit distinct data categories")
        if ("customer_original" in self.data_categories) != self.include_customer_original:
            raise ValueError("Customer originals require their separate explicit selection")
        return self

    @property
    def provider(self):
        # Endpoint hostname only; native P26 resolves the canonical provider from
        # the trusted connection port, including registered provider aliases.
        return urlsplit(self.base_url).hostname


class SaveEmbeddingProfile(StrictModel):
    profile_id: UUID
    expected_revision: int = Field(strict=True, ge=0)
    metadata: EmbeddingMetadata
    enabled: bool = False
    expected_budget_revision: int = Field(strict=True, ge=0)
    index_budget_micro_usd: int = Field(strict=True, ge=0, le=2_147_483_647)
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)


class ReconcileEmbeddingCall(StrictModel):
    call_id: UUID
    expected_revision: int = Field(strict=True, ge=1)
    input_tokens: int = Field(strict=True, ge=0, le=2_147_483_647)
    actual_micro_usd: int = Field(strict=True, ge=0, le=2_147_483_647)
    evidence_ref: str = Field(min_length=3, max_length=500)
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)


class EmbeddingSecrets(Protocol):
    # An embedding-specific slot is mandatory. Never call SecretPort.current()
    # or choose a tenant's chat connection implicitly.
    def provider_for(self, tenant_id: UUID, metadata: EmbeddingMetadata) -> str: ...
    def current_embedding(self, tenant_id: UUID, metadata: EmbeddingMetadata) -> SecretBinding: ...
    def resolve(self, binding: SecretBinding) -> SecretMaterial | None: ...


@dataclass(frozen=True)
class EmbeddingResponse:
    vectors: tuple[tuple[float, ...], ...] = field(repr=False)
    input_tokens: int | None = None
    request_id: str | None = None


class EmbeddingClient(Protocol):
    def embed(
        self,
        metadata: EmbeddingMetadata,
        texts: tuple[str, ...],
        credential: SecretMaterial,
        *,
        timeout: float,
    ) -> EmbeddingResponse: ...


def validate_response(value, *, count, dimensions):
    if (
        not isinstance(value, EmbeddingResponse)
        or len(value.vectors) != count
        or value.input_tokens is not None
        and (type(value.input_tokens) is not int or not 0 <= value.input_tokens <= 2_147_483_647)
        or value.request_id is not None
        and (
            not isinstance(value.request_id, str)
            or re.fullmatch(r"[A-Za-z0-9:_.-]{1,200}", value.request_id) is None
        )
    ):
        raise DomainError("SOURCE_UNAVAILABLE", "Embedding 响应形状或计量无效。")
    for vector in value.vectors:
        if (
            len(vector) != dimensions
            or any(type(v) not in {float, int} or not math.isfinite(v) for v in vector)
            or not any(vector)
        ):
            raise DomainError("SOURCE_UNAVAILABLE", "Embedding 维度或有限数值无效。")
    return value


def bounded_inputs(texts):
    if (
        not 1 <= len(texts) <= MAX_BATCH
        or any(
            not isinstance(t, str) or not t.strip() or "\x00" in t or len(t) > 20_000 for t in texts
        )
        or sum(len(t) for t in texts) > MAX_CHARACTERS
    ):
        raise DomainError("VALIDATION_FAILED", "Embedding 输入超过固定批次边界。")
    return tuple(texts)
