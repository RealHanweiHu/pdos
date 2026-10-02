"""Read-only operational progress; never expose prompts, observations or private inputs."""

from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, Engine, Table, func, select, text

from app.auth.errors import ObjectPermissionDeniedError
from app.auth.repository import AuthContext
from app.db.schema import tables

RunPhase = Literal[
    "debouncing",
    "queued",
    "running",
    "collecting",
    "tool",
    "model",
    "receipt_unknown",
    "saving",
    "waiting_input",
    "completed",
    "stopped",
    "cancelled",
    "paused",
    "pausing",
]


class RunBudgetProgress(BaseModel):
    lineage_id: UUID
    token_limit: int
    charged_tokens: int
    held_tokens: int
    remaining_tokens: int
    unresolved_calls: int
    active_seconds: float | None
    active_limit_seconds: int
    remaining_active_seconds: float | None
    absolute_deadline: datetime
    priced_model_cost_microusd: int
    model_cost_complete: bool


class RunProgress(BaseModel):
    model_config = ConfigDict(frozen=True)
    run_id: UUID
    status: str
    phase: RunPhase
    as_of: datetime
    stop_code: str | None
    saved_tool_steps: int
    tool_dispatches: int
    observations: int
    model_receipts: int
    saved_results: int
    last_tool: str | None
    budget: RunBudgetProgress | None


def _count(c: Connection, table: Table, tenant: UUID, run: UUID) -> int:
    return int(
        c.execute(
            select(func.count())
            .select_from(table)
            .where(table.c.tenant_id == tenant, table.c.run_id == run)
        ).scalar_one()
    )


def _budget(c: Connection, tenant: UUID, run: UUID, now: datetime) -> RunBudgetProgress | None:
    lineage = (
        c.execute(
            select(tables.budget_lineages)
            .join(
                tables.budget_run_links,
                (tables.budget_run_links.c.tenant_id == tables.budget_lineages.c.tenant_id)
                & (tables.budget_run_links.c.lineage_id == tables.budget_lineages.c.id),
            )
            .where(
                tables.budget_run_links.c.tenant_id == tenant,
                tables.budget_run_links.c.run_id == run,
            )
        )
        .mappings()
        .one_or_none()
    )
    if lineage is None:
        return None
    lid = lineage["id"]
    # Every journal revision is a snapshot. Sum only each attempt's latest revision.
    latest = (
        c.execute(
            text("""SELECT DISTINCT ON (attempt_id)
        call_kind,reservation_status,charged_tokens,held_tokens,dispatched_at
        FROM cehub_ai.budget_journal WHERE tenant_id=:tenant AND lineage_id=:lineage
        ORDER BY attempt_id,revision DESC"""),
            dict(tenant=tenant, lineage=lid),
        )
        .mappings()
        .all()
    )
    charged = sum(r["charged_tokens"] or 0 for r in latest)
    held = sum(r["held_tokens"] for r in latest)
    unresolved = sum(r["reservation_status"] in {"reserved", "unknown"} for r in latest)
    covered = (
        c.execute(
            select(tables.budget_activity_coverage.c.lineage_id).where(
                tables.budget_activity_coverage.c.tenant_id == tenant,
                tables.budget_activity_coverage.c.lineage_id == lid,
            )
        ).first()
        is not None
    )
    active = (
        float(
            c.execute(
                text("""SELECT coalesce(sum(greatest(0,extract(epoch FROM
        (least(:now,stopped_at,lease_expires_at)-started_at)))),0)
        FROM cehub_ai.budget_activity_spans WHERE tenant_id=:tenant AND lineage_id=:lineage"""),
                dict(tenant=tenant, lineage=lid, now=now),
            ).scalar_one()
        )
        if covered
        else None
    )
    costs = (
        c.execute(
            select(
                tables.model_invocations.c.cost_status,
                tables.model_invocations.c.normalized_cost_microusd,
            )
            .join(
                tables.budget_run_links,
                (tables.budget_run_links.c.tenant_id == tables.model_invocations.c.tenant_id)
                & (tables.budget_run_links.c.run_id == tables.model_invocations.c.run_id),
            )
            .where(
                tables.budget_run_links.c.tenant_id == tenant,
                tables.budget_run_links.c.lineage_id == lid,
            )
        )
        .mappings()
        .all()
    )
    known = {"priced", "not_invoked"}
    profile = lineage["profile"]
    return RunBudgetProgress(
        lineage_id=lid,
        token_limit=profile["lineage_token_limit"],
        charged_tokens=charged,
        held_tokens=held,
        remaining_tokens=max(0, profile["lineage_token_limit"] - charged - held),
        unresolved_calls=unresolved,
        active_seconds=active,
        active_limit_seconds=profile["active_seconds"],
        remaining_active_seconds=None
        if active is None
        else max(0, profile["active_seconds"] - active),
        absolute_deadline=lineage["absolute_deadline"],
        priced_model_cost_microusd=sum(
            r["normalized_cost_microusd"] or 0 for r in costs if r["cost_status"] in known
        ),
        model_cost_complete=all(r["cost_status"] in known for r in costs)
        and (
            bool(costs)
            or not any(r["call_kind"] == "model" and r["dispatched_at"] is not None for r in latest)
        )
        and not any(
            r["call_kind"] == "model"
            and r["dispatched_at"] is not None
            and r["reservation_status"] in {"reserved", "unknown"}
            for r in latest
        ),
    )


def read_progress(
    engine: Engine,
    *,
    context: AuthContext,
    project_id: UUID | None,
    run_id: UUID,
    market_space_id: UUID | None = None,
) -> RunProgress:
    # The API has authorized current project access. Private requests remain actor-bound.
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
        if market_space_id is not None:
            from app.ai.product_matrix_runs import run_row as matrix_run_row
            from app.ai.product_work_runs import run_row as product_run_row

            version = c.execute(
                select(tables.agent_runs.c.context_version).where(
                    tables.agent_runs.c.tenant_id == context.tenant.id,
                    tables.agent_runs.c.market_space_id == market_space_id,
                    tables.agent_runs.c.requested_by_user_id == context.user.id,
                    tables.agent_runs.c.id == run_id,
                )
            ).scalar_one_or_none()
            if version == "product-work-request-v1":
                product_run_row(c, context, market_space_id, run_id)
            else:
                matrix_run_row(c, context, market_space_id, run_id)
        elif project_id is None:
            from app.domain.process_templates import authorize

            authorize(c, context)
        now = c.execute(select(func.now())).scalar_one()
        row = (
            c.execute(
                select(
                    tables.agent_runs,
                    func.coalesce(
                        tables.agent_runs.c.requested_by_user_id,
                        tables.application_authorizations.c.principal_id,
                    ).label("actor"),
                )
                .outerjoin(
                    tables.application_authorizations,
                    (tables.application_authorizations.c.tenant_id == tables.agent_runs.c.tenant_id)
                    & (tables.application_authorizations.c.run_id == tables.agent_runs.c.id),
                )
                .where(
                    tables.agent_runs.c.tenant_id == context.tenant.id,
                    tables.agent_runs.c.project_id == project_id,
                    tables.agent_runs.c.scope_kind
                    == (
                        "market_space"
                        if market_space_id is not None
                        else "tenant"
                        if project_id is None
                        else "project"
                    ),
                    tables.agent_runs.c.market_space_id == market_space_id,
                    tables.agent_runs.c.id == run_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None or row["actor"] is not None and row["actor"] != context.user.id:
            raise ObjectPermissionDeniedError
        tenant = context.tenant.id
        observations = _count(c, tables.agent_tool_observations, tenant, run_id) + _count(
            c, tables.application_context_observations, tenant, run_id
        )
        steps = _count(c, tables.agent_loop_checkpoints, tenant, run_id)
        receipts = _count(c, tables.model_invocations, tenant, run_id)
        results = _count(c, tables.agent_result_checkpoints, tenant, run_id) + _count(
            c, tables.application_result_checkpoints, tenant, run_id
        )
        dispatches = _count(c, tables.agent_tool_dispatches, tenant, run_id)
        last_tool = c.execute(
            select(tables.agent_tool_intents.c.tool_key)
            .join(
                tables.agent_tool_dispatches,
                tables.agent_tool_dispatches.c.intent_id == tables.agent_tool_intents.c.id,
            )
            .where(
                tables.agent_tool_intents.c.tenant_id == tenant,
                tables.agent_tool_intents.c.run_id == run_id,
            )
            .order_by(tables.agent_tool_dispatches.c.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        pending_tool = (
            c.execute(
                select(tables.agent_tool_intents.c.id)
                .join(
                    tables.agent_tool_dispatches,
                    tables.agent_tool_dispatches.c.intent_id == tables.agent_tool_intents.c.id,
                )
                .outerjoin(
                    tables.agent_tool_observations,
                    tables.agent_tool_observations.c.tool_intent_id
                    == tables.agent_tool_intents.c.id,
                )
                .where(
                    tables.agent_tool_intents.c.tenant_id == tenant,
                    tables.agent_tool_intents.c.run_id == run_id,
                    tables.agent_tool_observations.c.id.is_(None),
                )
                .limit(1)
            ).first()
            is not None
        )
        outstanding = (
            c.execute(
                text("""SELECT reservation_status,dispatched_at FROM (
            SELECT DISTINCT ON (attempt_id) reservation_status,dispatched_at,call_kind
            FROM cehub_ai.budget_journal WHERE tenant_id=:tenant AND run_id=:run
            ORDER BY attempt_id,revision DESC) latest
            WHERE call_kind='model' AND reservation_status IN ('reserved','unknown')"""),
                dict(tenant=tenant, run=run_id),
            )
            .mappings()
            .all()
        )
        status = (
            "cancelled"
            if row["error_code"] in {"APPLICATION_REQUEST_CANCELLED", "EVENT_RUN_CANCELLED"}
            else row["status"]
        )
        pause = c.execute(
            select(tables.event_run_pauses.c.honored_at).where(
                tables.event_run_pauses.c.tenant_id == tenant,
                tables.event_run_pauses.c.run_id == run_id,
                tables.event_run_pauses.c.resolved_at.is_(None),
            )
        ).one_or_none()
        if pause is not None and status in {"debouncing", "queued", "running"}:
            status = "paused" if pause.honored_at is not None else "pausing"
        phase = (
            status
            if status in {"debouncing", "queued", "waiting_input", "cancelled", "paused", "pausing"}
            else "completed"
            if status == "succeeded"
            else "stopped"
            if status in {"failed", "degraded"}
            else "receipt_unknown"
            if any(r["reservation_status"] == "unknown" for r in outstanding)
            else "model"
            if any(r["dispatched_at"] is not None for r in outstanding)
            else "tool"
            if pending_tool
            else "saving"
            if results
            else "running"
            if observations
            else "collecting"
        )
        return RunProgress(
            run_id=run_id,
            status=status,
            phase=cast(RunPhase, phase),
            as_of=now,
            stop_code=row["error_code"],
            saved_tool_steps=steps,
            tool_dispatches=dispatches,
            observations=observations,
            model_receipts=receipts,
            saved_results=results,
            last_tool=last_tool,
            budget=_budget(c, tenant, run_id, now),
        )
