"""Temporal Activity is the sole complete 小Pai entry; history contains references only."""

import logging
import traceback
from contextvars import copy_context
from threading import Event, Thread
from uuid import UUID

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import OperationalError as CheckpointUnavailable
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from temporalio import activity

from pdos_next.database import tenant_session
from pdos_next.dispatch.context import event_context
from pdos_next.errors import DomainError
from pdos_next.service import Context
from pdos_next.workflows.checkpoints import verified_checkpoint_url

from .graph import AgentKernel
from .host import BoundHost
from .models import AgentRun
from .persistence import KernelStore
from .tools import default_registry


def configure_agent_kernel(engine, adapters):
    engine._pdos_agent_kernel_adapters = adapters


class KernelActivities:
    def __init__(self, engine, *, checkpoint_url=None, technical_engine=None):
        self.engine, self.checkpoint_url = engine, checkpoint_url
        self.technical_engine = technical_engine
        self.store = KernelStore(engine)

    def scope_failed(self, ctx, run_id):
        if self.technical_engine is None:
            return False
        # Only the separate dispatcher role may call this metadata-only function.
        # Its stored run binding and actual loss are independently checked in SQL.
        with tenant_session(
            self.technical_engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
        ) as session:
            return session.scalar(text("SELECT kernel_scope_failed(:run)"), {"run": run_id})

    @staticmethod
    def scope_failure(run_id):
        return {"run_id": str(run_id), "status": "failed", "error_code": "FORBIDDEN_SCOPE"}

    @activity.defn(name="advance_xiaopai_run")
    def advance(self, reference):
        keys = {"tenant_id", "category_id", "actor_id", "requester_id", "subject_id"}
        if (
            not isinstance(reference, dict)
            or not keys <= reference.keys()
            or set(reference) - keys - {"answer_ref"}
        ):
            raise DomainError("FORBIDDEN_SCOPE", "工作须使用固定的服务器运行信封。")
        if reference.get("category_id"):
            ctx = event_context(reference)
        else:
            try:
                ctx = Context(
                    *(UUID(reference[key]) for key in ("tenant_id", "actor_id", "requester_id"))
                )
            except (KeyError, ValueError, TypeError):
                raise DomainError("FORBIDDEN_SCOPE", "缺少服务器个人范围信封。") from None
        run_id = UUID(reference["subject_id"])
        with tenant_session(
            self.engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
        ) as s:
            row = s.get(AgentRun, run_id)
            if (
                not row
                or row.requester_id != ctx.requester_id
                or ctx.actor_id
                != (row.writer_id if row.trigger == "automation_service" else ctx.requester_id)
                or row.category_id != ctx.category_id
            ):
                if self.scope_failed(ctx, run_id):
                    return self.scope_failure(run_id)
                raise DomainError("FORBIDDEN_SCOPE", "工作信封不属于当前运行。")
            if row.reverted_at:
                return {"run_id": str(row.id), "status": "cancelled", "reverted": True}
            if row.state in {"completed", "partial", "failed", "cancelled"}:
                return {"run_id": str(row.id), "status": row.state}
            writer, goal = row.writer_id, row.goal
            summary_run = False
            if row.trigger in {"automation_manual", "automation_service"}:
                from pdos_next.domain.automations.runtime import binding

                _, rule_spec = binding(s, row)
                from pdos_next.personal_summary_runtime import selected

                summary_run = selected(rule_spec)
                goal += (
                    f"\n\n用途：{rule_spec.purpose}\n停止条件：{rule_spec.stop_condition}"
                    "\n本规则只读取资料并返回结果，禁止联网、MCP 和业务写入。"
                )
        try:
            scope = self.store.scope(
                tenant_id=ctx.tenant_id,
                requester_id=ctx.requester_id,
                writer_id=writer,
                category_id=ctx.category_id,
                run_id=run_id,
            )
        except DomainError:
            if self.scope_failed(ctx, run_id):
                return self.scope_failure(run_id)
            raise
        adapters = getattr(self.engine, "_pdos_agent_kernel_adapters", None)
        if adapters is None and not summary_run:
            with self.store.transaction(scope, lock=True) as (session, row):
                row.state, row.error_code = "waiting_input", "SOURCE_UNAVAILABLE"
                from .process_view import record_state

                record_state(session, row)
            self.store.emit(scope, {"type": "model_unavailable", "code": "SOURCE_UNAVAILABLE"})
            return {
                "run_id": str(scope.run_id),
                "status": "waiting_input",
                "error_code": "SOURCE_UNAVAILABLE",
            }
        answer = None
        host = None if summary_run else BoundHost(self.store, adapters)
        with self.store.transaction(scope, lock=True) as (_, row):
            row.state, row.error_code = "running", None
        kernel = (
            None if summary_run else AgentKernel(
                host, adapters.tool_registry or default_registry(), catalog=host.catalog
            )
        )
        stopped = Event()
        heartbeat_context = copy_context()

        def heartbeat():
            while not stopped.wait(10):
                activity.heartbeat(str(scope.run_id))

        thread = Thread(target=lambda: heartbeat_context.run(heartbeat), daemon=True)
        try:
            if reference.get("answer_ref") and not summary_run:
                from .category_adoption import resolve

                answer = resolve(self.engine, scope, reference["answer_ref"])
            activity.heartbeat(str(scope.run_id))
            thread.start()
            # No in-memory fallback in the production Activity.
            if not self.checkpoint_url:
                raise DomainError("SOURCE_UNAVAILABLE", "检查点存储未配置。")
            with PostgresSaver.from_conn_string(
                verified_checkpoint_url(self.checkpoint_url)
            ) as saver:
                if summary_run:
                    from pdos_next.personal_summary_graph import execute

                    result = execute(self.store, scope, checkpointer=saver)
                else:
                    result = kernel.execute(
                        scope,
                        goal=goal,
                        answer=answer,
                        checkpointer=saver,
                        preload=self.preload(scope, adapters),
                    )
            if result.get("__interrupt__"):
                with self.store.transaction(scope, lock=True) as (_, row):
                    row.state = "waiting_input"
                return {"run_id": str(scope.run_id), "status": "needs_input"}
            return {"run_id": str(scope.run_id), "status": result["output"]["status"]}
        except Exception as exc:
            if summary_run and isinstance(exc, (OperationalError, CheckpointUnavailable)):
                # No inference or external/business write occurred. Let the same
                # Temporal Activity retry its persisted graph/terminal result.
                raise
            if not isinstance(exc, DomainError):
                # Unexpected worker failures remain visible and never retry a model from here.
                # Frames and exception type are diagnostic; values/SQL parameters stay private.
                logging.getLogger(__name__).error(
                    "Unexpected %s in Run %s: %s",
                    type(exc).__name__,
                    scope.run_id,
                    "".join(traceback.format_tb(exc.__traceback__)),
                )
                exc = DomainError("INTERNAL_ERROR", "执行未完成，已提交结果保留，请核对运行记录。")
            if exc.code != "CANCELLED_RUN":
                try:
                    with self.store.transaction(scope, lock=True) as (session, row):
                        if summary_run and row.state in {"completed", "partial"}:
                            return {"run_id": str(scope.run_id), "status": row.state}
                        row.error_code = exc.code
                        row.state = (
                            "waiting_input" if exc.code == "EXTERNAL_OUTCOME_UNKNOWN" else "failed"
                        )
                        from .process_view import record_state

                        if row.state == "failed":
                            from .work_state import record_finish

                            record_finish(session, row, row.result or {})
                        record_state(session, row)
                    if exc.code == "EXTERNAL_OUTCOME_UNKNOWN":
                        from .run_reconciliation import mark_required

                        mark_required(self.store, scope)
                except DomainError:
                    if self.scope_failed(ctx, run_id):
                        return self.scope_failure(run_id)
            return {
                "run_id": str(scope.run_id),
                "status": "cancelled"
                if exc.code == "CANCELLED_RUN"
                else "needs_reconciliation"
                if exc.code == "EXTERNAL_OUTCOME_UNKNOWN"
                else "failed",
                "error_code": exc.code,
            }
        finally:
            stopped.set()
            if thread.is_alive():
                thread.join(timeout=1)
            if host is not None:
                host.gateway.close()

    def preload(self, scope, adapters):
        from pdos_next.domain.automations.runtime import preload

        from .requested_skills import preload as requested_preload

        fallback = (
            ()
            if scope.trigger in {"automation_manual", "automation_service"}
            else (tuple(adapters.preload(scope)) if adapters.preload else ())
        )
        return preload(self.store, scope, requested_preload(self.store, scope, fallback))

    @activity.defn(name="reconcile_xiaopai_run")
    def reconcile(self, reference):
        keys = {"tenant_id", "category_id", "actor_id", "requester_id", "subject_id"}
        if (
            not isinstance(reference, dict)
            or not keys <= reference.keys()
            or set(reference) - keys - {"activity_exhausted"}
            or type(reference.get("activity_exhausted", False)) is not bool
        ):
            raise DomainError("FORBIDDEN_SCOPE", "核对须使用服务器固定的运行信封。")
        if reference.get("category_id"):
            ctx = event_context({key: reference[key] for key in keys})
        else:
            ctx = Context(
                *(UUID(reference[key]) for key in ("tenant_id", "actor_id", "requester_id"))
            )
        run_id = UUID(reference["subject_id"])
        from .run_reconciliation import finalize

        try:
            return finalize(
                self.engine,
                ctx,
                run_id,
                automatic=True,
                activity_exhausted=reference.get("activity_exhausted", False),
            )
        except DomainError:
            if self.scope_failed(ctx, run_id):
                return self.scope_failure(run_id)
            raise
