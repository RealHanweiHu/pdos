import json

import httpx
import pytest
from pydantic import SecretStr

from pdos_next.providers.agent_client import (
    AgentProviderClient,
    parse_turn,
    request_body,
    tool_name,
)
from pdos_next.providers.types import ProviderError, ProviderRoute

SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}
TOOLS = [
    {"name": "category.read", "description": "Read actual scope", "parameters": {"type": "object"}}
]


@pytest.mark.parametrize("protocol", ["openai-compatible", "anthropic-native"])
def test_refusal_truncation_and_http_errors_keep_sanitized_request_id(protocol):
    body = reply(protocol)
    if protocol == "openai-compatible":
        body["choices"][0]["finish_reason"] = "length"
    else:
        body["stop_reason"] = "max_tokens"
    with pytest.raises(ProviderError) as error:
        parse_turn(body, route(protocol), "request_synthetic_1")
    assert error.value.request_id == "request_synthetic_1"
    client = AgentProviderClient(
        httpx.MockTransport(
            lambda _: httpx.Response(503, headers={"request-id": "request_synthetic_2"})
        )
    )
    with pytest.raises(ProviderError) as error:
        client.turn(route(protocol), system="fixed", messages=[], tools=TOOLS, output_schema=SCHEMA)
    assert error.value.request_id == "request_synthetic_2" and error.value.unknown
    client.close()


def route(protocol):
    return ProviderRoute(
        protocol,
        "https://synthetic-provider.test/v1",
        "synthetic-model",
        SecretStr("synthetic-fixture-only"),
        "synthetic@1",
    )


def reply(protocol, *, tools=False):
    if protocol == "openai-compatible":
        message = {"role": "assistant", "content": None if tools else '{"ok":true}'}
        if tools:
            message["tool_calls"] = [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": tool_name("category.read"), "arguments": "{}"},
                }
            ]
        return {
            "id": "req_1",
            "usage": {
                "prompt_tokens": 30,
                "completion_tokens": 5,
                "prompt_tokens_details": {"cached_tokens": 10},
            },
            "choices": [{"finish_reason": "tool_calls" if tools else "stop", "message": message}],
        }
    return {
        "id": "req_1",
        "role": "assistant",
        "stop_reason": "tool_use" if tools else "end_turn",
        "usage": {"input_tokens": 20, "output_tokens": 5, "cache_read_input_tokens": 10},
        "content": [
            {"type": "tool_use", "id": "call-1", "name": tool_name("category.read"), "input": {}}
        ]
        if tools
        else [{"type": "text", "text": '{"ok":true}'}],
    }


@pytest.mark.parametrize("protocol", ["openai-compatible", "anthropic-native"])
@pytest.mark.parametrize("tools", [False, True])
def test_native_tool_roundtrip_schema_and_server_secret(protocol, tools):
    seen = []

    def handle(request):
        body = json.loads(request.content)
        seen.append(body)
        assert "synthetic-fixture-only" not in request.content.decode()
        return httpx.Response(200, json=reply(protocol, tools=tools))

    client = AgentProviderClient(httpx.MockTransport(handle))
    result = client.turn(
        route(protocol),
        system="fixed",
        messages=[{"role": "user", "content": "dynamic"}],
        tools=TOOLS,
        output_schema=SCHEMA,
    )
    assert result.calls[0].name == "category.read" if tools else result.structured == {"ok": True}
    assert result.usage.input_tokens == 30 and result.usage.cache_read_tokens == 10
    if protocol == "openai-compatible":
        assert seen[0]["response_format"]["json_schema"]["schema"] == SCHEMA
    else:
        assert seen[0]["output_config"]["format"]["schema"] == SCHEMA
        assert seen[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
    client.close()


@pytest.mark.parametrize("protocol", ["openai-compatible", "anthropic-native"])
def test_tool_results_are_native_and_prefix_is_unchanged(protocol):
    r = route(protocol)
    initial = request_body(r, "fixed", [{"role": "user", "content": "a"}], TOOLS, SCHEMA, False)
    history = [
        {"role": "user", "content": "a"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c1", "name": "category.read", "arguments": {}}],
        },
        {"role": "tool", "tool_call_id": "c1", "content": '{"id":"actual"}'},
    ]
    second = request_body(r, "fixed", history, TOOLS, SCHEMA, False)
    assert initial["tools"] == second["tools"]
    if protocol == "openai-compatible":
        assert initial["messages"][0] == second["messages"][0]
        assert second["messages"][-1]["role"] == "tool"
    else:
        assert initial["system"] == second["system"]
        assert second["messages"][-1]["content"][0]["type"] == "tool_result"


@pytest.mark.parametrize("protocol", ["openai-compatible", "anthropic-native"])
@pytest.mark.parametrize("finish", [False, True])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_sse_requires_terminal_usage_and_preserves_native_result(protocol, finish, newline):
    events = []
    if protocol == "openai-compatible":
        packets = [
            json.dumps(
                {
                    "id": "req_1",
                    "choices": [
                        {"index": 0, "delta": {"content": '{"ok":true}'}, "finish_reason": "stop"}
                    ],
                }
            ),
            json.dumps({"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 3}}),
        ]
        if finish:
            packets.append("[DONE]")
    else:
        packets = [
            json.dumps(v)
            for v in [
                {
                    "type": "message_start",
                    "message": {
                        "id": "req_1",
                        "role": "assistant",
                        "usage": {"input_tokens": 3, "output_tokens": 0},
                    },
                },
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": '{"ok":true}'},
                },
                {"type": "content_block_stop", "index": 0},
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn"},
                    "usage": {"output_tokens": 3},
                },
            ]
        ]
        if finish:
            packets.append(json.dumps({"type": "message_stop"}))
    body = (newline * 2).join("data: " + p for p in packets) + newline * 2
    client = AgentProviderClient(httpx.MockTransport(lambda _: httpx.Response(200, text=body)))
    if finish:
        result = client.turn(
            route(protocol),
            system="fixed",
            messages=[],
            tools=TOOLS,
            output_schema=SCHEMA,
            emit=events.append,
        )
        assert result.structured == {"ok": True} and result.usage.output_tokens == 3
        assert events[0]["type"] == "text_delta"
    else:
        with pytest.raises(ProviderError, match="PROVIDER_RESULT_UNKNOWN"):
            client.turn(
                route(protocol),
                system="fixed",
                messages=[],
                tools=TOOLS,
                output_schema=SCHEMA,
                emit=events.append,
            )
    client.close()


@pytest.mark.parametrize(
    "status,code,unknown",
    [
        (429, "PROVIDER_RATE_LIMITED", False),
        (503, "PROVIDER_SERVER_ERROR", True),
        (302, "PROVIDER_REDIRECT_DENIED", False),
    ],
)
def test_transport_never_repeats_unknown_or_redirect(status, code, unknown):
    calls = []
    client = AgentProviderClient(
        httpx.MockTransport(lambda r: (calls.append(r), httpx.Response(status))[1])
    )
    with pytest.raises(ProviderError) as e:
        client.turn(
            route("openai-compatible"), system="fixed", messages=[], tools=[], output_schema=SCHEMA
        )
    assert e.value.code == code and e.value.unknown == unknown and len(calls) == 1
    client.close()


def test_native_wire_schema_has_finite_strict_objects_and_decodes_domain_json():
    from pdos_next.agent_kernel.types import WireAgentOutput
    from pdos_next.providers.agent_client import parse_turn

    schema = WireAgentOutput.model_json_schema()

    def inspect(value):
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert value.get("additionalProperties") is False
                assert set(value.get("required", [])) == set(value.get("properties", {}))
            for child in value.values():
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)

    inspect(schema)
    wire = WireAgentOutput(
        status="completed",
        summary="synthetic",
        result_json='{"candidate":"review"}',
        questions=[],
        unfinished=[],
    ).model_dump_json()
    payload = reply("openai-compatible")
    payload["choices"][0]["message"]["content"] = wire
    parsed = parse_turn(payload, route("openai-compatible"), None)
    assert parsed.structured["result"] == {"candidate": "review"}


@pytest.mark.parametrize("name", ["category.read", "mcp.private_dot_name", "mcp._0__1.lookup"])
def test_native_name_encoding_is_bijective_for_underscores_and_dots(name):
    from pdos_next.providers.agent_client import business_name

    assert business_name(tool_name(name)) == name
