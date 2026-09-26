"""In-app discussion reminders derived by the existing app-role scheduler."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import ColumnElement, Connection, and_, exists, or_, select

from app.ai.change_discussion_resume import RECOVERABLE
from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables
from app.domain.product_workspace import digest

if TYPE_CHECKING:
    from app.domain.reminders import ReminderSpec

ENTITY = "change_discussion"
READ_ROLES = tuple(
    role.value
    for role in Role
    if all(
        is_allowed(role, action)
        for action in (
            Action.MY_WORK_VIEW,
            Action.CHANGE_VIEW,
            Action.QUALITY_VIEW,
            Action.PRODUCT_ENGINEERING_VIEW,
        )
    )
)


def _recipient_scope(user: Any, binding: Any) -> ColumnElement[bool]:
    member = tables.project_members
    return and_(
        user.c.is_active.is_(True),
        user.c.role.in_(READ_ROLES),
        or_(
            user.c.role.in_((Role.OWNER.value, Role.ADMIN.value)),
            exists(
                select(member.c.id).where(
                    member.c.tenant_id == binding.c.tenant_id,
                    member.c.project_id == binding.c.project_id,
                    member.c.user_id == user.c.id,
                )
            ),
        ),
    )


def notification_visible() -> ColumnElement[bool]:
    """Recheck current project reach before exposing retained historical notification text."""
    from app.domain.meeting_notifications import visible as meeting_visible

    reminder = tables.reminders
    b, u, tenant = tables.debate_run_bindings, tables.users, tables.tenants
    return or_(
        reminder.c.target_entity.not_in((ENTITY, "meeting")),
        and_(reminder.c.target_entity == "meeting", meeting_visible()),
        exists(
            select(b.c.run_id)
            .select_from(b)
            .correlate(reminder)
            .join(u, (u.c.tenant_id == b.c.tenant_id) & (u.c.id == reminder.c.recipient_user_id))
            .join(tenant, tenant.c.id == b.c.tenant_id)
            .where(
                reminder.c.target_entity == ENTITY,
                b.c.tenant_id == reminder.c.tenant_id,
                b.c.project_id == reminder.c.project_id,
                b.c.run_id == reminder.c.target_entity_id,
                tenant.c.status == "active",
                _recipient_scope(u, b),
            )
        ),
    )


def specs(c: Connection, tenant_id: UUID, project_id: UUID, as_of: datetime) -> list[ReminderSpec]:
    from app.domain.reminders import ReminderSpec

    run, b, u, tenant = tables.agent_runs, tables.debate_run_bindings, tables.users, tables.tenants
    base = (
        b.join(run, (run.c.tenant_id == b.c.tenant_id) & (run.c.id == b.c.run_id))
        .join(u, (u.c.tenant_id == b.c.tenant_id) & (u.c.id == run.c.requested_by_user_id))
        .join(tenant, tenant.c.id == b.c.tenant_id)
    )
    scope = [
        b.c.tenant_id == tenant_id,
        b.c.project_id == project_id,
        tenant.c.status == "active",
        _recipient_scope(u, b),
    ]
    query = (
        select(run, b.c.config)
        .select_from(base)
        .where(
            *scope,
            run.c.status.in_(("succeeded", "degraded", "failed")),
            run.c.completed_at.is_not(None),
            run.c.completed_at <= as_of,
        )
    )
    items = []
    for record in c.execute(query).mappings():
        if record["error_code"] == "APPLICATION_REQUEST_CANCELLED":
            continue
        if (
            record["status"] == "degraded"
            and record["error_code"] in RECOVERABLE
            and record["run_context"].get("discussion_recovery_requested")
        ):
            continue
        if record["status"] == "succeeded":
            policy, label = "discussion_completed", "讨论已完成，请核对摘要"
        elif (record["error_code"] or "").startswith("BUDGET_") or record[
            "error_code"
        ] == "DAILY_BUDGET_EXCEEDED":
            policy, label = "discussion_budget_stopped", "讨论因预算停止，已保存的发言可回看"
        else:
            policy, label = "discussion_interrupted", "讨论已中断，请查看当前进度与处置"
        version = digest(
            {
                "status": record["status"],
                "error": record["error_code"],
                "at": record["completed_at"].isoformat(),
            }
        )[:24]
        items.append(
            ReminderSpec(
                dedupe_key=f"discussion-stop:{record['id']}:{version}",
                policy_key=policy,
                target_entity=ENTITY,
                target_entity_id=record["id"],
                recipient_user_id=record["requested_by_user_id"],
                title=f"{label}：{record['config']['request']['question']}"[:512],
                fire_at=record["completed_at"],
            )
        )
    review = tables.debate_brief_reviews
    newer = review.alias("newer_discussion_comparison")
    reviewed = (
        select(
            review.c.id,
            review.c.created_at,
            review.c.body,
            run.c.id.label("run_id"),
            run.c.requested_by_user_id,
            b.c.config,
        )
        .select_from(
            base.join(
                review, (review.c.tenant_id == b.c.tenant_id) & (review.c.run_id == b.c.run_id)
            )
        )
        .where(
            *scope,
            review.c.created_at <= as_of,
            review.c.created_by_user_id != run.c.requested_by_user_id,
            ~exists(
                select(newer.c.id).where(
                    newer.c.tenant_id == review.c.tenant_id,
                    newer.c.run_id == review.c.run_id,
                    or_(
                        newer.c.created_at > review.c.created_at,
                        and_(newer.c.created_at == review.c.created_at, newer.c.id > review.c.id),
                    ),
                )
            ),
        )
    )
    for record in c.execute(reviewed).mappings():
        label = (
            "摘要已有具名核对记录"
            if record["body"]["outcome"] == "validated"
            else "摘要已被退回，请查看对照意见"
        )
        items.append(
            ReminderSpec(
                dedupe_key=f"discussion-review:{record['id']}",
                policy_key="discussion_brief_reviewed",
                target_entity=ENTITY,
                target_entity_id=record["run_id"],
                recipient_user_id=record["requested_by_user_id"],
                title=f"{label}：{record['config']['request']['question']}"[:512],
                fire_at=record["created_at"],
            )
        )
    return items
