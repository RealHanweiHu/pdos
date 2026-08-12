from __future__ import annotations

import json

import httpx2
import pytest
from pydantic import SecretStr

from app.ai.model_catalog import AgentTier, ProtocolKind, ProviderName, ResolvedModelRoute
from app.ai.provider_adapters import (
    AnthropicNativeAdapter,
    ChatMessage,
    OpenAICompatibleAdapter,
    ProviderRequestError,
)


def route(protocol: ProtocolKind) -> ResolvedModelRoute:
    if protocol is ProtocolKind.ANTHROPIC_NATIVE:
        return ResolvedModelRoute(
            provider=ProviderName.ANTHROPIC,
            protocol=protocol,
            base_url="https://fake-anthropic.local",
            model="claude-test",
            api_key=SecretStr("anthropic-secret"),
            agent_tier=AgentTier.REASONING,
        )
    return ResolvedModelRoute(
        provider=ProviderName.MINIMAX,
        protocol=protocol,
        base_url="https://fake-openai.local/v1",
        model="minimax-test",
        api_key=SecretStr("openai-secret"),
        agent_tier=AgentTier.EXTRACTION,
    )


def test_openai_compatible_adapter_uses_plain_chat_completions_contract() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url == "https://fake-openai.local/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer openai-secret"
        body = json.loads(request.content)
        assert body == {
            "model": "minimax-test",
            "messages": [
                {"role": "system", "content": "Frozen system"},
                {"role": "user", "content": "Return JSON"},
            ],
            "temperature": 0,
        }
        return httpx2.Response(
            200,
            headers={"x-request-id": "req-openai"},
            json={
                "id": "completion-1",
                "model": "minimax-test-20260811",
                "choices": [{"message": {"content": '{"risk":"high"}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8},
            },
        )

    client = httpx2.Client(transport=httpx2.MockTransport(handler), follow_redirects=False)
    response = OpenAICompatibleAdapter(client).complete(
        route(ProtocolKind.OPENAI_COMPATIBLE),
        [
            ChatMessage(role="system", content="Frozen system"),
            ChatMessage(role="user", content="Return JSON"),
        ],
    )

    assert response.content == '{"risk":"high"}'
    assert response.input_tokens == 12
    assert response.output_tokens == 8
    assert response.request_id == "req-openai"
    assert response.model_version == "minimax-test-20260811"


def test_anthropic_adapter_uses_native_messages_contract() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url == "https://fake-anthropic.local/v1/messages"
        assert request.headers["x-api-key"] == "anthropic-secret"
        assert request.headers["anthropic-version"] == "2023-06-01"
        body = json.loads(request.content)
        assert body == {
            "model": "claude-test",
            "system": "Frozen system",
            "messages": [{"role": "user", "content": "Return JSON"}],
            "max_tokens": 4096,
            "temperature": 0,
        }
        return httpx2.Response(
            200,
            json={
                "id": "req-anthropic",
                "model": "claude-test-20260811",
                "content": [{"type": "text", "text": '{"risk":"low"}'}],
                "usage": {"input_tokens": 9, "output_tokens": 4},
            },
        )

    client = httpx2.Client(transport=httpx2.MockTransport(handler), follow_redirects=False)
    response = AnthropicNativeAdapter(client).complete(
        route(ProtocolKind.ANTHROPIC_NATIVE),
        [
            ChatMessage(role="system", content="Frozen system"),
            ChatMessage(role="user", content="Return JSON"),
        ],
    )

    assert response.content == '{"risk":"low"}'
    assert response.input_tokens == 9
    assert response.output_tokens == 4
    assert response.request_id == "req-anthropic"
    assert response.model_version == "claude-test-20260811"


@pytest.mark.parametrize("status_code", [307, 401, 429, 500])
def test_adapters_fail_closed_without_following_redirects_or_exposing_secrets(
    status_code: int,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        headers = {"location": "https://untrusted.example/steal"} if status_code == 307 else {}
        return httpx2.Response(status_code, headers=headers, text="provider failed")

    client = httpx2.Client(transport=httpx2.MockTransport(handler), follow_redirects=False)
    with pytest.raises(ProviderRequestError) as captured:
        OpenAICompatibleAdapter(client).complete(
            route(ProtocolKind.OPENAI_COMPATIBLE),
            [ChatMessage(role="user", content="Return JSON")],
        )

    assert captured.value.code == f"provider_http_{status_code}"
    assert "secret" not in str(captured.value).lower()


def test_adapter_rejects_malformed_success_payload() -> None:
    client = httpx2.Client(
        transport=httpx2.MockTransport(lambda request: httpx2.Response(200, json={"choices": []})),
        follow_redirects=False,
    )

    with pytest.raises(
        ProviderRequestError,
        match="provider returned an invalid response",
    ) as error:
        OpenAICompatibleAdapter(client).complete(
            route(ProtocolKind.OPENAI_COMPATIBLE),
            [ChatMessage(role="user", content="Return JSON")],
        )

    assert error.value.code == "provider_invalid_response"
