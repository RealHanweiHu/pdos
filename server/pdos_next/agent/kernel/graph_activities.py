"""Run bookkeeping around a plugin-executed graph (P100); never a model or tool call.

``open`` does what ``advance_xiaopai_run`` checks before it enters its graph, ``close``
what it records when the graph fails. The graph itself runs node by node as plugin
Activities between the two.
"""

from uuid import UUID

from temporalio import activity
from temporalio.exceptions import ApplicationError

from pdos_next.core.database import tenant_session
from pdos_next.core.dispatch.context import event_context
from pdos_next.core.service import Context
from pdos_next.errors import DomainError

from .activities import KernelActivities
from .models import AgentRun
from .persistence import KernelStore

KEYS = frozenset({"tenant_id", "category_id", "actor_id", "requester_id", "subject_id"})
TERMINAL = frozenset({"completed", "partial", "failed", "cancelled"})
PERSONAL_SUMMARY, KERNEL = "personal_summary", "kernel"
# Grace before the automatic receipt check of an unknown outcome, as in XiaopaiWork.
# Read here, in an Activity, so the workflow only ever sees the recorded value.
RECONCILE_AFTER_SECONDS = 300


def _context(reference, extra):
    if (
        not isinstance(reference, dict)
        or not KEYS <= reference.keys()
        or set(reference) - KEYS != {extra}
        or any(not isinstance(value, str) for value in reference.values())
    ):
        raise DomainError("FORBIDDEN_SCOPE", "工作须使用固定的服务器运行信封。")
    try:
        if reference["category_id"]:
            return event_context(reference), UUID(reference["subject_id"])
        return Context(
            *(UUID(reference[key]) for key in ("tenant_id", "actor_id", "requester_id"))
        ), UUID(reference["subject_id"])
    except (ValueError, TypeError):
        raise DomainError("FORBIDDEN_SCOPE", "缺少服务器范围信封。") from None


def _stop(error):
    # Nothing here is repeated by Temporal; the workflow closes the run instead.
    return ApplicationError(error.message, type=error.code, non_retryable=True)


class GraphRunActivities:
    def __init__(self, engine, *, technical_engine=None):
        self.engine, self.store = engine, KernelStore(engine)
        self.legacy = KernelActivities(engine, technical_engine=technical_engine)

    def _scope(self, ctx, run_id, writer):
        return self.store.scope(
            tenant_id=ctx.tenant_id, requester_id=ctx.requester_id, writer_id=writer,
            category_id=ctx.category_id, run_id=run_id,
        )

    @activity.defn(name="open_xiaopai_graph_run")
    def open(self, reference):
        try:
            return self._open(reference)
        except DomainError as error:
            raise _stop(error) from None

    def _open(self, reference):
        ctx, run_id = _context(reference, "kind")
        with tenant_session(
            self.engine, ctx.tenant_id, actor_id=ctx.actor_id,
            requester_id=ctx.requester_id, category_id=ctx.category_id,
        ) as session:
            row = session.get(AgentRun, run_id)
            if (
                not row
                or row.requester_id != ctx.requester_id
                or ctx.actor_id
                != (row.writer_id if row.trigger == "automation_service" else ctx.requester_id)
                or row.category_id != ctx.category_id
            ):
                if self.legacy.scope_failed(ctx, run_id):
                    return self.legacy.scope_failure(run_id)
                raise DomainError("FORBIDDEN_SCOPE", "工作信封不属于当前运行。")
            if row.reverted_at:
                return {"run_id": str(row.id), "status": "cancelled", "reverted": True}
            if row.state in TERMINAL:
                return {"run_id": str(row.id), "status": row.state}
            writer, goal = row.writer_id, row.goal
            summary = False
            if row.trigger in {"automation_manual", "automation_service"}:
                from pdos_next.domain.automations.runtime import binding
                from pdos_next.domain.my_work.summary_runtime import selected

                _, rule_spec = binding(session, row)
                summary = selected(rule_spec)
                goal += (
                    f"\n\n用途：{rule_spec.purpose}\n停止条件：{rule_spec.stop_condition}"
                    "\n本规则只读取资料并返回结果，禁止联网、MCP 和业务写入。"
                )
        kind = PERSONAL_SUMMARY if summary else KERNEL
        if reference["kind"] not in {kind, "any"}:
            raise DomainError("VALIDATION_FAILED", "该运行不属于所请求的插件执行图。")
        try:
            scope = self._scope(ctx, run_id, writer)
        except DomainError:
            if self.legacy.scope_failed(ctx, run_id):
                return self.legacy.scope_failure(run_id)
            raise
        if kind == KERNEL and getattr(self.engine, "_pdos_agent_kernel_adapters", None) is None:
            with self.store.transaction(scope, lock=True) as (session, row):
                row.state, row.error_code = "waiting_input", "SOURCE_UNAVAILABLE"
                from .process_view import record_state

                record_state(session, row)
            self.store.emit(scope, {"type": "model_unavailable", "code": "SOURCE_UNAVAILABLE"})
            return {"run_id": str(run_id), "status": "waiting_input",
                    "error_code": "SOURCE_UNAVAILABLE"}
        with self.store.transaction(scope, lock=True) as (_, row):
            if row.state in TERMINAL:
                return {"run_id": str(row.id), "status": row.state}
            row.state, row.error_code = "running", None
            row.versions = {**row.versions, "execution_engine": "temporal-langgraph/v1"}
        return {
            "run_id": str(run_id), "status": "running", "kind": kind,
            "cancel_epoch": scope.cancel_epoch, "writer_id": str(writer),
            "reconcile_after_seconds": RECONCILE_AFTER_SECONDS,
            # The summary graph reads no goal; keep its state to identifiers.
            **({"goal": goal} if kind == KERNEL else {}),
        }

    @activity.defn(name="close_xiaopai_graph_run")
    def close(self, reference):
        ctx, run_id = _context(reference, "error_code")
        code = reference["error_code"]
        if code == "CANCELLED_RUN":
            return {"run_id": str(run_id), "status": "cancelled", "error_code": code}
        unknown = code == "EXTERNAL_OUTCOME_UNKNOWN"
        try:
            with tenant_session(
                self.engine, ctx.tenant_id, actor_id=ctx.actor_id,
                requester_id=ctx.requester_id, category_id=ctx.category_id,
            ) as session:
                row = session.get(AgentRun, run_id)
                if not row or row.requester_id != ctx.requester_id:
                    raise DomainError("FORBIDDEN_SCOPE", "工作信封不属于当前运行。")
                writer = row.writer_id
            scope = self._scope(ctx, run_id, writer)
            with self.store.transaction(scope, lock=True) as (session, row):
                if row.state in TERMINAL:
                    return {"run_id": str(run_id), "status": row.state}
                row.error_code = code
                row.state = "waiting_input" if unknown else "failed"
                from .process_view import record_state

                if row.state == "failed":
                    from .work_state import record_finish

                    record_finish(session, row, row.result or {})
                record_state(session, row)
            if unknown:
                from .run_reconciliation import mark_required

                mark_required(self.store, scope)
        except DomainError as error:
            if self.legacy.scope_failed(ctx, run_id):
                return self.legacy.scope_failure(run_id)
            if error.code == "CANCELLED_RUN":
                return {"run_id": str(run_id), "status": "cancelled", "error_code": error.code}
            raise _stop(error) from None
        return {
            "run_id": str(run_id),
            "status": "needs_reconciliation" if unknown else "failed",
            "error_code": code,
        }
