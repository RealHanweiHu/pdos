"""Live named handoff actions from the latest immutable task packet."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Select, case, exists, literal, or_, select

from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables
from app.domain.organization import active_delegated_principals


def inbox_statement(
    connection: Connection, tenant: UUID, user: UUID, role: Role
) -> Select[Any] | None:
    if not is_allowed(role, Action.WORK_ITEM_EDIT):
        return None
    h, t, p = tables.task_takeover_packets, tables.tasks, tables.projects
    newer, original = h.alias("newer_takeover"), h.alias("original_takeover")
    review = (
        (h.c.action == "submitted")
        & (h.c.receiver_user_id == user)
        & (t.c.assignee_user_id == user)
    )
    sender = case((h.c.action == "submitted", h.c.actor_user_id), else_=original.c.actor_user_id)
    revise = (
        (sender == user)
        & (t.c.assignee_user_id != user)
        & or_(h.c.action == "returned", t.c.assignee_user_id != h.c.receiver_user_id)
    )
    query = (
        select(
            h.c.id,
            h.c.task_id,
            h.c.revision,
            h.c.created_at,
            t.c.title,
            t.c.due_date,
            t.c.priority,
            t.c.status,
            case((review, literal("review")), else_=literal("revise")).label("mode"),
            p.c.id.label("project_id"),
            p.c.code.label("project_code"),
            p.c.name.label("project_name"),
        )
        .select_from(
            h.join(
                t,
                (t.c.tenant_id == h.c.tenant_id)
                & (t.c.project_id == h.c.project_id)
                & (t.c.id == h.c.task_id),
            )
            .join(p, (p.c.tenant_id == h.c.tenant_id) & (p.c.id == h.c.project_id))
            .outerjoin(
                original,
                (original.c.tenant_id == h.c.tenant_id)
                & (original.c.project_id == h.c.project_id)
                & (original.c.task_id == h.c.task_id)
                & (original.c.id == h.c.submission_id),
            )
        )
        .where(
            h.c.tenant_id == tenant,
            t.c.status.not_in(("done", "skipped")),
            p.c.status.not_in(("completed", "archived")),
            or_(review, revise),
            ~exists(
                select(newer.c.id).where(
                    newer.c.tenant_id == h.c.tenant_id,
                    newer.c.task_id == h.c.task_id,
                    newer.c.revision > h.c.revision,
                )
            ),
        )
    )
    if role not in (Role.OWNER, Role.ADMIN):
        principals = (
            user,
            *active_delegated_principals(connection, tenant_id=tenant, delegate_user_id=user),
        )
        m = tables.project_members
        query = query.where(
            exists(
                select(m.c.id).where(
                    m.c.tenant_id == tenant,
                    m.c.project_id == h.c.project_id,
                    m.c.user_id.in_(principals),
                )
            )
        )
    return query
