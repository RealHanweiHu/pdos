"""Read real followup heads without treating unknown legacy state as open."""

from uuid import UUID

from sqlalchemy import exists, select

from pdos_next.domain.work_management import g0_sources
from pdos_next.domain.work_management import owner as work_owner
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal, now
from pdos_next.service import require_access

from . import owner
from .models import ProjectRiskFollowup


def projection(s, ctx, pid, project, risk_id, decision_id):
    """Minimal projection shared by the G0 card and the independent followup panel."""
    status = owner.legacy_status(s, ctx, pid, project.id, risk_id)
    blocked = None
    current = None
    try:
        current, _ = owner.current(s, ctx, pid, project, risk_id)
        orphan = current is None and s.scalar(
            select(
                exists().where(
                    ProjectRiskFollowup.tenant_id == ctx.tenant_id,
                    ProjectRiskFollowup.risk_id == risk_id,
                )
            )
        )
        if status != "open" or orphan or (current and current.g0_decision_id != decision_id):
            raise DomainError("VERSION_CONFLICT", "原风险或当前跟进状态无法核对。")
    except DomainError as error:
        if error.reason not in {"INTEGRITY_MISMATCH", "VERSION_CONFLICT", "FORBIDDEN_SCOPE"}:
            raise
        blocked = {"code": error.code, "message": error.message}
    return {
        "state": "unknown" if blocked else current.state if current else "open",
        "current": {"id": str(current.id), "revision": current.revision} if current else None,
        "summary": current.body["summary"] if current else None,
        "blocked": blocked,
    }


def workspace(s, ctx, pid, project_id):
    product = require_access(s, ctx, pid)
    project = work_owner.project(s, ctx, pid, project_id)
    members = [
        {"id": str(person.id), "name": person.name, "can_write": grant.can_write}
        for person, grant in s.execute(
            select(Principal, Grant)
            .join(
                Grant,
                (Grant.tenant_id == Principal.tenant_id) & (Grant.principal_id == Principal.id),
            )
            .where(
                Principal.tenant_id == ctx.tenant_id,
                Principal.kind == "human",
                Principal.active.is_(True),
                Grant.category_id == ctx.category_id,
                (Grant.expires_at.is_(None) | (Grant.expires_at > now())),
            )
            .order_by(Principal.name, Principal.id)
        )
    ]
    writable = bool(
        ctx.actor_id == ctx.requester_id
        and not ctx.agent_run_id
        and not ctx.run_id
        and any(m["id"] == str(ctx.requester_id) and m["can_write"] for m in members)
    )
    items = g0_sources.workspace_items(s, ctx, pid, project_id)
    histories = {}
    for row in s.scalars(
        select(ProjectRiskFollowup)
        .where(
            ProjectRiskFollowup.tenant_id == ctx.tenant_id,
            ProjectRiskFollowup.category_id == ctx.category_id,
            ProjectRiskFollowup.product_id == pid,
            ProjectRiskFollowup.project_id == project_id,
        )
        .order_by(ProjectRiskFollowup.risk_id, ProjectRiskFollowup.revision)
    ):
        owner.retained(s, ctx, pid, row)
        histories.setdefault(str(row.risk_id), []).append(
            {
                "id": str(row.id),
                "revision": row.revision,
                "action": row.action,
                "state": row.state,
                "summary": row.body["summary"],
                "actor_id": str(row.actor_id),
                "created_at": row.created_at.isoformat(),
                "receipt_id": str(row.receipt_id),
            }
        )
    rows = []
    for item in items:
        if item["kind"] != "risk":
            continue
        state = projection(s, ctx, pid, project, UUID(item["id"]), UUID(item["decision_id"]))
        rows.append(
            {
                **{
                    k: item[k]
                    for k in ("id", "decision_id", "title", "note", "due_date", "source", "task")
                },
                "responsible_id": item["owner_id"],
                **state,
                "can_record": writable
                and item["owner_id"] == str(ctx.requester_id)
                and state["blocked"] is None,
                "history": histories.get(item["id"], []),
            }
        )
    return {
        "project": {
            "id": str(project.id),
            "revision": project.revision,
            "name": project.name,
            "owner_id": str(project.owner_id),
            "visibility": project.visibility,
        },
        "product_revision": product.revision,
        "members": members,
        "risks": rows,
        "as_of": now().isoformat(),
    }
