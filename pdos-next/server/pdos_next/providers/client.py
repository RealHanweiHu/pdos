"""Bounded, non-streaming model requests with no redirects, proxy inheritance or retry.

Protocol sources (read 2026-10-02):
https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
https://platform.claude.com/docs/en/api/messages/create
https://platform.claude.com/docs/en/build-with-claude/prompt-caching
"""

import json
import re

import httpx

from pdos_next.providers.types import ProviderError, ProviderResponse, ProviderRoute, ProviderUsage


def _integer(value):
    if type(value) is not int or value < 0:
        raise ValueError("Invalid usage")
    return value


def _identifier(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9:_.-]{1,200}", value):
        raise ValueError("Invalid provider identifier")
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def json_value(content: str | bytes):
    def reject_constant(_):
        raise ValueError("Non-finite JSON number")

    return json.loads(content, object_pairs_hook=_unique_object, parse_constant=reject_constant)


def _usage(body: dict, protocol: str) -> ProviderUsage:
    value = body["usage"]
    if not isinstance(value, dict):
        raise ValueError("Usage required")
    if protocol == "openai-compatible":
        details = value.get("prompt_tokens_details", {})
        if details is None:
            details = {}
        if not isinstance(details, dict):
            raise ValueError("Invalid cache usage")
        return ProviderUsage(
            _integer(value["prompt_tokens"]),
            _integer(value["completion_tokens"]),
            _integer(details.get("cached_tokens", 0)),
            _integer(details.get("cache_write_tokens", 0)),
        )
    reads = _integer(value.get("cache_read_input_tokens", 0))
    writes = _integer(value.get("cache_creation_input_tokens", 0))
    return ProviderUsage(
        _integer(value["input_tokens"]) + reads + writes,
        _integer(value["output_tokens"]),
        reads,
        writes,
    )


def parse_response(body: dict, route: ProviderRoute, request_id=None) -> ProviderResponse:
    usage = None
    try:
        usage = _usage(body, route.protocol)
        request_id = _identifier(request_id or body.get("id"))
        model = _identifier(body.get("model"))
        if route.protocol == "openai-compatible":
            choices = body["choices"]
            if not isinstance(choices, list) or len(choices) != 1:
                raise ValueError("One choice required")
            choice = choices[0]
            reason = choice["finish_reason"]
            if reason == "length":
                raise ProviderError("PROVIDER_OUTPUT_TRUNCATED", usage=usage, request_id=request_id)
            if reason == "content_filter":
                raise ProviderError("PROVIDER_REFUSAL", usage=usage, request_id=request_id)
            if reason != "stop":
                raise ValueError("Unexpected provider finish reason")
            message = choice["message"]
            if message.get("refusal"):
                raise ProviderError("PROVIDER_REFUSAL", usage=usage, request_id=request_id)
            if (
                message.get("role") != "assistant"
                or message.get("tool_calls")
                or message.get("function_call")
            ):
                raise ValueError("Text-only assistant response required")
            content = message["content"]
        else:
            reason = body["stop_reason"]
            if reason == "max_tokens":
                raise ProviderError("PROVIDER_OUTPUT_TRUNCATED", usage=usage, request_id=request_id)
            if reason == "refusal":
                raise ProviderError("PROVIDER_REFUSAL", usage=usage, request_id=request_id)
            if (
                isinstance(body.get("stop_details"), dict)
                and body["stop_details"].get("type") == "refusal"
            ):
                raise ProviderError("PROVIDER_REFUSAL", usage=usage, request_id=request_id)
            if reason != "end_turn" or body.get("role") != "assistant":
                raise ValueError("Unexpected provider finish reason")
            blocks = body["content"]
            if not isinstance(blocks, list) or not blocks:
                raise ValueError("Text content required")
            texts = []
            for block in blocks:
                if not isinstance(block, dict) or block.get("type") != "text":
                    raise ValueError("Unexpected provider content block")
                if not isinstance(block.get("text"), str):
                    raise ValueError("Text content required")
                texts.append(block["text"])
            content = "".join(texts)
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Nonempty model text required")
        if usage.output_tokens > route.max_output_tokens:
            raise ProviderError(
                "PROVIDER_OUTPUT_LIMIT_EXCEEDED", usage=usage, request_id=request_id
            )
        return ProviderResponse(content, usage, request_id, model)
    except ProviderError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, IndexError):
        raise ProviderError(
            "PROVIDER_INVALID_RESPONSE", unknown=usage is None, usage=usage, request_id=request_id
        ) from None


class ProviderClient:
    def __init__(self, transport: httpx.BaseTransport | None = None):
        self._client = httpx.Client(
            transport=transport or httpx.HTTPTransport(retries=0, trust_env=False),
            trust_env=False,
            follow_redirects=False,
        )

    def close(self):
        self._client.close()

    def complete(self, route: ProviderRoute, *, system: str, instruction: str) -> ProviderResponse:
        route.assert_target_allowed(route.target_url)
        if route.protocol == "openai-compatible":
            body = {
                "model": route.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": instruction},
                ],
                route.openai_output_parameter: route.max_output_tokens,
                "stream": False,
            }
            headers = {"Authorization": f"Bearer {route.api_key.get_secret_value()}"}
        else:
            body = {
                "model": route.model,
                "system": system,
                "messages": [{"role": "user", "content": instruction}],
                "max_tokens": route.max_output_tokens,
                "stream": False,
            }
            headers = {
                "x-api-key": route.api_key.get_secret_value(),
                "anthropic-version": "2023-06-01",
            }
        headers["Accept-Encoding"] = "identity"
        request_id = None
        try:
            with self._client.stream(
                "POST", route.target_url, headers=headers, json=body, timeout=route.timeout_seconds
            ) as response:
                try:
                    request_id = _identifier(
                        response.headers.get("request-id") or response.headers.get("x-request-id")
                    )
                except ValueError:
                    pass
                if response.is_redirect:
                    raise ProviderError("PROVIDER_REDIRECT_DENIED", request_id=request_id)
                if response.status_code == 429:
                    raise ProviderError("PROVIDER_RATE_LIMITED", request_id=request_id)
                if response.status_code >= 500:
                    raise ProviderError(
                        "PROVIDER_SERVER_ERROR", unknown=True, request_id=request_id
                    )
                if response.status_code != 200:
                    raise ProviderError("PROVIDER_REQUEST_REJECTED", request_id=request_id)
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise ProviderError(
                        "PROVIDER_ENCODING_DENIED", unknown=True, request_id=request_id
                    )
                content = bytearray()
                for chunk in response.iter_bytes():
                    if len(content) + len(chunk) > route.response_bytes:
                        raise ProviderError(
                            "PROVIDER_RESPONSE_TOO_LARGE", unknown=True, request_id=request_id
                        )
                    content.extend(chunk)
                try:
                    payload = json_value(bytes(content))
                    if not isinstance(payload, dict):
                        raise ValueError("Object required")
                except (ValueError, UnicodeDecodeError, RecursionError):
                    raise ProviderError(
                        "PROVIDER_INVALID_RESPONSE", unknown=True, request_id=request_id
                    ) from None
                return parse_response(payload, route, request_id)
        except httpx.TimeoutException:
            raise ProviderError(
                "PROVIDER_RESULT_UNKNOWN", unknown=True, request_id=request_id
            ) from None
        except httpx.HTTPError:
            raise ProviderError(
                "PROVIDER_RESULT_UNKNOWN", unknown=True, request_id=request_id
            ) from None
