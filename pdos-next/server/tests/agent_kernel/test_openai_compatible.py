"""Custom OpenAI-compatible endpoints, using synthetic HTTP and no external calls."""

import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from pdos_next.agent_kernel.qualification_binding import model_identity
from pdos_next.errors import DomainError
from pdos_next.model_configuration.persistence import decode
from pdos_next.model_configuration.service import digest
from pdos_next.models import now
from pdos_next.providers.agent_client import AgentProviderClient, request_body
from pdos_next.providers.agent_wire import FINISH_TOOL
from pdos_next.providers.types import ProviderError
from pdos_next.schemas.model_configuration import ModelMetadata
from tests.agent_kernel.test_native_protocols import SCHEMA, TOOLS, reply, route


@pytest.mark.parametrize("mode", ["auto", "tools", "json_schema", "json_object", "text"])
@pytest.mark.parametrize("parameter", ["max_tokens", "max_completion_tokens"])
def test_custom_endpoint_preserves_selected_wire_options_and_frozen_prefix(mode, parameter):
    selected = replace(route("openai-compatible"), base_url="https://custom.invalid/api/v2",
        model="organization/custom-model:latest", openai_response_mode=mode,
        openai_output_parameter=parameter)
    body = request_body(selected, "frozen", [{"role": "user", "content": "task"}],
        TOOLS, SCHEMA, False)
    assert selected.target_url == "https://custom.invalid/api/v2/chat/completions"
    assert body[parameter] == selected.max_output_tokens
    assert ({"max_tokens", "max_completion_tokens"} - {parameter}).isdisjoint(body)
    assert body["messages"][0] == {"role": "system", "content": "frozen"}
    assert "reasoning_split" not in body
    if mode == "tools":
        assert "response_format" not in body
        assert body["tools"][-1]["function"]["name"] == FINISH_TOOL
    elif mode == "text":
        assert "response_format" not in body
    else:
        expected = "json_schema" if mode == "auto" else mode
        assert body["response_format"]["type"] == expected
    if mode in {"text", "json_object"}:
        assert json.dumps(SCHEMA) in body["messages"][-1]["content"]
    assert body["tools"][0]["function"]["parameters"] == TOOLS[0]["parameters"]


def function_reply():
    value = reply("openai-compatible", tools=True)
    value["choices"][0]["message"]["tool_calls"][0]["function"] = {
        "name": FINISH_TOOL, "arguments": '{"ok":true}'}
    return value


def test_generic_functions_roundtrip_business_tool_and_finish_before_followup():
    selected = replace(route("openai-compatible"), openai_response_mode="tools")
    seen = []
    responses = [reply("openai-compatible", tools=True), function_reply(), function_reply()]

    def handle(request):
        body = json.loads(request.content)
        seen.append(body)
        assert request.url == selected.target_url
        assert request.headers["authorization"] == "Bearer synthetic-fixture-only"
        assert "synthetic-fixture-only" not in request.content.decode()
        assert "response_format" not in body and "reasoning_split" not in body
        return httpx.Response(200, json=responses[len(seen) - 1])

    client = AgentProviderClient(httpx.MockTransport(handle))
    messages = [{"role": "user", "content": "synthetic"}]
    try:
        first = client.turn(selected, system="frozen", messages=messages,
            tools=TOOLS, output_schema=SCHEMA)
        assert first.calls[0].name == "category.read"
        messages.extend([
            {"role": "assistant", "content": first.text,
             "tool_calls": [c.model_dump(mode="json") for c in first.calls],
             "provider_continuation": first.continuation},
            {"role": "tool", "tool_call_id": first.calls[0].id, "content": "actual record"},
        ])
        final = client.turn(selected, system="frozen", messages=messages,
            tools=TOOLS, output_schema=SCHEMA)
        assert final.structured == {"ok": True} and not final.calls
        messages.extend([
            {"role": "assistant", "content": final.text,
             "provider_continuation": final.continuation},
            {"role": "user", "content": "follow up"},
        ])
        assert client.turn(selected, system="frozen", messages=messages,
            tools=TOOLS, output_schema=SCHEMA).structured == {"ok": True}
        assert seen[-1]["messages"][-2]["role"] == "tool"
        assert seen[-1]["messages"][-2]["tool_call_id"] == "call-1"
        assert seen[0]["tools"] == seen[-1]["tools"]
        # Continuations cannot migrate to another endpoint or response mode.
        with pytest.raises(DomainError):
            client.turn(replace(selected, base_url="https://another.invalid/v1"),
                system="frozen", messages=messages, tools=TOOLS, output_schema=SCHEMA)
        assert len(seen) == 3
    finally:
        client.close()


@pytest.mark.parametrize("mode", ["tools", "json_schema", "json_object", "text"])
def test_non_streaming_endpoint_with_progress_callback_omits_stream_options(mode):
    selected = replace(route("openai-compatible"), openai_response_mode=mode, streaming=False)
    seen = []

    def handle(request):
        seen.append(json.loads(request.content))
        assert seen[0]["stream"] is False and "stream_options" not in seen[0]
        value = function_reply() if mode == "tools" else reply("openai-compatible")
        if mode != "tools":
            value["choices"][0]["message"]["tool_calls"] = None
        value["usage"]["prompt_tokens_details"] = None
        return httpx.Response(200, json=value)

    client = AgentProviderClient(httpx.MockTransport(handle))
    try:
        result = client.turn(selected, system="frozen", messages=[], tools=[],
            output_schema=SCHEMA, emit=lambda _: None)
        assert result.structured == {"ok": True}
        assert result.usage.input_tokens == 30 and result.usage.cache_read_tokens == 0
        if mode != "tools":
            assert "tools" not in seen[0]
        assert len(seen) == 1
    finally:
        client.close()


def test_generic_functions_stream_and_missing_usage_keep_accounting_guard():
    selected = replace(route("openai-compatible"), openai_response_mode="tools")
    message = function_reply()["choices"][0]["message"]
    message["tool_calls"][0]["index"] = 0
    packets = [json.dumps({"id": "req_1", "choices": [
        {"index": 0, "delta": message, "finish_reason": "tool_calls"}]}),
        json.dumps({"choices": [], "usage": {"prompt_tokens": 30, "completion_tokens": 5}}),
        "[DONE]"]
    for include_usage in (True, False):
        content = "".join("data: " + p + "\n\n" for i, p in enumerate(packets)
            if include_usage or i != 1)
        client = AgentProviderClient(httpx.MockTransport(
            lambda _, content=content: httpx.Response(200, text=content)))
        try:
            if include_usage:
                result = client.turn(selected, system="frozen", messages=[], tools=TOOLS,
                    output_schema=SCHEMA, emit=lambda _: None)
                assert result.structured == {"ok": True} and not result.calls
            else:
                with pytest.raises(ProviderError) as failed:
                    client.turn(selected, system="frozen", messages=[], tools=TOOLS,
                        output_schema=SCHEMA, emit=lambda _: None)
                assert failed.value.unknown
        finally:
            client.close()


def test_old_saved_metadata_and_route_digests_stay_valid_without_new_fields():
    selected = route("openai-compatible")
    old_route = {key: getattr(selected, key) for key in (
        "protocol", "base_url", "model", "version", "max_output_tokens",
        "openai_output_parameter", "timeout_seconds", "response_bytes")}
    old_digest = hashlib.sha256(json.dumps(old_route, sort_keys=True).encode()).hexdigest()
    assert selected.digest == old_digest
    metadata = ModelMetadata(protocol=selected.protocol, base_url=selected.base_url,
        model=selected.model, model_version=selected.version)
    old_metadata = metadata.model_dump(mode="json",
        exclude={"openai_response_mode", "streaming", "connection_id", "context_window_tokens"})
    row = SimpleNamespace(tenant_id=uuid4(), id=uuid4(), revision=1, public_metadata=old_metadata,
        enabled=True, created_by=uuid4(), created_at=now(), secret_reference=None)
    row.binding_digest = digest({"tenant": str(row.tenant_id), "id": str(row.id),
        "revision": 1, "metadata": old_metadata, "enabled": True, "secret": None})
    decoded = decode(row)
    assert decoded.binding_digest == row.binding_digest
    assert decoded.metadata.openai_response_mode == "auto" and decoded.metadata.streaming
    for options in ({"openai_response_mode": "tools"}, {"streaming": False}):
        changed = metadata.model_copy(update=options)
        assert replace(decoded, metadata=changed).binding_digest != decoded.binding_digest
        assert changed.route(SecretStr("synthetic-key"), selected.version).digest != selected.digest
    for mode in ("text", "tools"):
        changed_identity = model_identity(replace(selected, openai_response_mode=mode))
        assert changed_identity != model_identity(selected)


@pytest.mark.parametrize("options", [
    {"openai_response_mode": "unknown"}, {"streaming": "true"},
    {"protocol": "anthropic-native", "openai_response_mode": "tools"},
])
def test_invalid_compatibility_options_fail_before_network(options):
    with pytest.raises(ValidationError):
        ModelMetadata.model_validate({
            "protocol": "openai-compatible", "base_url": "https://custom.invalid/v1",
            "model": "custom-model", "model_version": "v1", **options})
