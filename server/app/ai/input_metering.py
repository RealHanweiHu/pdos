"""Pinned, operator-published input metering; no automatic model qualification.

Local JSON tokenizers never load remote Python. Publication requires an external
manifest digest, matching golden qualification, and protocol-specific evidence.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

import httpx2
from jinja2 import StrictUndefined
from jinja2.sandbox import ImmutableSandboxedEnvironment
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from tokenizers import Tokenizer

from app.ai.egress import ProviderEgressPolicy
from app.ai.model_budget import InputTokenMeter, QualifiedModelMeter
from app.ai.model_catalog import GoldenQualification, ProtocolKind, ProviderName, ResolvedModelRoute
from app.ai.provider_adapters import ChatMessage, anthropic_input_payload

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Count = Annotated[int, Field(strict=True, ge=0)]
Label = Annotated[str, Field(min_length=1, max_length=256, pattern=r"\S")]


class MeteringError(ValueError):
    """No message body, credential, or arbitrary provider error is exposed."""


class Document(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MeterAsset(Document):
    path: str = Field(min_length=1, max_length=256)
    sha256: Digest


class MeterCase(Document):
    key: Label
    category: Literal["short_text", "unicode", "structured_schema", "near_input_limit"]
    messages: tuple[ChatMessage, ...] = Field(min_length=1, max_length=64)
    counted_input_tokens: Count
    observed_input_tokens: Count
    provider_request_id: Label
    observed_at: AwareDatetime


class MeterEvidence(Document):
    schema_version: Literal[1]
    qualification_key: Label
    cases: tuple[MeterCase, ...] = Field(min_length=4, max_length=128)

    @model_validator(mode="after")
    def coverage(self) -> Self:
        if {c.category for c in self.cases} != {
            "short_text",
            "unicode",
            "structured_schema",
            "near_input_limit",
        } or any(
            len(values) != len(self.cases)
            for values in (
                {c.key for c in self.cases},
                {c.provider_request_id for c in self.cases},
            )
        ):
            raise ValueError("meter evidence coverage or identities invalid")
        return self


class MeterPublication(Document):
    key: Label
    provider: ProviderName
    model: Label
    protocol: ProtocolKind
    base_url: str = Field(min_length=1, max_length=512)
    implementation: Literal["hf_text_template.v1", "anthropic_count_tokens.v1"]
    window_tokens: int = Field(strict=True, gt=0)
    output_token_limit: int = Field(strict=True, gt=0)
    max_qualified_input_tokens: int = Field(strict=True, gt=0)
    output_parameter: Literal["max_tokens", "max_completion_tokens"]
    input_margin_tokens: Count
    input_margin_percent: int = Field(strict=True, ge=0, le=100)
    source_ref: Label
    reviewed_by: Label
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    tokenizer: MeterAsset | None = None
    chat_template: MeterAsset | None = None
    tokenizer_config: MeterAsset | None = None
    evidence: MeterAsset

    @model_validator(mode="after")
    def compatible(self) -> Self:
        endpoint = urlsplit(self.base_url)
        if (
            endpoint.scheme not in {"http", "https"}
            or not endpoint.hostname
            or endpoint.username
            or endpoint.password
            or endpoint.query
            or endpoint.fragment
            or self.base_url.endswith("/")
            or self.valid_until <= self.valid_from
            or self.output_token_limit + self.max_qualified_input_tokens > self.window_tokens
        ):
            raise ValueError("invalid metering publication")
        local = self.implementation == "hf_text_template.v1"
        assets = (self.tokenizer, self.chat_template, self.tokenizer_config)
        if local and (self.protocol is not ProtocolKind.OPENAI_COMPATIBLE or not all(assets)):
            raise ValueError("local tokenizer requires compatible text protocol and pinned assets")
        if not local and (
            any(assets)
            or self.provider is not ProviderName.ANTHROPIC
            or self.protocol is not ProtocolKind.ANTHROPIC_NATIVE
            or self.output_parameter != "max_tokens"
        ):
            raise ValueError("native token counting qualification invalid")
        return self

    def admitted_count(self, raw: int) -> int:
        return raw + self.input_margin_tokens + (raw * self.input_margin_percent + 99) // 100


class MeterPublicationSet(Document):
    schema_version: Literal[1]
    golden_suite_version: Label
    golden_suite_digest: Label
    models: tuple[MeterPublication, ...] = Field(max_length=64)

    @model_validator(mode="after")
    def unique(self) -> Self:
        keys = [(p.provider, p.model) for p in self.models]
        if len(keys) != len(set(keys)) or len({p.key for p in self.models}) != len(keys):
            raise ValueError("duplicate metering qualification")
        return self


def _read(path: Path, digest: str, limit: int) -> bytes:
    with path.open("rb") as file:
        body = file.read(limit + 1)
    if len(body) > limit or sha256(body).hexdigest() != digest:
        raise MeteringError("meter asset integrity failed")
    return body


def _asset(root: Path, ref: MeterAsset, limit: int) -> bytes:
    relative = Path(ref.path)
    path = (root / relative).resolve()
    if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(root.resolve()):
        raise MeteringError("meter asset path invalid")
    return _read(path, ref.sha256, limit)


class LocalTemplateMeter:
    """Text-only pinned tokenizer and immutable sandboxed chat template."""

    def __init__(self, tokenizer: bytes, template: bytes, config: bytes):
        self._tokenizer = Tokenizer.from_str(tokenizer.decode("utf-8"))
        # A tokenizer export may contain deployment padding/truncation. Counting
        # must see the entire prompt, without automatic special tokens twice.
        self._tokenizer.no_truncation()
        self._tokenizer.no_padding()
        environment = ImmutableSandboxedEnvironment(
            trim_blocks=True, lstrip_blocks=True, undefined=StrictUndefined
        )

        def reject(message: str) -> None:
            del message
            raise MeteringError("unsupported chat message shape")

        environment.globals["raise_exception"] = reject
        environment.filters["tojson"] = lambda value, **kwargs: json.dumps(value, **kwargs)
        self._template = environment.from_string(template.decode("utf-8"))
        configuration = json.loads(config)
        self._special_tokens = {}
        for key in (
            "bos_token",
            "eos_token",
            "unk_token",
            "pad_token",
            "sep_token",
            "cls_token",
            "mask_token",
        ):
            value = configuration.get(key)
            if isinstance(value, dict):
                value = value.get("content")
            if isinstance(value, str):
                self._special_tokens[key] = value

    def count(self, route: ResolvedModelRoute, messages: Sequence[ChatMessage]) -> int:
        if route.protocol is not ProtocolKind.OPENAI_COMPATIBLE:
            raise MeteringError("meter protocol mismatch")
        if not messages or len(messages) > 64:
            raise MeteringError("meter message count invalid")
        rendered = self._template.render(
            messages=[m.model_dump(mode="json") for m in messages],
            add_generation_prompt=True,
            tools=None,
            documents=None,
            **self._special_tokens,
        )
        if len(rendered) > 16_000_000:
            raise MeteringError("meter rendered input too large")
        return len(self._tokenizer.encode(rendered, add_special_tokens=False).ids)


class AnthropicInputMeter:
    def __init__(self, client: httpx2.Client, policy: ProviderEgressPolicy):
        self._client, self._policy = client, policy

    def count(self, route: ResolvedModelRoute, messages: Sequence[ChatMessage]) -> int:
        if (
            route.provider is not ProviderName.ANTHROPIC
            or route.protocol is not ProtocolKind.ANTHROPIC_NATIVE
        ):
            raise MeteringError("meter protocol mismatch")
        url = f"{route.base_url}/v1/messages/count_tokens"
        self._policy.assert_request_allowed(route, url)
        try:
            with self._client.stream(
                "POST",
                url,
                json=anthropic_input_payload(route, messages),
                headers={
                    "x-api-key": route.api_key.get_secret_value(),
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                timeout=10,
                follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise MeteringError("meter response unavailable")
                body = bytearray()
                for chunk in response.iter_bytes(chunk_size=8192):
                    if len(body) + len(chunk) > 64_000:
                        raise MeteringError("meter response too large")
                    body.extend(chunk)
                count = json.loads(body)["input_tokens"]
            if type(count) is not int or count < 0:
                raise MeteringError("meter count invalid")
            return count
        except (httpx2.HTTPError, ValueError, KeyError, TypeError) as error:
            raise MeteringError("meter count unavailable") from error


class PublishedInputMeter:
    def __init__(
        self,
        implementation: InputTokenMeter,
        publication: MeterPublication,
        path: Path,
        digest: str,
        clock: Callable[[], datetime],
    ):
        self._implementation, self._publication = implementation, publication
        self._path, self._digest, self._clock = path, digest, clock

    def ensure_current(self, route: ResolvedModelRoute) -> None:
        p = self._publication
        _read(self._path, self._digest, 2_000_000)
        if not p.valid_from <= self._clock() < p.valid_until:
            raise MeteringError("meter qualification expired or not effective")
        if (route.provider, route.model, route.protocol, route.base_url) != (
            p.provider,
            p.model,
            p.protocol,
            p.base_url,
        ):
            raise MeteringError("meter qualified route mismatch")

    def count(self, route: ResolvedModelRoute, messages: Sequence[ChatMessage]) -> int:
        self.ensure_current(route)
        count = self._publication.admitted_count(self._implementation.count(route, messages))
        self.ensure_current(route)
        if count > self._publication.max_qualified_input_tokens:
            raise MeteringError("input exceeds qualified metering coverage")
        return count


def load_published_meters(
    path: Path,
    *,
    expected_sha256: str,
    qualifications: Sequence[GoldenQualification],
    client: httpx2.Client,
    egress_policy: ProviderEgressPolicy,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[tuple[ProviderName, str], QualifiedModelMeter]:
    """Read only. The expected digest comes from trusted deployment configuration."""
    try:
        document = MeterPublicationSet.model_validate_json(_read(path, expected_sha256, 2_000_000))
        passed = {
            (q.provider, q.model)
            for q in qualifications
            if q.status == "passed"
            and q.suite_version == document.golden_suite_version
            and q.suite_digest == document.golden_suite_digest
        }
        result = {}
        for p in document.models:
            if (p.provider, p.model) not in passed or not p.valid_from <= clock() < p.valid_until:
                raise MeteringError("meter lacks effective matching golden qualification")
            evidence = MeterEvidence.model_validate_json(_asset(path.parent, p.evidence, 8_000_000))
            if evidence.qualification_key != p.key:
                raise MeteringError("meter evidence identity mismatch")
            raw: InputTokenMeter
            if p.implementation == "hf_text_template.v1":
                assert p.tokenizer and p.chat_template and p.tokenizer_config
                raw = LocalTemplateMeter(
                    _asset(path.parent, p.tokenizer, 64_000_000),
                    _asset(path.parent, p.chat_template, 256_000),
                    _asset(path.parent, p.tokenizer_config, 1_000_000),
                )
            else:
                raw = AnthropicInputMeter(client, egress_policy)
            from pydantic import SecretStr

            from app.ai.model_catalog import AgentTier

            sample_route = ResolvedModelRoute(
                provider=p.provider,
                model=p.model,
                protocol=p.protocol,
                base_url=p.base_url,
                api_key=SecretStr("unused"),
                agent_tier=AgentTier.DEFAULT,
            )
            target = (
                f"{p.base_url}/chat/completions"
                if p.protocol is ProtocolKind.OPENAI_COMPATIBLE
                else f"{p.base_url}/v1/messages/count_tokens"
            )
            egress_policy.assert_request_allowed(sample_route, target)
            if not any(
                case.category == "near_input_limit"
                and p.admitted_count(case.counted_input_tokens) * 5
                >= p.max_qualified_input_tokens * 4
                for case in evidence.cases
            ):
                raise MeteringError("meter evidence does not reach qualified input limit")
            for case in evidence.cases:
                if (
                    case.observed_at > p.valid_from
                    or not case.observed_input_tokens
                    <= p.admitted_count(case.counted_input_tokens)
                    <= p.max_qualified_input_tokens
                ):
                    raise MeteringError("meter evidence is future-dated or under-reserved")
                if (
                    isinstance(raw, LocalTemplateMeter)
                    and raw.count(sample_route, case.messages) != case.counted_input_tokens
                ):
                    raise MeteringError("meter evidence cannot be reproduced")
            result[(p.provider, p.model)] = QualifiedModelMeter(
                protocol=p.protocol,
                window_tokens=p.window_tokens,
                output_token_limit=p.output_token_limit,
                output_parameter=p.output_parameter,
                qualification_ref=f"meter-publication:sha256:{expected_sha256}:{p.key}",
                meter_version=p.implementation,
                meter=PublishedInputMeter(raw, p, path, expected_sha256, clock),
            )
        return result
    except Exception as error:
        raise MeteringError("published metering qualification is invalid") from error
