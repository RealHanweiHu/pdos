"""D592 and D578: which part of a request could be reused, and how long the first output took.

Synthetic storage, a scripted host and a mock transport; no database, no provider.
"""

import json
from dataclasses import replace

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from pdos_next.agent.kernel.context_layout import compare, outline
from pdos_next.agent.kernel.context_observability import RUNTIME_KEY, record_call
from pdos_next.agent.kernel.graph import AgentKernel, Budget
from pdos_next.agent.kernel.tools import default_registry
from pdos_next.agent.kernel.types import ModelTurn, ToolCall
from pdos_next.core.service import digest
from pdos_next.providers.agent_client import AgentProviderClient, request_body
from tests.agent.kernel.test_context_observability import Store, completed
from tests.agent.kernel.test_graph import Host, final, scope
from tests.agent.kernel.test_native_protocols import SCHEMA, TOOLS, reply, route

SEGMENTS = {"system": 40, "tools": 20}
ENVELOPE = {"role": "user", "content": json.dumps({"goal": "PRIVATE goal"})}
SKILL = {"role": "user", "content": "PRIVATE skill body"}
ASSISTANT = {"role": "assistant", "content": "", "tool_calls": [
    {"id": "a", "name": "category.read", "arguments": {}}]}
RESULT = {"role": "tool", "tool_call_id": "a", "content": json.dumps({"rows": ["PRIVATE row"]})}


def lay(messages, *, tools="b" * 64, system="c" * 64, loaded=0):
    return outline(prompt_digest=system, tools_digest=tools, segments=SEGMENTS,
                   messages=messages, loaded_skills=loaded)


def test_outline_labels_each_part_and_holds_no_text():
    value = lay([ENVELOPE, SKILL, ASSISTANT, RESULT])
    assert [row[0] for row in value["rows"]] == [
        "system", "tools", "envelope", "skill", "loop", "loop"]
    assert value["rows"][0][1:] == ["c" * 16, 40] and value["rows"][1][1:] == ["b" * 16, 20]
    assert value["rows"][2][1] == digest(ENVELOPE)[:16]
    assert all(type(row[2]) is int and row[2] >= 0 for row in value["rows"])
    assert "PRIVATE" not in json.dumps(value)


def test_first_call_records_its_stable_digests_and_expects_nothing():
    value = compare(None, lay([ENVELOPE, SKILL]), cache_read=184)
    assert value["basis"] == "first_call" and value["reason"] == "first_call_in_run"
    assert value["expected_reusable_tokens"] is None
    assert value["read_to_expected_ratio"] is None
    assert value["stable_prefix_tokens"] == 60
    assert (value["system_digest"], value["tools_digest"]) == ("c" * 16, "b" * 16)
    assert value["envelope_digest"] == digest(ENVELOPE)[:16]
    assert value["skills_digest"] == digest([digest(SKILL)[:16]])[:16]


def test_an_appended_request_expects_the_whole_previous_request_back():
    before = lay([ENVELOPE, SKILL])
    after = lay([ENVELOPE, SKILL, ASSISTANT, RESULT])
    expected = sum(row[2] for row in before["rows"])
    value = compare(before, after, cache_read=expected // 2)
    assert value["reason"] == "append_only" and value["shared_chunks"] == 4
    assert value["expected_reusable_tokens"] == expected
    assert value["first_changed"] is None and value["first_changed_message"] is None
    assert value["read_to_expected_ratio"] == round((expected // 2) / expected, 3)


@pytest.mark.parametrize("change,options,reason,label,message,kept", [
    (lambda: lay([ENVELOPE, SKILL, ASSISTANT, RESULT], system="d" * 64), {},
     "system_changed", "system", None, 0),
    (lambda: lay([ENVELOPE, SKILL, ASSISTANT, RESULT], tools="e" * 64, loaded=1), {},
     "tools_widened_by_skill_load", "tools", None, 1),
    (lambda: lay([ENVELOPE, SKILL, ASSISTANT, RESULT], tools="e" * 64), {},
     "tools_changed", "tools", None, 1),
    (lambda: lay([{**ENVELOPE, "content": "{}"}, SKILL, ASSISTANT, RESULT]),
     {"reductions": [{"kind": "history_directory"}]}, "envelope_reduced", "envelope", 0, 2),
    (lambda: lay([{**ENVELOPE, "content": "{}"}, SKILL, ASSISTANT, RESULT]),
     {"cleanup_applied": True, "reductions": [{"kind": "older_tool_result"}]},
     "tool_cleanup_rewrote_envelope", "envelope", 0, 2),
    (lambda: lay([{**ENVELOPE, "content": "{}"}, SKILL, ASSISTANT, RESULT]), {},
     "envelope_changed", "envelope", 0, 2),
    (lambda: lay([ENVELOPE, SKILL, ASSISTANT, {**RESULT, "content": "{}"}]),
     {"cleanup_applied": True}, "tool_cleanup", "loop", 3, 5),
    (lambda: lay([ENVELOPE, SKILL, ASSISTANT, {**RESULT, "content": "{}"}]), {},
     "messages_changed", "loop", 3, 5),
])
def test_the_first_part_that_differs_names_why_the_rest_cannot_be_reused(
        change, options, reason, label, message, kept):
    before = lay([ENVELOPE, SKILL, ASSISTANT, RESULT])
    value = compare(before, change(), **options)
    assert (value["reason"], value["first_changed"]) == (reason, label)
    assert value["first_changed_message"] == message and value["shared_chunks"] == kept
    assert value["expected_reusable_tokens"] == sum(row[2] for row in before["rows"][:kept])


def test_a_request_that_lost_its_tail_is_named_as_such():
    value = compare(lay([ENVELOPE, SKILL, ASSISTANT, RESULT]), lay([ENVELOPE, SKILL]))
    assert value["reason"] == "messages_removed" and value["first_changed"] is None


def test_each_main_call_is_compared_with_the_one_before_and_failures_do_not_advance():
    bound = scope()
    store = Store(bound)
    first = completed(store, bound)
    first.result["timing"] = {"streamed": True, "headers_ms": 120, "first_output_ms": 900,
                              "total_ms": 4000, "note": "PRIVATE"}
    one = record_call(store, bound, ModelTurn(ledger_call_id=first.id), [ENVELOPE])
    assert one["prefix"]["reason"] == "first_call_in_run"
    assert one["latency"] == {"streamed": True, "headers_ms": 120, "first_output_ms": 900,
                              "total_ms": 4000}
    second = completed(store, bound)
    two = record_call(store, bound, ModelTurn(ledger_call_id=second.id),
                      [ENVELOPE, ASSISTANT, RESULT])
    assert two["prefix"]["reason"] == "append_only" and two["prefix"]["shared_chunks"] == 3
    # 80 cached tokens were reported by the synthetic ledger row.
    assert two["prefix"]["read_to_expected_ratio"] == round(
        80 / two["prefix"]["expected_reusable_tokens"], 3)
    assert two["latency"] is None  # A row saved before D578 has no timing.
    body = store.session.events[-1].body
    assert body["prefix"] == two["prefix"] and "PRIVATE" not in json.dumps(body)
    assert "PRIVATE" not in json.dumps(store.run.versions[RUNTIME_KEY])


def test_child_graphs_record_digests_but_are_not_compared_with_each_other():
    bound = scope(isolation="research")
    store = Store(bound)
    for _ in range(2):
        row = completed(store, bound)
        value = record_call(store, bound, ModelTurn(ledger_call_id=row.id), [ENVELOPE])
        assert (value["prefix"]["basis"], value["prefix"]["reason"]) == (
            "not_compared", "child_graph")
        assert value["prefix"]["expected_reusable_tokens"] is None
    assert store.run.versions[RUNTIME_KEY]["layouts"] == {}


def read(identity):
    return ModelTurn(calls=(ToolCall(id=identity, name="category.read", arguments={}),))


def test_consecutive_requests_of_one_run_share_a_byte_identical_prefix():
    """Replay without a model: each request must begin with the whole previous one.

    Six model calls, so the round-4 progress note is in the loop as well.
    """
    host = Host([*(read(name) for name in "abcde"), final()])
    AgentKernel(host, default_registry(), budget=Budget()).execute(
        scope(), goal="Synthetic question", checkpointer=InMemorySaver(),
        execution_key="prefix-replay")
    selected = route("openai-compatible")
    bodies = [request_body(selected, system, messages, tools, SCHEMA, True)
              for (system, tools), messages in zip(
                  host.prefixes, host.captured_model_messages, strict=True)]
    assert len(bodies) == 6
    assert any('"type": "server_progress"' in message["content"]
               for message in bodies[-1]["messages"] if message["role"] == "user")
    outlines = [lay(messages) for messages in host.captured_model_messages]
    for index in range(1, len(bodies)):
        earlier, later = bodies[index - 1], bodies[index]
        assert json.dumps(later["tools"]) == json.dumps(earlier["tools"])
        sent = json.dumps(earlier["messages"], ensure_ascii=False)
        again = json.dumps(later["messages"][:len(earlier["messages"])], ensure_ascii=False)
        assert again == sent and len(later["messages"]) > len(earlier["messages"])
        value = compare(outlines[index - 1], outlines[index])
        assert value["reason"] == "append_only"
        assert value["shared_chunks"] == len(outlines[index - 1]["rows"])


def test_a_streamed_call_reports_when_the_first_output_arrived():
    selected = replace(route("openai-compatible"), openai_response_mode="tools")
    packets = [
        {"id": "req_1", "choices": [{"index": 0, "delta": {"role": "assistant"}}]},
        {"id": "req_1", "choices": [{"index": 0, "delta": {"content": '{"ok":true}'},
                                     "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 30, "completion_tokens": 5}},
    ]
    content = "".join("data: " + json.dumps(packet) + "\n\n" for packet in packets)
    client = AgentProviderClient(httpx.MockTransport(
        lambda _: httpx.Response(200, text=content + "data: [DONE]\n\n")))
    try:
        result = client.turn(selected, system="frozen", messages=[], tools=TOOLS,
                             output_schema=SCHEMA, emit=lambda _: None)
    finally:
        client.close()
    timing = result.timing
    assert timing["streamed"] is True
    assert all(type(timing[key]) is int for key in ("headers_ms", "first_output_ms", "total_ms"))
    assert 0 <= timing["headers_ms"] <= timing["first_output_ms"] <= timing["total_ms"]
    # Timing is observation only: it does not make two otherwise equal turns differ.
    assert replace(result, timing=None) == result


def test_a_call_that_was_not_streamed_has_no_first_output_time():
    client = AgentProviderClient(httpx.MockTransport(
        lambda _: httpx.Response(200, json=reply("openai-compatible"))))
    try:
        result = client.turn(route("openai-compatible"), system="frozen", messages=[],
                             tools=[], output_schema=SCHEMA)
    finally:
        client.close()
    assert result.timing["streamed"] is False and result.timing["first_output_ms"] is None
    assert type(result.timing["total_ms"]) is int
