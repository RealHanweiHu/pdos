import json

import httpx2
import pytest

from app.ai.model_catalog import ProtocolKind
from app.ai.provider_adapters import (
    AnthropicNativeAdapter,
    OpenAICompatibleAdapter,
    ProviderCallLimits,
    ProviderRequestError,
)
from app.ai.provider_streaming import observe_text, partial_answer, partial_approach
from tests.test_model_provider_adapters import policy, route


def sse(events):
    return "".join(
        "data: " + (event if isinstance(event, str) else json.dumps(event)) + "\n\n"
        for event in events
    )


@pytest.mark.parametrize(
    "protocol", [ProtocolKind.OPENAI_COMPATIBLE, ProtocolKind.ANTHROPIC_NATIVE]
)
def test_real_adapters_stream_provider_text_and_preserve_bounded_usage(protocol):
    observed = []
    parts = ['{"answer":"你好', '，我们继续聊。","citation_ids":[]}']
    if protocol is ProtocolKind.OPENAI_COMPATIBLE:
        events = [
            {
                "id": "stream-1",
                "model": "synthetic",
                "choices": [{"delta": {"content": part}, "finish_reason": None}],
            }
            for part in parts
        ]
        events += [
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 20, "completion_tokens": 10}},
            "[DONE]",
        ]
    else:
        events = [
            {
                "type": "message_start",
                "message": {
                    "id": "stream-1",
                    "model": "synthetic",
                    "usage": {"input_tokens": 20, "output_tokens": 0},
                },
            }
        ]
        events += [
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": part}}
            for part in parts
        ]
        events += [
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
                "usage": {"output_tokens": 10},
            },
            {"type": "message_stop"},
        ]

    def handler(request):
        payload = json.loads(request.content)
        assert payload["stream"] is True
        assert payload.get("max_completion_tokens", payload.get("max_tokens")) == 64
        return httpx2.Response(200, text=sse(events), headers={"content-type": "text/event-stream"})

    resolved = route(protocol)
    with (
        httpx2.Client(transport=httpx2.MockTransport(handler)) as client,
        observe_text(observed.append),
    ):
        adapter = (
            OpenAICompatibleAdapter(client, policy(resolved))
            if protocol is ProtocolKind.OPENAI_COMPATIBLE
            else AnthropicNativeAdapter(client, policy(resolved))
        )
        result = adapter.complete_bounded(
            resolved,
            [],
            limits=ProviderCallLimits(
                max_output_tokens=64,
                openai_output_parameter="max_completion_tokens"
                if protocol is ProtocolKind.OPENAI_COMPATIBLE
                else None,
            ),
        )
    assert result.content == "".join(parts)
    assert (result.input_tokens, result.output_tokens) == (20, 10)
    assert partial_answer(observed[1]) == "你好"
    assert partial_answer(observed[-1]) == "你好，我们继续聊。"


def test_incomplete_stream_keeps_known_usage_and_does_not_claim_completion():
    resolved = route(ProtocolKind.OPENAI_COMPATIBLE)
    events = [
        {
            "choices": [{"delta": {"content": '{"answer":"半条'}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 3},
        }
    ]
    with (
        httpx2.Client(
            transport=httpx2.MockTransport(lambda _: httpx2.Response(200, text=sse(events)))
        ) as client,
        observe_text(lambda _: None),
        pytest.raises(ProviderRequestError) as failure,
    ):
        OpenAICompatibleAdapter(client, policy(resolved)).complete(resolved, [])
    assert failure.value.code == "provider_invalid_response"
    assert failure.value.usage.output_tokens == 3


def test_minimax_clean_eof_after_stop_and_usage_preserves_the_complete_reply():
    resolved = route(ProtocolKind.OPENAI_COMPATIBLE)
    content = '<think>内部思考</think>\n{"answer":"你好！","citation_ids":[]}'
    events = [
        {"choices": [{"delta": {"content": content}}]},
        {"choices": [{"delta": {"role": ""}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 20, "completion_tokens": 10}},
    ]
    observed = []
    with (
        httpx2.Client(
            transport=httpx2.MockTransport(lambda _: httpx2.Response(200, text=sse(events)))
        ) as client,
        observe_text(observed.append),
    ):
        result = OpenAICompatibleAdapter(client, policy(resolved)).complete(resolved, [])
    assert result.content == content
    assert (result.input_tokens, result.output_tokens) == (20, 10)
    assert partial_answer(observed[-1]) == "你好！"


@pytest.mark.parametrize("missing", ["finish", "usage", "content"])
def test_clean_eof_cannot_replace_missing_completion_evidence(missing):
    resolved = route(ProtocolKind.OPENAI_COMPATIBLE)
    events = []
    if missing != "content":
        events.append({"choices": [{"delta": {"content": '{"answer":"你好"}'}}]})
    if missing != "finish":
        events.append({"choices": [{"delta": {}, "finish_reason": "stop"}]})
    if missing != "usage":
        events.append({"choices": [], "usage": {"prompt_tokens": 20, "completion_tokens": 10}})
    with (
        httpx2.Client(
            transport=httpx2.MockTransport(lambda _: httpx2.Response(200, text=sse(events)))
        ) as client,
        observe_text(lambda _: None),
        pytest.raises(ProviderRequestError) as failure,
    ):
        OpenAICompatibleAdapter(client, policy(resolved)).complete(resolved, [])
    assert failure.value.code == "provider_invalid_response"


def test_thinking_exhausting_the_output_limit_is_truncation_even_with_no_answer():
    resolved = route(ProtocolKind.OPENAI_COMPATIBLE)
    events = [
        {"choices": [{"delta": {"reasoning_content": "thinking"}}]},
        {"choices": [{"delta": {}, "finish_reason": "length"}]},
        {"choices": [], "usage": {"prompt_tokens": 20, "completion_tokens": 64}},
    ]
    with (
        httpx2.Client(
            transport=httpx2.MockTransport(lambda _: httpx2.Response(200, text=sse(events)))
        ) as client,
        observe_text(lambda _: None),
        pytest.raises(ProviderRequestError) as failure,
    ):
        OpenAICompatibleAdapter(client, policy(resolved)).complete(resolved, [])
    assert failure.value.code == "provider_output_truncated"
    assert failure.value.usage.output_tokens == 64


@pytest.mark.parametrize(
    "text, expected",
    [
        (' {"answer":"\\u4f60\\u597', "你"),
        ('{"answer":"a\\', "a"),
        ('{"answer":"a\\n', "a\n"),
        ('{"other":{"answer":"leak"}}', ""),
        ('{"answer":"\\ud83d', ""),
        ('{"answer":"\\ud83d\\ude00"}', "😀"),
        ('<think>{"answer":"内部思考"}', ""),
        ('<think>内部思考</think>\n{"answer":"你好', "你好"),
        ('<think>内部思考</think>\n```json\n{"answer":"你好', "你好"),
    ],
)
def test_partial_json_never_exposes_other_fields_or_incomplete_escape(text, expected):
    assert partial_answer(text) == expected


@pytest.mark.parametrize(
    "protocol", [ProtocolKind.OPENAI_COMPATIBLE, ProtocolKind.ANTHROPIC_NATIVE]
)
def test_private_reasoning_only_reports_a_phase_and_public_approach_streams(protocol):
    private = "private reasoning that must never be displayed"
    public = '{"approach":"先核对公开规格。","answer":"资料尚不足。"}'
    if protocol is ProtocolKind.OPENAI_COMPATIBLE:
        events = [
            {"choices": [{"delta": {"reasoning_content": private}}]},
            {"choices": [{"delta": {"reasoning_content": private}}]},
            {"choices": [{"delta": {"content": public}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 20, "completion_tokens": 10}},
            "[DONE]",
        ]
    else:
        events = [
            {
                "type": "message_start",
                "message": {
                    "id": "s1",
                    "model": "synthetic",
                    "usage": {"input_tokens": 20, "output_tokens": 0},
                },
            },
            {
                "type": "content_block_delta",
                "delta": {"type": "thinking_delta", "thinking": private},
            },
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": public}},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
                "usage": {"output_tokens": 10},
            },
            {"type": "message_stop"},
        ]
    observed, phases = [], []
    resolved = route(protocol)
    with (
        httpx2.Client(
            transport=httpx2.MockTransport(lambda _: httpx2.Response(200, text=sse(events)))
        ) as client,
        observe_text(observed.append, on_thinking=lambda: phases.append("thinking")),
    ):
        adapter = (
            OpenAICompatibleAdapter(client, policy(resolved))
            if protocol is ProtocolKind.OPENAI_COMPATIBLE
            else AnthropicNativeAdapter(client, policy(resolved))
        )
        result = adapter.complete(resolved, [])
    assert phases == ["thinking"]
    assert private not in "".join(observed) and private not in result.content
    assert partial_approach(observed[-1]) == "先核对公开规格。"
    assert partial_answer(observed[-1]) == "资料尚不足。"


@pytest.mark.parametrize(
    "content,summary,answer",
    [
        ('{"approach":"先核对\\u4f60\\u597', "先核对你", ""),
        ('{"approach":"先查资料。","answer":"正在整', "先查资料。", "正在整"),
        ('<think>{"approach":"private"}', "", ""),
        ('<think>private</think>\n{"approach":"公开摘要","answer":"回复"}', "公开摘要", "回复"),
        ('{"other":{"approach":"private"}}', "", ""),
    ],
)
def test_public_summary_and_answer_are_decoded_without_nested_or_hidden_fields(
    content, summary, answer
):
    assert partial_approach(content) == summary and partial_answer(content) == answer
