"""Trusted composition. Missing business adapters fail visibly, never fake a result."""

from dataclasses import dataclass, field

from pdos_next.errors import DomainError
from pdos_next.models import Receipt
from pdos_next.service import receipt_view

from . import policy
from .bindings import WriteSource, execution_key
from .execution import verify_source
from .gateway import AgentGateway
from .models import AgentToolCall
from .persistence import KernelStore
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
        )

    def current(self, scope):
        self.store.current(scope)

    def context(self, scope, goal):
        self.current(scope)
        projected = self.adapters.project_context(scope, goal)
        if not isinstance(projected, dict):
            raise DomainError("VALIDATION_FAILED", "上下文须按技能要求投影。")
        return projected

    def enabled(self, scope, skill):
        with self.store.transaction(scope) as (session, _):
            return policy.skill_enabled(session, scope, skill)

    def qualified(self, scope, skill, operation):
        route = self.adapters.route_for(scope)
        if route is None:
            return False
        with self.store.transaction(scope) as (session, run):
            if (
                route.version != run.versions.get("model_version")
                or route.digest != run.versions.get("model_route_digest")
            ):
                raise DomainError("VERSION_CONFLICT", "原模型输出不能使用其他模型的资格。")
            return policy.qualified(session, scope, skill, run.versions["model_version"])

    def model(self, scope, **kwargs):
        return self.gateway.turn(scope, emit=lambda e: self.emit(scope, e), **kwargs)

    def read(self, scope, spec, arguments, intent_key):
        callback = self.adapters.read_tools.get(spec.name)
        if callback is None:
            raise DomainError(
                "SOURCE_UNAVAILABLE", "此读取能力尚未配置。", detail={"tool": spec.name}
            )
        if spec.name in {"research.read", "evidence.artifact.read"}:
            return callback(scope, arguments)
        call_id, previous = self.store.claim(scope, intent_key, spec.name, arguments)
        if previous is not None:
            return previous
        try:
            result = callback(scope, arguments)
            self.store.settle(scope, call_id, result=result)
            return result
        except Exception:
            self.store.release_call(scope, call_id, error="SOURCE_UNAVAILABLE")
            raise

    def prepare(self, scope, spec, arguments, intent_key):
        self.current(scope)
        return self.adapters.prepare_candidate(scope, spec, arguments, intent_key)

    def write(self, scope, spec, arguments, intent_key, *, source: WriteSource):
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
