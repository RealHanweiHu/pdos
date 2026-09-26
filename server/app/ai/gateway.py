"""Tenant-routed structured model gateway with budget circuit and immutable traces."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import asdict, dataclass, replace
from time import perf_counter
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Engine

from app.ai.budget_evidence import BudgetRequestBinding
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.context_projection import ContextProjection, project_gateway_context
from app.ai.model_budget import ModelBudgetController
from app.ai.model_call_fence import ModelCallFence, ModelCallFenceError
from app.ai.model_catalog import (
    AgentTier,
    GoldenQualification,
    ModelCatalog,
    ProtocolKind,
    ProviderName,
    ResolvedModelRoute,
)
from app.ai.observations import AgentObservationError, AgentObservations, context_receipt_body
from app.ai.provider_adapters import (
    ChatMessage,
    ProviderCallLimits,
    ProviderRequestError,
    ProviderResponse,
)
from app.ai.run_store import AgentRunStore
from app.contracts.runtime_policy import RunBudgetProfile
from app.db.schema import tables
from app.domain.model_governance import ModelGovernanceService


class GatewayInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    tenant_id: UUID
    project_id: UUID | None
    run_id: UUID | None
    model_call_id: UUID | None = None
    context_receipt_id: UUID | None = None
    expected_provider: ProviderName | None = None
    expected_model: str | None = None
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
    model: str | None = None
    version: str | None = None
    source: str | None = None

    def __post_init__(self) -> None:
        if any(
            type(rate) is not int or rate < 0
            for rate in (
                self.input_microusd_per_million_tokens,
                self.output_microusd_per_million_tokens,
            )
        ):
            raise ValueError("provider rates must be nonnegative")
        for value in (self.model, self.version, self.source):
            if value is not None and not value.strip():
                raise ValueError("rate provenance must be nonblank when provided")

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
    invocation_id: UUID | None = None


class ModelProviderAdapter(Protocol):
    def complete(
        self,
        route: ResolvedModelRoute,
        messages: Sequence[ChatMessage],
    ) -> ProviderResponse: ...


@runtime_checkable
class BoundedModelProviderAdapter(Protocol):
    def complete_bounded(
        self,
        route: ResolvedModelRoute,
        messages: Sequence[ChatMessage],
        *,
        limits: ProviderCallLimits,
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
        run_store: AgentRunStore | None = None,
        call_limits: Mapping[tuple[ProviderName, str], ProviderCallLimits] | None = None,
        budget_controller: ModelBudgetController | None = None,
        application_lease_keeper: object | None = None,
    ) -> None:
        if not 1 <= max_structured_attempts <= 3:
            raise ValueError("structured attempt budget must be between 1 and 3")
        if budget_controller is not None and call_limits is not None:
            raise ValueError("budget controller owns provider call limits")
        self._engine = engine
        self._catalog = catalog
        self._qualifications = qualifications
        self._governance = governance
        self._adapters = adapters
        self._rate_cards = dict(rate_cards)
        self._max_structured_attempts = max_structured_attempts
        self._run_store = run_store
        # Trusted service configuration. An explicit map opts into bounded calls;
        # an absent model or unsupported adapter must never fall back to legacy.
        self._call_limits = dict(call_limits) if call_limits is not None else None
        self._budget_controller = budget_controller
        self.application_lease_keeper = application_lease_keeper
        self._call_fence = ModelCallFence(engine, run_store)
        self._active_call: ContextVar[UUID | None] = ContextVar("model_call_session", default=None)

    @property
    def creation_budget_profile(self) -> RunBudgetProfile | None:
        return self._budget_controller.profile if self._budget_controller is not None else None

    def require_current_daily_budget(self, tenant_id: UUID) -> None:
        """Admission preview for explicit continuation; dispatch still reserves atomically."""
        if self._governance.get(tenant_id=tenant_id).budget.exhausted:
            raise BudgetLedgerError("DAILY_BUDGET_EXCEEDED")

    def invoke_structured[OutputT: BaseModel](
        self,
        invocation: GatewayInvocation,
        output_type: type[OutputT],
    ) -> GatewayResult[OutputT]:
        projection = project_gateway_context(invocation.context)
        if self._budget_controller is not None and (
            self._run_store is None or not self._run_store.projection_only
        ):
            try:
                verifier = self._source_verifier(invocation, output_type)
                if verifier is not None:
                    verifier()
            except BudgetLedgerError as error:
                return GatewayResult(
                    status="degraded",
                    output=None,
                    error_code=error.code,
                    structured_attempts=0,
                    removed_context_paths=projection.removed_paths,
                )
        if invocation.context_receipt_id is not None:
            if self._run_store is None or not self._run_store.projection_only:
                raise AgentObservationError("AGENT_CONTEXT_RECEIPT_LEASE_REQUIRED")
            AgentObservations(self._engine, self._run_store).verify(
                invocation.context_receipt_id,
                invocation.model_call_id,
                context_receipt_body(
                    context=invocation.context,
                    prompt_version=invocation.prompt_version,
                    system_prompt=invocation.system_prompt,
                    instruction=invocation.instruction,
                    output_type=output_type,
                ),
            )
        snapshot = self._governance.get(tenant_id=invocation.tenant_id)
        selection = snapshot.selection
        if invocation.expected_provider is not None and (
            selection is None
            or selection.provider != invocation.expected_provider
            or selection.model != invocation.expected_model
        ):
            raise AgentObservationError("AGENT_LOOP_MODEL_BINDING_CHANGED")
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
        if self._budget_controller is not None and not self._call_fence.restricted:
            from app.ai.application_checkpoints import load

            try:
                checkpoint = load(self._engine, self, invocation, output_type, route=route)
                if checkpoint is not None:
                    verifier = self._source_verifier(invocation, output_type)
                    if verifier is not None:
                        verifier()
                    return checkpoint
            except BudgetLedgerError as error:
                return GatewayResult(
                    status="degraded",
                    output=None,
                    error_code=error.code,
                    structured_attempts=0,
                    removed_context_paths=projection.removed_paths,
                )
        if snapshot.budget.exhausted:
            invocation_id = self._record(
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
                invocation_id=invocation_id,
            )

        adapter = self._adapters.get(route.protocol)
        if adapter is None:
            raise RuntimeError("configured model protocol has no adapter")

        limits = None
        if self._call_limits is not None:
            limits = self._call_limits.get((route.provider, route.model))
            valid_parameter = limits is not None and (
                limits.openai_output_parameter is not None
                if route.protocol is ProtocolKind.OPENAI_COMPATIBLE
                else limits.openai_output_parameter in {None, "max_tokens"}
            )
            if not valid_parameter or not isinstance(adapter, BoundedModelProviderAdapter):
                error_code = "PROVIDER_OUTPUT_LIMIT_UNCONFIGURED"
                invocation_id = self._record(
                    invocation,
                    route=route,
                    status="provider_error",
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=0,
                    structured_attempts=0,
                    error_code=error_code,
                )
                return GatewayResult(
                    status="degraded",
                    output=None,
                    error_code=error_code,
                    structured_attempts=0,
                    removed_context_paths=projection.removed_paths,
                    invocation_id=invocation_id,
                )

        try:
            session_id = self._call_fence.begin(
                tenant_id=invocation.tenant_id,
                run_id=invocation.run_id,
                project_id=invocation.project_id,
                agent_key=invocation.agent_key,
                budgeted=self._budget_controller is not None,
            )
        except ModelCallFenceError as error:
            invocation_id = self._record(
                invocation,
                route=route,
                status="budget_exceeded",
                input_tokens=0,
                output_tokens=0,
                latency_ms=0,
                structured_attempts=0,
                error_code=error.code,
            )
            return GatewayResult(
                status="degraded",
                output=None,
                error_code=error.code,
                structured_attempts=0,
                removed_context_paths=projection.removed_paths,
                invocation_id=invocation_id,
            )
        token = self._active_call.set(session_id)
        try:
            result = self._invoke_ready(
                invocation,
                output_type,
                route=route,
                adapter=adapter,
                limits=limits,
                projection=projection,
                daily_token_limit=snapshot.budget.daily_token_budget,
            )
            assert result.invocation_id is not None
            from app.ai.application_checkpoints import save

            application = self._budget_controller is not None and not self._call_fence.restricted
            try:
                self._call_fence.finish(
                    tenant_id=invocation.tenant_id,
                    session_id=session_id,
                    invocation_id=result.invocation_id,
                    before_commit=(lambda c: save(c, self, invocation, result))
                    if application
                    else None,
                )
            except BudgetLedgerError as error:
                # A known provider receipt remains chargeable even if ownership
                # expires before persistence. Do not store or disclose the output.
                self._call_fence.finish(
                    tenant_id=invocation.tenant_id,
                    session_id=session_id,
                    invocation_id=result.invocation_id,
                )
                result = replace(result, status="degraded", output=None, error_code=error.code)
            return result
        except BaseException:
            # Preserve the original interruption or persistence failure. A failed
            # recovery write leaves the original durable open record in place.
            with suppress(Exception):
                self._call_fence.unknown(tenant_id=invocation.tenant_id, session_id=session_id)
            raise
        finally:
            self._active_call.reset(token)

    def _invoke_ready[OutputT: BaseModel](
        self,
        invocation: GatewayInvocation,
        output_type: type[OutputT],
        *,
        route: ResolvedModelRoute,
        adapter: ModelProviderAdapter,
        limits: ProviderCallLimits | None,
        projection: ContextProjection,
        daily_token_limit: int,
    ) -> GatewayResult[OutputT]:
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
                if self._budget_controller is not None:
                    if not isinstance(adapter, BoundedModelProviderAdapter):
                        raise BudgetLedgerError("BUDGET_BOUNDED_ADAPTER_REQUIRED")
                    response = self._budget_controller.complete(
                        tenant_id=invocation.tenant_id,
                        run_id=invocation.run_id,
                        model_call_id=invocation.model_call_id,
                        structured_attempt=attempt,
                        daily_token_limit=daily_token_limit,
                        route=route,
                        messages=messages,
                        adapter=adapter,
                        before_dispatch=self._manifest_recorder(invocation, route, projection),
                        before_measurement=self._source_verifier(invocation),
                    )
                elif limits is not None:
                    assert isinstance(adapter, BoundedModelProviderAdapter)
                    response = adapter.complete_bounded(route, messages, limits=limits)
                else:
                    response = adapter.complete(route, messages)
            except BudgetLedgerError as error:
                invocation_id = self._record(
                    invocation,
                    route=route,
                    status="budget_exceeded",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_tokens=cache_read_tokens,
                    cache_creation_tokens=cache_creation_tokens,
                    latency_ms=self._elapsed_ms(started_at),
                    structured_attempts=attempt - 1,
                    error_code=error.code,
                )
                return GatewayResult(
                    status="degraded",
                    output=None,
                    error_code=error.code,
                    structured_attempts=attempt - 1,
                    removed_context_paths=projection.removed_paths,
                    invocation_id=invocation_id,
                )
            except ProviderRequestError as error:
                if error.usage is not None:
                    input_tokens += error.usage.input_tokens
                    output_tokens += error.usage.output_tokens
                    cache_read_tokens += error.usage.cache_read_tokens
                    cache_creation_tokens += error.usage.cache_creation_tokens
                error_code = error.code.upper()
                invocation_id = self._record(
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
                    request_id=error.request_id,
                    usage_complete=error.usage is not None,
                )
                return GatewayResult(
                    status="degraded",
                    output=None,
                    error_code=error_code,
                    structured_attempts=attempt,
                    removed_context_paths=projection.removed_paths,
                    invocation_id=invocation_id,
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

            invocation_id = self._record(
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
            if self._budget_controller is not None and (
                self._run_store is None or not self._run_store.projection_only
            ):
                try:
                    verifier = self._source_verifier(invocation)
                    if verifier is not None:
                        verifier()
                except BudgetLedgerError as error:
                    return GatewayResult(
                        status="degraded",
                        output=None,
                        error_code=error.code,
                        structured_attempts=attempt,
                        removed_context_paths=projection.removed_paths,
                        invocation_id=invocation_id,
                    )
            return GatewayResult(
                status="succeeded",
                output=output,
                error_code=None,
                structured_attempts=attempt,
                removed_context_paths=projection.removed_paths,
                invocation_id=invocation_id,
            )

        invocation_id = self._record(
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
            invocation_id=invocation_id,
        )

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return max(0, int((perf_counter() - started_at) * 1000))

    def _source_verifier(
        self, invocation: GatewayInvocation, output_type: type[BaseModel] | None = None
    ) -> Callable[[], None] | None:
        if self._run_store is None or not self._run_store.projection_only:
            from app.ai.application_authorization import verify_application_authorization

            def verify_application() -> None:
                from app.ai.application_context import verify_chat_context

                verify_application_authorization(
                    self._engine,
                    tenant_id=invocation.tenant_id,
                    run_id=invocation.run_id,
                    project_id=invocation.project_id,
                    agent_key=invocation.agent_key,
                )
                verify_chat_context(self._engine, invocation, output_type)
                from app.ai.application_leases import verify

                verify(self._engine, self, invocation.tenant_id, invocation.run_id)

            return verify_application
        if (
            invocation.context_receipt_id is None
            or self._run_store is None
            or not self._run_store.projection_only
        ):
            return None
        run_store = self._run_store
        receipt_id = invocation.context_receipt_id

        def verify() -> None:
            from app.ai.context_manifests import bind_bundle

            port = AgentObservations(self._engine, run_store)
            try:
                bind_bundle(port, invocation.agent_key, loop="loop" in invocation.context)
                port._call(
                    "SELECT cehub_ai.verify_agent_context_sources(:receipt)", receipt=receipt_id
                )
            except AgentObservationError as error:
                raise BudgetLedgerError(error.code) from error

        return verify

    def _manifest_recorder(
        self,
        invocation: GatewayInvocation,
        route: ResolvedModelRoute,
        projection: ContextProjection,
    ) -> Callable[[UUID, BudgetRequestBinding], None] | None:
        if self._run_store is None or not self._run_store.projection_only:
            verifier = self._source_verifier(invocation)

            def record_application(attempt_id: UUID, binding: BudgetRequestBinding) -> None:
                from app.ai.application_context import freeze_chat_manifest

                if verifier is not None:
                    verifier()
                qualifications = sorted(
                    (
                        q
                        for q in self._qualifications
                        if q.provider == route.provider
                        and q.model == route.model
                        and q.status == "passed"
                    ),
                    key=lambda q: q.model_dump_json(),
                )
                if not qualifications:
                    raise BudgetLedgerError("BUDGET_MODEL_QUALIFICATION_UNAVAILABLE")
                freeze_chat_manifest(
                    self._engine,
                    invocation,
                    attempt_id=attempt_id,
                    qualification=qualifications[0].model_dump(mode="json"),
                    removed_paths=projection.removed_paths,
                    gateway=self,
                )

            return record_application
        if invocation.context_receipt_id is None or self._run_store is None:
            return None
        if not self._run_store.projection_only:
            return None

        run_store = self._run_store
        receipt_id = invocation.context_receipt_id

        def record(attempt_id: UUID, binding: BudgetRequestBinding) -> None:
            from app.ai.context_manifests import bind_bundle, freeze_manifest

            port = AgentObservations(self._engine, run_store)
            try:
                bundle = bind_bundle(port, invocation.agent_key, loop="loop" in invocation.context)
                if bundle is None:
                    return
                qualifications = sorted(
                    (
                        q
                        for q in self._qualifications
                        if q.provider == route.provider
                        and q.model == route.model
                        and q.status == "passed"
                    ),
                    key=lambda q: q.model_dump_json(),
                )
                if not qualifications:
                    raise BudgetLedgerError("BUDGET_MODEL_QUALIFICATION_UNAVAILABLE")
                freeze_manifest(
                    port,
                    receipt_id=receipt_id,
                    attempt_id=attempt_id,
                    qualification=qualifications[0].model_dump(mode="json"),
                    removed_paths=projection.removed_paths,
                )
            except AgentObservationError as error:
                raise BudgetLedgerError(error.code) from error

        return record

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
        usage_complete: bool = True,
    ) -> UUID:
        rate_card = self._rate_cards.get(route.provider)
        cost_status = "unknown"
        cost: int | None = None
        rate_snapshot: dict[str, object] | None = None
        if structured_attempts == 0:
            # A server-side rejection made no provider request; this is a known zero.
            cost_status, cost = "not_invoked", 0
        elif (
            status != "provider_error"
            and rate_card is not None
            and rate_card.model == route.model
            and rate_card.version is not None
            and rate_card.source is not None
            and cache_read_tokens == 0
            and cache_creation_tokens == 0
        ):
            # Cache pricing differs by protocol. Until a card defines those meters,
            # preserve the usage but do not pretend the ordinary rate covers them.
            cost_status = "priced"
            cost = rate_card.cost(input_tokens=input_tokens, output_tokens=output_tokens)
            rate_snapshot = {
                **asdict(rate_card),
                "provider": route.provider.value,
                "currency": "USD",
                "rate_unit": "microusd_per_million_tokens",
                "calculation": "aggregate_then_ceil.v1",
            }
        invocation_id = uuid4()
        with self._engine.begin() as connection:
            if self._run_store is not None and self._run_store.projection_only:
                self._run_store.bind(connection)
            connection.execute(
                tables.model_invocations.insert(),
                {
                    "id": invocation_id,
                    "tenant_id": invocation.tenant_id,
                    "project_id": invocation.project_id,
                    "run_id": invocation.run_id,
                    "budget_call_id": (
                        invocation.model_call_id
                        if self._budget_controller is not None and invocation.run_id is not None
                        else None
                    ),
                    "model_call_session_id": self._active_call.get(),
                    "context_receipt_id": invocation.context_receipt_id,
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
                    "usage_status": (
                        "not_invoked"
                        if structured_attempts == 0
                        else "known"
                        if usage_complete
                        else "partial"
                        if input_tokens + output_tokens
                        else "unknown"
                    ),
                    "input_meter_version": "normalized_input.v1",
                    "cache_read_tokens": cache_read_tokens,
                    "cache_creation_tokens": cache_creation_tokens,
                    "latency_ms": latency_ms,
                    "normalized_cost_microusd": cost,
                    "cost_status": cost_status,
                    "rate_card_snapshot": rate_snapshot,
                    "structured_attempts": structured_attempts,
                    "error_code": error_code,
                },
            )
        return invocation_id


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
    if document.startswith("<think>"):
        closing_tag = "</think>"
        closing_index = document.find(closing_tag, len("<think>"))
        if closing_index != -1:
            document = document[closing_index + len(closing_tag) :].strip()
    if not document.startswith("```"):
        return document
    lines = document.splitlines()
    if len(lines) < 3 or lines[-1].strip() != "```":
        return document
    return "\n".join(lines[1:-1]).strip()
