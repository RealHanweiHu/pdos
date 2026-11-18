"""Documented MiniMax text wire with synthetic HTTP, never an external call."""

import json
from dataclasses import replace

import httpx
import pytest
from pydantic import ValidationError

from pdos_next.agent.kernel.qualification_binding import fingerprint, model_identity
from pdos_next.domain.categories.preproject.schemas import ProposalCreate
from pdos_next.errors import DomainError
from pdos_next.providers.agent_client import (
    AgentProviderClient,
    parse_turn,
    request_body,
    tool_name,
)
from pdos_next.providers.agent_wire import (
    FINISH_TOOL,
    MINIMAX_CODEC,
    inline_refs,
    restore_assistant,
    wire_schemas,
)
from pdos_next.providers.types import ProviderError
from tests.agent.kernel.test_native_protocols import SCHEMA, TOOLS, reply, route

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


def proposal_reply(groups):
    value = reply("openai-compatible", tools=True)
    message = value["choices"][0]["message"]
    message["tool_calls"][0]["function"] = {
        "name": tool_name("proposal.create"),
        "arguments": json.dumps({
            "title": "合成提案", "entry_kind": "new_product", "groups": groups,
        }, ensure_ascii=False),
    }
    return value, message


@pytest.mark.parametrize("layout", ["single", "many", "json", "native"])
def test_minimax_proposal_arrays_reach_domain_validation_and_replay_original_wire(layout):
    section = {
        "kind": "section",
        "content": {"key": "worth_it", "text": "合成应急补气"},
        "source_refs": "",
    }
    option = {"kind": "option", "content": {"name": "暂缓", "kind": "do_nothing"}}
    if layout == "single":
        groups = {"items": {"item": section}, "questions": ""}
    elif layout == "many":
        groups = {"items": {"item": [section, option]}}
    elif layout == "json":
        groups = json.dumps({"items": json.dumps([section]), "questions": "[]"})
    else:
        groups = {"items": [{**section, "source_refs": []}]}
    value, message = proposal_reply(groups)
    configured = minimax()
    turn = parse_turn(value, configured)
    parsed = ProposalCreate.model_validate(turn.calls[0].arguments)
    assert [item.kind for item in parsed.groups.items] == (
        ["section", "option"] if layout == "many" else ["section"]
    )
    assert parsed.groups.items[0].content == section["content"]
    assert not parsed.groups.items[0].source_refs

    history = [assistant(turn)]
    call = history[0]["tool_calls"][0]
    arguments = call["arguments"]
    native_arguments = json.loads(message["tool_calls"][0]["function"]["arguments"])
    for stored_arguments in (arguments, native_arguments):
        call["arguments"] = stored_arguments
        body = request_body(configured, "fixed", history, TOOLS, SCHEMA, False)
        assert body["messages"][1] == message
    call["arguments"] = {**arguments, "title": "changed"}
    with pytest.raises(DomainError, match="原模型协议续接"):
        request_body(configured, "fixed", history, TOOLS, SCHEMA, False)


@pytest.mark.parametrize(("groups", "path"), [
    ("", ("groups",)),
    (
        {"items": {"kind": "section", "content": {"key": "worth_it", "text": "合成"}}},
        ("groups", "items"),
    ),
    ({"items": {"item": [], "unknown": 1}}, ("groups", "items")),
    ({"items": {"item": {"kind": "section", "content": {"key": "unknown", "text": "合成"}}}},
     ("groups", "items", 0)),
    ({"items": {"item": {"kind": "question", "content": {"question": "缺负责人和期限"}}}},
     ("groups", "items", 0, "owner_id")),
])
def test_minimax_proposal_still_rejects_invalid_arguments(groups, path):
    value, _ = proposal_reply(groups)
    turn = parse_turn(value, minimax())
    with pytest.raises(ValidationError) as error:
        ProposalCreate.model_validate(turn.calls[0].arguments)
    assert path in [item["loc"] for item in error.value.errors()]


def test_proposal_array_envelope_is_scoped_to_minimax_m3_and_proposal_create():
    groups = {"items": {"item": []}}
    value, message = proposal_reply(groups)
    for configured in (route("openai-compatible"), replace(minimax(), model="MiniMax-M3.1-Flash")):
        assert parse_turn(value, configured).calls[0].arguments["groups"] == groups
    message["tool_calls"][0]["function"]["name"] = tool_name("proposal.item.patch")
    assert parse_turn(value, minimax()).calls[0].arguments["groups"] == groups


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


def finish_with(arguments):
    value = output_reply()
    value["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = arguments
    return value


def final(result_json):
    return json.dumps({"status": "completed", "summary": "synthetic", "result_json": result_json,
                       "questions": [], "unfinished": []})


@pytest.mark.parametrize("broken", ['{"a": 1 "b": 2}', '{"a": 1}}', '{"a": 1, "a": 2}', "[1]"])
def test_malformed_result_json_is_a_known_turn_sent_to_format_repair(broken):
    """D244: a complete reply is billable and repairable, never an unknown outcome."""
    from pydantic import ValidationError

    from pdos_next.agent.kernel.types import AgentOutput

    turn = parse_turn(finish_with(final(broken)), minimax())
    assert turn.usage.output_tokens == 5 and turn.request_id
    assert turn.structured["result"] is None and "result_json" not in turn.structured
    with pytest.raises(ValidationError):
        AgentOutput.model_validate(turn.structured)


# The shape captured on 2026-11-18 (D610): the arguments stop inside the first option.
CUT_OFF = ('{"status":"needs_input","summary":"合成：范围内没有找到。","result_json":"{}",'
           '"questions":[{"id":"q_scope","question":"是否扩大范围？","why":"当前范围没有结果。",'
           '"options":{"item":{"value":"expand_all","label":')


@pytest.mark.parametrize("broken", [CUT_OFF, "", '{"status":"completed",}', "not json"])
def test_final_arguments_that_are_not_json_are_a_known_turn_sent_to_format_repair(broken):
    """D611: a complete reply with its usage is never an unknown outcome."""
    from pdos_next.agent.kernel.types import AgentOutput

    turn = parse_turn(finish_with(broken), minimax())
    assert turn.usage.output_tokens == 5 and turn.request_id
    assert turn.structured == {} and turn.calls == ()
    with pytest.raises(ValidationError):
        AgentOutput.model_validate(turn.structured)
    # The broken text is not replayed to the provider: the stored call carries {}.
    sent = restore_assistant(minimax(), assistant(turn))
    assert sent[0]["tool_calls"][0]["function"] == {"name": FINISH_TOOL, "arguments": "{}"}
    assert sent[0]["reasoning_content"] == PRIVATE
    assert sent[1]["role"] == "tool" and sent[1]["tool_call_id"] == sent[0]["tool_calls"][0]["id"]


def test_business_arguments_that_are_not_json_are_still_an_unknown_outcome():
    value = reply("openai-compatible", tools=True)
    value["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = '{"category_id":'
    with pytest.raises(ProviderError) as failure:
        parse_turn(value, minimax())
    assert failure.value.code == "PROVIDER_INVALID_RESPONSE" and failure.value.unknown


def test_a_broken_final_call_beside_another_call_is_still_an_unknown_outcome():
    value = finish_with(CUT_OFF)
    calls = value["choices"][0]["message"]["tool_calls"]
    calls.append({**calls[0], "id": "call_other"})
    with pytest.raises(ProviderError) as failure:
        parse_turn(value, minimax())
    assert failure.value.unknown


def test_empty_result_object_stays_valid():
    turn = parse_turn(finish_with(final("{}")), minimax())
    assert turn.structured["result"] == {}


@pytest.mark.parametrize("text", ["只是一段纯文本回答", "[1, 2]", ""])
def test_plain_text_final_is_a_known_turn_with_an_empty_object(text):
    value = reply("openai-compatible")
    value["choices"][0]["message"]["content"] = text
    turn = parse_turn(value, route("openai-compatible"))
    assert turn.structured == {} and turn.usage.output_tokens == 5


OPTIONS = [{"value": "quality_issue", "label": "品质问题单"},
           {"value": "rfq_or_spec", "label": "客户 RFQ 或规格书"}]


def asking(options, depends_on):
    return json.dumps({
        "status": "needs_input", "summary": "需要先确认范围。", "result_json": "{}",
        "unfinished": [], "questions": [{
            "id": "q_scope", "question": "那次工作属于哪种材料？", "why": "范围越具体越好找。",
            "options": options, "recommended": None, "allow_free_text": True,
            "depends_on": depends_on,
        }],
    }, ensure_ascii=False)


@pytest.mark.parametrize("options, depends_on", [
    ({"item": OPTIONS}, ""),  # 2026-11-13 capture, first two attempts.
    (json.dumps(OPTIONS, ensure_ascii=False), "[]"),  # Same run, third attempt.
    ({"items": OPTIONS}, None),
    (OPTIONS, {}),  # 2026-11-13 rerun: six attempts in one run wrote the empty list as {}.
    (OPTIONS, []),
])
def test_question_lists_in_another_unambiguous_encoding_are_read_as_lists(options, depends_on):
    """D477: these encodings cost real runs their whole answer after two repairs."""
    from pdos_next.agent.kernel.types import AgentOutput

    turn = parse_turn(finish_with(asking(options, depends_on)), minimax())
    question = AgentOutput.model_validate(turn.structured).questions[0]
    assert [item.model_dump() for item in question.options] == OPTIONS
    assert question.depends_on == []


def test_empty_question_lists_are_empty_and_dependencies_keep_their_items():
    from pdos_next.agent.kernel.types import AgentOutput

    turn = parse_turn(finish_with(asking("", '["q_other"]')), minimax())
    question = AgentOutput.model_validate(turn.structured).questions[0]
    assert question.options == [] and question.depends_on == ["q_other"]
    empty = parse_turn(finish_with(asking({}, {})), minimax())
    question = AgentOutput.model_validate(empty.structured).questions[0]
    assert question.options == [] and question.depends_on == []


def test_the_two_encodings_captured_in_the_rerun_after_p122_are_read():
    """D477 余项 ②, user 2026-11-14: a nested wrapper, and a wrapper around one text."""
    from pdos_next.agent.kernel.types import AgentOutput

    turn = parse_turn(finish_with(asking({"item": {"item": OPTIONS}}, {"item": "q_other"})),
                      minimax())
    question = AgentOutput.model_validate(turn.structured).questions[0]
    assert [item.model_dump() for item in question.options] == OPTIONS
    assert question.depends_on == ["q_other"]
    as_text = parse_turn(finish_with(asking(OPTIONS, {"items": '["q_other"]'})), minimax())
    assert as_text.structured["questions"][0]["depends_on"] == ["q_other"]


@pytest.mark.parametrize("options", [
    "品质问题单、客户规格书",  # Prose is not a list.
    {"choices": OPTIONS},  # Not one of the captured wrappers.
    {"item": OPTIONS, "more": 1},
    {"item": OPTIONS[0]},  # A single object is not read as a list.
    {"item": {"item": OPTIONS[0]}},
    {"item": {}},
    {"item": ""},
    '{"value": "a", "label": "b"}',
    {"q_other": True},  # Only the empty object is read as an empty list.
    "{}",
    5,
])
def test_any_other_form_is_left_for_format_repair(options):
    from pydantic import ValidationError

    from pdos_next.agent.kernel.types import AgentOutput

    turn = parse_turn(finish_with(asking(options, [])), minimax())
    assert turn.structured["questions"][0]["options"] == options  # Returned as it came.
    with pytest.raises(ValidationError):
        AgentOutput.model_validate(turn.structured)


def test_list_items_are_not_touched_and_other_fields_are_not_read_this_way():
    from pydantic import ValidationError

    from pdos_next.agent.kernel.types import AgentOutput

    wrong_item = parse_turn(finish_with(asking({"item": ["只有文字"]}, "")), minimax())
    assert wrong_item.structured["questions"][0]["options"] == ["只有文字"]
    with pytest.raises(ValidationError):
        AgentOutput.model_validate(wrong_item.structured)
    value = json.loads(asking(OPTIONS, []))
    value["unfinished"] = ""
    untouched = parse_turn(finish_with(json.dumps(value, ensure_ascii=False)), minimax())
    assert untouched.structured["unfinished"] == ""
    with pytest.raises(ValidationError):
        AgentOutput.model_validate(untouched.structured)


REPEATED_ID = "chatcmpl-tool-afcb05bc4727a0b1"


def repeated_id_packets(arguments, *, last_id=REPEATED_ID):
    """The 11-06 capture: the full call id resent on every chunk of one call."""
    packets = []
    for position, piece in enumerate(arguments):
        packets.append({"id": "synthetic-repeat", "choices": [{"index": 0, "delta": {
            "tool_calls": [{
                "index": 0, "type": "function",
                "id": last_id if position == len(arguments) - 1 else REPEATED_ID,
                "function": {"name": tool_name("category.read") if position == 0 else "",
                             "arguments": piece},
            }]}}]})
    packets.append({"id": "synthetic-repeat",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]})
    packets.append({"id": "synthetic-repeat", "choices": [],
                    "usage": {"prompt_tokens": 30, "completion_tokens": 20},
                    "base_resp": {"status_code": 0, "status_msg": ""}})
    return packets


def test_a_repeated_call_id_counts_once_and_the_reply_stays_known():
    """D254: 15 chunks x 30 characters once built a 450-character id and an unknown."""
    arguments = '{"cursor":  0 }'
    assert len(arguments) * len(REPEATED_ID) > 200
    client = terminal_client(repeated_id_packets(arguments))
    try:
        turn = client.turn(minimax(), system="fixed", messages=[], tools=TOOLS,
                           output_schema=SCHEMA, emit=lambda _: None)
        assert [(c.id, c.name, c.arguments) for c in turn.calls] == [
            (REPEATED_ID, "category.read", {"cursor": 0})
        ]
        assert turn.usage.output_tokens == 20
    finally:
        client.close()


def test_a_different_id_inside_one_call_is_still_a_broken_stream():
    client = terminal_client(repeated_id_packets('{"cursor":0}', last_id="chatcmpl-tool-other"))
    try:
        with pytest.raises(ProviderError) as failure:
            client.turn(minimax(), system="fixed", messages=[], tools=TOOLS,
                        output_schema=SCHEMA, emit=lambda _: None)
        assert failure.value.unknown
    finally:
        client.close()


# MiniMax-M3 returns arguments cut short under an unresolved ``$ref``; see inline_refs.
OPTION = {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]}
REFERENCED = {
    "$defs": {
        "Option": OPTION,
        "Question": {
            "type": "object",
            "properties": {"options": {"type": "array", "items": {"$ref": "#/$defs/Option"}}},
        },
    },
    "type": "object",
    "properties": {"questions": {"type": "array", "items": {"$ref": "#/$defs/Question"}}},
}
REFERENCED_TOOLS = [{"name": "calc.cost", "description": "Synthetic", "parameters": REFERENCED}]


def test_minimax_request_writes_schema_references_out():
    original = json.dumps(REFERENCED_TOOLS)
    body = request_body(minimax(), "fixed", [], REFERENCED_TOOLS, REFERENCED, False)
    assert [tool["function"]["name"] for tool in body["tools"]] == [
        tool_name("calc.cost"), FINISH_TOOL]
    for tool in body["tools"]:
        parameters = tool["function"]["parameters"]
        assert "$ref" not in json.dumps(parameters) and "$defs" not in parameters
        assert parameters["properties"]["questions"]["items"]["properties"]["options"][
            "items"] == OPTION
    assert json.dumps(REFERENCED_TOOLS) == original  # the registered definitions are untouched


@pytest.mark.parametrize("protocol", ["openai-compatible", "anthropic-native"])
def test_routes_that_resolve_references_keep_the_registered_schema(protocol):
    body = request_body(route(protocol), "fixed", [], REFERENCED_TOOLS, REFERENCED, False)
    sent = body["tools"][0]
    assert (sent["function"]["parameters"] if protocol == "openai-compatible"
            else sent["input_schema"]) == REFERENCED


def test_inline_refs_keeps_sibling_keys_and_leaves_unresolvable_schemas_alone():
    described = {"$defs": {"Name": {"type": "string"}}, "type": "object", "properties": {
        "name": {"$ref": "#/$defs/Name", "description": "Synthetic"}}}
    assert inline_refs(described) == {"type": "object", "properties": {
        "name": {"type": "string", "description": "Synthetic"}}}
    recursive = {"$defs": {"Node": {"type": "object", "properties": {
        "next": {"$ref": "#/$defs/Node"}}}}, "$ref": "#/$defs/Node"}
    assert inline_refs(recursive) is recursive
    foreign = {"type": "object", "properties": {"x": {"$ref": "https://synthetic.test/x.json"}}}
    assert inline_refs(foreign) is foreign


def test_admission_measures_the_definitions_as_minimax_sends_them():
    from pdos_next.agent.kernel.context_budget import measure, segments

    sent, schema = wire_schemas(minimax(), REFERENCED_TOOLS, REFERENCED)
    assert measure(minimax(), "fixed", REFERENCED_TOOLS, [], REFERENCED)["segments"] == segments(
        "fixed", sent, [], schema)["segments"]
    assert measure(route("openai-compatible"), "fixed", REFERENCED_TOOLS, [], REFERENCED)[
        "segments"] == segments("fixed", REFERENCED_TOOLS, [], REFERENCED)["segments"]
