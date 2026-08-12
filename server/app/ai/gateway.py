"""Tenant-routed structured model gateway with budget circuit and immutable traces."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Engine

from app.ai.context_projection import project_gateway_context
from app.ai.model_catalog import (
    AgentTier,
    GoldenQualification,
    ModelCatalog,
    ProtocolKind,
    ProviderName,
    ResolvedModelRoute,
)
from app.ai.provider_adapters import ChatMessage, ProviderRequestError, ProviderResponse
from app.db.schema import tables
from app.domain.model_governance import ModelGovernanceService


class GatewayInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    tenant_id: UUID
    project_id: UUID | None
    run_id: UUID | None
    agent_key: str = Field(min_length=1, max_length=64)
    agent_tier: AgentTier = AgentTier.DEFAULT
    prompt_version: str = Field(min_length=1, max_length=128)
    system_prompt: str = Field(min_length=1, max_length=200_000)
    instruction: str = Field(min_length=1, max_length=200_000)
    context: dict[str, object]


@dataclass(frozen=True)
class ProviderRateCard:
    input_microusd_per_million_tokens: int
    output_microusd_per_million_tokens: int

    def __post_init__(self) -> None:
        if (
            self.input_microusd_per_million_tokens < 0
            or self.output_microusd_per_million_tokens < 0
        ):
            raise ValueError("provider rates must be nonnegative")

    def cost(self, *, input_tokens: int, output_tokens: int) -> int:
        numerator = (
            input_tokens * self.input_microusd_per_million_tokens
            + output_tokens * self.output_microusd_per_million_tokens
        )
        return (numerator + 999_999) // 1_000_000 if numerator else 0


@dataclass(frozen=True)
class GatewayResult[OutputT: BaseModel]:
    status: Literal["succeeded", "degraded"]
    output: OutputT | None
    error_code: str | None
    structured_attempts: int
    removed_context_paths: tuple[str, ...]


class ModelProviderAdapter(Protocol):
    def complete(
        self,
        route: ResolvedModelRoute,
        messages: Sequence[ChatMessage],
    ) -> ProviderResponse: ...


class StructuredModelGateway:
    def __init__(
        self,
        engine: Engine,
        *,
        catalog: ModelCatalog,
        qualifications: list[GoldenQualification],
        governance: ModelGovernanceService,
        adapters: Mapping[ProtocolKind, ModelProviderAdapter],
        rate_cards: Mapping[ProviderName, ProviderRateCard],
        max_structured_attempts: int = 2,
    ) -> None:
        if not 1 <= max_structured_attempts <= 3:
            raise ValueError("structured attempt budget must be between 1 and 3")
        self._engine = engine
        self._catalog = catalog
        self._qualifications = qualifications
        self._governance = governance
        self._adapters = adapters
        self._rate_cards = rate_cards
        self._max_structured_attempts = max_structured_attempts

    def invoke_structured[OutputT: BaseModel](
        self,
        invocation: GatewayInvocation,
        output_type: type[OutputT],
    ) -> GatewayResult[OutputT]:
        projection = project_gateway_context(invocation.context)
        snapshot = self._governance.get(tenant_id=invocation.tenant_id)
        selection = snapshot.selection
        if selection is None or not selection.available:
            return GatewayResult(
                status="degraded",
                output=None,
                error_code="MODEL_NOT_AVAILABLE",
                structured_attempts=0,
                removed_context_paths=projection.removed_paths,
            )
        route = self._catalog.resolve_route(
            provider=selection.provider,
            model=selection.model,
            agent_tier=invocation.agent_tier,
            qualifications=self._qualifications,
        )
        if snapshot.budget.exhausted:
            self._record(
                invocation,
                route=route,
                status="budget_exceeded",
                input_tokens=0,
                output_tokens=0,
                latency_ms=0,
                structured_attempts=0,
                error_code="DAILY_BUDGET_EXCEEDED",
            )
            return GatewayResult(
                status="degraded",
                output=None,
                error_code="DAILY_BUDGET_EXCEEDED",
                structured_attempts=0,
                removed_context_paths=projection.removed_paths,
            )

        adapter = self._adapters.get(route.protocol)
        if adapter is None:
            raise RuntimeError("configured model protocol has no adapter")

        input_tokens = 0
        output_tokens = 0
        cache_read_tokens = 0
        cache_creation_tokens = 0
        last_response: ProviderResponse | None = None
        schema_json = json.dumps(
            output_type.model_json_schema(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        context_json = json.dumps(
            projection.payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        started_at = perf_counter()
        for attempt in range(1, self._max_structured_attempts + 1):
            messages = structured_messages(
                system_prompt=invocation.system_prompt,
                instruction=invocation.instruction,
                context_json=context_json,
                schema_json=schema_json,
                retry=attempt > 1,
            )
            try:
                response = adapter.complete(route, messages)
            except ProviderRequestError as error:
                error_code = error.code.upper()
                self._record(
                    invocation,
                    route=route,
                    status="provider_error",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_tokens=cache_read_tokens,
                    cache_creation_tokens=cache_creation_tokens,
                    latency_ms=self._elapsed_ms(started_at),
                    structured_attempts=attempt,
                    error_code=error_code,
                )
                return GatewayResult(
                    status="degraded",
                    output=None,
                    error_code=error_code,
                    structured_attempts=attempt,
                    removed_context_paths=projection.removed_paths,
                )
            last_response = response
            input_tokens += response.input_tokens
            output_tokens += response.output_tokens
            cache_read_tokens += response.cache_read_tokens
            cache_creation_tokens += response.cache_creation_tokens
            try:
                output = output_type.model_validate_json(json_document(response.content))
            except ValidationError:
                continue

            self._record(
                invocation,
                route=route,
                status="succeeded",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_creation_tokens=cache_creation_tokens,
                latency_ms=self._elapsed_ms(started_at),
                structured_attempts=attempt,
                request_id=response.request_id,
                model_version=response.model_version,
            )
            return GatewayResult(
                status="succeeded",
                output=output,
                error_code=None,
                structured_attempts=attempt,
                removed_context_paths=projection.removed_paths,
            )

        self._record(
            invocation,
            route=route,
            status="schema_error",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
            latency_ms=self._elapsed_ms(started_at),
            structured_attempts=self._max_structured_attempts,
            error_code="STRUCTURED_OUTPUT_INVALID",
            request_id=last_response.request_id if last_response is not None else None,
            model_version=last_response.model_version if last_response is not None else None,
        )
        return GatewayResult(
            status="degraded",
            output=None,
            error_code="STRUCTURED_OUTPUT_INVALID",
            structured_attempts=self._max_structured_attempts,
            removed_context_paths=projection.removed_paths,
        )

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return max(0, int((perf_counter() - started_at) * 1000))

    def _record(
        self,
        invocation: GatewayInvocation,
        *,
        route: ResolvedModelRoute,
        status: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
        latency_ms: int,
        structured_attempts: int,
        error_code: str | None = None,
        request_id: str | None = None,
        model_version: str | None = None,
    ) -> None:
        rate_card = self._rate_cards.get(route.provider, ProviderRateCard(0, 0))
        with self._engine.begin() as connection:
            connection.execute(
                tables.model_invocations.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": invocation.tenant_id,
                    "project_id": invocation.project_id,
                    "run_id": invocation.run_id,
                    "request_id": request_id,
                    "agent_key": invocation.agent_key,
                    "agent_tier": invocation.agent_tier.value,
                    "prompt_version": invocation.prompt_version,
                    "provider": route.provider.value,
                    "model": route.model,
                    "model_version": model_version,
                    "protocol": route.protocol.value,
                    "status": status,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                    "cache_read_tokens": cache_read_tokens,
                    "cache_creation_tokens": cache_creation_tokens,
                    "latency_ms": latency_ms,
                    "normalized_cost_microusd": rate_card.cost(
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    ),
                    "structured_attempts": structured_attempts,
                    "error_code": error_code,
                },
            )


def structured_messages(
    *,
    system_prompt: str,
    instruction: str,
    context_json: str,
    schema_json: str,
    retry: bool,
) -> list[ChatMessage]:
    retry_instruction = (
        "\nThe previous response failed schema validation. Correct the format; "
        "do not add commentary."
        if retry
        else ""
    )
    return [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(
            role="user",
            content=(
                f"{instruction}{retry_instruction}\n\n"
                f"OUTPUT_JSON_SCHEMA\n{schema_json}\n\n"
                f"PDOS_CONTEXT_JSON\n{context_json}"
            ),
        ),
    ]


def json_document(content: str) -> str:
    document = content.strip()
    if not document.startswith("```"):
        return document
    lines = document.splitlines()
    if len(lines) < 3 or lines[-1].strip() != "```":
        return document
    return "\n".join(lines[1:-1]).strip()
