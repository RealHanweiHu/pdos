"""Explicit related discussions inherit the original budget and cancellation domain."""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, func, select, text
from sqlalchemy.exc import DBAPIError

from app.ai.budget_ledger import BudgetLedger, BudgetLedgerError
from app.ai.discussion_sources import require_disclosure
from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError


def parent(
    c: Connection, context: AuthContext, project: UUID, ecr_id: UUID | None, parent_id: UUID
) -> Any:
    runs, bindings = tables.agent_runs, tables.debate_run_bindings
    row = (
        c.execute(
            select(runs)
            .where(
                runs.c.tenant_id == context.tenant.id,
                runs.c.project_id == project,
                runs.c.id == parent_id,
                runs.c.requested_by_user_id == context.user.id,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    bound = (
        c.execute(
            select(bindings).where(
                bindings.c.tenant_id == context.tenant.id, bindings.c.run_id == parent_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None or bound is None or bound["ecr_id"] != ecr_id:
        raise ProductWorkError("请选择本人在当前话题下的原讨论")
    require_disclosure(c, context.tenant.id, context.user.id, bound)
    if row["status"] in {"queued", "running", "waiting_input"} or row["run_context"].get(
        "discussion_recovery_requested"
    ):
        raise ProductWorkError("请先等待原讨论停止，再按新资料关联继续")
    link = BudgetLedger._link(c, context.tenant.id, parent_id)
    if link is None:
        raise BudgetLedgerError("BUDGET_PARENT_RUN_UNBOUND")
    from app.ai.run_progress import _budget

    budget = _budget(
        c, context.tenant.id, parent_id, c.execute(select(func.clock_timestamp())).scalar_one()
    )
    if budget is None or budget.remaining_tokens <= 0:
        raise ProductWorkError("原累计额度已用尽，关联继续不会重新分配预算")
    intents, dispatched, observed = (
        tables.agent_tool_intents,
        tables.agent_tool_dispatches,
        tables.application_tool_observations,
    )
    unknown_research = c.execute(
        select(dispatched.c.intent_id)
        .join(
            intents,
            (intents.c.tenant_id == dispatched.c.tenant_id)
            & (intents.c.id == dispatched.c.intent_id),
        )
        .where(
            intents.c.tenant_id == context.tenant.id,
            intents.c.lineage_id == link["id"],
            intents.c.tool_key.in_(("research.search_public", "research.capture_snapshot")),
            ~select(observed.c.id)
            .where(
                observed.c.tenant_id == dispatched.c.tenant_id,
                observed.c.tool_intent_id == dispatched.c.intent_id,
            )
            .exists(),
        )
        .limit(1)
    ).first()
    if unknown_research:
        raise ProductWorkError("原共享请求有结果未知的研究读取，不能另开关联讨论重复派发")
    if budget.unresolved_calls:
        raise ProductWorkError("原共享请求仍有未结算或结果未知的调用，请先核对后继续")
    try:
        c.execute(
            text("SELECT cehub_ai.check_run_active_budget(:t,:r)"),
            {"t": context.tenant.id, "r": parent_id},
        )
    except DBAPIError as error:
        code = getattr(getattr(error.orig, "diag", None), "message_primary", "")
        if code.startswith("BUDGET_"):
            raise BudgetLedgerError(code) from error
        raise
    return link


def cancellation(c: Connection, tenant: UUID, run_id: UUID) -> bool:
    link, cancelled = tables.budget_run_links, tables.application_cancellations
    return (
        c.execute(
            select(cancelled.c.id)
            .join(
                link,
                (link.c.tenant_id == cancelled.c.tenant_id)
                & (link.c.lineage_id == cancelled.c.lineage_id),
            )
            .where(link.c.tenant_id == tenant, link.c.run_id == run_id)
        ).first()
        is not None
    )


def cancel_related(
    engine: Engine, context: AuthContext, project: UUID, ecr_id: UUID | None, run_id: UUID
) -> dict[str, Any]:
    from app.ai.change_discussion_contract import RUN_VERSION
    from app.ai.change_discussion_resume import RECOVERABLE
    from app.ai.change_discussion_runs import authorize, binding, event, result

    authorize(engine, context, project, edit=True)
    with engine.begin() as c:
        # Match the existing cancellation function's tenant -> budget -> run locks.
        c.execute(
            select(tables.tenants.c.id)
            .where(tables.tenants.c.id == context.tenant.id)
            .with_for_update()
        ).one()
        BudgetLedger._lock(c, context.tenant.id)
        runs = tables.agent_runs
        row = (
            c.execute(
                select(runs).where(
                    runs.c.tenant_id == context.tenant.id,
                    runs.c.project_id == project,
                    runs.c.id == run_id,
                    runs.c.requested_by_user_id == context.user.id,
                    runs.c.context_version == RUN_VERSION,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ProductWorkError("请由原发起人停止关联讨论")
        bound = binding(c, context.tenant.id, run_id)
        if bound["ecr_id"] != ecr_id:
            raise ProductWorkError("原讨论不属于当前话题")
        require_disclosure(c, context.tenant.id, context.user.id, bound)
        link = BudgetLedger._link(c, context.tenant.id, run_id)
        if link is None:
            raise ProductWorkError("原讨论缺少共享预算记录")
        # The SQL control also stops any other authorized application siblings.
        c.execute(
            text("SELECT cehub_ai.cancel_application_request(:t,:r,:a)"),
            {"t": context.tenant.id, "r": run_id, "a": context.user.id},
        ).scalar_one()
        links = tables.budget_run_links
        related = (
            c.execute(
                select(runs)
                .join(
                    links, (links.c.tenant_id == runs.c.tenant_id) & (links.c.run_id == runs.c.id)
                )
                .where(runs.c.tenant_id == context.tenant.id, links.c.lineage_id == link["id"])
                .order_by(runs.c.id)
                .with_for_update(of=runs)
            )
            .mappings()
            .all()
        )
        if any(r["requested_by_user_id"] != context.user.id for r in related):
            raise ProductWorkError("关联运行的发起人不一致，无法停止共享请求")
        if not cancellation(c, context.tenant.id, run_id):
            c.execute(
                tables.application_cancellations.insert().values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    run_id=run_id,
                    lineage_id=link["id"],
                    actor_user_id=context.user.id,
                    created_at=func.clock_timestamp(),
                )
            )
        for original in related:
            if original["context_version"] != RUN_VERSION:
                continue
            stopped = original["error_code"] == "APPLICATION_REQUEST_CANCELLED"
            pending = original["status"] == "degraded" and original["error_code"] in RECOVERABLE
            if not stopped and not pending:
                continue
            b = binding(c, context.tenant.id, original["id"])
            session_status = c.execute(
                select(tables.debate_sessions.c.status).where(
                    tables.debate_sessions.c.id == b["session_id"]
                )
            ).scalar_one()
            if session_status == "cancelled" and not original["run_context"].get(
                "discussion_recovery_requested"
            ):
                continue
            c.execute(
                runs.update()
                .where(runs.c.id == original["id"])
                .values(
                    status="failed",
                    error_code="APPLICATION_REQUEST_CANCELLED",
                    completed_at=func.clock_timestamp(),
                    updated_at=func.clock_timestamp(),
                    run_context={**original["run_context"], "discussion_recovery_requested": False},
                )
            )
            c.execute(
                tables.debate_sessions.update()
                .where(tables.debate_sessions.c.id == b["session_id"])
                .values(
                    status="cancelled",
                    stop_reason="related_request_cancelled",
                    updated_at=func.clock_timestamp(),
                )
            )
            event(
                c, context.tenant.id, b["session_id"], "related_request_cancelled", context.user.id
            )
        current = c.execute(select(runs).where(runs.c.id == run_id)).mappings().one()
        return result(c, current)
