"""Current DPA and durable budget before every registered-graph provider attempt."""

from dataclasses import asdict, replace

from pdos_agent_runtime.graph import in_registered_agent_graph

from pdos_next.errors import DomainError
from pdos_next.providers.agent_client import AgentProviderClient, prompt_cache_policy, request_body
from pdos_next.providers.types import ProviderError, ProviderTokenCount, ProviderUsage

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
        data_categories_for=None,
        context_admitter=None,
    ):
        # route_for captures tenant configuration/secrets/capability qualification at the host.
        self.store, self.route_for = store, route_for
        self.provider_for = provider_for or (lambda scope, route: route.version)
        self.rate_card_for, self.cost_required = rate_card_for, cost_required
        self.client = client or AgentProviderClient()
        self.context_guard = context_guard
        self.data_categories_for = data_categories_for
        self.context_admitter = context_admitter

    def close(self):
        self.client.close()

    def context_baseline(self, scope, route, request_key):
        """Freeze the estimator input before admission, including on replay.

        Only digests/numbers persist here. A later provider observation cannot
        change an already admitted request's reductions or durable call key.
        """
        with self.store.transaction(scope, lock=True) as (_, run):
            admissions = run.versions.get("context_admissions", {})
            if request_key in admissions:
                return admissions[request_key]["calibration"]
            previous = run.versions.get("context_observations", {}).get(scope.isolation)
            if previous and previous.get("route_digest") != route.digest:
                previous = None
            run.versions = {**run.versions, "context_admissions": {
                **admissions, request_key: {"calibration": previous},
            }}
            return previous

    def observe_context(self, scope, route, budget, usage, *, only_if_missing=False):
        if usage.input_tokens <= 0:
            return
        with self.store.transaction(scope, lock=True) as (_, run):
            observations = run.versions.get("context_observations", {})
            if only_if_missing and scope.isolation in observations:
                return
            run.versions = {**run.versions, "context_observations": {
                **observations, scope.isolation: {
                    "route_digest": route.digest,
                    "estimated_total": budget["estimated_total"],
                    "actual_input_tokens": usage.input_tokens,
                },
            }}

    def turn(self, scope, *, system, messages, tools, output_schema, emit=None, loaded_skills=()):
        if not in_registered_agent_graph():
            raise DomainError("FORBIDDEN_SCOPE", "模型只能由登记的小Pai执行图调用。")
        from pdos_next.domain.automations.runtime import guard_tool

        guard_tool(self.store, scope, "model")
        self.store.current(scope)
        from .proposal_context import check

        check(self.store, scope)
        if self.context_guard is not None:
            self.context_guard(scope)
        source_categories = self.data_categories_for(scope) if self.data_categories_for else None
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
        from pdos_next.service import digest

        from .context_budget import fit_messages

        calibration = self.context_baseline(
            scope, route, digest([
                system, messages, tools, output_schema, route.digest, scope.isolation,
            ]),
        )

        try:
            if self.context_admitter is not None:
                messages, context_budget = self.context_admitter(
                    scope, route=route, system=system, tools=tools, messages=messages,
                    output_schema=output_schema, loaded_skills=loaded_skills,
                    calibration=calibration,
                )
            else:
                messages, context_budget = fit_messages(
                    route, system, tools, messages, output_schema,
                    calibration=calibration,
                )
        except DomainError as error:
            if error.reason == "CONTEXT_INCOMPLETE":
                self.store.emit(scope, {"type": "context_incomplete", **error.detail})
            raise
        request = {
            "system": system,
            "messages": messages,
            "tools": tools,
            "output_schema": output_schema,
            "route": route.digest,
            "provider_key": provider_key,
        }
        replay_only = False
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
                **({"budget_policy": route.budget_policy}
                   if route.budget_policy != "enforced" else {}),
            }
            binding = ModelBinding(
                model_version=route.version, model_route_digest=route.digest,
                tool_definitions_digest=digest(tools), prompt_digest=digest(system),
                isolation=scope.isolation, cancel_epoch=scope.cancel_epoch,
                loaded_skills=tuple(loaded_skills),
            ).model_dump(mode="json")
            request["execution_binding"] = binding
            decision = egress(session, scope, provider_key, data_categories=source_categories)
            cache_allowed = getattr(decision, "prompt_cache_allowed", False) is True
            if route.protocol == "anthropic-native":
                # True is the historical wire default, preserving existing keys.
                if not cache_allowed:
                    request["prompt_cache_allowed"] = False
                if prior_model is not None:
                    from sqlalchemy import case, select

                    from .models import AgentToolCall

                    alternate = dict(request)
                    if cache_allowed:
                        alternate["prompt_cache_allowed"] = False
                    else:
                        alternate.pop("prompt_cache_allowed")
                    current_key, alternate_key = ("model:" + digest(value)
                                                  for value in (request, alternate))
                    existing_key = session.scalar(select(AgentToolCall.call_key).where(
                        AgentToolCall.run_id == scope.run_id, AgentToolCall.tool == "model",
                        AgentToolCall.call_key.in_([current_key, alternate_key]),
                    ).order_by(case((AgentToolCall.call_key == current_key, 0), else_=1))
                        .limit(1).with_for_update())
                    if existing_key == alternate_key:
                        # Only the original claim may restore a completed result or
                        # reject an unknown/started one; no new outbound dispatch.
                        request, replay_only = alternate, True
        from pdos_next.service import digest

        call_key = "model:" + digest(request)
        import json

        wire = request_body(route, system, messages, tools, output_schema, bool(emit),
                            prompt_cache_allowed=cache_allowed)
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
            **({"budget_policy": route.budget_policy} if route.budget_policy != "enforced" else {}),
        )
        if saved is not None:
            from .types import ModelTurn, ToolCall

            if saved.get("context_budget"):
                self.observe_context(
                    scope, route, saved["context_budget"], ProviderUsage(**saved["usage"]),
                    only_if_missing=True,
                )
            return ModelTurn(
                saved["text"],
                tuple(ToolCall.model_validate(c) for c in saved["calls"]),
                usage=ProviderUsage(**saved["usage"]),
                request_id=saved["request_id"],
                structured=saved["structured"],
                ledger_call_id=call_id,
                continuation=saved.get("continuation"),
            )
        if replay_only:
            self.store.release_call(scope, call_id, error="VERSION_CONFLICT", usage=0)
            raise DomainError("VERSION_CONFLICT", "原模型调用已变化，不能重新发送。")
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
            self._recheck_dispatch(scope, route, provider_key, decision, pricing)
            if (route.protocol == "anthropic-native"
                    and context_budget["admission_tokens"] * 10 >= context_budget["focus"] * 9):
                count, count_call_id = self._count_context(
                    scope, route, request, binding, decision, pricing,
                )
                context_budget = {
                    **context_budget, "provider_counted_input_tokens": count.input_tokens,
                    "provider_count_call_id": str(count_call_id),
                }
                # Count is preflight metadata, never a generation usage/calibration.
                if count.input_tokens > context_budget["focus"]:
                    from .context_budget import required_items

                    detail = {"reason_key": "provider_count_exceeds_focus",
                              "context_budget": context_budget,
                              "missing": required_items(system, tools, messages, output_schema)}
                    self.store.emit(scope, {"type": "context_incomplete", **detail})
                    raise DomainError(
                        "CONTEXT_INCOMPLETE", "服务商预先计量超过当前上下文预算，请缩小范围。",
                        detail=detail, recovery={"action": "reduce_required_context"},
                    )
                self._recheck_dispatch(scope, route, provider_key, decision, pricing)
            dispatch_started = True
            with prompt_cache_policy(cache_allowed):
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
            code = "EXTERNAL_OUTCOME_UNKNOWN" if dispatch_started else "SOURCE_UNAVAILABLE"
            self.store.release_call(scope, call_id, unknown=dispatch_started, error=code)
            raise DomainError(
                code, "模型调用未形成可用结果。", detail={"call_id": str(call_id)}
            ) from None
        context_budget = {
            **context_budget, "actual_input_tokens": result.usage.input_tokens,
            "input_estimate_error_ratio": abs(
                context_budget["estimated_total"] - result.usage.input_tokens
            ) / result.usage.input_tokens if result.usage.input_tokens else None,
        }
        saved = {
            "context_budget": context_budget,
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
        self.observe_context(scope, route, context_budget, result.usage)
        return replace(result, ledger_call_id=call_id)

    def _recheck_dispatch(self, scope, route, provider_key, decision, pricing):
        """Every count/generation attempt uses the same current host-bound scope."""
        from .proposal_context import check

        self.store.current(scope)
        latest = self.route_for(scope)
        if (latest is None or latest.digest != route.digest
                or self.provider_for(scope, latest) != provider_key):
            raise DomainError("VERSION_CONFLICT", "模型配置已变化。")
        check(self.store, scope)
        if self.context_guard is not None:
            self.context_guard(scope)
        categories = self.data_categories_for(scope) if self.data_categories_for else None
        with self.store.transaction(scope) as (session, _):
            checked = egress(session, scope, provider_key, data_categories=categories)
            if checked.data_categories != decision.data_categories:
                raise DomainError("SOURCE_STALE", "本次发送的资料类别已变化，请重新核对。")
            if (route.protocol == "anthropic-native"
                    and getattr(checked, "prompt_cache_allowed", False)
                    != getattr(decision, "prompt_cache_allowed", False)):
                raise DomainError("SOURCE_STALE", "服务商缓存许可已变化，请重新发起。")
        if pricing:
            latest_price = self.rate_card_for(scope, latest)
            if latest_price is None or latest_price.snapshot() != pricing.snapshot():
                raise DomainError("VERSION_CONFLICT", "价格卡已变化。")
            latest_price.validate(provider_key, latest)

    def _count_context(self, scope, route, request, binding, decision, pricing):
        """A separate technical ledger call, carrying no business READ or model usage."""
        from pdos_next.service import digest

        cache_allowed = request.get("prompt_cache_allowed", True)
        payload = {**request, "prompt_cache_allowed": cache_allowed,
                   "endpoint": route.token_count_url}
        count_id, saved = self.store.claim(
            scope, "model.count_tokens:" + digest(payload), "model.count_tokens", payload,
            execution_binding={"kind": "unbound", "dispatch": "anthropic-count-tokens/v1",
                               "model_binding": binding},
        )
        if saved is not None:
            return ProviderTokenCount(saved["input_tokens"]), count_id
        try:
            self._recheck_dispatch(scope, route, decision.provider, decision, pricing)
            self.store.emit(scope, {"type": "egress_checked", "operation": "model.count_tokens",
                                   **{key: val.isoformat() if hasattr(val, "isoformat") else val
                                      for key, val in asdict(decision).items()}})
            with prompt_cache_policy(cache_allowed):
                count = self.client.count_tokens(
                    route, system=request["system"], messages=request["messages"],
                    tools=request["tools"], output_schema=request["output_schema"],
                    cancelled=lambda: self._cancelled(scope),
                )
            self.store.current(scope)
            self.store.settle(scope, count_id, result={"input_tokens": count.input_tokens},
                              usage=0, request_id=count.request_id)
            return count, count_id
        except ProviderError as error:
            code = "RATE_LIMITED" if error.code == "PROVIDER_RATE_LIMITED" else "SOURCE_UNAVAILABLE"
            if error.code == "MODEL_CANCELLED":
                try:
                    self.store.current(scope)
                except DomainError as current_error:
                    code = current_error.code
            self.store.release_call(scope, count_id, error=code, unknown=error.unknown,
                                    request_id=error.request_id)
            raise DomainError(code, "上下文预先计量未成功，未发起模型生成。",
                              detail={"provider_reason": error.code,
                                      "count_call_id": str(count_id)}) from None
        except Exception:
            self.store.release_call(scope, count_id, error="SOURCE_UNAVAILABLE", unknown=True)
            raise

    def _cancelled(self, scope):
        try:
            self.store.current(scope)
            return False
        except DomainError:
            return True
