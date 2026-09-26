from __future__ import annotations

import json

import httpx2
import pytest

from app.ai.model_catalog import ProtocolKind
from app.ai.provider_adapters import (
    AnthropicNativeAdapter,
    ChatMessage,
    OpenAICompatibleAdapter,
    ProviderCallLimits,
    ProviderRequestError,
)
from tests.test_model_provider_adapters import policy, route


def payload(protocol: ProtocolKind) -> dict[str, object]:
    if protocol is ProtocolKind.OPENAI_COMPATIBLE:
        return {
            "id": "synthetic-receipt",
            "choices": [{"message": {"content": '{"risk":"low"}'}}],
            "usage": {
                "prompt_tokens": 17,
                "completion_tokens": 4,
                "prompt_tokens_details": {"cached_tokens": 5},
            },
        }
    return {
        "id": "synthetic-receipt",
        "content": [{"type": "text", "text": '{"risk":"low"}'}],
        "usage": {
            "input_tokens": 9,
            "output_tokens": 4,
            "cache_read_input_tokens": 5,
            "cache_creation_input_tokens": 3,
        },
    }


def adapter_type(
    protocol: ProtocolKind,
) -> type[OpenAICompatibleAdapter] | type[AnthropicNativeAdapter]:
    return (
        OpenAICompatibleAdapter
        if protocol is ProtocolKind.OPENAI_COMPATIBLE
        else AnthropicNativeAdapter
    )


@pytest.mark.parametrize("protocol", list(ProtocolKind))
@pytest.mark.parametrize("bad_content", ["missing", "empty", "truncated"])
def test_rejected_content_retains_verified_usage(protocol: ProtocolKind, bad_content: str) -> None:
    body = payload(protocol)
    key = "choices" if protocol is ProtocolKind.OPENAI_COMPATIBLE else "content"
    if bad_content == "missing":
        del body[key]
    elif bad_content == "empty":
        body[key] = []
    elif protocol is ProtocolKind.OPENAI_COMPATIBLE:
        body["choices"] = [{"message": {"content": '{"risk":"low"}'}, "finish_reason": "length"}]
    else:
        body["stop_reason"] = "max_tokens"
    resolved = route(protocol)
    with (
        httpx2.Client(
            transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=body))
        ) as client,
        pytest.raises(ProviderRequestError) as error,
    ):
        adapter_type(protocol)(client, policy(resolved)).complete(
            resolved, [ChatMessage(role="user", content="Return JSON")]
        )
    assert error.value.code == (
        "provider_output_truncated" if bad_content == "truncated" else "provider_invalid_response"
    )
    assert error.value.request_id == "synthetic-receipt"
    usage = error.value.usage
    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens, usage.cache_read_tokens) == (17, 4, 5)
    assert usage.cache_creation_tokens == (3 if protocol is ProtocolKind.ANTHROPIC_NATIVE else 0)


@pytest.mark.parametrize("protocol", list(ProtocolKind))
@pytest.mark.parametrize(
    "bad_usage",
    [
        None,
        {},
        {"input_tokens": True},
        {"prompt_tokens": 2, "completion_tokens": 1, "prompt_tokens_details": {"cached_tokens": 3}},
    ],
)
def test_invalid_usage_does_not_become_zero_evidence(
    protocol: ProtocolKind, bad_usage: object
) -> None:
    body = payload(protocol)
    body["usage"] = bad_usage
    resolved = route(protocol)
    with (
        httpx2.Client(
            transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=body))
        ) as client,
        pytest.raises(ProviderRequestError) as error,
    ):
        adapter_type(protocol)(client, policy(resolved)).complete(
            resolved, [ChatMessage(role="user", content="Return JSON")]
        )
    assert error.value.code == "provider_invalid_response"
    assert error.value.usage is None


@pytest.mark.parametrize(
    ("protocol", "parameter"),
    [
        (ProtocolKind.OPENAI_COMPATIBLE, "max_tokens"),
        (ProtocolKind.OPENAI_COMPATIBLE, "max_completion_tokens"),
        (ProtocolKind.ANTHROPIC_NATIVE, None),
    ],
)
def test_bounded_wire_call_sends_exactly_one_explicit_output_limit(
    protocol: ProtocolKind, parameter: str | None
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        expected = parameter or "max_tokens"
        assert body[expected] == 73
        assert (set(body) & {"max_tokens", "max_completion_tokens"}) == {expected}
        return httpx2.Response(200, json=payload(protocol))

    resolved = route(protocol)
    limits = ProviderCallLimits(73, parameter)  # type: ignore[arg-type]
    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        result = adapter_type(protocol)(client, policy(resolved)).complete_bounded(
            resolved, [ChatMessage(role="user", content="Return JSON")], limits=limits
        )
    assert result.input_tokens == 17


@pytest.mark.parametrize(
    ("protocol", "limits"),
    [
        (ProtocolKind.OPENAI_COMPATIBLE, ProviderCallLimits(73)),
        (ProtocolKind.ANTHROPIC_NATIVE, ProviderCallLimits(73, "max_completion_tokens")),
    ],
)
def test_unconfigured_bounded_wire_call_never_reaches_transport(
    protocol: ProtocolKind, limits: ProviderCallLimits
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        pytest.fail("unconfigured output limit reached transport")

    resolved = route(protocol)
    with (
        httpx2.Client(transport=httpx2.MockTransport(handler)) as client,
        pytest.raises(ProviderRequestError) as error,
    ):
        adapter_type(protocol)(client, policy(resolved)).complete_bounded(
            resolved, [ChatMessage(role="user", content="Return JSON")], limits=limits
        )
    assert error.value.code == "provider_output_limit_unconfigured"
    assert error.value.usage is None


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_output_limit_requires_positive_integer(value: int) -> None:
    with pytest.raises(ValueError, match="positive output token limit"):
        ProviderCallLimits(value)
