"""Resume known discussion progress under unchanged authority, lineage and limits."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, RowMapping, func, select, text
from sqlalchemy.exc import DBAPIError

from app.ai.application_authorization import policy_version
from app.ai.application_leases import ApplicationLeaseKeeper
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.change_discussion_contract import call_id
from app.ai.run_progress import _budget
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain

RECOVERABLE = (
    "APPLICATION_RUN_LEASE_EXPIRED",
    "DAILY_BUDGET_EXCEEDED",
    "BUDGET_TENANT_TOKENS_EXHAUSTED",
    "BUDGET_TENANT_CALL_BUSY",
    "BUDGET_LINEAGE_CALL_BUSY",
)


def state(c: Connection, row: Any, bound: Any) -> dict[str, Any]:
    tenant, run = row["tenant_id"], row["id"]
    now = c.execute(select(func.clock_timestamp())).scalar_one()
    budget = _budget(c, tenant, run, now)
    leases, receipts, checkpoints = (
        tables.application_run_leases,
        tables.debate_turn_receipts,
        tables.application_result_checkpoints,
    )
    lease = (
        c.execute(
            select(leases)
            .where(leases.c.tenant_id == tenant, leases.c.run_id == run)
            .order_by(leases.c.generation.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    saved = {
        (r.seat_id, r.round_number)
        for r in c.execute(
            select(receipts.c.seat_id, receipts.c.round_number).where(
                receipts.c.tenant_id == tenant, receipts.c.run_id == run
            )
        )
    }
    from app.ai.discussion_initiation import effective_config, receipt

    initiation = receipt(c, tenant, run)
    config = effective_config(bound["config"], initiation) if initiation else bound["config"]
    calls = [
        {
            "seat_id": seat["id"],
            "round_number": n,
            "model_call_id": str(call_id(run, UUID(seat["id"]), n)),
        }
        for n in range(1, bound["config"]["request"]["rounds"] + 1)
        for seat in config["seats"]
        if (UUID(seat["id"]), n) not in saved
    ]
    if config.get("initiation") and initiation is None:
        planning_id = config["initiation"]["id"]
        calls.insert(
            0,
            {
                "seat_id": planning_id,
                "round_number": 1,
                "model_call_id": str(call_id(run, UUID(planning_id), 1)),
            },
        )
    if config["request"].get("research_steps"):
        from app.ai.discussion_research_loop import research_call

        calls += [
            {
                "seat_id": seat["id"],
                "round_number": n,
                "model_call_id": str(research_call(run, UUID(seat["id"]), n, step)),
            }
            for n in range(1, config["request"]["rounds"] + 1)
            for seat in config["seats"]
            if (UUID(seat["id"]), n) not in saved
            for step in range(1, config["request"]["research_steps"] + 1)
        ]
    cp_ids = {
        str(v)
        for v in c.execute(
            select(checkpoints.c.model_call_id).where(
                checkpoints.c.tenant_id == tenant, checkpoints.c.run_id == run
            )
        ).scalars()
    }
    journal = tables.budget_journal
    prior_calls = set(
        c.execute(
            select(journal.c.request_binding["model_call_id"].as_string()).where(
                journal.c.tenant_id == tenant, journal.c.run_id == run
            )
        ).scalars()
    )
    unresolved_sessions = c.execute(
        text("""SELECT EXISTS(
      SELECT 1 FROM cehub_ai.model_call_sessions s
      WHERE s.tenant_id=:t AND s.run_id=:r AND NOT EXISTS(
       SELECT 1 FROM cehub_ai.model_call_events e WHERE e.tenant_id=s.tenant_id
       AND e.session_id=s.id AND e.state='closed'))"""),
        {"t": tenant, "r": run},
    ).scalar_one()
    tools, observations = tables.agent_tool_dispatches, tables.application_tool_observations
    unknown_tool = c.execute(
        select(tools.c.intent_id)
        .where(
            tools.c.tenant_id == tenant,
            tools.c.run_id == run,
            ~select(observations.c.id)
            .where(
                observations.c.tenant_id == tools.c.tenant_id,
                observations.c.run_id == tools.c.run_id,
                observations.c.tool_intent_id == tools.c.intent_id,
            )
            .exists(),
        )
        .limit(1)
    ).first()
    reasons = []
    if unknown_tool:
        reasons.append("研究工具已有派发但缺少实际结果，不能重复读取或伪造成功")
    from app.ai.discussion_lineage import cancellation

    if cancellation(c, tenant, run):
        reasons.append("原共享请求已停止，不能恢复或另开关联讨论")
    if row["status"] != "degraded" or row["error_code"] not in RECOVERABLE:
        reasons.append("本次停止不属于可按原预算接续的暂时中断")
    if lease is None:
        reasons.append("尚无原执行租约可接续")
    elif lease["generation"] >= 3:
        reasons.append("原运行恢复次数已达上限")
    elif lease["ended_at"] is None and lease["expires_at"] > now:
        reasons.append("原执行仍持有租约，请等待其停止")
    if budget is None:
        reasons.append("缺少原运行预算记录")
    else:
        if budget.absolute_deadline <= now:
            reasons.append("原运行绝对期限已到，恢复不能延长")
        if budget.remaining_tokens <= 0 or budget.remaining_active_seconds == 0:
            reasons.append("原运行累计额度已用尽，恢复不能重置")
        if budget.unresolved_calls or unresolved_sessions:
            reasons.append("仍有未结算或结果未知的调用，需先按原记录对账")
    if any(v["model_call_id"] in prior_calls and v["model_call_id"] not in cp_ids for v in calls):
        reasons.append("未完成席位已有调用预算记录但缺少可复用结果，不能重复派发")
    return _plain(
        {
            "can_request": not reasons,
            "reasons": reasons,
            "previous_lease_id": lease["id"] if lease else None,
            "generation": lease["generation"] if lease else None,
            "remaining_calls": calls,
            "budget": budget.model_dump(mode="json") if budget else None,
        }
    )


def request(c: Connection, row: Any, bound: Any, actor: UUID) -> dict[str, Any]:
    from app.ai.change_notice_preparation import require_discussion_enabled
    from app.ai.discussion_sources import current as current_source

    require_discussion_enabled(bound["source"])

    if row["run_context"].get("discussion_recovery_requested") and row["run_context"].get(
        "discussion_resume_request_id"
    ):
        return dict(row["run_context"])
    eligibility = state(c, row, bound)
    if not eligibility["can_request"]:
        raise ProductWorkError("；".join(eligibility["reasons"]))
    current = current_source(c, row["tenant_id"], row["project_id"], bound)
    if current["digest"] != bound["source"]["digest"]:
        raise ProductWorkError("原讨论资料已变化，请按当前资料重新分析")
    identity = uuid4()
    c.execute(
        tables.debate_resume_requests.insert().values(
            id=identity,
            tenant_id=row["tenant_id"],
            run_id=row["id"],
            previous_lease_id=UUID(eligibility["previous_lease_id"]),
            requested_by_user_id=actor,
            body={
                "source_digest": bound["source"]["digest"],
                "stop_code": row["error_code"],
                "remaining_calls": eligibility["remaining_calls"],
            },
        )
    )
    return {
        **row["run_context"],
        "discussion_recovery_requested": True,
        "discussion_resume_request_id": str(identity),
    }


def claim(
    c: Connection, gateway: Any, row: RowMapping, actor: UUID, auth_version: int | None
) -> RowMapping:
    from app.ai.change_discussion_runs import binding
    from app.ai.change_notice_preparation import require_discussion_enabled
    from app.ai.discussion_sources import current as current_source

    keeper, profile = (
        getattr(gateway, "application_lease_keeper", None),
        getattr(gateway, "creation_budget_profile", None),
    )
    if not isinstance(keeper, ApplicationLeaseKeeper) or profile is None:
        raise BudgetLedgerError("APPLICATION_RECOVERY_BUDGET_REQUIRED")
    bound = binding(c, row["tenant_id"], row["id"])
    require_discussion_enabled(bound["source"])
    if not row["run_context"].get("discussion_resume_request_id"):
        updated = request(c, row, bound, actor)
        row = (
            c.execute(
                tables.agent_runs.update()
                .where(tables.agent_runs.c.id == row["id"])
                .values(run_context=updated)
                .returning(tables.agent_runs)
            )
            .mappings()
            .one()
        )
    gateway.require_current_daily_budget(row["tenant_id"])
    eligibility = state(c, row, bound)
    if not eligibility["can_request"]:
        raise ProductWorkError("；".join(eligibility["reasons"]))
    current = current_source(c, row["tenant_id"], row["project_id"], bound)
    if current["digest"] != bound["source"]["digest"]:
        raise ProductWorkError("原讨论资料已变化")
    try:
        token = c.execute(
            text("""SELECT cehub_ai.claim_discussion_resume(
          :t,:r,:actor,:auth,:owner,:request,:policy,CAST(:profile AS jsonb))"""),
            {
                "t": row["tenant_id"],
                "r": row["id"],
                "actor": actor,
                "auth": auth_version,
                "owner": keeper.owner_id,
                "request": UUID(row["run_context"]["discussion_resume_request_id"]),
                "policy": policy_version(),
                "profile": json.dumps(profile.model_dump(mode="json")),
            },
        ).scalar_one()
    except DBAPIError as error:
        code = getattr(getattr(error.orig, "diag", None), "message_primary", "")
        if getattr(error.orig, "sqlstate", None) == "22023" and code.startswith(
            ("APPLICATION_", "BUDGET_")
        ):
            raise BudgetLedgerError(code) from error
        raise
    keeper.register_recovery(row["tenant_id"], row["id"], token)
    return (
        c.execute(select(tables.agent_runs).where(tables.agent_runs.c.id == row["id"]))
        .mappings()
        .one()
    )
