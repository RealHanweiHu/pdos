"""Native tools + JSON schema + bounded SSE for the two configured model protocols.

Official protocol references verified 2026-10-08:
https://developers.openai.com/api/docs/guides/structured-outputs
https://platform.claude.com/docs/en/build-with-claude/structured-outputs
https://platform.claude.com/docs/en/build-with-claude/streaming
MiniMax text/function continuation verified 2026-10-16:
https://platform.minimax.cn/docs/api-reference/text-openai-api
https://platform.minimax.cn/docs/api-reference/text-chat-openai
The host authorizes every attempt; this transport never retries a possibly sent request.
"""

import json
from contextlib import contextmanager
from contextvars import ContextVar

import httpx

from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.errors import DomainError
from pdos_next.providers.agent_wire import (
    FINISH_TOOL,
    FUNCTION_CODECS,
    MINIMAX_CODEC,
    business_name,
    finish_tool,
    private_continuation,
    public_text,
    restore_assistant,
    tool_name,
)
from pdos_next.providers.client import _identifier, _usage, json_value
from pdos_next.providers.types import ProviderError, ProviderRoute, ProviderTokenCount

_PROMPT_CACHE_ALLOWED = ContextVar("pdos_anthropic_prompt_cache_allowed", default=True)


@contextmanager
def prompt_cache_policy(allowed):
    """Host-only dispatch fact; preserves the existing synthetic client's turn interface."""
    token = _PROMPT_CACHE_ALLOWED.set(allowed is True)
    try:
        yield
    finally:
        _PROMPT_CACHE_ALLOWED.reset(token)


def _cache_mark(message):
    content = message["content"]
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    else:
        content = [dict(block) for block in content]
    if content:
        content[-1]["cache_control"] = {"type": "ephemeral"}
    message["content"] = content


def request_body(route, system, messages, tools, output_schema, streaming,
                 *, prompt_cache_allowed=None):
    if prompt_cache_allowed is None:
        prompt_cache_allowed = _PROMPT_CACHE_ALLOWED.get()
    streaming = streaming and route.streaming
    definitions = [{**t, "name": tool_name(t["name"])} for t in tools]
    if route.protocol == "openai-compatible":
        history = [{"role": "system", "content": system}]
        for message in messages:
            restored = restore_assistant(route, message)
            if restored is not None:
                history.extend(restored)
                continue
            value = dict(message)
            value.pop("provider_continuation", None)
            if value.get("tool_calls"):
                value["tool_calls"] = [
                    {
                        "id": c["id"],
                        "type": "function",
                        "function": {
                            "name": tool_name(c["name"]),
                            "arguments": json.dumps(c["arguments"]),
                        },
                    }
                    for c in value["tool_calls"]
                ]
            history.append(value)
        body = {
            "model": route.model,
            "messages": history,
            route.openai_output_parameter: route.max_output_tokens,
            "stream": streaming,
            **({"stream_options": {"include_usage": True}} if streaming else {}),
        }
        if definitions:
            body["tools"] = [{"type": "function", "function": t} for t in definitions]
        if route.agent_response_codec in FUNCTION_CODECS:
            body.setdefault("tools", []).append(finish_tool(output_schema))
            if route.agent_response_codec == MINIMAX_CODEC:
                body["reasoning_split"] = True
        elif route.openai_response_mode in {"auto", "json_schema"}:
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "agent_output", "schema": output_schema, "strict": True,
            }}
        else:
            # Dynamic schemas belong at the context tail, never in the frozen prefix.
            history.append({"role": "user", "content":
                "Return the final response as a JSON object matching this JSON Schema. "
                "Use the available business tools first when needed. Do not wrap JSON in "
                "Markdown. JSON Schema: " + json.dumps(output_schema, ensure_ascii=False)})
            if route.openai_response_mode == "json_object":
                body["response_format"] = {"type": "json_object"}
        return body
    if any(message.get("provider_continuation") is not None for message in messages):
        raise DomainError("VERSION_CONFLICT", "原模型协议续接不能用于其他协议。")
    history = []
    for message in messages:
        role, content = message["role"], message.get("content", "")
        if role == "tool":
            value = {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": message["tool_call_id"],
                        "content": content,
                    }
                ],
            }
        elif role == "assistant" and message.get("tool_calls"):
            blocks = ([{"type": "text", "text": content}] if content else []) + [
                {
                    "type": "tool_use",
                    "id": c["id"],
                    "name": tool_name(c["name"]),
                    "input": c["arguments"],
                }
                for c in message["tool_calls"]
            ]
            value = {"role": role, "content": blocks}
        else:
            value = {"role": role, "content": content}
        if history and history[-1]["role"] == value["role"] and isinstance(value["content"], list):
            previous = history[-1]["content"]
            if isinstance(previous, str):
                previous = [{"type": "text", "text": previous}]
            history[-1]["content"] = previous + value["content"]
        else:
            history.append(value)
    if history and prompt_cache_allowed:
        _cache_mark(history[0])
        if len(history) > 1:
            _cache_mark(history[-1])
    return {
        "model": route.model,
        "system": [{"type": "text", "text": system,
                    **({"cache_control": {"type": "ephemeral"}} if prompt_cache_allowed else {})}],
        "messages": history,
        "tools": [
            {"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
            for t in definitions
        ],
        "output_config": {"format": {"type": "json_schema", "schema": output_schema}},
        "max_tokens": route.max_output_tokens,
        "stream": streaming,
    }


def parse_turn(body, route, request_id=None):
    valid_request_id = None
    try:
        valid_request_id = _identifier(request_id or body.get("id"))
        usage = _usage(body, route.protocol)
        calls, text, continuation, native_output = [], "", None, None
        if route.protocol == "openai-compatible":
            if len(body["choices"]) != 1:
                raise ValueError("One choice required")
            choice = body["choices"][0]
            if choice["finish_reason"] == "length":
                raise ProviderError("PROVIDER_OUTPUT_TRUNCATED", usage=usage)
            if choice["finish_reason"] not in {"stop", "tool_calls"}:
                raise ProviderError("PROVIDER_REFUSAL", usage=usage)
            message = choice["message"]
            if message.get("refusal") or message.get("role") != "assistant":
                raise ProviderError("PROVIDER_REFUSAL", usage=usage)
            minimax = route.agent_response_codec == MINIMAX_CODEC
            text = public_text(message.get("content")) if minimax else message.get("content") or ""
            for call in message.get("tool_calls") or []:
                if call["type"] != "function":
                    raise ValueError("Native function required")
                arguments = json_value(call["function"]["arguments"])
                if (
                    route.agent_response_codec in FUNCTION_CODECS
                    and call["function"]["name"] == FINISH_TOOL
                ):
                    if len(message["tool_calls"]) != 1 or not isinstance(arguments, dict):
                        raise ValueError("Output function cannot mix with business calls")
                    # Validate the protocol identity without exposing an executable tool.
                    ToolCall(id=call["id"], name=FINISH_TOOL, arguments=arguments)
                    native_output = arguments
                    continue
                calls.append(
                    ToolCall(
                        id=call["id"],
                        name=business_name(call["function"]["name"]),
                        arguments=arguments,
                    )
                )
            if (
                route.agent_response_codec in FUNCTION_CODECS
                or message.get("reasoning_content") is not None
            ):
                continuation = private_continuation(route, message)
        else:
            if body["stop_reason"] == "max_tokens":
                raise ProviderError("PROVIDER_OUTPUT_TRUNCATED", usage=usage)
            if body["stop_reason"] not in {"end_turn", "tool_use"}:
                raise ProviderError("PROVIDER_REFUSAL", usage=usage)
            for block in body["content"]:
                if block["type"] == "text":
                    text += block["text"]
                elif block["type"] == "tool_use":
                    calls.append(
                        ToolCall(
                            id=block["id"],
                            name=business_name(block["name"]),
                            arguments=block["input"],
                        )
                    )
                else:
                    raise ValueError("Unsupported model output block")
        if (
            len({c.id for c in calls}) != len(calls)
            or usage.output_tokens > route.max_output_tokens
        ):
            raise ValueError("Duplicate call or output limit")
        structured = native_output if native_output is not None else (
            json_value(text) if not calls else None
        )
        if isinstance(structured, dict) and "result_json" in structured:
            decoded = json_value(structured.pop("result_json"))
            if not isinstance(decoded, dict):
                raise ValueError("Business result object required")
            structured["result"] = decoded
        if not calls and not isinstance(structured, dict):
            raise ValueError("Structured final object required")
        return ModelTurn(text, tuple(calls), usage, valid_request_id, structured,
                         continuation=continuation)
    except ProviderError as error:
        error.request_id = error.request_id or valid_request_id
        raise
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise ProviderError(
            "PROVIDER_INVALID_RESPONSE", unknown=True, request_id=valid_request_id
        ) from None


class StreamAccumulator:
    def __init__(self, protocol, emit, *, minimax=False):
        self.protocol, self.emit = protocol, emit
        self.minimax = minimax
        self.minimax_final = False
        self.body = (
            {
                "usage": {},
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "", "tool_calls": []},
                        "finish_reason": None,
                    }
                ],
            }
            if protocol == "openai-compatible"
            else {}
        )
        self.calls = {}
        self.stopped = False

    def accept(self, data):
        if self.protocol == "openai-compatible":
            if data == "[DONE]":
                self.stopped = True
                return
            chunk = json_value(data)
            if self.minimax:
                if self.minimax_final:
                    raise ValueError("Data after MiniMax terminal usage")
                prior_id = self.body.get("id")
                if prior_id and chunk.get("id", prior_id) != prior_id:
                    raise ValueError("Stream response identity changed")
                if "base_resp" in chunk:
                    if not isinstance(chunk["base_resp"], dict):
                        raise ValueError("Invalid MiniMax status")
                    status = chunk["base_resp"].get("status_code")
                    if (
                        type(status) is not int or status != 0
                        or chunk.get("choices") != []
                        or not prior_id or chunk.get("id") != prior_id
                        or not self.body["choices"][0]["finish_reason"]
                    ):
                        raise ValueError("Invalid MiniMax terminal usage")
                    _usage(chunk, self.protocol)
                    self.minimax_final = True
            if chunk.get("usage") is not None:
                self.body["usage"] = chunk["usage"]
            choices = chunk.get("choices", [])
            if not choices:
                return
            if len(choices) != 1 or choices[0].get("index", 0) != 0:
                raise ValueError("One streamed choice required")
            delta = choices[0].get("delta", {})
            message = self.body["choices"][0]["message"]
            if delta.get("reasoning_content") is not None:
                if not isinstance(delta["reasoning_content"], str):
                    raise ValueError("Reasoning stream must be text")
                message["reasoning_content"] = message.get("reasoning_content", "") + delta[
                    "reasoning_content"
                ]
            if delta.get("content"):
                message["content"] += delta["content"]
                self.emit({"type": "text_delta", "text": delta["content"]})
            for value in delta.get("tool_calls") or []:
                call = self.calls.setdefault(
                    value["index"],
                    {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                )
                call["id"] += value.get("id", "")
                for key in ("name", "arguments"):
                    call["function"][key] += value.get("function", {}).get(key, "")
            message["tool_calls"] = [self.calls[n] for n in sorted(self.calls)]
            if choices[0].get("finish_reason"):
                self.body["choices"][0]["finish_reason"] = choices[0]["finish_reason"]
            self.body["id"] = chunk.get("id", self.body.get("id"))
            return
        chunk = json_value(data)
        kind = chunk["type"]
        if kind == "message_start":
            self.body = chunk["message"]
            self.body["content"] = []
        elif kind == "content_block_start":
            self.calls[chunk["index"]] = chunk["content_block"]
        elif kind == "content_block_delta":
            block = self.calls[chunk["index"]]
            delta = chunk["delta"]
            if delta["type"] == "text_delta":
                block["text"] += delta["text"]
                self.emit({"type": "text_delta", "text": delta["text"]})
            elif delta["type"] == "input_json_delta":
                block["_json"] = block.get("_json", "") + delta["partial_json"]
            else:
                raise ValueError("Unsupported stream delta")
        elif kind == "content_block_stop":
            block = self.calls[chunk["index"]]
            if "_json" in block:
                block["input"] = json_value(block.pop("_json"))
        elif kind == "message_delta":
            self.body.update(chunk["delta"])
            self.body["usage"].update(chunk.get("usage", {}))
        elif kind == "message_stop":
            self.body["content"] = [self.calls[n] for n in sorted(self.calls)]
            self.stopped = True
        elif kind == "error":
            raise ProviderError("PROVIDER_SERVER_ERROR", unknown=True)
        elif kind != "ping":
            raise ValueError("Unsupported stream event")


class AgentProviderClient:
    def __init__(self, transport=None):
        self.client = httpx.Client(
            transport=transport or httpx.HTTPTransport(retries=0),
            trust_env=False,
            follow_redirects=False,
        )

    def close(self):
        self.client.close()

    def count_tokens(self, route, *, system, messages, tools, output_schema,
                     cancelled=lambda: False):
        """Same-host preflight only; no generation, caching, retries or usage object.

        https://platform.claude.com/docs/en/build-with-claude/token-counting
        https://platform.claude.com/docs/en/api/typescript/messages/count_tokens
        """
        target = route.token_count_url
        route.assert_target_allowed(target)
        body = request_body(route, system, messages, tools, output_schema, False)
        body.pop("max_tokens")
        body.pop("stream")
        if cancelled():
            raise ProviderError("MODEL_CANCELLED")
        request_id = None
        try:
            with self.client.stream("POST", target, json=body, headers={
                "Accept-Encoding": "identity", "x-api-key": route.api_key.get_secret_value(),
                "anthropic-version": "2023-06-01",
            }, timeout=route.timeout_seconds) as response:
                request_id = _identifier(response.headers.get("request-id"))
                if response.status_code == 429:
                    raise ProviderError("PROVIDER_RATE_LIMITED")
                if response.is_redirect:
                    raise ProviderError("PROVIDER_REDIRECT_DENIED")
                if response.status_code != 200:
                    raise ProviderError("PROVIDER_COUNT_REJECTED")
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise ProviderError("PROVIDER_ENCODING_DENIED", unknown=True)
                raw = bytearray()
                for chunk in response.iter_bytes():
                    if cancelled():
                        raise ProviderError("MODEL_CANCELLED", unknown=True)
                    raw.extend(chunk)
                    if len(raw) > min(route.response_bytes, 16384):
                        raise ProviderError("PROVIDER_RESPONSE_TOO_LARGE", unknown=True)
                return ProviderTokenCount(json_value(raw)["input_tokens"], request_id)
        except ProviderError as error:
            error.request_id = error.request_id or request_id
            raise
        except (httpx.HTTPError, ValueError, UnicodeDecodeError, KeyError, TypeError):
            raise ProviderError(
                "PROVIDER_COUNT_INVALID", unknown=True, request_id=request_id,
            ) from None

    def turn(
        self,
        route: ProviderRoute,
        *,
        system,
        messages,
        tools,
        output_schema,
        emit=None,
        cancelled=lambda: False,
    ):
        route.assert_target_allowed(route.target_url)
        streaming = emit is not None and route.streaming
        body = request_body(route, system, messages, tools, output_schema, streaming)
        headers = {"Accept-Encoding": "identity"}
        if route.protocol == "openai-compatible":
            headers["Authorization"] = f"Bearer {route.api_key.get_secret_value()}"
        else:
            headers.update(
                {"x-api-key": route.api_key.get_secret_value(), "anthropic-version": "2023-06-01"}
            )
        if cancelled():
            raise ProviderError("MODEL_CANCELLED")
        request_id = None
        try:
            with self.client.stream(
                "POST", route.target_url, json=body, headers=headers, timeout=route.timeout_seconds
            ) as response:
                request_id = _identifier(
                    response.headers.get("request-id") or response.headers.get("x-request-id")
                )
                if response.status_code == 429:
                    raise ProviderError("PROVIDER_RATE_LIMITED")
                if response.is_redirect:
                    raise ProviderError("PROVIDER_REDIRECT_DENIED")
                if response.status_code >= 500:
                    raise ProviderError("PROVIDER_SERVER_ERROR", unknown=True)
                if response.status_code != 200:
                    raise ProviderError("PROVIDER_REQUEST_REJECTED")
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise ProviderError("PROVIDER_ENCODING_DENIED", unknown=True)
                raw, size = bytearray(), 0
                minimax = route.agent_response_codec == MINIMAX_CODEC
                accumulator = StreamAccumulator(
                    route.protocol, (lambda _: None) if minimax else emit,
                    minimax=minimax,
                )
                for chunk in response.iter_bytes():
                    if cancelled():
                        raise ProviderError("MODEL_CANCELLED", unknown=True)
                    size += len(chunk)
                    if size > route.response_bytes:
                        raise ProviderError("PROVIDER_RESPONSE_TOO_LARGE", unknown=True)
                    raw.extend(chunk)
                    if streaming:
                        # Native SSE may use LF or CRLF. Normalize only complete CRLFs,
                        # preserving a trailing CR until the following chunk arrives.
                        raw = bytearray(raw.replace(b"\r\n", b"\n"))
                        while b"\n\n" in raw:
                            packet, _, tail = raw.partition(b"\n\n")
                            raw = bytearray(tail)
                            values = [
                                line[5:].strip()
                                for line in packet.splitlines()
                                if line.startswith(b"data:")
                            ]
                            if values:
                                accumulator.accept(b"\n".join(values).decode())
                if streaming:
                    # MiniMax can close normally after its identified success/usage
                    # summary without [DONE]. Never accept a partial SSE packet.
                    if raw.strip() or not (accumulator.stopped or accumulator.minimax_final):
                        raise ProviderError(
                            "PROVIDER_RESULT_UNKNOWN", unknown=True,
                            request_id=_identifier(accumulator.body.get("id")),
                        )
                    payload = accumulator.body
                else:
                    payload = json_value(raw)
                result = parse_turn(
                    payload,
                    route,
                    request_id,
                )
                if minimax and emit is not None and result.text:
                    # MiniMax can inline thinking tags even on a split request. Only
                    # publish text after the complete native response is parsed.
                    emit({"type": "text_delta", "text": result.text})
                return result
        except ProviderError as error:
            error.request_id = error.request_id or request_id
            raise
        except DomainError as error:
            if request_id:
                error.detail = {**error.detail, "provider_request_id": request_id}
            raise
        except (httpx.HTTPError, ValueError, UnicodeDecodeError, KeyError):
            raise ProviderError(
                "PROVIDER_RESULT_UNKNOWN", unknown=True, request_id=request_id
            ) from None
