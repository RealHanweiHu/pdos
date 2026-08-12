"""The two frozen HTTP protocol shapes supported by the PDOS model gateway."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
class ProviderResponse:
    content: str
    input_tokens: int
    output_tokens: int
    request_id: str | None
    model_version: str | None
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


class ProviderRequestError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _token_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError
    return value


class OpenAICompatibleAdapter:
    def __init__(self, client: httpx2.Client, egress_policy: ProviderEgressPolicy) -> None:
        self._client = client
        self._egress_policy = egress_policy

    def complete(
        self,
        route: ResolvedModelRoute,
        messages: Sequence[ChatMessage],
    ) -> ProviderResponse:
        if route.protocol is not ProtocolKind.OPENAI_COMPATIBLE:
            raise ProviderRequestError("provider_protocol_mismatch", "provider protocol mismatch")
        target_url = f"{route.base_url}/chat/completions"
        self._assert_egress(route, target_url)
        response = self._post(
            target_url,
            headers={
                "Authorization": f"Bearer {route.api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
            json={
                "model": route.model,
                "messages": [message.model_dump(mode="json") for message in messages],
                "temperature": 0,
            },
        )
        try:
            body = response.json()
            if not isinstance(body, Mapping):
                raise ValueError
            choices = body["choices"]
            if not isinstance(choices, list) or not choices:
                raise ValueError
            choice = choices[0]
            if not isinstance(choice, Mapping):
                raise ValueError
            message = choice["message"]
            if not isinstance(message, Mapping):
                raise ValueError
            usage = body["usage"]
            if not isinstance(usage, Mapping):
                raise ValueError
            details = usage.get("prompt_tokens_details", {})
            if not isinstance(details, Mapping):
                raise ValueError
            return ProviderResponse(
                content=_text(message["content"]),
                input_tokens=_token_count(usage["prompt_tokens"]),
                output_tokens=_token_count(usage["completion_tokens"]),
                request_id=response.headers.get("x-request-id") or _optional_text(body.get("id")),
                model_version=_optional_text(body.get("model")),
                cache_read_tokens=_optional_token_count(details.get("cached_tokens")),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ProviderRequestError(
                "provider_invalid_response",
                "provider returned an invalid response",
            ) from error

    def _post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
    ) -> httpx2.Response:
        try:
            response = self._client.post(url, headers=headers, json=json, timeout=30.0)
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


class AnthropicNativeAdapter:
    def __init__(self, client: httpx2.Client, egress_policy: ProviderEgressPolicy) -> None:
        self._client = client
        self._egress_policy = egress_policy

    def complete(
        self,
        route: ResolvedModelRoute,
        messages: Sequence[ChatMessage],
    ) -> ProviderResponse:
        if route.protocol is not ProtocolKind.ANTHROPIC_NATIVE:
            raise ProviderRequestError("provider_protocol_mismatch", "provider protocol mismatch")
        system = "\n\n".join(message.content for message in messages if message.role == "system")
        provider_messages = [
            message.model_dump(mode="json") for message in messages if message.role != "system"
        ]
        payload: dict[str, object] = {
            "model": route.model,
            "messages": provider_messages,
            "max_tokens": 4096,
            "temperature": 0,
        }
        if system:
            payload["system"] = system
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
        try:
            body = response.json()
            if not isinstance(body, Mapping):
                raise ValueError
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
            usage = body["usage"]
            if not isinstance(usage, Mapping):
                raise ValueError
            return ProviderResponse(
                content="\n".join(text_blocks),
                input_tokens=_token_count(usage["input_tokens"]),
                output_tokens=_token_count(usage["output_tokens"]),
                request_id=_optional_text(body.get("id")),
                model_version=_optional_text(body.get("model")),
                cache_read_tokens=_optional_token_count(usage.get("cache_read_input_tokens")),
                cache_creation_tokens=_optional_token_count(
                    usage.get("cache_creation_input_tokens")
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ProviderRequestError(
                "provider_invalid_response",
                "provider returned an invalid response",
            ) from error

    def _post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
    ) -> httpx2.Response:
        try:
            response = self._client.post(url, headers=headers, json=json, timeout=30.0)
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
) -> dict[ProtocolKind, OpenAICompatibleAdapter | AnthropicNativeAdapter]:
    policy = ProviderEgressPolicy.from_catalog(catalog)
    return {
        ProtocolKind.OPENAI_COMPATIBLE: OpenAICompatibleAdapter(client, policy),
        ProtocolKind.ANTHROPIC_NATIVE: AnthropicNativeAdapter(client, policy),
    }
