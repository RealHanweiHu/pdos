"""Documented MiniMax text wire with synthetic HTTP, never an external call."""

import json
from dataclasses import replace

import httpx
import pytest

from pdos_next.agent_kernel.qualification_binding import fingerprint, model_identity
from pdos_next.errors import DomainError
from pdos_next.providers.agent_client import (
    AgentProviderClient,
    parse_turn,
    request_body,
    tool_name,
)
from pdos_next.providers.agent_wire import FINISH_TOOL, MINIMAX_CODEC
from pdos_next.providers.types import ProviderError
from tests.agent_kernel.test_native_protocols import SCHEMA, TOOLS, reply, route

PRIVATE = "SYNTHETIC_PRIVATE_REASONING_NOT_A_PUBLIC_RESULT"


def minimax():
    return replace(
        route("openai-compatible"),
        base_url="https://api.minimax.cn/v1",
        model="MiniMax-M3",
        version="MiniMax-M3",
    )


def assistant(turn):
    return {
        "role": "assistant",
        "content": turn.text,
        **(
            {"tool_calls": [call.model_dump(mode="json") for call in turn.calls]}
            if turn.calls
            else {}
        ),
        "provider_continuation": turn.continuation,
    }


def output_reply(*, inline=False):
    value = reply("openai-compatible", tools=True)
    message = value["choices"][0]["message"]
    message["content"] = "<think>" + PRIVATE + "</think>" if inline else None
    if not inline:
        message["reasoning_content"] = PRIVATE
    message["tool_calls"][0]["function"] = {"name": FINISH_TOOL, "arguments": '{"ok":true}'}
    return value


def test_minimax_uses_native_function_schema_and_codec_is_in_quality_identity():
    configured = minimax()
    body = request_body(configured, "fixed", [], TOOLS, SCHEMA, True)
    assert configured.agent_response_codec == MINIMAX_CODEC
    assert "response_format" not in body and body["reasoning_split"] is True
    assert body["tools"][-1]["function"]["name"] == FINISH_TOOL
    assert body["tools"][-1]["function"]["parameters"] == SCHEMA
    assert body["max_completion_tokens"] == configured.max_output_tokens
    assert body["stream_options"] == {"include_usage": True}
    assert model_identity(configured) == fingerprint(
        {
            "protocol": configured.protocol,
            "base_url": configured.base_url,
            "model": configured.model,
            "version": configured.version,
            "agent_response_codec": MINIMAX_CODEC,
        }
    )
    assert (
        replace(configured, base_url="https://synthetic.invalid/v1").agent_response_codec
        == "native-schema/v1"
    )


def test_business_call_preserves_native_thinking_and_full_arguments_without_public_echo():
    configured = minimax()
    value = reply("openai-compatible", tools=True)
    value["choices"][0]["message"]["reasoning_content"] = PRIVATE
    turn = parse_turn(value, configured)
    assert turn.calls[0].name == "category.read" and PRIVATE not in repr(turn)
    history = [
        {"role": "user", "content": "Synthetic scope"},
        assistant(turn),
        {"role": "tool", "tool_call_id": "call-1", "content": '{"actual":"scope"}'},
    ]
    body = request_body(configured, "fixed", history, TOOLS, SCHEMA, False)
    assert body["messages"][2] == value["choices"][0]["message"]
    assert body["messages"][3] == history[2]
    assert "provider_continuation" not in str(body)


@pytest.mark.parametrize("inline", [False, True])
def test_native_output_is_structured_only_and_protocol_ack_precedes_followup(inline):
    configured = minimax()
    value = output_reply(inline=inline)
    turn = parse_turn(value, configured)
    assert turn.structured == {"ok": True} and not turn.calls and not turn.text
    assert PRIVATE not in repr(turn)
    history = [
        {"role": "user", "content": "Synthetic"},
        assistant(turn),
        {"role": "user", "content": "Synthetic follow-up"},
    ]
    body = request_body(configured, "fixed", history, TOOLS, SCHEMA, False)
    assert body["messages"][2] == value["choices"][0]["message"]
    assert body["messages"][3] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": '{"response_received": true}',
    }
    assert body["messages"][4] == history[2]
    assert body["tools"] == request_body(configured, "fixed", [], TOOLS, SCHEMA, False)["tools"]


@pytest.mark.parametrize("corruption", ["route", "text", "tool"])
def test_corrupt_continuation_stops_before_any_http_attempt(corruption):
    configured = minimax()
    value = reply("openai-compatible", tools=True)
    value["choices"][0]["message"]["reasoning_content"] = PRIVATE
    history = [assistant(parse_turn(value, configured))]
    if corruption == "route":
        history[0]["provider_continuation"]["route_digest"] = "different-route"
    elif corruption == "text":
        history[0]["content"] = "altered"
    else:
        history[0]["tool_calls"][0]["arguments"] = {"changed": True}
    calls = []
    client = AgentProviderClient(httpx.MockTransport(lambda request: calls.append(request)))
    try:
        with pytest.raises(DomainError) as failure:
            client.turn(
                configured, system="fixed", messages=history, tools=TOOLS, output_schema=SCHEMA
            )
        assert failure.value.code == "VERSION_CONFLICT" and not calls
    finally:
        client.close()


def test_final_output_cannot_mix_with_domain_commands():
    value = output_reply()
    value["choices"][0]["message"]["tool_calls"].append(
        {
            "id": "other",
            "type": "function",
            "function": {
                "name": tool_name("proposal.create"),
                "arguments": "{}",
            },
        }
    )
    with pytest.raises(ProviderError) as failure:
        parse_turn(value, minimax())
    assert failure.value.code == "PROVIDER_INVALID_RESPONSE"


class Fragments(httpx.SyncByteStream):
    def __init__(self, wire):
        self.wire = wire

    def __iter__(self):
        for start in range(0, len(self.wire), 7):
            yield self.wire[start : start + 7]


@pytest.mark.parametrize("inline", [False, True])
@pytest.mark.parametrize("truncated", [False, True])
def test_stream_keeps_thinking_private_and_completion_usage_includes_it_once(inline, truncated):
    content = "<think>" + PRIVATE + " 私有合成片段</think>" if inline else ""
    deltas = (
        [{"content": content[:4]}, {"content": content[4:]}]
        if inline
        else [
            {"reasoning_content": PRIVATE[:6]},
            {"reasoning_content": PRIVATE[6:]},
        ]
    )
    deltas += [
        {
            "tool_calls": [
                {
                    "index": 0,
                    "id": "native-1",
                    "type": "function",
                    "function": {"name": FINISH_TOOL, "arguments": '{"ok":'},
                }
            ]
        },
        {"tool_calls": [{"index": 0, "function": {"arguments": "true}"}}]},
    ]
    packets = [
        {"id": "synthetic-stream", "choices": [{"index": 0, "delta": delta}]} for delta in deltas
    ]
    packets.append(
        {
            "choices": [
                {"index": 0, "delta": {}, "finish_reason": "length" if truncated else "tool_calls"}
            ]
        }
    )
    packets.append(
        {
            "choices": [],
            "usage": {
                "prompt_tokens": 30,
                "completion_tokens": 20,
                "completion_tokens_details": {"reasoning_tokens": 12},
            },
        }
    )
    wire = (
        "".join(
            "data: " + json.dumps(packet, ensure_ascii=False) + "\r\n\r\n" for packet in packets
        )
        + "data: [DONE]\r\n\r\n"
    ).encode()
    requests, events = [], []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=Fragments(wire)
        )

    client = AgentProviderClient(httpx.MockTransport(handle))
    try:
        if truncated:
            with pytest.raises(ProviderError) as failure:
                client.turn(
                    minimax(),
                    system="fixed",
                    messages=[],
                    tools=TOOLS,
                    output_schema=SCHEMA,
                    emit=events.append,
                )
            assert failure.value.code == "PROVIDER_OUTPUT_TRUNCATED"
            assert failure.value.usage.output_tokens == 20
        else:
            turn = client.turn(
                minimax(),
                system="fixed",
                messages=[],
                tools=TOOLS,
                output_schema=SCHEMA,
                emit=events.append,
            )
            assert turn.structured == {"ok": True} and turn.usage.output_tokens == 20
            assert PRIVATE in str(turn.continuation)
        assert len(requests) == 1 and PRIVATE not in str(events) and not events
    finally:
        client.close()


def test_unclosed_thinking_is_not_misread_as_a_final_result():
    value = output_reply(inline=True)
    value["choices"][0]["message"]["content"] = "<think>" + PRIVATE
    with pytest.raises(ProviderError):
        parse_turn(value, minimax())


def terminal_usage_packets():
    return [
        {
            "id": "synthetic-terminal",
            "choices": [{"index": 0, "delta": {"tool_calls": [{
                "index": 0, "id": "native-1", "type": "function",
                "function": {"name": FINISH_TOOL, "arguments": '{"ok":true}'},
            }]}}],
        },
        {
            "id": "synthetic-terminal",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
        },
        {
            "id": "synthetic-terminal", "choices": [],
            "usage": {"prompt_tokens": 30, "completion_tokens": 20},
            "base_resp": {"status_code": 0, "status_msg": ""},
        },
    ]


def terminal_client(packets, tail=b""):
    wire = "".join("data: " + json.dumps(p) + "\n\n" for p in packets).encode() + tail
    return AgentProviderClient(httpx.MockTransport(lambda _: httpx.Response(
        200, headers={"content-type": "text/event-stream"}, stream=Fragments(wire),
    )))


@pytest.mark.parametrize("done", [False, True])
def test_minimax_identified_terminal_usage_completes_at_clean_eof(done):
    client = terminal_client(terminal_usage_packets(), b"data: [DONE]\n\n" if done else b"")
    try:
        turn = client.turn(minimax(), system="fixed", messages=[], tools=TOOLS,
                           output_schema=SCHEMA, emit=lambda _: None)
        assert turn.structured == {"ok": True}
        assert turn.request_id == "synthetic-terminal"
        assert turn.usage.input_tokens == 30 and turn.usage.output_tokens == 20
    finally:
        client.close()


@pytest.mark.parametrize("corruption", [
    "missing_finish", "missing_usage", "missing_status", "error_status", "invalid_status",
    "different_id", "missing_id", "extra_data", "partial_packet", "other_provider",
])
def test_terminal_usage_never_accepts_incomplete_or_unbound_stream(corruption):
    packets = terminal_usage_packets()
    tail = b""
    configured = minimax()
    if corruption == "missing_finish":
        packets.pop(1)
    elif corruption == "missing_usage":
        packets[-1].pop("usage")
    elif corruption == "missing_status":
        packets[-1].pop("base_resp")
    elif corruption == "error_status":
        packets[-1]["base_resp"]["status_code"] = 1000
    elif corruption == "invalid_status":
        packets[-1]["base_resp"] = None
    elif corruption == "different_id":
        packets[-1]["id"] = "another-response"
    elif corruption == "missing_id":
        packets[-1].pop("id")
    elif corruption == "extra_data":
        packets.append(packets[0])
    elif corruption == "partial_packet":
        tail = b'data: {"unfinished":'
    else:
        configured = route("openai-compatible")
    client = terminal_client(packets, tail)
    try:
        with pytest.raises(ProviderError) as failure:
            client.turn(configured, system="fixed", messages=[], tools=TOOLS,
                        output_schema=SCHEMA, emit=lambda _: None)
        assert failure.value.unknown
    finally:
        client.close()
