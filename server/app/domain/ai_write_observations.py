"""Read-only, receipt-derived trial observations; never a write qualification."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, func, select

from app.db.schema import tables


def observation_query(tenant_id: UUID, as_of: datetime) -> Any:
    """One row per original draft before aggregation, regardless of edit count."""
    drafts = tables.ai_meeting_drafts
    actions = tables.ai_meeting_draft_actions
    calls = tables.model_invocations
    runs = tables.agent_runs
    policies = tables.ai_write_policies
    history = (
        select(
            actions.c.draft_id,
            func.bool_or(actions.c.action == "confirm").label("confirmed"),
            func.bool_or(actions.c.action == "edit").label("edited"),
            func.bool_or(actions.c.action == "withdraw").label("withdrawn"),
            func.bool_or(actions.c.action == "publish").label("published"),
        )
        .where(actions.c.tenant_id == tenant_id, actions.c.created_at <= as_of)
        .group_by(actions.c.draft_id)
        .subquery()
    )
    confirmed = func.coalesce(history.c.confirmed, False)
    edited = func.coalesce(history.c.edited, False)
    withdrawn = func.coalesce(history.c.withdrawn, False)
    dimensions = (
        drafts.c.draft_kind,
        policies.c.revision.label("policy_revision"),
        calls.c.provider,
        calls.c.model,
        calls.c.model_version,
        calls.c.prompt_version,
        runs.c.context_version,
    )
    return (
        select(
            *dimensions,
            func.count().label("generated"),
            func.count().filter(confirmed).label("confirmed"),
            func.count().filter(edited).label("edited"),
            func.count().filter(withdrawn).label("withdrawn"),
            func.count().filter(confirmed | withdrawn).label("handled"),
            func.count().filter(~confirmed & ~withdrawn).label("pending"),
            func.count().filter(confirmed & ~edited & ~withdrawn).label("retained_original"),
            func.count().filter(confirmed & withdrawn).label("withdrawn_after_confirmation"),
            func.count().filter(func.coalesce(history.c.published, False)).label("published"),
        )
        .select_from(
            drafts.join(
                calls,
                (calls.c.tenant_id == drafts.c.tenant_id)
                & (calls.c.id == drafts.c.model_invocation_id),
            )
            .join(
                runs,
                (runs.c.tenant_id == drafts.c.tenant_id) & (runs.c.id == drafts.c.run_id),
            )
            .join(
                policies,
                (policies.c.tenant_id == drafts.c.tenant_id)
                & (policies.c.id == drafts.c.policy_id),
            )
            .outerjoin(history, history.c.draft_id == drafts.c.id)
        )
        .where(
            drafts.c.tenant_id == tenant_id,
            drafts.c.capture_mode == "trial",
            drafts.c.created_at >= as_of - timedelta(days=30),
            drafts.c.created_at <= as_of,
        )
        .group_by(*dimensions)
    )


class AiWriteObservationService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def get(
        self, *, tenant_id: UUID, as_of: datetime | None = None, offset: int = 0
    ) -> dict[str, Any]:
        observed_at = as_of or datetime.now(UTC)
        groups = observation_query(tenant_id, observed_at).subquery()
        query = select(groups).order_by(
            groups.c.draft_kind,
            groups.c.policy_revision.desc(),
            groups.c.provider,
            groups.c.model,
            groups.c.model_version.asc().nulls_first(),
            groups.c.prompt_version,
            groups.c.context_version,
        )
        with self.engine.connect() as connection:
            rows = connection.execute(query.offset(offset).limit(21)).mappings().all()
        return {
            "as_of": observed_at,
            "window_start": observed_at - timedelta(days=30),
            "items": [dict(row) for row in rows[:20]],
            "next_offset": offset + 20 if len(rows) > 20 else None,
            "qualification_granted": False,
            "scope_notice": "按草稿生成时间统计近30天的会议试运行，办理状态截至本次读取时点。"
            "不同政策、模型、提示词和上下文版本分别列示；未确认稿不计入已办理分母。"
            "未登记的模型版本保留未知；这些观察不代替真实评测、抽检或自动写入资格。",
        }
