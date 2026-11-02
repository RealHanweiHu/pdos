"""Immutable HTTP route and normalized usage, extracted from the existing adapter rules."""

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import SecretStr

ProtocolKind = Literal["openai-compatible", "anthropic-native"]
OpenAIResponseMode = Literal["auto", "tools", "json_schema", "json_object", "text"]


def output_limit_upper_bound(base_url, model):
    if urlsplit(base_url).hostname in {"api.minimax.cn", "api.minimax.io"} and model in {
        "MiniMax-M3", "MiniMax-M3.1-Flash",
    }:
        return 524288
    return 32768


@dataclass(frozen=True)
class ProviderRoute:
    protocol: ProtocolKind
    base_url: str
    model: str
    api_key: SecretStr = field(repr=False)
    version: str
    max_output_tokens: int = 2048
    openai_output_parameter: Literal["max_tokens", "max_completion_tokens"] = (
        "max_completion_tokens"
    )
    timeout_seconds: float = 30.0
    response_bytes: int = 1_048_576
    configuration_digest: str | None = None
    budget_policy: Literal["enforced", "development_unlimited"] = "enforced"
    openai_response_mode: OpenAIResponseMode = "auto"
    streaming: bool = True
    connection_id: UUID | None = None
    context_window_tokens: int | None = None

    def __post_init__(self):
        if self.protocol not in {"openai-compatible", "anthropic-native"}:
            raise ValueError("Unsupported model protocol")
        if not isinstance(self.api_key, SecretStr) or not self.api_key.get_secret_value():
            raise ValueError("A server-injected model credential is required")
        if any(ord(c) <= 32 for c in self.api_key.get_secret_value()):
            raise ValueError("Invalid server-injected credential")
        if any(not isinstance(v, str) or not v.strip() for v in (self.model, self.version)):
            raise ValueError("A configured model and version are required")
        if len(self.model) > 200 or len(self.version) > 200:
            raise ValueError("Model configuration exceeds its bound")
        if type(self.max_output_tokens) is not int or not (
            1 <= self.max_output_tokens <= output_limit_upper_bound(self.base_url, self.model)
        ):
            raise ValueError("Invalid model output limit")
        if self.context_window_tokens is not None and (
            type(self.context_window_tokens) is not int
            or not 1024 <= self.context_window_tokens <= 10_000_000
        ):
            raise ValueError("Invalid context window")
        if self.budget_policy not in {"enforced", "development_unlimited"} or (
            self.budget_policy == "development_unlimited"
            and urlsplit(self.base_url).hostname not in {"api.minimax.cn", "api.minimax.io"}
        ):
            raise ValueError("Invalid development budget policy")
        if self.openai_output_parameter not in {"max_tokens", "max_completion_tokens"}:
            raise ValueError("An explicit supported output parameter is required")
        if self.openai_response_mode not in {"auto", "tools", "json_schema", "json_object", "text"}:
            raise ValueError("Unsupported OpenAI response mode")
        if self.protocol != "openai-compatible" and self.openai_response_mode != "auto":
            raise ValueError("OpenAI response mode requires the OpenAI compatible protocol")
        if type(self.streaming) is not bool:
            raise ValueError("An explicit streaming flag is required")
        if self.connection_id is not None and not isinstance(self.connection_id, UUID):
            raise ValueError("Invalid server connection selection")
        if type(self.timeout_seconds) not in {int, float} or not 1 <= self.timeout_seconds <= 90:
            raise ValueError("Invalid provider timeout")
        if type(self.response_bytes) is not int or not 1024 <= self.response_bytes <= 2_097_152:
            raise ValueError("Invalid provider response bound")
        if self.configuration_digest is not None and not re.fullmatch(
            r"[a-f0-9]{64}", self.configuration_digest
        ):
            raise ValueError("Invalid server configuration binding")
        self.assert_target_allowed(self.target_url)

    @property
    def target_url(self) -> str:
        endpoint = "chat/completions" if self.protocol == "openai-compatible" else "messages"
        return f"{self.base_url.rstrip('/')}/{endpoint}"

    @property
    def token_count_url(self) -> str:
        if self.protocol != "anthropic-native":
            raise ValueError("Token counting requires the configured Anthropic route")
        return f"{self.base_url.rstrip('/')}/messages/count_tokens"

    @property
    def agent_response_codec(self):
        from .agent_wire import response_codec

        return response_codec(self.protocol, self.base_url, self.openai_response_mode)

    @property
    def digest(self) -> str:
        """Public route binding excludes credentials; version covers server configuration."""
        body = dict(
            protocol=self.protocol,
            base_url=self.base_url,
            model=self.model,
            version=self.version,
            max_output_tokens=self.max_output_tokens,
            openai_output_parameter=self.openai_output_parameter,
            timeout_seconds=self.timeout_seconds,
            response_bytes=self.response_bytes,
        )
        if self.configuration_digest is not None:
            body["configuration_digest"] = self.configuration_digest
        if self.context_window_tokens is not None:
            body["context_window_tokens"] = self.context_window_tokens
        # Preserve existing route bindings when the new options retain their defaults.
        if self.openai_response_mode != "auto":
            body["openai_response_mode"] = self.openai_response_mode
        if not self.streaming:
            body["streaming"] = False
        if self.connection_id is not None:
            body["connection_id"] = str(self.connection_id)
        if self.budget_policy != "enforced":
            body["budget_policy"] = self.budget_policy
        if self.agent_response_codec != "native-schema/v1":
            body["agent_response_codec"] = self.agent_response_codec
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()

    def assert_target_allowed(self, target: str):
        """Exact server endpoint policy, distinct from permission to send business material."""
        try:
            base = urlsplit(self.base_url)
            parsed = urlsplit(target)
            _ = base.port, parsed.port
        except (ValueError, TypeError):
            raise ValueError("Invalid configured provider endpoint") from None
        if (
            base.scheme not in {"https", "http"}
            or not base.hostname
            or not re.fullmatch(r"[A-Za-z0-9.:-]+", base.hostname)
            or base.username is not None
            or base.password is not None
            or base.query
            or base.fragment
            or any(ord(c) <= 32 for c in self.base_url)
            or not re.fullmatch(r"[A-Za-z0-9_./-]*", base.path)
            or any(part in {".", ".."} for part in base.path.split("/"))
            or (base.scheme == "http" and base.hostname not in {"localhost", "127.0.0.1", "::1"})
            or target not in ({self.target_url, self.token_count_url}
                              if self.protocol == "anthropic-native" else {self.target_url})
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Provider endpoint is outside the configured boundary")


@dataclass(frozen=True)
class ProviderUsage:
    """input_tokens includes cache tokens; cache fields are breakdowns, not additions."""

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    def __post_init__(self):
        values = (
            self.input_tokens,
            self.output_tokens,
            self.cache_read_tokens,
            self.cache_creation_tokens,
        )
        if any(type(v) is not int or v < 0 for v in values):
            raise ValueError("Invalid provider usage")
        if self.cache_read_tokens + self.cache_creation_tokens > self.input_tokens:
            raise ValueError("Invalid cache usage breakdown")


@dataclass(frozen=True)
class ProviderTokenCount:
    """Provider preflight count; never generation usage or an estimator calibration."""

    input_tokens: int
    request_id: str | None = None

    def __post_init__(self):
        if type(self.input_tokens) is not int or self.input_tokens < 0:
            raise ValueError("Invalid provider token count")


@dataclass(frozen=True)
class ProviderResponse:
    content: str
    usage: ProviderUsage
    request_id: str | None = None
    model_version: str | None = None


class ProviderError(Exception):
    def __init__(
        self,
        code: str,
        *,
        unknown: bool = False,
        usage: ProviderUsage | None = None,
        request_id: str | None = None,
    ):
        self.code, self.unknown = code, unknown
        self.usage, self.request_id = usage, request_id
        super().__init__(code)
