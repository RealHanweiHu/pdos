"""Xiaopai asks and escalations delivered through the existing reminder policy."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ColumnElement, Connection, exists, or_, select

from app.db.schema import tables

if TYPE_CHECKING:
    from app.domain.reminders import ReminderSpec


def recipient_allowed(
    user_id: object, tenant_id: object, project_id: object
) -> ColumnElement[bool]:
    u, m = tables.users, tables.project_members
    member = exists(
        select(m.c.id)
        .where(
            m.c.tenant_id == tenant_id,
            m.c.project_id == project_id,
            m.c.user_id == u.c.id,
        )
        .correlate(u, tables.reminders, tables.xiaopai_followups, tables.projects)
    )
    return exists(
        select(u.c.id)
        .where(
            u.c.id == user_id,
            u.c.tenant_id == tenant_id,
            u.c.is_active,
            u.c.role.not_in(("supplier", "customer")),
            or_(u.c.role.in_(("owner", "admin")), member),
        )
        .correlate(tables.reminders, tables.xiaopai_followups, tables.projects)
    )


def specs(c: Connection, tenant_id: UUID, project_id: UUID, now: datetime) -> list[ReminderSpec]:
    from app.domain.reminders import ReminderSpec

    f, d, t, p = (
        tables.xiaopai_followups,
        tables.xiaopai_delegations,
        tables.tasks,
        tables.projects,
    )
    rows = (
        c.execute(
            select(f, t.c.title, p.c.owner_user_id)
            .join(d, d.c.id == f.c.delegation_id)
            .join(t, t.c.id == f.c.task_id)
            .join(p, p.c.id == f.c.project_id)
            .where(
                f.c.tenant_id == tenant_id,
                f.c.project_id == project_id,
                d.c.status == "active",
                f.c.status.not_in(("resolved", "cancelled", "blocked")),
                t.c.status.not_in(("done", "skipped")),
                t.c.assignee_user_id == f.c.recipient_user_id,
                recipient_allowed(f.c.recipient_user_id, f.c.tenant_id, f.c.project_id),
            )
        )
        .mappings()
        .all()
    )
    result = []
    for row in rows:
        if row["status"] in {
            "pending",
            "waiting_reply",
            "waiting_progress",
            "no_reply",
            "no_progress",
        }:
            result.append(
                ReminderSpec(
                    dedupe_key=f"xiaopai:{row['id']}:ask",
                    policy_key="xiaopai_ask",
                    target_entity="task",
                    target_entity_id=row["task_id"],
                    recipient_user_id=row["recipient_user_id"],
                    title=f"小Pai询问进展：{row['title']}；请补充进展、阻塞与下一检查点"[:512],
                    fire_at=row["requested_at"],
                )
            )
        if (
            row["status"] in {"no_reply", "no_progress"}
            and row["owner_user_id"]
            and row["owner_user_id"] != row["recipient_user_id"]
            and c.execute(
                select(recipient_allowed(row["owner_user_id"], tenant_id, project_id))
            ).scalar_one()
        ):
            reason = "未回复" if row["status"] == "no_reply" else "到检查点仍未推进，请协助处理"
            result.append(
                ReminderSpec(
                    dedupe_key=f"xiaopai:{row['id']}:escalate",
                    policy_key="xiaopai_escalation",
                    target_entity="task",
                    target_entity_id=row["task_id"],
                    recipient_user_id=row["owner_user_id"],
                    title=f"小Pai升级：{row['title']}，{reason}"[:512],
                    fire_at=row["updated_at"],
                    escalation_level=1,
                )
            )
    return result


def visible() -> ColumnElement[bool]:
    """Recheck project membership before disclosing any retained Xiaopai notification."""
    r = tables.reminders
    return or_(
        r.c.policy_key.not_like("xiaopai_%"),
        recipient_allowed(r.c.recipient_user_id, r.c.tenant_id, r.c.project_id),
    )
