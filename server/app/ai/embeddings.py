"""Replaceable, fail-closed embedding gateway for verified Memory."""

from __future__ import annotations

import math
import os
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

import httpx2

MAX_EMBEDDING_INPUT_CHARS = 30_000


class EmbeddingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class EmbeddingResult:
    provider: str
    model: str
    values: tuple[float, ...]

    @property
    def dimensions(self) -> int:
        return len(self.values)


class EmbeddingGateway(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    def embed(self, text: str) -> EmbeddingResult: ...


class OpenAICompatibleEmbeddingGateway:
    def __init__(
        self,
        client: httpx2.Client,
        *,
        base_url: str,
        api_key: str,
        model: str,
        dimensions: int,
        provider: str = "openai-compatible",
    ) -> None:
        self._client = client
        self._base_url = _validated_base_url(base_url)
        self._api_key = api_key
        self._model = model.strip()
        self._dimensions = dimensions
        self._provider = provider.strip()
        if not self._api_key or not self._model or not self._provider:
            raise EmbeddingError("EMBEDDING_NOT_CONFIGURED", "embedding route is incomplete")
        if not 1 <= dimensions <= 4096:
            raise EmbeddingError("EMBEDDING_DIMENSIONS_INVALID", "embedding dimensions invalid")

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, text: str) -> EmbeddingResult:
        normalized = text.strip()
        if not normalized or len(normalized) > MAX_EMBEDDING_INPUT_CHARS:
            raise EmbeddingError("EMBEDDING_INPUT_INVALID", "embedding input is invalid")
        try:
            response = self._client.post(
                f"{self._base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self._model, "input": normalized},
                timeout=30.0,
            )
        except httpx2.HTTPError as error:
            raise EmbeddingError("EMBEDDING_TRANSPORT_ERROR", "embedding request failed") from error
        if not 200 <= response.status_code < 300:
            raise EmbeddingError(
                f"EMBEDDING_HTTP_{response.status_code}",
                "embedding request failed",
            )
        try:
            body = response.json()
            if not isinstance(body, Mapping):
                raise ValueError
            data = body["data"]
            if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], Mapping):
                raise ValueError
            raw_values = data[0]["embedding"]
            if not isinstance(raw_values, Sequence) or isinstance(raw_values, (str, bytes)):
                raise ValueError
            values = tuple(_finite_number(value) for value in raw_values)
            if len(values) != self._dimensions:
                raise EmbeddingError(
                    "EMBEDDING_DIMENSION_MISMATCH",
                    "embedding response dimensions do not match configuration",
                )
        except EmbeddingError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise EmbeddingError(
                "EMBEDDING_RESPONSE_INVALID",
                "embedding response is invalid",
            ) from error
        return EmbeddingResult(provider=self._provider, model=self._model, values=values)


def _finite_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError
    number = float(value)
    if not math.isfinite(number):
        raise ValueError
    return number


def _validated_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise EmbeddingError("EMBEDDING_BASE_URL_INVALID", "embedding base URL is invalid")
    is_local = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and is_local):
        raise EmbeddingError("EMBEDDING_BASE_URL_INVALID", "embedding base URL is invalid")
    return normalized


@contextmanager
def configured_embedding_gateway(
    environment: Mapping[str, str] | None = None,
) -> Iterator[EmbeddingGateway]:
    source = os.environ if environment is None else environment
    required = {
        "base_url": source.get("PDOS_EMBEDDING_BASE_URL", ""),
        "api_key": source.get("PDOS_EMBEDDING_API_KEY", ""),
        "model": source.get("PDOS_EMBEDDING_MODEL", ""),
        "dimensions": source.get("PDOS_EMBEDDING_DIMENSIONS", ""),
    }
    if any(not value for value in required.values()):
        raise EmbeddingError("EMBEDDING_NOT_CONFIGURED", "embedding route is not configured")
    try:
        dimensions = int(required["dimensions"])
    except ValueError as error:
        raise EmbeddingError(
            "EMBEDDING_DIMENSIONS_INVALID",
            "embedding dimensions invalid",
        ) from error
    client = httpx2.Client(follow_redirects=False, trust_env=False)
    try:
        yield OpenAICompatibleEmbeddingGateway(
            client,
            base_url=required["base_url"],
            api_key=required["api_key"],
            model=required["model"],
            dimensions=dimensions,
            provider=source.get("PDOS_EMBEDDING_PROVIDER", "openai-compatible"),
        )
    finally:
        client.close()
