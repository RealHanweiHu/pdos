"""Named execution-result confirmations, using one bounded relational query."""

from typing import Any
from uuid import UUID

from sqlalchemy import Select, exists, select

from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables


def inbox_statement(tenant_id: UUID, user_id: UUID, role: Role) -> Select[Any] | None:
    if not is_allowed(role, Action.CHANGE_APPROVE) or not is_allowed(
        role, Action.PRODUCT_ENGINEERING_VIEW
    ):
        return None
    r, b, e, p, t, c = (
        tables.change_execution_results,
        tables.change_execution_tasks,
        tables.engineering_change_requests,
        tables.projects,
        tables.tasks,
        tables.change_execution_confirmations,
    )
    newer = r.alias("newer_execution_result")
    statement = (
        select(
            r.c.id,
            r.c.binding_id,
            r.c.revision_number,
            r.c.created_at,
            b.c.ecr_id,
            b.c.task_id,
            b.c.snapshot["item"]["action"].as_string().label("action"),
            e.c.code.label("ecr_code"),
            t.c.title,
            p.c.id.label("project_id"),
            p.c.code.label("project_code"),
            p.c.name.label("project_name"),
        )
        .join(
            b,
            (b.c.tenant_id == r.c.tenant_id)
            & (b.c.project_id == r.c.project_id)
            & (b.c.id == r.c.binding_id),
        )
        .join(
            e,
            (e.c.tenant_id == b.c.tenant_id)
            & (e.c.project_id == b.c.project_id)
            & (e.c.id == b.c.ecr_id),
        )
        .join(p, (p.c.tenant_id == b.c.tenant_id) & (p.c.id == b.c.project_id))
        .join(
            t,
            (t.c.tenant_id == b.c.tenant_id)
            & (t.c.project_id == b.c.project_id)
            & (t.c.id == b.c.task_id),
        )
        .where(
            r.c.tenant_id == tenant_id,
            r.c.reviewer_user_id == user_id,
            r.c.outcome == "ready_for_confirmation",
            ~exists(
                select(newer.c.id).where(
                    newer.c.tenant_id == r.c.tenant_id,
                    newer.c.binding_id == r.c.binding_id,
                    newer.c.revision_number > r.c.revision_number,
                )
            ),
            ~exists(
                select(c.c.id).where(
                    c.c.tenant_id == r.c.tenant_id,
                    c.c.project_id == r.c.project_id,
                    c.c.result_id == r.c.id,
                )
            ),
        )
    )
    if role not in (Role.OWNER, Role.ADMIN):
        m = tables.project_members
        statement = statement.where(
            exists(
                select(m.c.id).where(
                    m.c.tenant_id == r.c.tenant_id,
                    m.c.project_id == r.c.project_id,
                    m.c.user_id == user_id,
                )
            )
        )
    return statement
