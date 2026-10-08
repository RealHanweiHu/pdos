"""Opt-in provider streaming; the existing gateway still validates and meters the result."""

import json
import logging
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict

import httpx2

from app.ai.model_catalog import ProtocolKind
from app.ai.provider_adapters import ProviderRequestError, ProviderResponse, _usage

_observer: ContextVar[Callable[[str], None] | None] = ContextVar("provider_text", default=None)
_thinking_observer: ContextVar[Callable[[], None] | None] = ContextVar(
    "provider_thinking_phase", default=None
)
logger = logging.getLogger(__name__)


@contextmanager
def observe_text(
    callback: Callable[[str], None], *, on_thinking: Callable[[], None] | None = None
) -> Iterator[None]:
    token = _observer.set(callback)
    thinking_token = _thinking_observer.set(on_thinking)
    try:
        yield
    finally:
        _observer.reset(token)
        _thinking_observer.reset(thinking_token)


def enabled() -> bool:
    return _observer.get() is not None


def complete_stream(client, url, headers, payload, timeout, protocol) -> ProviderResponse:
    observer = _observer.get()
    assert observer is not None
    observer("")  # A structured retry replaces the previous provisional output.
    payload = {**payload, "stream": True}
    if protocol is ProtocolKind.OPENAI_COMPATIBLE:
        payload["stream_options"] = {"include_usage": True}
    content, request_id, model, finish = "", None, None, None
    usage_body: dict = {}
    ended = False
    usage = None
    thinking_reported = False
    try:
        with client.stream("POST", url, headers=headers, json=payload, timeout=timeout) as response:
            if not 200 <= response.status_code < 300:
                raise ProviderRequestError(
                    f"provider_http_{response.status_code}", "provider request failed"
                )
            request_id = response.headers.get("x-request-id")
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data:
                    continue
                if data == "[DONE]":
                    ended = True
                    break
                body = json.loads(data)
                if (
                    not isinstance(body, Mapping)
                    or body.get("error")
                    or body.get("type") == "error"
                ):
                    raise ValueError("invalid provider event")
                delta = ""
                thinking = False
                if protocol is ProtocolKind.OPENAI_COMPATIBLE:
                    request_id = request_id or body.get("id")
                    model = body.get("model") or model
                    if body.get("usage"):
                        usage_body = dict(body["usage"])
                    choices = body.get("choices", [])
                    if choices:
                        choice = choices[0]
                        fields = choice.get("delta", {})
                        delta = fields.get("content") or ""
                        thinking = bool(fields.get("reasoning_content") or fields.get("reasoning"))
                        finish = choice.get("finish_reason") or finish
                else:
                    kind = body.get("type")
                    thinking = (
                        kind == "content_block_delta"
                        and body.get("delta", {}).get("type") == "thinking_delta"
                    )
                    if kind == "message_start":
                        message = body["message"]
                        request_id = request_id or message.get("id")
                        model = message.get("model")
                        usage_body.update(message["usage"])
                    elif (
                        kind == "content_block_delta" and body["delta"].get("type") == "text_delta"
                    ):
                        delta = body["delta"]["text"]
                    elif kind == "message_delta":
                        usage_body.update(body.get("usage", {}))
                        finish = body.get("delta", {}).get("stop_reason") or finish
                    elif kind == "message_stop":
                        ended = True
                        break
                if usage_body:
                    usage = _usage(usage_body, protocol)
                if not isinstance(delta, str) or len(content) + len(delta) > 200_000:
                    raise ValueError("invalid provider text")
                if delta:
                    content += delta
                    thinking = thinking or content.lstrip().startswith("<think>")
                if thinking and not thinking_reported:
                    thinking_reported = True
                    callback = _thinking_observer.get()
                    if callback:
                        callback()  # Phase only; private reasoning text is never forwarded.
                if delta:
                    observer(content)
        # MiniMax closes a successful OpenAI-compatible stream after its stop
        # and usage chunks without sending [DONE]. A clean EOF is sufficient
        # only with an explicit completion reason; partial streams still fail.
        complete_end = ended or (
            protocol is ProtocolKind.OPENAI_COMPATIBLE
            and finish in {"stop", "length", "tool_calls", "function_call", "content_filter"}
        )
        if not complete_end or not finish:
            raise ValueError("incomplete provider stream")
        if finish in {"length", "max_tokens"}:
            raise ProviderRequestError(
                "provider_output_truncated",
                "provider output reached its limit",
                usage=usage,
                request_id=request_id,
            )
        if finish == "content_filter":
            raise ProviderRequestError(
                "provider_output_filtered",
                "provider output was filtered",
                usage=usage,
                request_id=request_id,
            )
        if not content or usage is None:
            raise ValueError("incomplete provider stream")
        return ProviderResponse(
            content=content, request_id=request_id, model_version=model, **asdict(usage)
        )
    except httpx2.HTTPError as error:
        raise ProviderRequestError(
            "provider_transport_error",
            "provider stream interrupted",
            usage=usage,
            request_id=request_id,
        ) from error
    except (KeyError, TypeError, ValueError) as error:
        logger.warning(
            "Provider stream rejected: protocol=%s terminal_marker=%s finish=%s "
            "content_length=%s usage_known=%s request_id=%s",
            protocol.value,
            ended,
            finish,
            len(content),
            usage is not None,
            request_id,
        )
        raise ProviderRequestError(
            "provider_invalid_response",
            "provider returned an incomplete stream",
            usage=usage,
            request_id=request_id,
        ) from error


def _partial_public_text(content: str, field: str, limit: int) -> str:
    """Decode only the public approach/answer prefix, never nested or thinking fields."""
    import re

    document = content.lstrip()
    if document.startswith("<think>"):
        closing = document.find("</think>")
        if closing == -1:
            return ""
        document = document[closing + len("</think>") :].lstrip()
    if document.startswith("```"):
        opening_line = document.find("\n")
        if opening_line == -1:
            return ""
        document = document[opening_line + 1 :]
    match = re.match(r'^\s*\{\s*"(approach|answer)"\s*:\s*', document)
    if not match:
        return ""
    start = match.end()
    if match.group(1) != field:
        try:
            previous, end = json.JSONDecoder().raw_decode(document, start)
        except ValueError:
            return ""
        if not isinstance(previous, str):
            return ""
        match = re.match(r'\s*,\s*"' + field + r'"\s*:\s*', document[end:])
        if not match:
            return ""
        start = end + match.end()
    if document[start : start + 1] != '"':
        return ""
    raw = document[start + 1 :]
    end, index = 0, 0
    while index < len(raw):
        char = raw[index]
        if char == '"':
            break
        if char == "\\":
            if index + 1 >= len(raw):
                break
            width = 6 if raw[index + 1] == "u" else 2
            if index + width > len(raw):
                break
            index += width
        else:
            index += 1
        end = index
    try:
        answer = json.loads('"' + raw[:end] + '"')
        # UTF-16 surrogate halves cannot be encoded as UTF-8 SSE data.
        return answer.encode("utf-16", errors="surrogatepass").decode("utf-16", errors="ignore")[
            :limit
        ]
    except (ValueError, UnicodeError):
        return ""


def partial_answer(content: str) -> str:
    return _partial_public_text(content, "answer", 12_000)


def partial_approach(content: str) -> str:
    return _partial_public_text(content, "approach", 512)
