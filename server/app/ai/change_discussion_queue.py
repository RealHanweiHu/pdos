"""Existing application worker adapter for persisted professional discussion requests."""

import logging
from contextlib import suppress
from typing import Any
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, and_, func, or_, select, text

from app.ai.application_gateway import ApplicationModelGateway
from app.ai.application_leases import ApplicationLeaseKeeper
from app.ai.application_queue_claim import claim_application_queue
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.change_discussion_contract import KEY, PURPOSE, RUN_VERSION
from app.ai.change_discussion_resume import (
    RECOVERABLE,
)
from app.ai.change_discussion_resume import (
    claim as claim_resume,
)
from app.ai.change_discussion_resume import (
    request as request_resume,
)
from app.ai.change_discussion_runs import ChangeDiscussionRuns, authorize, binding, event, result
from app.ai.discussion_sources import require_disclosure
from app.ai.rollout_guard import require_live_key
from app.auth.repository import AuthContext, AuthRepository
from app.db.schema import tables
from app.domain.debates import DebateService
from app.domain.product_workspace import ProductWorkError

logger = logging.getLogger(__name__)


class HumanInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    content: str = Field(min_length=1, max_length=4000)


def control(
    engine: Engine,
    context: AuthContext,
    project: UUID,
    ecr_id: UUID | None,
    run_id: UUID,
    action: str,
    message: HumanInput | None = None,
) -> dict[str, Any]:
    if action == "cancel_related":
        from app.ai.discussion_lineage import cancel_related

        return cancel_related(engine, context, project, ecr_id, run_id)
    authorize(engine, context, project, edit=True)
    with engine.begin() as c:
        c.execute(
            text(
                "SELECT pg_advisory_xact_lock(hashtextextended("
                "'pdos-budget:' || CAST(:t AS text),0))"
            ),
            {"t": context.tenant.id},
        )
        t = tables.agent_runs
        row = (
            c.execute(
                select(t)
                .where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.project_id == project,
                    t.c.id == run_id,
                    t.c.context_version == RUN_VERSION,
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ProductWorkError("原讨论不存在")
        b = binding(c, context.tenant.id, run_id)
        require_disclosure(c, context.tenant.id, context.user.id, b)
        if b["ecr_id"] != ecr_id:
            raise ProductWorkError("原讨论不属于此变更")
        s = tables.debate_sessions
        session = (
            c.execute(
                select(s)
                .where(s.c.tenant_id == context.tenant.id, s.c.id == b["session_id"])
                .with_for_update()
            )
            .mappings()
            .one()
        )
        if action == "input" and message is not None:
            turn_id = uuid5(
                b["session_id"], f"pdos-discussion-input:{context.user.id}:{message.request_id}"
            )
            turns = tables.debate_turns
            old = (
                c.execute(
                    select(turns).where(
                        turns.c.tenant_id == context.tenant.id, turns.c.id == turn_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old:
                if old["content"] != message.content:
                    raise ProductWorkError("原插话请求已有不同内容")
                return result(c, row)
            if row["status"] not in {"queued", "running"} or session["status"] not in {
                "convened",
                "preparing",
                "arguing",
            }:
                raise ProductWorkError("讨论已停止，不能追加本次输入")
            c.execute(
                turns.insert().values(
                    id=turn_id,
                    tenant_id=context.tenant.id,
                    session_id=b["session_id"],
                    round_number=session["round_count"],
                    sequence=DebateService._next_sequence(
                        c, tenant_id=context.tenant.id, session_id=b["session_id"]
                    ),
                    speaker_kind="human",
                    author_user_id=context.user.id,
                    content=message.content,
                    citations=[],
                    input_tokens=0,
                    output_tokens=0,
                    created_at=func.clock_timestamp(),
                )
            )
        elif action in {"cancel", "recover"}:
            if row["requested_by_user_id"] != context.user.id:
                raise ProductWorkError("请由原发起人办理停止或恢复")
            if action == "cancel":
                if row["error_code"] == "APPLICATION_REQUEST_CANCELLED":
                    return result(c, row)
                if row["status"] not in {"queued", "running"} and not (
                    row["status"] == "degraded"
                    and row["run_context"].get("discussion_recovery_requested")
                ):
                    raise ProductWorkError("原运行已停止")
                row = (
                    c.execute(
                        t.update()
                        .where(t.c.id == run_id)
                        .values(
                            status="degraded",
                            error_code="APPLICATION_REQUEST_CANCELLED",
                            run_context={
                                **row["run_context"],
                                "discussion_recovery_requested": False,
                            },
                            completed_at=func.clock_timestamp(),
                            updated_at=func.clock_timestamp(),
                        )
                        .returning(t)
                    )
                    .mappings()
                    .one()
                )
                c.execute(
                    s.update()
                    .where(s.c.id == b["session_id"])
                    .values(
                        status="cancelled",
                        stop_reason="user_cancelled",
                        updated_at=func.clock_timestamp(),
                    )
                )
            else:
                updated_context = request_resume(c, row, b, context.user.id)
                row = (
                    c.execute(
                        t.update()
                        .where(t.c.id == run_id)
                        .values(run_context=updated_context, updated_at=func.clock_timestamp())
                        .returning(t)
                    )
                    .mappings()
                    .one()
                )
        else:
            raise ProductWorkError("未知讨论操作")
        event(c, context.tenant.id, b["session_id"], action, context.user.id)
        return result(c, row)


class ChangeDiscussionQueue:
    def __init__(self, engine: Engine, *, gateway: ApplicationModelGateway):
        self.engine, self.gateway = engine, gateway

    def run_next(self) -> bool:
        t = tables.agent_runs
        bindings, origin = tables.debate_run_bindings, tables.agent_runs.alias("origin_analysis")
        # A convened child shares its parent's model/tool budget. Let the original
        # analysis finish saving its candidate before claiming professional turns.
        origin_ready = (
            ~select(bindings.c.id)
            .join(
                origin,
                (origin.c.tenant_id == bindings.c.tenant_id)
                & (origin.c.id == bindings.c.origin_run_id),
            )
            .where(
                bindings.c.tenant_id == t.c.tenant_id,
                bindings.c.run_id == t.c.id,
                origin.c.status.in_(("queued", "running", "waiting_input")),
            )
            .correlate(t)
            .exists()
        )
        recoverable = and_(
            t.c.status == "degraded",
            t.c.error_code.in_(RECOVERABLE),
            t.c.run_context["discussion_recovery_requested"].as_boolean().is_(True),
        )
        row = None
        try:
            with self.engine.begin() as c:
                row = (
                    c.execute(
                        select(t)
                        .where(
                            t.c.context_version == RUN_VERSION,
                            origin_ready,
                            or_(t.c.status == "queued", recoverable),
                        )
                        .order_by(t.c.created_at, t.c.id)
                        .limit(1)
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    return False
                # Match model settlement and expiry: tenant budget lock before run ownership.
                c.execute(
                    text(
                        "SELECT pg_advisory_xact_lock(hashtextextended("
                        "'pdos-budget:' || CAST(:t AS text),0))"
                    ),
                    {"t": row["tenant_id"]},
                )
                row = (
                    c.execute(
                        select(t)
                        .where(
                            t.c.id == row["id"],
                            origin_ready,
                            or_(t.c.status == "queued", recoverable),
                        )
                        .with_for_update(skip_locked=True)
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    return False
                require_live_key(KEY)
                context = AuthRepository(self.engine).find_user_context(row["requested_by_user_id"])
                if context is None or context.tenant.id != row["tenant_id"]:
                    raise ProductWorkError("原发起人已不可用")
                authorize(self.engine, context, row["project_id"], edit=True)
                if row["status"] == "queued":
                    row = claim_application_queue(
                        c,
                        self.gateway,
                        row,
                        auth_version=context.user.auth_version,
                        purpose=PURPOSE,
                    )
                else:
                    row = claim_resume(
                        c, self.gateway, row, context.user.id, context.user.auth_version
                    )
            ChangeDiscussionRuns(self.engine, gateway=self.gateway).execute(row)
        except Exception as error:
            if row is None:
                raise
            code = getattr(error, "code", "DISCUSSION_EXECUTION_FAILED")
            keeper = getattr(self.gateway, "application_lease_keeper", None)
            acquired = (
                isinstance(keeper, ApplicationLeaseKeeper)
                and keeper.token(row["tenant_id"], row["id"]) is not None
            )
            if acquired:
                # Expired ownership stays with the lease expiry/recovery path.
                with suppress(BudgetLedgerError):
                    ChangeDiscussionRuns(self.engine, gateway=self.gateway).finish(
                        row,
                        "budget_stopped"
                        if code.startswith("BUDGET_") or code == "DAILY_BUDGET_EXCEEDED"
                        else "interrupted",
                        code,
                    )
            else:
                with self.engine.begin() as c:
                    stopped = c.execute(
                        t.update()
                        .where(
                            t.c.tenant_id == row["tenant_id"],
                            t.c.id == row["id"],
                            or_(t.c.status == "queued", recoverable),
                        )
                        .values(
                            status="degraded" if code in RECOVERABLE else "failed",
                            run_context={
                                **row["run_context"],
                                "discussion_recovery_requested": False,
                            },
                            error_code=code,
                            completed_at=func.clock_timestamp(),
                            updated_at=func.clock_timestamp(),
                        )
                        .returning(t.c.id)
                    ).first()
                    if stopped:
                        b = binding(c, row["tenant_id"], row["id"])
                        c.execute(
                            tables.debate_sessions.update()
                            .where(tables.debate_sessions.c.id == b["session_id"])
                            .values(
                                status="budget_stopped"
                                if code.startswith("BUDGET_") or code == "DAILY_BUDGET_EXCEEDED"
                                else "interrupted",
                                stop_reason=code,
                                updated_at=func.clock_timestamp(),
                            )
                        )
                        event(c, row["tenant_id"], b["session_id"], "worker_stopped")
            logger.warning("application_discussion_stopped run=%s reason=%s", row["id"], code)
        return True
