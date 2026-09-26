from __future__ import annotations

import json
from dataclasses import replace

import httpx2
import pytest
from pydantic import SecretStr

from app.ai.egress import ProviderEgressPolicy
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


def policy(resolved_route: ResolvedModelRoute) -> ProviderEgressPolicy:
    return ProviderEgressPolicy.from_routes([resolved_route])


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
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 8,
                    "prompt_tokens_details": {"cached_tokens": 7},
                },
            },
        )

    client = httpx2.Client(transport=httpx2.MockTransport(handler), follow_redirects=False)
    resolved_route = route(ProtocolKind.OPENAI_COMPATIBLE)
    response = OpenAICompatibleAdapter(client, policy(resolved_route)).complete(
        resolved_route,
        [
            ChatMessage(role="system", content="Frozen system"),
            ChatMessage(role="user", content="Return JSON"),
        ],
    )

    assert response.content == '{"risk":"high"}'
    assert response.input_tokens == 12
    assert response.output_tokens == 8
    assert response.cache_read_tokens == 7
    assert response.cache_creation_tokens == 0
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
                "usage": {
                    "input_tokens": 9,
                    "output_tokens": 4,
                    "cache_read_input_tokens": 5,
                    "cache_creation_input_tokens": 3,
                },
            },
        )

    client = httpx2.Client(transport=httpx2.MockTransport(handler), follow_redirects=False)
    resolved_route = route(ProtocolKind.ANTHROPIC_NATIVE)
    response = AnthropicNativeAdapter(client, policy(resolved_route)).complete(
        resolved_route,
        [
            ChatMessage(role="system", content="Frozen system"),
            ChatMessage(role="user", content="Return JSON"),
        ],
    )

    assert response.content == '{"risk":"low"}'
    assert response.input_tokens == 17
    assert response.output_tokens == 4
    assert response.cache_read_tokens == 5
    assert response.cache_creation_tokens == 3
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
        resolved_route = route(ProtocolKind.OPENAI_COMPATIBLE)
        OpenAICompatibleAdapter(client, policy(resolved_route)).complete(
            resolved_route,
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
        resolved_route = route(ProtocolKind.OPENAI_COMPATIBLE)
        OpenAICompatibleAdapter(client, policy(resolved_route)).complete(
            resolved_route,
            [ChatMessage(role="user", content="Return JSON")],
        )

    assert error.value.code == "provider_invalid_response"


def test_adapter_denies_an_injected_route_before_the_http_transport() -> None:
    transport_calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal transport_calls
        transport_calls += 1
        return httpx2.Response(200, json={})

    allowed_route = route(ProtocolKind.OPENAI_COMPATIBLE)
    injected_route = replace(allowed_route, base_url="https://untrusted.example/v1")
    client = httpx2.Client(transport=httpx2.MockTransport(handler), follow_redirects=False)

    with pytest.raises(ProviderRequestError) as error:
        OpenAICompatibleAdapter(client, policy(allowed_route)).complete(
            injected_route,
            [ChatMessage(role="user", content="Return JSON")],
        )

    assert error.value.code == "provider_egress_denied"
    assert transport_calls == 0


@pytest.mark.parametrize("protocol", list(ProtocolKind))
@pytest.mark.parametrize("seconds", [30.0, 90.0])
def test_provider_transport_honors_bounded_server_wait_policy(
    protocol: ProtocolKind, seconds: float
) -> None:
    calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        assert request.extensions["timeout"] == dict.fromkeys(
            ("connect", "read", "write", "pool"), seconds
        )
        return httpx2.Response(529, text="provider overloaded")

    resolved = route(protocol)
    adapter_type = (
        AnthropicNativeAdapter
        if protocol is ProtocolKind.ANTHROPIC_NATIVE
        else OpenAICompatibleAdapter
    )
    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        with pytest.raises(ProviderRequestError) as error:
            adapter_type(client, policy(resolved), request_timeout_seconds=seconds).complete(
                resolved, [ChatMessage(role="user", content="synthetic test")]
            )
        assert error.value.code == "provider_http_529"
        assert calls == 1
        for invalid in (0, 91, float("nan")):
            with pytest.raises(ValueError, match="between 1 and 90"):
                adapter_type(client, policy(resolved), request_timeout_seconds=invalid)


@pytest.mark.parametrize(
    ("route_name", "seconds", "attempts"),
    [("suggest_test_plan_changes", 90.0, 1), ("chat", 30.0, 2), (None, 30.0, 2)],
)
def test_long_wait_is_bound_to_server_test_plan_route(
    monkeypatch: pytest.MonkeyPatch, route_name: str | None, seconds: float, attempts: int
) -> None:
    from collections.abc import Iterator
    from contextlib import contextmanager
    from types import SimpleNamespace

    from sqlalchemy import create_engine
    from starlette.requests import Request

    from app.api import ai

    marker = object()

    @contextmanager
    def gateway(engine: object, **kwargs: object) -> Iterator[object]:
        assert kwargs == {
            "request_timeout_seconds": seconds,
            "max_structured_attempts": attempts,
        }
        yield marker

    monkeypatch.setattr(ai, "configured_application_gateway", gateway)
    request = Request({"type": "http", "route": SimpleNamespace(name=route_name)})
    engine = create_engine("sqlite://")
    assert list(ai.get_application_gateway(request, engine)) == [marker]
    engine.dispose()
