"""Kernel bookkeeping Activities that never run a model: reconciliation and helpers.

The 小Pai graph itself runs node by node on the Temporal LangGraph plugin (P100); see
``plugin_graph`` and ``graph_activities``.
"""

from uuid import UUID

from sqlalchemy import text
from temporalio import activity
from temporalio.exceptions import ApplicationError

from pdos_next.core.database import tenant_session
from pdos_next.core.dispatch.context import event_context
from pdos_next.core.service import Context
from pdos_next.errors import DomainError

from .persistence import KernelStore
from .run_lease import RunBusy, run_lease


def configure_agent_kernel(engine, adapters):
    engine._pdos_agent_kernel_adapters = adapters


class KernelActivities:
    def __init__(self, engine, *, technical_engine=None):
        self.engine, self.technical_engine = engine, technical_engine
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
            with run_lease(self.engine, run_id):
                return finalize(
                    self.engine,
                    ctx,
                    run_id,
                    automatic=True,
                    activity_exhausted=reference.get("activity_exhausted", False),
                )
        except RunBusy:
            # A timed-out attempt is still stopping; reconcile after it has (D243).
            raise ApplicationError("小Pai run is still held by an earlier attempt") from None
        except DomainError:
            if self.scope_failed(ctx, run_id):
                return self.scope_failure(run_id)
            raise
