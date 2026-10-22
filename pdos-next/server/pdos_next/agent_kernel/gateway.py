"""Current DPA and durable budget before every registered-graph provider attempt."""

from dataclasses import asdict, replace

from pdos_agent_runtime.graph import in_registered_agent_graph

from pdos_next.errors import DomainError
from pdos_next.providers.agent_client import AgentProviderClient, request_body
from pdos_next.providers.types import ProviderError, ProviderUsage

from .bindings import ModelBinding
from .disclosure import CHAIN_KEY, record_disclosure
from .execution import validate_skill_load
from .policy import egress
from .pricing import CostUsage


class AgentGateway:
    def __init__(
        self,
        store,
        *,
        route_for,
        provider_for=None,
        rate_card_for=None,
        cost_required=True,
        client=None,
        context_guard=None,
    ):
        # route_for captures tenant configuration/secrets/capability qualification at the host.
        self.store, self.route_for = store, route_for
        self.provider_for = provider_for or (lambda scope, route: route.version)
        self.rate_card_for, self.cost_required = rate_card_for, cost_required
        self.client = client or AgentProviderClient()
        self.context_guard = context_guard

    def close(self):
        self.client.close()

    def turn(self, scope, *, system, messages, tools, output_schema, emit=None, loaded_skills=()):
        if not in_registered_agent_graph():
            raise DomainError("FORBIDDEN_SCOPE", "模型只能由登记的小Pai执行图调用。")
        self.store.current(scope)
        from .proposal_context import check

        check(self.store, scope)
        if self.context_guard is not None:
            self.context_guard(scope)
        route = self.route_for(scope)
        if route is None:
            raise DomainError("SOURCE_UNAVAILABLE", "当前模型未配置，AI 暂不可用。")
        provider_key = self.provider_for(scope, route)
        if not isinstance(provider_key, str) or not provider_key:
            raise DomainError("SOURCE_UNAVAILABLE", "当前服务商身份未登记。")
        if not isinstance(system, str) or any(
            not isinstance(message, dict) or not isinstance(message.get("content", ""), str)
            for message in messages
        ):
            raise DomainError("VALIDATION_FAILED", "当前费用资格只覆盖纯文本模型请求。")
        request = {
            "system": system,
            "messages": messages,
            "tools": tools,
            "output_schema": output_schema,
            "route": route.digest,
            "provider_key": provider_key,
        }
        with self.store.transaction(scope, lock=True) as (session, run):
            for binding in loaded_skills:
                validate_skill_load(session, scope, binding)
            prior_model = run.versions.get("model_version")
            prior_route = run.versions.get("model_route_digest")
            prior_provider = run.versions.get("provider_key")
            if (
                prior_model is not None
                and prior_model != route.version
                or prior_route is not None
                and prior_route != route.digest
                or prior_provider is not None
                and prior_provider != provider_key
            ):
                raise DomainError("VERSION_CONFLICT", "原运行的模型版本不能静默替换。")
            from pdos_next.service import digest

            tool_digests = run.versions.get("tool_definitions", {})
            prompt_digests = run.versions.get("prompt_prefixes", {})
            if prompt_digests.get(scope.isolation, digest(system)) != digest(system):
                raise DomainError("VERSION_CONFLICT", "原运行的提示前缀不能静默替换。")
            # The disclosure may grow when a skill loads, and only that way: the
            # chain keeps every earlier, narrower list verifiable (see .disclosure).
            chain = record_disclosure(
                run.versions,
                scope.isolation,
                [item["name"] for item in tools],
                digest(tools),
            )
            run.versions = {
                **run.versions,
                "model_version": route.version,
                "model_route_digest": route.digest,
                "provider_key": provider_key,
                "tool_definitions": {**tool_digests, scope.isolation: digest(tools)},
                "prompt_prefixes": {**prompt_digests, scope.isolation: digest(system)},
                CHAIN_KEY: chain,
            }
            binding = ModelBinding(
                model_version=route.version, model_route_digest=route.digest,
                tool_definitions_digest=digest(tools), prompt_digest=digest(system),
                isolation=scope.isolation, cancel_epoch=scope.cancel_epoch,
                loaded_skills=tuple(loaded_skills),
            ).model_dump(mode="json")
            request["execution_binding"] = binding
            decision = egress(session, scope, provider_key)
        from pdos_next.service import digest

        call_key = "model:" + digest(request)
        import json

        wire = request_body(route, system, messages, tools, output_schema, bool(emit))
        wire_bytes = len(json.dumps(wire, ensure_ascii=False).encode())
        input_upper = wire_bytes + 4096  # Explicitly unmetered synthetic transport fixtures only.
        pricing = self.rate_card_for(scope, route) if self.rate_card_for else None
        if self.cost_required and pricing is None:
            raise DomainError("SOURCE_UNAVAILABLE", "模型费用尚无当前价格卡与验证预算。")
        cost_lease = None
        if pricing:
            pricing.validate(provider_key, route)
            input_upper = pricing.input_upper_bound(wire_bytes)
            cost_lease = (
                pricing.reserve(input_upper, route.max_output_tokens),
                input_upper,
                route.max_output_tokens,
                pricing.snapshot(),
            )
        reserve = input_upper + route.max_output_tokens
        call_id, saved = self.store.claim(
            scope, call_key, "model", request, reservation=reserve, cost_lease=cost_lease,
            execution_binding=binding,
        )
        if saved is not None:
            from .types import ModelTurn, ToolCall

            return ModelTurn(
                saved["text"],
                tuple(ToolCall.model_validate(c) for c in saved["calls"]),
                usage=ProviderUsage(**saved["usage"]),
                request_id=saved["request_id"],
                structured=saved["structured"],
                ledger_call_id=call_id,
                continuation=saved.get("continuation"),
            )
        dispatch_started = False
        try:
            self.store.emit(
                scope,
                {
                    "type": "egress_checked",
                    **{
                        k: v.isoformat() if hasattr(v, "isoformat") else v
                        for k, v in asdict(decision).items()
                    },
                },
            )
            # Revocation/rotation after reservation still prevents sending the old scope.
            self.store.current(scope)
            latest = self.route_for(scope)
            if (
                latest is None
                or latest.digest != route.digest
                or self.provider_for(scope, latest) != provider_key
            ):
                raise DomainError("VERSION_CONFLICT", "模型配置已变化。")
            check(self.store, scope)
            if self.context_guard is not None:
                self.context_guard(scope)
            with self.store.transaction(scope) as (session, _):
                egress(session, scope, provider_key)
            if pricing:
                latest_price = self.rate_card_for(scope, latest)
                if latest_price is None or latest_price.snapshot() != pricing.snapshot():
                    raise DomainError("VERSION_CONFLICT", "价格卡已变化。")
                latest_price.validate(provider_key, latest)
            dispatch_started = True
            result = self.client.turn(
                route,
                system=system,
                messages=messages,
                tools=tools,
                output_schema=output_schema,
                emit=emit,
                cancelled=lambda: self._cancelled(scope),
            )
        except ProviderError as error:
            usage = error.usage
            unknown = error.unknown or bool(
                usage
                and (
                    usage.input_tokens > input_upper
                    or usage.output_tokens > route.max_output_tokens
                )
            )
            charged = usage.input_tokens + usage.output_tokens if usage else 0
            cancellation_code = None
            if error.code == "MODEL_CANCELLED":
                # The native transport also closes on revoked ACL/budget. Only the
                # actual persisted cancel epoch/state can call this a cancelled Run.
                try:
                    self.store.current(scope)
                except DomainError as current_error:
                    cancellation_code = current_error.code
                else:
                    cancellation_code = (
                        "EXTERNAL_OUTCOME_UNKNOWN" if unknown else "SOURCE_UNAVAILABLE"
                    )
            code = (
                cancellation_code
                if error.code == "MODEL_CANCELLED"
                else (
                    "EXTERNAL_OUTCOME_UNKNOWN"
                    if unknown
                    else "RATE_LIMITED"
                    if error.code == "PROVIDER_RATE_LIMITED"
                    else "SOURCE_UNAVAILABLE"
                )
            )
            self.store.release_call(
                scope,
                call_id,
                usage=0 if unknown else charged,
                unknown=unknown,
                error=code,
                request_id=error.request_id,
                cost_usage=CostUsage(usage.input_tokens, usage.output_tokens, pricing.actual(usage))
                if pricing and usage and not unknown
                else CostUsage(0, 0, pricing.actual(ProviderUsage(0, 0)))
                if pricing and not unknown
                else None,
            )
            raise DomainError(
                code,
                "模型调用未形成可用结果，请查看原调用回执。",
                detail={"provider_reason": error.code, "call_id": str(call_id)},
            ) from None
        except DomainError as error:
            self.store.release_call(
                scope,
                call_id,
                usage=0,
                unknown=dispatch_started,
                error=error.code,
                request_id=error.detail.get("provider_request_id"),
            )
            raise
        except Exception:
            self.store.release_call(scope, call_id, unknown=True, error="EXTERNAL_OUTCOME_UNKNOWN")
            raise DomainError(
                "EXTERNAL_OUTCOME_UNKNOWN", "原模型调用需对账。", detail={"call_id": str(call_id)}
            ) from None
        saved = {
            "text": result.text,
            "calls": [c.model_dump(mode="json") for c in result.calls],
            "structured": result.structured,
            "usage": asdict(result.usage),
            "request_id": result.request_id,
        }
        if result.continuation is not None:
            saved["continuation"] = result.continuation
        usage = result.usage.input_tokens + result.usage.output_tokens
        cost_usage = None
        if pricing:
            if (
                result.usage.input_tokens > input_upper
                or result.usage.output_tokens > route.max_output_tokens
            ):
                self.store.release_call(
                    scope, call_id, unknown=True, error="EXTERNAL_OUTCOME_UNKNOWN"
                )
                raise DomainError("EXTERNAL_OUTCOME_UNKNOWN", "服务商用量超出预约口径，需对账。")
            cost_usage = CostUsage(
                result.usage.input_tokens, result.usage.output_tokens, pricing.actual(result.usage)
            )
        try:
            check(self.store, scope)
            self.store.settle(
                scope,
                call_id,
                result=saved,
                usage=usage,
                request_id=result.request_id,
                cost_usage=cost_usage,
            )
        except DomainError as error:
            self.store.release_call(scope, call_id, usage=usage, unknown=True, error=error.code)
            raise
        self.store.current(scope)
        return replace(result, ledger_call_id=call_id)

    def _cancelled(self, scope):
        try:
            self.store.current(scope)
            return False
        except DomainError:
            return True
