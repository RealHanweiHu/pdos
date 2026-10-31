"""Run-accounted query embedding from an actual assistant.search READ.

The trusted host may opt a Run into an explicit profile. The production default
is no port, which preserves keyword search. No page/list endpoint uses this code.
"""

from dataclasses import asdict, dataclass, field
from types import SimpleNamespace
from uuid import UUID

from pdos_agent_runtime.graph import in_registered_agent_graph
from sqlalchemy import select

from pdos_next.agent_kernel import policy
from pdos_next.agent_kernel.models import AgentToolCall
from pdos_next.agent_kernel.pricing import CostUsage
from pdos_next.errors import DomainError
from pdos_next.model_configuration.ports import SecretBinding
from pdos_next.model_configuration.service import secret_digest
from pdos_next.providers.types import ProviderError, ProviderUsage
from pdos_next.service import digest

from .embedding_hybrid import hybrid_search
from .embedding_identity import canonical_provider
from .embedding_profiles import active, bound_secret
from .embedding_query_binding import (
    SNAPSHOT,
    TOOL,
    QueryProfile,
    bind,
    key,
    payload,
    source,
)
from .embedding_runtime import unit_vector, wire_bytes
from .embedding_schemas import EmbeddingResponse, bounded_inputs, validate_response


@dataclass(frozen=True)
class QueryPorts:
    backend: object = field(repr=False)
    profile_for: object = field(repr=False)  # Trusted host selector, never a model/HTTP parameter.
    scan_strategy: str = "exact"


@dataclass(frozen=True)
class QueryResult:
    profile: QueryProfile | None = None
    vector: tuple | None = field(default=None, repr=False)
    status: str = "keyword"

    def search(self, session, ctx, data, **filters):
        result = hybrid_search(
            session,
            ctx,
            data,
            profile_version_id=self.profile.profile_version_id if self.profile else None,
            vector=self.vector,
            strategy=self.profile.scan_strategy if self.profile else "exact",
            **filters,
        )
        if self.status not in {"keyword", "ready"}:
            return {**result, "semantic": {"status": "unavailable", "reason": self.status}}
        return result


class QueryEmbedding:
    def __init__(self, store, ports, *, source_guard):
        self.store, self.ports, self.source_guard = store, ports, source_guard

    def frozen_profile(self, session, scope, run):
        if SNAPSHOT in run.versions:
            value = run.versions[SNAPSHOT]
            if run.versions.get(SNAPSHOT + "_digest") != digest(value):
                raise DomainError("VERSION_CONFLICT", "固定 Embedding profile 已变化。")
            return QueryProfile.model_validate(value) if value is not None else None
        selected = self.ports.profile_for(scope)
        snapshot = None
        if selected is not None:
            try:
                profile, metadata = active(session, scope.tenant_id, UUID(str(selected)))
            except DomainError as error:
                if error.code != "SOURCE_UNAVAILABLE":
                    raise
            else:
                snapshot = QueryProfile(
                    profile_version_id=profile.id,
                    binding_digest=profile.binding_digest,
                    dimensions=metadata.dimensions,
                    scan_strategy=self.ports.scan_strategy,
                )
        value = snapshot.model_dump(mode="json") if snapshot else None
        run.versions = {**run.versions, SNAPSHOT: value, SNAPSHOT + "_digest": digest(value)}
        return snapshot

    def prepare(self, scope, parent_id, arguments):
        if not in_registered_agent_graph() or scope.isolation != "main":
            raise DomainError("FORBIDDEN_SCOPE", "Query embedding 只能继承主注册图的实际检索。")
        # Reuse the native cross-process composition fence without keeping an
        # RLS read transaction open over provider IO. A concurrent worker cannot
        # conservatively release the first worker's still-active reservation.
        with self.store.composition_lock(scope, key(scope.run_id, parent_id)):
            return self._prepare(scope, parent_id, arguments)

    def _prepare(self, scope, parent_id, arguments):
        cached = None
        with self.store.transaction(scope, lock=True) as (session, run):
            parent, query = source(session, scope, run, parent_id, arguments)
            frozen = self.frozen_profile(session, scope, run)
            if frozen is None:
                return QueryResult()
            binding = bind(parent, frozen, query, scope.cancel_epoch).model_dump(mode="json")
            call_key, call_payload = key(run.id, parent.id), payload(parent.id, frozen, query)
            previous = session.scalar(
                select(AgentToolCall).where(
                    AgentToolCall.run_id == run.id, AgentToolCall.call_key == call_key
                )
            )
            if previous is not None:
                if (
                    previous.tool != TOOL
                    or previous.execution_binding != binding
                    or previous.input_digest != digest([TOOL, call_payload])
                ):
                    raise DomainError(
                        "DUPLICATE_INTENT_CONFLICT", "原 Query embedding 已绑定不同输入。"
                    )
                if previous.state in {"unknown", "failed", "reconciled"}:
                    return QueryResult(frozen, status="query_outcome_or_usage_unknown")
            try:
                profile, metadata = active(session, scope.tenant_id, frozen.profile_version_id)
            except DomainError as error:
                if error.code != "SOURCE_UNAVAILABLE":
                    raise
                return QueryResult(frozen, status="profile_disabled_or_unavailable")
            if (
                profile.binding_digest != frozen.binding_digest
                or metadata.dimensions != frozen.dimensions
            ):
                raise DomainError("VERSION_CONFLICT", "固定 Embedding 空间已变化。")
            secret_snapshot = dict(profile.secret_json)
            if previous is not None and previous.state == "completed":
                cached = self.saved(frozen, previous.result, binding)
        texts = bounded_inputs((query,))
        categories = frozenset(self.source_guard(scope))
        if cached is not None:
            return cached  # Current carried-source authority is rechecked even without outbound.
        # Profile categories select background index material. Query egress uses
        # the actual Run-carried union and P26, rather than substituting those
        # categories or imposing a second query permission policy.
        backend = self.ports.backend
        frozen_secret = SecretBinding(
            **{
                **secret_snapshot,
                "tenant_id": UUID(secret_snapshot["tenant_id"]),
                "reference": UUID(secret_snapshot["reference"]),
                "version": UUID(secret_snapshot["version"]),
            }
        )
        route = SimpleNamespace(model=metadata.model, version=metadata.model_version)
        try:
            secret = bound_secret(backend.secrets, scope.tenant_id, metadata, required=True)
            if secret_digest(secret) != secret_digest(frozen_secret):
                return QueryResult(frozen, status="query_configuration_changed")
            provider = canonical_provider(backend.secrets, scope.tenant_id, metadata)
            card = backend.pricing_for(scope.tenant_id, metadata)
            card.validate(provider, route)
        except Exception:  # noqa: BLE001 -- optional host configuration is unavailable, never free
            return QueryResult(frozen, status="query_configuration_unavailable")
        upper = card.input_upper_bound(wire_bytes(metadata, texts))
        reserve = card.reserve(upper, 0)
        with self.store.transaction(scope) as (session, _run):
            try:
                decision = policy.egress(
                    session, scope, provider, data_categories=categories
                )
            except DomainError as error:
                if error.detail.get("reason_key") == "provider_agreement_category":
                    return QueryResult(frozen, status="query_egress_not_permitted")
                raise
        try:
            call_id, saved = self.store.claim(
                scope,
                call_key,
                TOOL,
                call_payload,
                reservation=upper,
                cost_lease=(reserve, upper, 0, card.snapshot()),
                execution_binding=binding,
            )
        except DomainError as error:
            if error.code in {"EXTERNAL_OUTCOME_UNKNOWN", "RATE_LIMITED"}:
                # A crashed derived call is conservatively closed by the native
                # claim/release path. Keyword retrieval remains a usable result.
                return QueryResult(frozen, status="query_unavailable")
            raise
        if saved is not None:
            # claim races remain bound to the same key; ordinary replay above
            # normally handles this without needing current pricing or a key.
            return self.saved(frozen, saved, binding)
        sent, measured_cost = False, None
        try:
            self.store.current(scope)
            current_categories = frozenset(self.source_guard(scope))
            if current_categories != categories:
                raise DomainError("SOURCE_STALE", "查询发送前当前来源类别已变化。")
            with self.store.transaction(scope) as (session, run):
                source(session, scope, run, parent_id, arguments)
                latest, latest_metadata = active(
                    session, scope.tenant_id, frozen.profile_version_id
                )
                if latest.binding_digest != frozen.binding_digest or latest_metadata != metadata:
                    raise DomainError("VERSION_CONFLICT", "查询发送前 Embedding profile 已变化。")
                if canonical_provider(backend.secrets, scope.tenant_id, metadata) != provider:
                    raise DomainError("VERSION_CONFLICT", "查询发送前 Embedding 服务商已变化。")
                decision = policy.egress(
                    session, scope, provider, data_categories=current_categories
                )
            latest_secret = bound_secret(backend.secrets, scope.tenant_id, metadata, required=True)
            if secret_digest(latest_secret) != secret_digest(secret):
                raise DomainError("VERSION_CONFLICT", "查询发送前 Embedding 凭据已轮换。")
            latest_card = backend.pricing_for(scope.tenant_id, metadata)
            latest_card.validate(provider, route)
            if latest_card.snapshot() != card.snapshot():
                raise DomainError("VERSION_CONFLICT", "查询发送前 Embedding 价格已变化。")
            material = backend.secrets.resolve(secret)
            if material is None or material.binding != secret:
                raise DomainError("SOURCE_UNAVAILABLE", "独立 Embedding 凭据当前不可用。")
            self.store.emit(
                scope,
                {
                    "type": "egress_checked",
                    "purpose": "query_embedding",
                    "call_id": str(call_id),
                    **{
                        name: value.isoformat() if hasattr(value, "isoformat") else value
                        for name, value in asdict(decision).items()
                    },
                },
            )
            sent = True
            response = backend.client.embed(metadata, texts, material, timeout=30.0)
            try:
                validate_response(response, count=1, dimensions=metadata.dimensions)
            except (DomainError, TypeError, ValueError, AttributeError):
                measured = None
                if (
                    isinstance(response, EmbeddingResponse)
                    and type(response.input_tokens) is int
                    and response.input_tokens >= 0
                ):
                    measured = ProviderUsage(response.input_tokens, 0)
                raise ProviderError("PROVIDER_RESPONSE_INVALID", usage=measured) from None
            if response.input_tokens is None or response.input_tokens > upper:
                self.store.release_call(
                    scope,
                    call_id,
                    unknown=True,
                    error="EXTERNAL_OUTCOME_UNKNOWN",
                    request_id=response.request_id,
                )
                return QueryResult(frozen, status="query_usage_unknown")
            vector = unit_vector(response.vectors[0])
            cost = card.actual(ProviderUsage(response.input_tokens, 0))
            if cost > reserve:
                raise ProviderError("PROVIDER_USAGE_INVALID", unknown=True)
            measured_cost = CostUsage(response.input_tokens, 0, cost)
            self.store.current(scope)
            self.store.settle(
                scope,
                call_id,
                result={"vector": list(vector), "query_digest": binding["query_digest"]},
                usage=response.input_tokens,
                request_id=response.request_id,
                cost_usage=measured_cost,
            )
            self.store.current(scope)
            return QueryResult(frozen, vector, "ready")
        except DomainError as error:
            self.store.release_call(
                scope,
                call_id,
                unknown=sent and measured_cost is None,
                error=error.code,
                cost_usage=measured_cost,
                usage=measured_cost.input_tokens if measured_cost else 0,
            )
            raise
        except Exception as error:  # noqa: BLE001 -- redact provider/KMS bodies and credentials
            actual = self.error_cost(error, card, upper, reserve)
            self.store.release_call(
                scope,
                call_id,
                unknown=sent and actual is None,
                error="SOURCE_UNAVAILABLE",
                cost_usage=actual,
                usage=actual.input_tokens if actual else 0,
                request_id=error.request_id if isinstance(error, ProviderError) else None,
            )
            return QueryResult(frozen, status="query_unavailable")

    @staticmethod
    def saved(profile, saved, binding):
        try:
            if (
                not isinstance(saved, dict)
                or set(saved) != {"vector", "query_digest"}
                or saved["query_digest"] != binding["query_digest"]
            ):
                raise ValueError
            vector = tuple(saved["vector"])
            validate_response(EmbeddingResponse((vector,)), count=1, dimensions=profile.dimensions)
            if abs(sum(value * value for value in vector) - 1) > 1e-5:
                raise ValueError
        except (TypeError, ValueError, KeyError, ProviderError, DomainError):
            raise DomainError("VERSION_CONFLICT", "原 Query embedding 结果不匹配。") from None
        return QueryResult(profile, vector, "ready")

    @staticmethod
    def error_cost(error, card, upper, reserve):
        if not isinstance(error, ProviderError) or error.unknown:
            return None
        usage = error.usage
        if (
            not isinstance(usage, ProviderUsage)
            or usage.input_tokens > upper
            or usage.output_tokens != 0
        ):
            return None
        try:
            cost = card.actual(usage)
        except (ArithmeticError, TypeError, ValueError):
            return None
        return CostUsage(usage.input_tokens, 0, cost) if 0 <= cost <= reserve else None
