"""Execute a bounded provider attempt only after a durable unique dispatch grant.

This service receives trusted scope, profile, and separately qualified metering.
It does not infer model qualification, grant authorization, or perform retries.
Default application/Agent factories must not adopt it until their scope, legacy
accounting, metering evidence, and restricted-role service ports are connected.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID, uuid5

import httpx2

from app.ai.budget_evidence import BudgetRequestBinding, BudgetUsageEvidence
from app.ai.budget_ledger import BudgetLedgerError, BudgetReceipt
from app.ai.egress import ProviderEgressPolicy
from app.ai.model_catalog import GoldenQualification, ProtocolKind, ProviderName, ResolvedModelRoute
from app.ai.provider_adapters import (
    ChatMessage,
    ProviderCallLimits,
    ProviderRequestError,
    ProviderResponse,
    ProviderUsage,
)
from app.contracts.runtime_policy import RunBudgetProfile


class ModelBudgetPort(Protocol):
    def open_lineage(self, *, tenant_id: UUID, run_id: UUID, profile: RunBudgetProfile) -> UUID: ...

    def require_active(self, *, tenant_id: UUID, run_id: UUID) -> None: ...

    def reserve(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID,
        attempt_id: UUID,
        call_kind: Literal["model", "tool"],
        input_tokens: int,
        output_tokens: int,
        tenant_daily_token_limit: int,
        request_binding: BudgetRequestBinding | None = None,
    ) -> BudgetReceipt: ...

    def transition(
        self,
        *,
        tenant_id: UUID,
        attempt_id: UUID,
        action: Literal["dispatch", "unknown", "cancel", "settle"],
        charged_tokens: int | None = None,
        reconciliation_ref: str | None = None,
        provider_request_id: str | None = None,
        usage_evidence: BudgetUsageEvidence | None = None,
    ) -> BudgetReceipt: ...


class InputTokenMeter(Protocol):
    def count(self, route: ResolvedModelRoute, messages: Sequence[ChatMessage]) -> int:
        """Count the full wire prompt, including protocol framing, without a model call."""
        ...


@runtime_checkable
class CurrentInputTokenMeter(Protocol):
    def ensure_current(self, route: ResolvedModelRoute) -> None: ...


class BoundedProvider(Protocol):
    def complete_bounded(
        self,
        route: ResolvedModelRoute,
        messages: Sequence[ChatMessage],
        *,
        limits: ProviderCallLimits,
    ) -> ProviderResponse: ...


@dataclass(frozen=True)
class QualifiedModelMeter:
    protocol: ProtocolKind
    window_tokens: int
    output_token_limit: int
    output_parameter: str
    qualification_ref: str
    meter_version: str
    meter: InputTokenMeter

    def __post_init__(self) -> None:
        if type(self.window_tokens) is not int or self.window_tokens <= 0:
            raise ValueError("qualified model window required")
        if (
            type(self.output_token_limit) is not int
            or not 0 < self.output_token_limit <= self.window_tokens
        ):
            raise ValueError("qualified model output limit required")
        if not self.qualification_ref.strip() or not self.meter_version.strip():
            raise ValueError("qualified metering provenance required")
        if self.output_parameter not in {"max_tokens", "max_completion_tokens"} or (
            self.protocol is ProtocolKind.ANTHROPIC_NATIVE and self.output_parameter != "max_tokens"
        ):
            raise ValueError("qualified output parameter required")


def evidence_digest(payload: dict[str, object]) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


class ModelBudgetController:
    def __init__(
        self,
        ledger: ModelBudgetPort,
        *,
        profile: RunBudgetProfile,
        meters: Mapping[tuple[ProviderName, str], QualifiedModelMeter],
    ) -> None:
        self._ledger = ledger
        self._profile = profile
        self._meters = dict(meters)

    @property
    def profile(self) -> RunBudgetProfile:
        return self._profile

    @classmethod
    def from_publication(
        cls,
        ledger: ModelBudgetPort,
        *,
        profile: RunBudgetProfile,
        path: Path,
        expected_sha256: str,
        qualifications: Sequence[GoldenQualification],
        client: httpx2.Client,
        egress_policy: ProviderEgressPolicy,
    ) -> ModelBudgetController:
        from app.ai.input_metering import load_published_meters

        return cls(
            ledger,
            profile=profile,
            meters=load_published_meters(
                path,
                expected_sha256=expected_sha256,
                qualifications=qualifications,
                client=client,
                egress_policy=egress_policy,
            ),
        )

    def complete(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID | None,
        model_call_id: UUID | None,
        structured_attempt: int,
        daily_token_limit: int,
        route: ResolvedModelRoute,
        messages: Sequence[ChatMessage],
        adapter: BoundedProvider,
        before_dispatch: Callable[[UUID, BudgetRequestBinding], None] | None = None,
        before_measurement: Callable[[], None] | None = None,
    ) -> ProviderResponse:
        if run_id is None or model_call_id is None:
            raise BudgetLedgerError("BUDGET_CALL_IDENTITY_REQUIRED")
        qualified = self._meters.get((route.provider, route.model))
        if qualified is None or qualified.protocol is not route.protocol:
            raise BudgetLedgerError("BUDGET_MODEL_METER_UNQUALIFIED")
        if before_measurement is not None:
            before_measurement()
        try:
            input_limit = self._profile.effective_input_limit(qualified.window_tokens)
            tokens = qualified.meter.count(route, messages)
        except Exception as error:
            raise BudgetLedgerError("BUDGET_INPUT_METER_UNAVAILABLE") from error
        if type(tokens) is not int or tokens < 0:
            raise BudgetLedgerError("BUDGET_INPUT_METER_INVALID")
        if tokens > input_limit:
            raise BudgetLedgerError("BUDGET_CONTEXT_WINDOW_EXCEEDED")
        limits = ProviderCallLimits(
            min(self._profile.output_token_reserve, qualified.output_token_limit),
            qualified.output_parameter,  # type: ignore[arg-type]
        )
        # Hash actual structured messages, including schema and retry suffix;
        # credentials and source text are never written into this budget journal.
        request_digest = evidence_digest(
            {
                "provider": route.provider.value,
                "model": route.model,
                "protocol": route.protocol.value,
                "base_url": route.base_url,
                "messages": [message.model_dump(mode="json") for message in messages],
                "output_parameter": qualified.output_parameter,
                "output_limit": limits.max_output_tokens,
            }
        )
        binding = BudgetRequestBinding(
            model_call_id=model_call_id,
            structured_attempt=structured_attempt,
            request_digest=request_digest,
            provider=route.provider,
            model=route.model,
            protocol=route.protocol,
            qualification_ref=qualified.qualification_ref,
            meter_version=qualified.meter_version,
            qualified_window=qualified.window_tokens,
            qualified_output_limit=qualified.output_token_limit,
            output_parameter=qualified.output_parameter,  # type: ignore[arg-type]
            output_limit=limits.max_output_tokens,
        )
        attempt_id = uuid5(model_call_id, f"model-budget-attempt:{structured_attempt}")
        self._ledger.open_lineage(tenant_id=tenant_id, run_id=run_id, profile=self._profile)
        reservation = self._ledger.reserve(
            tenant_id=tenant_id,
            run_id=run_id,
            attempt_id=attempt_id,
            call_kind="model",
            input_tokens=tokens,
            output_tokens=limits.max_output_tokens,
            tenant_daily_token_limit=daily_token_limit,
            request_binding=binding,
        )
        # Only revision 1 is an undispatched reservation. A completed or in-flight
        # replay must not try to create a new pre-dispatch context manifest.
        if (
            reservation.revision > 1
            and reservation.entry.reservation_status != "cancelled_before_dispatch"
        ):
            raise BudgetLedgerError("BUDGET_ATTEMPT_ALREADY_DISPATCHED")
        try:
            if isinstance(qualified.meter, CurrentInputTokenMeter):
                try:
                    qualified.meter.ensure_current(route)
                except Exception as error:
                    raise BudgetLedgerError("BUDGET_MODEL_METER_UNQUALIFIED") from error
            if before_dispatch is not None:
                before_dispatch(attempt_id, binding)
            grant = self._ledger.transition(
                tenant_id=tenant_id, attempt_id=attempt_id, action="dispatch"
            )
        except BudgetLedgerError:
            # A concurrent grant can make cancellation invalid; its hold stays.
            with suppress(BudgetLedgerError):
                self._ledger.transition(tenant_id=tenant_id, attempt_id=attempt_id, action="cancel")
            raise
        if not grant.dispatch_granted:
            raise BudgetLedgerError("BUDGET_ATTEMPT_ALREADY_DISPATCHED")
        try:
            response = adapter.complete_bounded(route, messages, limits=limits)
        except ProviderRequestError as error:
            if error.usage is None:
                self._unknown(tenant_id, attempt_id)
            else:
                self._settle(
                    tenant_id,
                    attempt_id,
                    BudgetUsageEvidence(
                        request_digest=request_digest,
                        input_tokens=error.usage.input_tokens,
                        output_tokens=error.usage.output_tokens,
                        cache_read_tokens=error.usage.cache_read_tokens,
                        cache_creation_tokens=error.usage.cache_creation_tokens,
                        request_id=error.request_id,
                        error_code=error.code,
                    ),
                )
            raise
        except BaseException:
            # The transport may have sent bytes. Cancellation, SDK exceptions,
            # and process interruption must not release its reservation.
            self._unknown(tenant_id, attempt_id)
            raise
        exceeded = (
            "provider_output_limit_exceeded"
            if response.output_tokens > limits.max_output_tokens
            else "provider_input_limit_exceeded"
            if response.input_tokens > input_limit
            else None
        )
        self._settle(
            tenant_id,
            attempt_id,
            BudgetUsageEvidence(
                request_digest=request_digest,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                cache_read_tokens=response.cache_read_tokens,
                cache_creation_tokens=response.cache_creation_tokens,
                request_id=response.request_id,
                model_version=response.model_version,
                error_code=exceeded,
            ),
        )
        if exceeded is not None:
            raise ProviderRequestError(
                exceeded,
                "provider usage exceeded the admitted limit",
                usage=ProviderUsage(
                    response.input_tokens,
                    response.output_tokens,
                    response.cache_read_tokens,
                    response.cache_creation_tokens,
                ),
                request_id=response.request_id,
            )
        try:
            self._ledger.require_active(tenant_id=tenant_id, run_id=run_id)
        except BudgetLedgerError as error:
            # Settlement has committed. Preserve known usage while withholding
            # an output returned after cumulative execution time was exhausted.
            raise ProviderRequestError(
                error.code,
                "run active execution budget no longer permits output",
                usage=ProviderUsage(
                    response.input_tokens,
                    response.output_tokens,
                    response.cache_read_tokens,
                    response.cache_creation_tokens,
                ),
                request_id=response.request_id,
            ) from error
        return response

    def _unknown(self, tenant: UUID, attempt: UUID) -> None:
        try:
            self._ledger.transition(tenant_id=tenant, attempt_id=attempt, action="unknown")
        except BudgetLedgerError as error:
            raise ProviderRequestError(
                "budget_receipt_failed", "dispatched budget remains held"
            ) from error

    def _settle(self, tenant: UUID, attempt: UUID, evidence: BudgetUsageEvidence) -> None:
        try:
            self._ledger.transition(
                tenant_id=tenant,
                attempt_id=attempt,
                action="settle",
                charged_tokens=evidence.input_tokens + evidence.output_tokens,
                reconciliation_ref=evidence.evidence_ref,
                provider_request_id=evidence.request_id,
                usage_evidence=evidence,
            )
        except BudgetLedgerError as error:
            # This failure happened after transport, never report it as zero calls.
            raise ProviderRequestError(
                "budget_receipt_failed",
                "dispatched budget remains held",
                usage=ProviderUsage(
                    evidence.input_tokens,
                    evidence.output_tokens,
                    evidence.cache_read_tokens,
                    evidence.cache_creation_tokens,
                ),
                request_id=evidence.request_id,
            ) from error
