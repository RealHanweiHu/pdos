"""Trusted composition. Missing business adapters fail visibly, never fake a result."""

from dataclasses import dataclass, field

from pdos_next.errors import DomainError
from pdos_next.models import Receipt
from pdos_next.service import digest, receipt_view

from . import policy
from .bindings import WriteSource, execution_key
from .execution import verify_source
from .gateway import AgentGateway
from .models import AgentToolCall
from .persistence import KernelStore
from .read_execution import ReadSource, build_read_binding, verify_read_source
from .skills import SkillCatalog


@dataclass(frozen=True)
class KernelAdapters:
    route_for: object
    project_context: object
    verify_result: object
    prepare_candidate: object
    execute_command: object
    read_tools: dict = field(default_factory=dict)
    provider_client: object | None = None
    provider_for: object | None = None
    preload: object | None = None
    rate_card_for: object | None = None
    cost_required: bool = True
    skill_catalog: object | None = None
    tool_registry: object | None = None
    recover_command: object | None = None
    compute_engines: dict = field(default_factory=dict)
    read_restores: dict = field(default_factory=dict)
    read_resumes: dict = field(default_factory=dict)
    context_guard: object | None = None
    citation_guard: object | None = None
    source_action_guard: object | None = None


class BoundHost:
    def __init__(self, store: KernelStore, adapters: KernelAdapters):
        self.store, self.adapters = store, adapters
        self.catalog = adapters.skill_catalog or SkillCatalog()
        self.gateway = AgentGateway(
            store,
            route_for=adapters.route_for,
            provider_for=adapters.provider_for,
            rate_card_for=adapters.rate_card_for,
            cost_required=adapters.cost_required,
            client=adapters.provider_client,
            context_guard=self.context_guard,
            data_categories_for=adapters.citation_guard,
            context_admitter=self.admit_context,
        )

    def current(self, scope):
        self.store.current(scope)

    def checkpoint_layout(self, scope):
        from .session_checkpoints import LAYOUT_KEY
        with self.store.transaction(scope) as (_, run):
            return run.versions.get(LAYOUT_KEY)

    def context(self, scope, goal):
        return self.skill_context(scope, goal, bindings=())["context"]

    def skill_context(self, scope, goal, *, bindings):
        from pdos_next.personal_preferences import context_preferences

        from .context_projection import combine_contracts, project, snapshot

        self.current(scope)
        skills = [self.catalog.load(binding.key, scope, self.enabled) for binding in bindings]
        if any(skill.version != binding.version or skill.digest != binding.digest
               for skill, binding in zip(skills, bindings, strict=True)):
            raise DomainError("VERSION_CONFLICT", "已加载方法的资料合同已变化。")
        schema = combine_contracts(self.catalog, skills)
        raw = self.adapters.project_context(scope, goal, frozenset(schema["properties"]))
        with self.store.transaction(scope, lock=True) as (session, run):
            preferences = run.versions.get("personal_preferences_context")
            if preferences is None:
                preferences = context_preferences(session, scope)
                run.versions = {**run.versions, "personal_preferences_context": preferences}
            raw = {**raw, "personal_preferences": preferences}
            action = run.versions.get("verification_action")
            if action is not None:
                from pdos_next.enterprise_search.verification_actions import context_value

                raw["verification_action"] = context_value(action)
        value, omitted, issues = project(raw, schema)
        reference = snapshot(self.store, scope, value=value, schema=schema, bindings=bindings,
                             omitted=omitted, issues=issues)
        return {"context": value, "context_ref": reference,
                "omitted_fields": [entry["field"] for entry in omitted]}

    def enabled(self, scope, skill):
        from pdos_next.domain.automations.runtime import permitted_skill

        if not permitted_skill(self.store, scope, skill):
            return False
        with self.store.transaction(scope) as (session, _):
            return policy.skill_enabled(session, scope, skill)

    def qualified(self, scope, skill, operation):
        route = self.adapters.route_for(scope)
        if route is None:
            return False
        with self.store.transaction(scope) as (session, run):
            if route.version != run.versions.get(
                "model_version"
            ) or route.digest != run.versions.get("model_route_digest"):
                raise DomainError("VERSION_CONFLICT", "原模型输出不能使用其他模型的资格。")
            from .qualification_binding import model_identity, tool_identity
            from .tools import default_registry

            return policy.qualified(
                session,
                scope,
                skill,
                run.versions["model_version"],
                model_digest=model_identity(route),
                tool_digest=tool_identity(skill, self.adapters.tool_registry or default_registry()),
            )

    def model(self, scope, **kwargs):
        if scope.isolation == "main":
            from .context_projection import check_messages

            check_messages(self.store, scope, kwargs["messages"], kwargs.get("loaded_skills", ()))
        return self.gateway.turn(scope, emit=lambda e: self.emit(scope, e), **kwargs)

    def context_guard(self, scope):
        from pdos_next.personal_preferences import recheck_context_preferences

        if self.adapters.context_guard is not None:
            self.adapters.context_guard(scope)
        with self.store.transaction(scope) as (session, run):
            preferences = run.versions.get("personal_preferences_context")
            if preferences is not None and not recheck_context_preferences(
                session, scope, preferences,
            ):
                raise DomainError(
                    "CONVERSATION_HISTORY_REVOKED", "本次携带中的导航对象已无权读取，请重新发起。",
                )

    def admit_context(self, scope, *, route, system, tools, messages, output_schema, loaded_skills,
                      calibration=None):
        from .context_budget import fit_messages, measure
        from .context_projection import combine_contracts, project, snapshot
        from .tools import default_registry

        registry = self.adapters.tool_registry or default_registry()

        def compact(name, value):
            spec = registry.get(name)
            if spec.tier != "READ" or not value.get("execution_ref"):
                return None
            return self.tool_message(scope, spec, value, force=True)

        reduced, budget = fit_messages(
            route, system, tools, messages, output_schema,
            compact_tool=compact, allow_envelope=scope.isolation == "main",
            calibration=calibration,
        )
        if budget["reductions"] and reduced and reduced[0] != messages[0]:
            import json

            envelope = json.loads(reduced[0]["content"])
            with self.store.transaction(scope) as (_, run):
                saved = run.versions.get("context_snapshots", {})
                original = next((entry for entry in saved.values()
                                 if entry["event_id"] == envelope["context_ref"]), None)
                if original is None:
                    raise DomainError("SOURCE_STALE", "缩减前的资料快照不可核对。")
                previous_omitted = original["omitted"]
            skills = [self.catalog.load(binding.key, scope, self.enabled)
                      for binding in loaded_skills]
            schema = combine_contracts(self.catalog, skills)
            value, omitted, issues = project(envelope["context"], schema)
            omissions = {entry["field"]: entry for entry in [*previous_omitted, *omitted]}
            omitted = list(omissions.values())
            envelope["context_ref"] = snapshot(
                self.store, scope, value=value, schema=schema, bindings=loaded_skills,
                omitted=omitted, issues=issues,
            )
            envelope["omitted_fields"] = [entry["field"] for entry in omitted]
            reduced[0]["content"] = json.dumps(envelope, ensure_ascii=False)
            budget = {**measure(route, system, tools, reduced, output_schema,
                                calibration=calibration),
                      "reductions": budget["reductions"]}
        return reduced, budget

    def read(self, scope, spec, arguments, intent_key, *, source: ReadSource | None = None):
        from pdos_next.domain.automations.runtime import guard_tool

        guard_tool(self.store, scope, spec.name)
        if spec.name == "result.read":
            return self.read_result(scope, spec, arguments, intent_key, source=source)
        if self.adapters.source_action_guard is not None and spec.name in {
            "research.search", "research.fanout", "mcp.read",
        }:
            self.adapters.source_action_guard(scope, spec.name)
        callback = self.adapters.read_tools.get(spec.name)
        if callback is None:
            raise DomainError(
                "SOURCE_UNAVAILABLE", "此读取能力尚未配置。", detail={"tool": spec.name}
            )
        engine = self.adapters.compute_engines.get(spec.name)
        restore = self.adapters.read_restores.get(spec.name)
        resume = self.adapters.read_resumes.get(spec.name)
        if resume is not None:
            with self.store.composition_lock(scope, intent_key):
                return self.read_callback(
                    scope, spec, arguments, intent_key, source=source,
                    callback=lambda bound, args: resume(bound, args, intent_key=intent_key),
                    restore=(lambda previous: restore(scope, arguments, previous)),
                    resume_started=True,
                )
        return self.read_callback(
            scope, spec, arguments, intent_key, source=source,
            callback=callback, engine=engine,
            restore=(lambda previous: restore(scope, arguments, previous)) if restore else None,
        )

    def read_result(self, scope, spec, arguments, intent_key, *, source, original_reader=None):
        from pydantic import ValidationError

        from .result_continuation import ResultReadInput

        try:
            data = ResultReadInput.model_validate(arguments)
        except ValidationError:
            raise DomainError("VALIDATION_FAILED", "结果续读需要有效句柄和正整数页码。") from None
        with self.store.composition_lock(scope, intent_key, wait=True):
            return self.read_callback(
                scope, spec, arguments, intent_key, source=source,
                callback=lambda bound, _: self.continue_result(
                    bound, data, original_reader=original_reader,
                ), resume_started=True,
            )

    def continue_result(self, scope, data, *, original_reader=None):
        from .result_continuation import durable_read, page_view
        from .tools import default_registry

        registry = self.adapters.tool_registry or default_registry()
        spec, arguments, intent, source, fingerprint = durable_read(
            self.store, scope, data.handle, registry,
        )
        # Re-enter the original registered adapter, including its restore/source
        # guards. A handle never turns historical JSON into current permission.
        current = (original_reader or self.read)(scope, spec, arguments, intent, source=source)
        raw = {key: value for key, value in current.items() if key != "execution_ref"}
        if digest(raw) != fingerprint:
            raise DomainError("SOURCE_STALE", "原结果已变化，请重新读取资料。")
        return page_view(current, data.handle, data.page, min(spec.max_result_tokens, 4_000) - 64)

    def tool_message(self, scope, spec, value, *, force=False):
        from .context_budget import estimate_tokens
        from .result_continuation import handle_for, page_view, serialized

        if not force and estimate_tokens(serialized(value)) <= spec.max_result_tokens:
            return value
        reference = value.get("execution_ref") if isinstance(value, dict) else None
        if spec.tier != "READ" or spec.name in {"skill.load", "result.read"} or not reference:
            # Receipts, skill bodies and errors are required content. The call
            # budget guard will report them explicitly rather than silently cut.
            return value
        from uuid import UUID

        with self.store.transaction(scope) as (session, _):
            call = session.get(AgentToolCall, UUID(reference["call_id"]))
            raw = {key: child for key, child in value.items() if key != "execution_ref"}
            if (
                not call or call.tenant_id != scope.tenant_id or call.run_id != scope.run_id
                or call.tool != spec.name or call.state != "completed"
                or call.error_code is not None or call.receipt_id is not None
                or call.result != raw
                or call.execution_binding.get("isolation") != scope.isolation
            ):
                raise DomainError("FORBIDDEN_SCOPE", "超长结果缺少当前运行的可信读取账本。")
            handle = handle_for(call.id, call.result)
        result = page_view(value, handle, 1, min(spec.max_result_tokens, 4_000) - 64)
        if force:
            result = {key: child for key, child in result.items() if key != "preview"}
            result.update(omitted=True, read_more={
                "tool": "result.read", "arguments": {"handle": handle, "page": 1},
            })
        return result

    def read_callback(
        self, scope, spec, arguments, intent_key, *, source, callback,
        engine=None, read_kind="ordinary/v1", metadata=None, restore=None, resume_started=False,
    ):
        """Registered graph composition supplies callbacks and proof policy.

        The provider sees only the tool arguments. Even isolated raw reads bind
        the actual completed model response, and replay rechecks its source data.
        Pure results exist before claim so their immutable digest is never patched.
        """
        from .deterministic_proofs import canonical_hash
        from .tools import default_registry
        with self.store.transaction(scope) as (session, run):
            model = verify_read_source(
                session, scope, run, spec, arguments, source,
                self.adapters.tool_registry or default_registry(),
                self.adapters.route_for(scope),
                catalog=self.catalog,
                intent_key=intent_key,
            )
            computed = engine.calculate(arguments) if engine is not None else None
            if engine is not None:
                read_kind = "compute/v1"
                metadata = {
                    "engine_version": engine.version, "result_digest": canonical_hash(computed)
                }
            binding = build_read_binding(
                scope, run, spec, source, model,
                read_kind=read_kind, server_metadata=metadata,
            ).model_dump(mode="json")
        call_id, previous = self.store.claim(
            scope, intent_key, spec.name, arguments, execution_binding=binding,
            **({"resume_started": True} if resume_started else {}),
        )
        try:
            if previous is not None and restore is not None:
                result = restore(previous)
            else:
                result = computed if engine is not None else callback(scope, arguments)
            if previous is not None:
                fingerprint = canonical_hash if engine is not None else digest
                if fingerprint(result) != fingerprint(previous):
                    raise DomainError(
                        "SOURCE_STALE", "读取结果已变化，请使用新的运行重新读取。",
                        detail={"reason": "read_result_changed"},
                    )
            else:
                self.store.settle(scope, call_id, result=result)
            return {
                **result,
                "execution_ref": {"call_id": str(call_id), "read_kind": read_kind},
            } if isinstance(result, dict) else result
        except Exception:
            if previous is None:
                self.store.release_call(scope, call_id, error="SOURCE_UNAVAILABLE")
            raise

    def prepare(self, scope, spec, arguments, intent_key, *, source: WriteSource | None = None):
        from pdos_next.domain.automations.runtime import guard_tool

        guard_tool(self.store, scope, writing=True)
        if self.adapters.source_action_guard is not None:
            self.adapters.source_action_guard(scope, spec.name)
        self.current(scope)
        if spec.name == "verification.preparation.record":
            return self.adapters.prepare_candidate(
                scope, spec, arguments, intent_key, source=source,
            )
        return self.adapters.prepare_candidate(scope, spec, arguments, intent_key)

    def write(self, scope, spec, arguments, intent_key, *, source: WriteSource):
        from pdos_next.domain.automations.runtime import guard_tool

        guard_tool(self.store, scope, writing=True)
        if self.adapters.source_action_guard is not None:
            self.adapters.source_action_guard(scope, spec.name)
        self.current(scope)
        if spec.tier != "T0" or scope.isolation != "main":
            raise DomainError("NAMED_DECISION_REQUIRED", "该工具没有 AI 自动执行权。")
        from .tools import default_registry

        if not isinstance(source, WriteSource) or intent_key != execution_key(
            scope.run_id, source.model_call_id, source.response_index
        ):
            raise DomainError("FORBIDDEN_SCOPE", "执行引用须由服务器实际模型账本生成。")
        with self.store.transaction(scope) as (session, run):
            verify_source(
                session, scope, run, spec, arguments, source, catalog=self.catalog,
                registry=self.adapters.tool_registry or default_registry(),
                route=self.adapters.route_for(scope),
            )
        # The domain owner repeats these checks and binds the Call in its own Session.
        return self.adapters.execute_command(
            scope, spec.operation_key, arguments, intent_key, source=source
        )

    def recover(self, scope, spec, arguments, intent_key, *, source: WriteSource):
        if spec.tier != "T0" or scope.isolation != "main":
            return None
        if self.adapters.recover_command is None:
            return None
        return self.adapters.recover_command(scope, spec, arguments, intent_key, source=source)

    def receipt(self, scope, result):
        from uuid import UUID

        try:
            receipt_id = UUID(result["id"])
            if result.get("existing_result") is True:
                with self.store.transaction(scope) as (session, _):
                    row = session.get(Receipt, receipt_id)
                    if (
                        not row or row.tenant_id != scope.tenant_id
                        or row.category_id != scope.category_id
                        or row.product_id != scope.product_id
                        or {k: v for k, v in result.items() if k != "existing_result"}
                        != receipt_view(row)
                    ):
                        raise DomainError("FORBIDDEN_SCOPE", "已有回执不在当前可读范围。", 403)
                    return {
                        "id": str(row.id), "operation": row.operation,
                        "subject_id": str(row.subject_id), "result": row.result,
                        "existing_result": True,
                    }
            call_id = UUID(result["agent_call_id"])
        except (KeyError, TypeError, ValueError):
            raise DomainError("VALIDATION_FAILED", "工具未返回真实领域回执。") from None
        with self.store.transaction(scope) as (session, _):
            row = session.get(Receipt, receipt_id)
            call = session.get(AgentToolCall, call_id)
            if (
                not row
                or row.tenant_id != scope.tenant_id
                or row.category_id != scope.category_id
                or row.actor_id != scope.writer_id
                or row.requester_id != scope.requester_id
                or getattr(row, "agent_run_id", None) != scope.run_id
                or not call or call.tenant_id != scope.tenant_id or call.run_id != scope.run_id
                or call.state != "completed" or call.receipt_id != row.id
                or call.result != result
            ):
                raise DomainError("FORBIDDEN_SCOPE", "回执不属于服务器绑定运行。")
            return {
                "id": str(row.id),
                "operation": row.operation,
                "subject_id": str(row.subject_id),
                "result": row.result,
            }

    def verify(self, scope, result, tool_results):
        from .verification import fill_counts

        self.current(scope)
        checked = self.adapters.verify_result(scope, result, tool_results)
        return fill_counts(checked, tool_results)

    def emit(self, scope, event):
        return self.store.emit(scope, event)

    def finish(self, scope, result):
        self.store.finish(scope, result)
