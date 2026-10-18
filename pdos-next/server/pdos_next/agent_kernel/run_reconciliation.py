"""Technical outcome closure. Never invokes a model or repeats a business/external action."""

from datetime import timedelta
from uuid import uuid4

from pydantic import Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from pdos_next.clock import now
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.model_configuration.commands import CurrentAdministrator
from pdos_next.model_configuration.ports import ManagementContext
from pdos_next.models import Principal, Receipt, RequestKey
from pdos_next.schema_base import StrictModel
from pdos_next.service import receipt_view

from .execution import scope_for_run
from .models import AgentEvent, AgentRun, AgentToolCall
from .persistence import KernelStore

AFTER = timedelta(minutes=5)
TERMINAL = frozenset({"completed", "partial", "failed", "cancelled"})


class ReconcileInput(StrictModel):
    expected_cancel_epoch: int = Field(strict=True, ge=0)


def required(run):
    return run.state == "waiting_input" and run.error_code == "EXTERNAL_OUTCOME_UNKNOWN"


def completed_record(session, run):
    # A model may use any business-result field name. Only this server-written,
    # append-only event proves that technical reconciliation actually happened.
    event = session.scalar(
        select(AgentEvent)
        .where(
            AgentEvent.run_id == run.id,
            AgentEvent.body["type"].astext == "run_reconciled",
        )
        .order_by(AgentEvent.sequence.desc())
        .limit(1)
    )
    if event is None:
        return None
    keys = {
        "event_id",
        "mode",
        "initiated_by",
        "closed_at",
        "original_cancel_epoch",
        "business_receipt_count",
        "recovered_call_count",
        "failed_call_count",
        "held_tokens",
        "estimated_micro_usd",
        "may_start_new_request",
        "external_effect_unknown",
    }
    if event.body.get("event_id") != str(event.id) or not keys <= event.body.keys():
        raise DomainError("SOURCE_UNAVAILABLE", "原核对记录无法与实际运行事件核对。")
    return {key: event.body[key] for key in keys}


def owner(session, ctx, run):
    actor = session.get(Principal, ctx.actor_id)
    if (
        run is None
        or run.tenant_id != ctx.tenant_id
        or run.category_id != ctx.category_id
        or run.requester_id != ctx.requester_id
        or ctx.actor_id != ctx.requester_id
        or ctx.run_id
        or ctx.agent_run_id
        or not actor
        or not actor.active
        or actor.kind != "human"
    ):
        raise DomainError("FORBIDDEN_SCOPE", "只能核对当前有权读取的本人运行。", 403)
    from .project_scope import require_run_project

    require_run_project(session, ctx, run)
    if run.proposal_id:
        from pdos_next.domain.preproject.access import proposal

        proposal(session, ctx, run.proposal_id)
    return run


def administrator(session, ctx):
    return CurrentAdministrator(session, ctx).is_current_human_admin(
        ManagementContext(ctx.tenant_id, ctx.actor_id)
    )


def mark_required(store, scope):
    with store.transaction(scope, lock=True) as (session, run):
        if not required(run):
            return
        exists = session.scalar(
            select(AgentEvent.id)
            .where(
                AgentEvent.run_id == run.id,
                AgentEvent.body["type"].astext == "reconciliation_required",
            )
            .limit(1)
        )
        if not exists:
            sequence = (
                session.scalar(
                    select(func.coalesce(func.max(AgentEvent.sequence), 0)).where(
                        AgentEvent.run_id == run.id,
                    )
                )
                + 1
            )
            session.add(
                AgentEvent(
                    tenant_id=run.tenant_id,
                    run_id=run.id,
                    sequence=sequence,
                    body={
                        "type": "reconciliation_required",
                        "automatic_after_seconds": int(AFTER.total_seconds()),
                        "cancel_epoch": run.cancel_epoch,
                    },
                )
            )


def _calls(session, run):
    # No raw replies, model messages or tool parameters in the management projection.
    return session.execute(
        select(
            AgentToolCall.id,
            AgentToolCall.tool,
            AgentToolCall.state,
            AgentToolCall.call_key,
            AgentToolCall.receipt_id,
            AgentToolCall.execution_binding,
            AgentToolCall.charged_tokens,
            AgentToolCall.reserved_tokens,
            AgentToolCall.cost_state,
            AgentToolCall.cost_charged_micro_usd,
        )
        .where(AgentToolCall.run_id == run.id)
        .order_by(AgentToolCall.id)
    ).all()


def _receipts(session, run):
    if run.trigger == "automation_service":
        from pdos_next.domain.automations.service_runtime import run_binding

        run_binding(session, run)
        return session.execute(
            select(
                Receipt.id,
                Receipt.operation,
                Receipt.subject_type,
                Receipt.subject_id,
                Receipt.subject_revision,
            )
            .where(
                Receipt.agent_run_id == run.id,
                Receipt.actor_id == run.writer_id,
                Receipt.requester_id == run.requester_id,
            )
            .order_by(Receipt.id)
        ).all()
    prior = session.scalar(text("SELECT current_setting('pdos.actor_id',true)"))
    try:
        with session.begin_nested():
            session.execute(
                text("SELECT set_config('pdos.actor_id',:actor,true)"),
                {"actor": str(run.requester_id)},
            )
            ids = set(
                session.scalars(
                    text("SELECT kernel_reconciliation_receipt_ids(:id)"), {"id": run.id}
                )
            )
            rows = (
                session.execute(
                    select(
                        Receipt.id,
                        Receipt.operation,
                        Receipt.subject_type,
                        Receipt.subject_id,
                        Receipt.subject_revision,
                    ).where(Receipt.id.in_(ids))
                ).all()
                if ids
                else []
            )
            session.execute(
                text("SELECT set_config('pdos.actor_id',:actor,true)"), {"actor": prior or ""}
            )
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) == "P0001":
            raise DomainError("FORBIDDEN_SCOPE", "运行回执的当前读取范围已变化。", 403) from None
        raise
    if {row.id for row in rows} != ids:
        raise DomainError(
            "FORBIDDEN_SCOPE", "运行包含当前不可读的回执，不能将其当作没有结果。", 403
        )
    return sorted(rows, key=lambda row: row.id)


def inspect(session, ctx, run, *, call_cursor=None, receipt_cursor=None, page_size=50):
    owner(session, ctx, run)
    calls, receipts = _calls(session, run), _receipts(session, run)
    anchor = session.scalar(
        select(AgentEvent)
        .where(
            AgentEvent.run_id == run.id,
            AgentEvent.body["type"].astext == "reconciliation_required",
        )
        .order_by(AgentEvent.sequence)
        .limit(1)
    )
    if call_cursor is not None and call_cursor not in {row.id for row in calls}:
        raise DomainError("FORBIDDEN_SCOPE", "调用游标不属于当前运行。", 403)
    if receipt_cursor is not None and receipt_cursor not in {row.id for row in receipts}:
        raise DomainError("FORBIDDEN_SCOPE", "回执游标不属于当前运行。", 403)
    call_page = [row for row in calls if call_cursor is None or row.id > call_cursor]
    receipt_page = [row for row in receipts if receipt_cursor is None or row.id > receipt_cursor]
    return {
        "run_id": str(run.id),
        "status": run.state,
        "cancel_epoch": run.cancel_epoch,
        "required": required(run),
        "can_finalize": required(run) and administrator(session, ctx),
        "automatic_after": (anchor.created_at + AFTER).isoformat() if anchor else None,
        "counts": {
            "calls": len(calls),
            "pending_calls": sum(row.state in {"started", "unknown"} for row in calls),
            "business_receipts": len(receipts),
        },
        "held_tokens": run.held_tokens,
        "estimated_micro_usd": sum(
            row.cost_charged_micro_usd for row in calls if row.cost_state == "estimated_unknown"
        ),
        "completed": completed_record(session, run),
        "calls": [
            {
                "id": str(row.id),
                "tool": row.tool,
                "state": row.state,
                "receipt_id": str(row.receipt_id) if row.receipt_id else None,
                "charged_tokens": row.charged_tokens,
                "held_tokens": row.reserved_tokens,
                "cost_state": row.cost_state,
            }
            for row in call_page[:page_size]
        ],
        "receipts": [
            {
                "id": str(row.id),
                "operation": row.operation,
                "subject_type": row.subject_type,
                "subject_id": str(row.subject_id),
                "subject_revision": row.subject_revision,
            }
            for row in receipt_page[:page_size]
        ],
        "next_call_cursor": str(call_page[page_size - 1].id)
        if len(call_page) > page_size
        else None,
        "next_receipt_cursor": str(receipt_page[page_size - 1].id)
        if len(receipt_page) > page_size
        else None,
    }


def finalize(
    engine, ctx, run_id, *, expected_cancel_epoch=None, automatic=False, activity_exhausted=False
):
    with tenant_session(
        engine,
        ctx.tenant_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        category_id=ctx.category_id,
    ) as session:
        run = session.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
        if automatic and run is not None and run.trigger == "automation_service":
            from pdos_next.domain.automations.service_runtime import run_binding

            if (
                ctx.actor_id != run.writer_id
                or ctx.requester_id != run.requester_id
                or ctx.category_id != run.category_id
                or ctx.agent_run_id
                or ctx.run_id
            ):
                raise DomainError("FORBIDDEN_SCOPE", "后台核对须使用实际服务运行身份。", 403)
            run_binding(session, run)
        else:
            run = owner(session, ctx, run)
        previous = completed_record(session, run)
        if previous is not None:
            if (
                expected_cancel_epoch is not None
                and previous["original_cancel_epoch"] != expected_cancel_epoch
            ):
                raise DomainError("VERSION_CONFLICT", "原核对请求的运行版本不一致。")
            return {"run_id": str(run.id), "status": run.state, "reconciliation": previous}
        if run.state in TERMINAL or run.reverted_at:
            return {"run_id": str(run.id), "status": run.state, "reconciliation": None}
        if not required(run) and not (
            automatic and activity_exhausted and run.state in {"queued", "running"}
        ):
            raise DomainError("VERSION_CONFLICT", "此运行正在执行或等待正常答复，无须结束等待。")
        if expected_cancel_epoch is not None and expected_cancel_epoch != run.cancel_epoch:
            raise DomainError("VERSION_CONFLICT", "运行状态已变化，请重新核对。")
        if not automatic:
            if not administrator(session, ctx):
                raise DomainError("FORBIDDEN_SCOPE", "提前结束等待由当前租户管理员办理。", 403)
        scope = scope_for_run(run)
        original_epoch = run.cancel_epoch
        # Technical state belongs to the stored Run identity. The actual human/system
        # initiator is recorded separately; no business command or approval is executed.
        session.execute(
            text("SELECT set_config('pdos.actor_id',:actor,true)"), {"actor": str(run.writer_id)}
        )
        session.info["scope"] = (run.tenant_id, run.writer_id, run.requester_id, run.category_id)
        KernelStore(engine).authority(session, scope)
        calls = _calls(session, run)
        pending = [row for row in calls if row.state in {"started", "unknown"}]
        recovered = []
        for call in pending:
            receipt = session.scalar(
                select(Receipt)
                .join(RequestKey, RequestKey.receipt_id == Receipt.id)
                .where(
                    RequestKey.actor_id == run.writer_id,
                    RequestKey.key == call.call_key,
                    Receipt.agent_run_id == run.id,
                    Receipt.actor_id == run.writer_id,
                    Receipt.requester_id == run.requester_id,
                    Receipt.operation == call.tool,
                )
            )
            if receipt is not None and call.tool != "model":
                actual = session.get(AgentToolCall, call.id)
                if call.execution_binding.get("kind") == "domain_t0":
                    from .execution import finish_domain_call

                    finish_domain_call(session, scope, actual.id, receipt.id)
                else:
                    if actual.state == "started" and actual.reserved_tokens:
                        session.execute(
                            text(
                                "SELECT kernel_release_call("
                                ":run,:call,'EXTERNAL_OUTCOME_UNKNOWN',true,0,NULL)"
                            ),
                            {"run": run.id, "call": actual.id},
                        )
                        session.refresh(actual)
                        session.refresh(run)
                    actual.state, actual.receipt_id, actual.result = (
                        "completed",
                        receipt.id,
                        receipt_view(receipt),
                    )
                    actual.error_code = None
                recovered.append(str(call.id))
        session.flush()
        # The existing trigger charges the original bounded estimate and releases
        # both Run and wallet reservations. No unknown call is treated as free.
        session.execute(
            text("""SELECT kernel_release_call(:run,id,'EXTERNAL_OUTCOME_UNKNOWN',true,0,NULL)
            FROM agent_tool_calls WHERE run_id=:run AND state='started' ORDER BY id"""),
            {"run": run.id},
        )
        session.expire_all()
        run = session.get(AgentRun, run_id)
        remaining = list(
            session.scalars(
                select(AgentToolCall)
                .where(
                    AgentToolCall.run_id == run.id,
                    AgentToolCall.state == "unknown",
                )
                .order_by(AgentToolCall.id)
                .with_for_update()
            )
        )
        uncertain_external = any(
            row.tool.startswith("mcp.") and row.execution_binding.get("dispatch") != "mcp-read/v1"
            for row in remaining
        )
        for call in remaining:
            call.state, call.error_code = "failed", "EXTERNAL_OUTCOME_UNKNOWN"
        session.flush()
        receipts = _receipts(session, run)
        finished = _calls(session, run)
        identity = uuid4()
        record = {
            "event_id": str(identity),
            "mode": "automatic" if automatic else "administrator",
            "initiated_by": None if automatic else str(ctx.actor_id),
            "closed_at": now().isoformat(),
            "original_cancel_epoch": original_epoch,
            "business_receipt_count": len(receipts),
            "recovered_call_count": len(recovered),
            "failed_call_count": len(remaining),
            "held_tokens": run.held_tokens,
            "estimated_micro_usd": sum(
                row.cost_charged_micro_usd
                for row in finished
                if row.cost_state == "estimated_unknown"
            ),
            "may_start_new_request": True,
            "external_effect_unknown": uncertain_external,
        }
        summary = (
            f"原运行已核对：保留 {len(receipts)} 条已提交动作，"
            f"{len(remaining)} 次不确定调用已结束等待。"
        )
        run.state = "partial" if receipts else "failed"
        run.error_code, run.cancel_epoch = "EXTERNAL_OUTCOME_UNKNOWN", original_epoch + 1
        run.result = {
            "status": run.state,
            "summary": summary,
            "result": {"reconciliation": record},
            "questions": [],
            "unfinished": [
                "原目标尚未全部完成。核对已有结果后，可调整目标以新请求继续；不自动重复原调用。"
            ],
        }
        sequence = (
            session.scalar(
                select(func.coalesce(func.max(AgentEvent.sequence), 0)).where(
                    AgentEvent.run_id == run.id
                )
            )
            + 1
        )
        session.add(
            AgentEvent(
                id=identity,
                tenant_id=run.tenant_id,
                run_id=run.id,
                sequence=sequence,
                body={
                    "type": "run_reconciled",
                    **record,
                    "recovered_call_ids": recovered,
                    "failed_call_ids": [str(row.id) for row in remaining],
                    "business_receipt_ids": [str(row.id) for row in receipts],
                },
            )
        )
        session.flush()
        session.execute(
            text("SELECT set_config('pdos.actor_id',:actor,true)"), {"actor": str(ctx.actor_id)}
        )
        session.info["scope"] = (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id)
        if not automatic and not administrator(session, ctx):
            raise DomainError("FORBIDDEN_SCOPE", "当前管理员资格已变化。", 403)
        return {"run_id": str(run.id), "status": run.state, "reconciliation": record}
