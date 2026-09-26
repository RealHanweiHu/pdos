"""The two frozen HTTP protocol shapes supported by the PDOS model gateway."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Literal

import httpx2
from pydantic import BaseModel, ConfigDict, Field

from app.ai.egress import EgressDeniedError, ProviderEgressPolicy
from app.ai.model_catalog import ModelCatalog, ProtocolKind, ResolvedModelRoute


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=200_000)


@dataclass(frozen=True)
class ProviderUsage:
    """Normalized input includes cache tokens; cache fields remain breakdowns."""

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    def __post_init__(self) -> None:
        for value in asdict(self).values():
            _token_count(value)


@dataclass(frozen=True)
class ProviderCallLimits:
    max_output_tokens: int
    openai_output_parameter: Literal["max_tokens", "max_completion_tokens"] | None = None

    def __post_init__(self) -> None:
        if type(self.max_output_tokens) is not int or self.max_output_tokens <= 0:
            raise ValueError("positive output token limit required")
        if self.openai_output_parameter not in {None, "max_tokens", "max_completion_tokens"}:
            raise ValueError("unsupported output token parameter")


@dataclass(frozen=True)
class ProviderResponse:
    content: str
    input_tokens: int
    output_tokens: int
    request_id: str | None
    model_version: str | None
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


class ProviderRequestError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        usage: ProviderUsage | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.usage = usage
        self.request_id = request_id


def _token_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError
    return value


def _usage(value: object, protocol: ProtocolKind) -> ProviderUsage:
    if not isinstance(value, Mapping):
        raise ValueError("provider usage required")
    if protocol is ProtocolKind.OPENAI_COMPATIBLE:
        inputs = _token_count(value["prompt_tokens"])
        details = value.get("prompt_tokens_details", {})
        if not isinstance(details, Mapping):
            raise ValueError("invalid cache usage")
        reads = _optional_token_count(details.get("cached_tokens"))
        if reads > inputs:
            raise ValueError("cached tokens exceed total prompt tokens")
        return ProviderUsage(inputs, _token_count(value["completion_tokens"]), reads)
    reads = _optional_token_count(value.get("cache_read_input_tokens"))
    writes = _optional_token_count(value.get("cache_creation_input_tokens"))
    return ProviderUsage(
        _token_count(value["input_tokens"]) + reads + writes,
        _token_count(value["output_tokens"]),
        reads,
        writes,
    )


class OpenAICompatibleAdapter:
    def __init__(
        self,
        client: httpx2.Client,
        egress_policy: ProviderEgressPolicy,
        *,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        if not 1 <= request_timeout_seconds <= 90:
            raise ValueError("provider timeout must be between 1 and 90 seconds")
        self._request_timeout = request_timeout_seconds
        self._client = client
        self._egress_policy = egress_policy

    def complete(
        self,
        route: ResolvedModelRoute,
        messages: Sequence[ChatMessage],
    ) -> ProviderResponse:
        return self._complete(route, messages, limits=None)

    def complete_bounded(
        self,
        route: ResolvedModelRoute,
        messages: Sequence[ChatMessage],
        *,
        limits: ProviderCallLimits,
    ) -> ProviderResponse:
        return self._complete(route, messages, limits=limits)

    def _complete(
        self,
        route: ResolvedModelRoute,
        messages: Sequence[ChatMessage],
        *,
        limits: ProviderCallLimits | None,
    ) -> ProviderResponse:
        if route.protocol is not ProtocolKind.OPENAI_COMPATIBLE:
            raise ProviderRequestError("provider_protocol_mismatch", "provider protocol mismatch")
        payload: dict[str, object] = {
            "model": route.model,
            "messages": [message.model_dump(mode="json") for message in messages],
            "temperature": 0,
        }
        if limits is not None:
            if limits.openai_output_parameter is None:
                raise ProviderRequestError(
                    "provider_output_limit_unconfigured", "output parameter is not configured"
                )
            payload[limits.openai_output_parameter] = limits.max_output_tokens
        target_url = f"{route.base_url}/chat/completions"
        self._assert_egress(route, target_url)
        response = self._post(
            target_url,
            headers={
                "Authorization": f"Bearer {route.api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        usage: ProviderUsage | None = None
        request_id = response.headers.get("x-request-id")
        try:
            body = response.json()
            if not isinstance(body, Mapping):
                raise ValueError
            request_id = request_id or _optional_text(body.get("id"))
            usage = _usage(body["usage"], route.protocol)
            choices = body["choices"]
            if not isinstance(choices, list) or not choices:
                raise ValueError
            choice = choices[0]
            if not isinstance(choice, Mapping):
                raise ValueError
            if choice.get("finish_reason") == "length":
                raise ProviderRequestError(
                    "provider_output_truncated",
                    "provider output reached its limit",
                    usage=usage,
                    request_id=request_id,
                )
            message = choice["message"]
            if not isinstance(message, Mapping):
                raise ValueError
            return ProviderResponse(
                content=_text(message["content"]),
                request_id=request_id,
                model_version=_optional_text(body.get("model")),
                **asdict(usage),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ProviderRequestError(
                "provider_invalid_response",
                "provider returned an invalid response",
                usage=usage,
                request_id=request_id,
            ) from error

    def _post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
    ) -> httpx2.Response:
        try:
            response = self._client.post(
                url, headers=headers, json=json, timeout=self._request_timeout
            )
        except httpx2.HTTPError as error:
            raise ProviderRequestError(
                "provider_transport_error",
                "provider request failed",
            ) from error
        if not 200 <= response.status_code < 300:
            raise ProviderRequestError(
                f"provider_http_{response.status_code}",
                "provider request failed",
            )
        return response

    def _assert_egress(self, route: ResolvedModelRoute, target_url: str) -> None:
        try:
            self._egress_policy.assert_request_allowed(route, target_url)
        except EgressDeniedError as error:
            raise ProviderRequestError(
                "provider_egress_denied", "provider egress denied"
            ) from error


def anthropic_input_payload(
    route: ResolvedModelRoute, messages: Sequence[ChatMessage]
) -> dict[str, object]:
    """The exact text input shared by generation and the input counting endpoint."""
    system = "\n\n".join(message.content for message in messages if message.role == "system")
    payload: dict[str, object] = {
        "model": route.model,
        "messages": [
            message.model_dump(mode="json") for message in messages if message.role != "system"
        ],
    }
    if system:
        payload["system"] = system
    return payload


class AnthropicNativeAdapter:
    def __init__(
        self,
        client: httpx2.Client,
        egress_policy: ProviderEgressPolicy,
        *,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        if not 1 <= request_timeout_seconds <= 90:
            raise ValueError("provider timeout must be between 1 and 90 seconds")
        self._request_timeout = request_timeout_seconds
        self._client = client
        self._egress_policy = egress_policy

    def complete(
        self,
        route: ResolvedModelRoute,
        messages: Sequence[ChatMessage],
    ) -> ProviderResponse:
        return self._complete(route, messages, limits=None)

    def complete_bounded(
        self,
        route: ResolvedModelRoute,
        messages: Sequence[ChatMessage],
        *,
        limits: ProviderCallLimits,
    ) -> ProviderResponse:
        return self._complete(route, messages, limits=limits)

    def _complete(
        self,
        route: ResolvedModelRoute,
        messages: Sequence[ChatMessage],
        *,
        limits: ProviderCallLimits | None,
    ) -> ProviderResponse:
        if route.protocol is not ProtocolKind.ANTHROPIC_NATIVE:
            raise ProviderRequestError("provider_protocol_mismatch", "provider protocol mismatch")
        if limits is not None and limits.openai_output_parameter not in {None, "max_tokens"}:
            raise ProviderRequestError(
                "provider_output_limit_unconfigured", "native output parameter mismatch"
            )
        payload = anthropic_input_payload(route, messages)
        payload.update(
            max_tokens=limits.max_output_tokens if limits is not None else 4096, temperature=0
        )
        target_url = f"{route.base_url}/v1/messages"
        self._assert_egress(route, target_url)
        response = self._post(
            target_url,
            headers={
                "x-api-key": route.api_key.get_secret_value(),
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        usage: ProviderUsage | None = None
        request_id: str | None = None
        try:
            body = response.json()
            if not isinstance(body, Mapping):
                raise ValueError
            request_id = _optional_text(body.get("id"))
            usage = _usage(body["usage"], route.protocol)
            if body.get("stop_reason") == "max_tokens":
                raise ProviderRequestError(
                    "provider_output_truncated",
                    "provider output reached its limit",
                    usage=usage,
                    request_id=request_id,
                )
            blocks = body["content"]
            if not isinstance(blocks, list) or not blocks:
                raise ValueError
            text_blocks = [
                _text(block["text"])
                for block in blocks
                if isinstance(block, Mapping) and block.get("type") == "text"
            ]
            if not text_blocks:
                raise ValueError
            return ProviderResponse(
                content="\n".join(text_blocks),
                request_id=request_id,
                model_version=_optional_text(body.get("model")),
                **asdict(usage),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ProviderRequestError(
                "provider_invalid_response",
                "provider returned an invalid response",
                usage=usage,
                request_id=request_id,
            ) from error

    def _post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
    ) -> httpx2.Response:
        try:
            response = self._client.post(
                url, headers=headers, json=json, timeout=self._request_timeout
            )
        except httpx2.HTTPError as error:
            raise ProviderRequestError(
                "provider_transport_error",
                "provider request failed",
            ) from error
        if not 200 <= response.status_code < 300:
            raise ProviderRequestError(
                f"provider_http_{response.status_code}",
                "provider request failed",
            )
        return response

    def _assert_egress(self, route: ResolvedModelRoute, target_url: str) -> None:
        try:
            self._egress_policy.assert_request_allowed(route, target_url)
        except EgressDeniedError as error:
            raise ProviderRequestError(
                "provider_egress_denied", "provider egress denied"
            ) from error


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_token_count(value: object) -> int:
    return 0 if value is None else _token_count(value)


def configured_provider_adapters(
    catalog: ModelCatalog,
    client: httpx2.Client,
    *,
    request_timeout_seconds: float = 30.0,
) -> dict[ProtocolKind, OpenAICompatibleAdapter | AnthropicNativeAdapter]:
    policy = ProviderEgressPolicy.from_catalog(catalog)
    return {
        ProtocolKind.OPENAI_COMPATIBLE: OpenAICompatibleAdapter(
            client, policy, request_timeout_seconds=request_timeout_seconds
        ),
        ProtocolKind.ANTHROPIC_NATIVE: AnthropicNativeAdapter(
            client, policy, request_timeout_seconds=request_timeout_seconds
        ),
    }
