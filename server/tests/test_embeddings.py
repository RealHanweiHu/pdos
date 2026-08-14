from __future__ import annotations

import json

import httpx2
import pytest

from app.ai.embeddings import (
    EmbeddingError,
    OpenAICompatibleEmbeddingGateway,
    configured_embedding_gateway,
)


def test_openai_compatible_embedding_contract_and_finite_dimensions() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url == "https://embedding.example/v1/embeddings"
        assert request.headers["authorization"] == "Bearer secret"
        assert json.loads(request.content) == {
            "model": "embedding-v1",
            "input": "connector lesson",
        }
        return httpx2.Response(200, json={"data": [{"embedding": [1, 0.5, -0.25]}]})

    client = httpx2.Client(transport=httpx2.MockTransport(handler), follow_redirects=False)
    try:
        gateway = OpenAICompatibleEmbeddingGateway(
            client,
            base_url="https://embedding.example/v1/",
            api_key="secret",
            model="embedding-v1",
            dimensions=3,
            provider="minimax-compatible",
        )
        result = gateway.embed(" connector lesson ")
    finally:
        client.close()
    assert result.provider == "minimax-compatible"
    assert result.model == "embedding-v1"
    assert result.values == (1.0, 0.5, -0.25)
    assert result.dimensions == 3


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"data": []}, "EMBEDDING_RESPONSE_INVALID"),
        ({"data": [{"embedding": [1, 2]}]}, "EMBEDDING_DIMENSION_MISMATCH"),
        ({"data": [{"embedding": [1, True, 3]}]}, "EMBEDDING_RESPONSE_INVALID"),
        ('{"data":[{"embedding":[1,1e999,3]}]}', "EMBEDDING_RESPONSE_INVALID"),
    ],
)
def test_embedding_gateway_rejects_malformed_or_dimension_drift(
    body: dict[str, object] | str,
    code: str,
) -> None:
    def response(request: httpx2.Request) -> httpx2.Response:
        if isinstance(body, str):
            return httpx2.Response(200, content=body, headers={"content-type": "application/json"})
        return httpx2.Response(200, json=body)

    client = httpx2.Client(
        transport=httpx2.MockTransport(response),
        follow_redirects=False,
    )
    try:
        gateway = OpenAICompatibleEmbeddingGateway(
            client,
            base_url="https://embedding.example/v1",
            api_key="secret",
            model="embedding-v1",
            dimensions=3,
        )
        with pytest.raises(EmbeddingError) as captured:
            gateway.embed("bounded input")
    finally:
        client.close()
    assert captured.value.code == code


@pytest.mark.parametrize(
    "base_url",
    [
        "http://embedding.example/v1",
        "ftp://embedding.example/v1",
        "https://user:secret@embedding.example/v1",
        "https://embedding.example/v1?redirect=https://evil.example",
    ],
)
def test_embedding_gateway_rejects_unsafe_base_urls(base_url: str) -> None:
    client = httpx2.Client()
    try:
        with pytest.raises(EmbeddingError) as captured:
            OpenAICompatibleEmbeddingGateway(
                client,
                base_url=base_url,
                api_key="secret",
                model="embedding-v1",
                dimensions=3,
            )
    finally:
        client.close()
    assert captured.value.code == "EMBEDDING_BASE_URL_INVALID"


def test_embedding_configuration_is_explicit_and_model_replaceable() -> None:
    with pytest.raises(EmbeddingError) as missing, configured_embedding_gateway({}):
        pass
    assert missing.value.code == "EMBEDDING_NOT_CONFIGURED"

    environment = {
        "PDOS_EMBEDDING_BASE_URL": "http://127.0.0.1:43123/v1",
        "PDOS_EMBEDDING_API_KEY": "private-key",
        "PDOS_EMBEDDING_MODEL": "replacement-model",
        "PDOS_EMBEDDING_DIMENSIONS": "768",
        "PDOS_EMBEDDING_PROVIDER": "replacement-provider",
    }
    with configured_embedding_gateway(environment) as gateway:
        assert gateway.provider == "replacement-provider"
        assert gateway.model == "replacement-model"
        assert gateway.dimensions == 768
