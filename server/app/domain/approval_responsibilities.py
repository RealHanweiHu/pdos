"""Focused authority handover context for the existing policy publication services."""

from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Engine, exists, or_, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkAccessError, _plain
from app.domain.resource_reservations import _project

Kind = Literal["execution", "baseline", "commitment"]
POLICIES = {
    "execution": tables.project_execution_policies,
    "baseline": tables.baseline_change_policies,
    "commitment": tables.schedule_commitment_policies,
}


def history_statement(tenant: UUID, project: UUID, kind: Kind, before: int | None = None) -> Any:
    t = POLICIES[kind]
    q = select(t).where(t.c.tenant_id == tenant, t.c.project_id == project)
    if before is not None:
        q = q.where(t.c.version < before)
    return q.order_by(t.c.version.desc()).limit(21)


def pending_statement(tenant: UUID, project: UUID, kind: Kind, policy: UUID) -> Any:
    if kind == "execution":
        t = tables.project_execution_requests
        return (
            select(t.c.id, t.c.round_no.label("version"), t.c.request_reason.label("reason"))
            .where(
                t.c.tenant_id == tenant,
                t.c.project_id == project,
                t.c.policy_id == policy,
                t.c.state.in_(("pending_approval", "approved")),
                ~exists(
                    select(tables.initial_plan_applications.c.id).where(
                        tables.initial_plan_applications.c.tenant_id == tenant,
                        tables.initial_plan_applications.c.execution_request_id == t.c.id,
                    )
                ),
            )
            .order_by(t.c.round_no.desc())
        )
    t, d = tables.baseline_change_requests, tables.baseline_change_decisions
    return (
        select(t.c.id, t.c.created_at.label("created_at"), t.c.reason)
        .where(
            t.c.tenant_id == tenant,
            t.c.project_id == project,
            t.c.policy_id == policy,
            ~exists(select(d.c.id).where(d.c.tenant_id == tenant, d.c.change_id == t.c.id)),
        )
        .order_by(t.c.created_at.desc(), t.c.id)
    )


def read(
    engine: Engine, ctx: AuthContext, project: UUID, kind: Kind, id: UUID, before: int | None = None
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        p = _project(c, ctx, project)
        t = POLICIES[kind]
        selected = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == ctx.tenant.id, t.c.project_id == project, t.c.id == id
                )
            )
            .mappings()
            .one_or_none()
        )
        if selected is None:
            raise ProductWorkAccessError("批准政策不存在或不属于此项目")
        latest = c.execute(history_statement(ctx.tenant.id, project, kind)).mappings().first()
        assert latest is not None
        history = (
            c.execute(history_statement(ctx.tenant.id, project, kind, before)).mappings().all()
        )
        u, m = tables.users, tables.project_members
        members = list(
            c.execute(
                select(u.c.id, u.c.display_name)
                .where(
                    u.c.tenant_id == ctx.tenant.id,
                    u.c.is_active.is_(True),
                    u.c.role.in_(("owner", "admin", "project_manager", "engineer", "quality")),
                    or_(
                        u.c.role.in_(("owner", "admin")),
                        exists(
                            select(m.c.id).where(
                                m.c.tenant_id == ctx.tenant.id,
                                m.c.project_id == project,
                                m.c.user_id == u.c.id,
                            )
                        ),
                    ),
                )
                .order_by(u.c.display_name, u.c.id)
            ).mappings()
        )
        ids = {
            r[field]
            for r in [selected, latest, *history[:20]]
            for field in ("approver_user_id", "created_by_user_id")
        }
        names = {
            str(r.id): r.display_name
            for r in c.execute(
                select(u.c.id, u.c.display_name).where(
                    u.c.tenant_id == ctx.tenant.id, u.c.id.in_(ids)
                )
            )
        }
        pending = (
            []
            if kind == "commitment"
            else [
                dict(r)
                for r in c.execute(
                    pending_statement(ctx.tenant.id, project, kind, id).limit(101)
                ).mappings()
            ]
        )
        return _plain(
            {
                "selected": dict(selected),
                "current": dict(latest),
                "people": names,
                "members": [dict(r) for r in members],
                "history": [dict(r) for r in history[:20]],
                "next_before_version": history[19]["version"] if len(history) > 20 else None,
                "pending": pending[:100],
                "pending_has_more": len(pending) > 100,
                "can_configure": is_allowed(ctx.user.role, Action.TENANT_MANAGE)
                and p["status"] not in {"completed", "archived"}
                and selected["id"] == latest["id"],
            }
        )
