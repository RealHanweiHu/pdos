"""Explicit business consumers that prevent withdrawing a confirmed risk."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, cast, func, literal, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import Select

from app.auth.roles import Action
from app.db.schema import tables
from app.domain.risks import RiskVersionConflictError

KINDS = {
    "task": ("风险行动任务", Action.WORK_ITEM_VIEW),
    "initialization": ("引用风险的初始化任务", Action.WORK_ITEM_VIEW),
    "meeting": ("会议议题", Action.MEETING_VIEW),
    "gate": ("已完成的阶段评审", Action.GATE_VIEW),
    "handoff": ("任务交接遗留项", Action.WORK_ITEM_VIEW),
}


class RiskReferencedError(RiskVersionConflictError):
    """The risk is retained because other business records already use it."""


def query(kind: str, tenant: UUID, project: UUID, risk: UUID) -> Select[Any]:
    if kind == "task":
        t = tables.tasks
        return select(
            t.c.id,
            t.c.id.label("target_id"),
            t.c.title,
            t.c.status,
            t.c.updated_at,
        ).where(
            t.c.tenant_id == tenant,
            t.c.project_id == project,
            t.c.kind == "risk_action",
            t.c.source_entity == "risks",
            t.c.source_entity_id == risk,
        )
    if kind == "initialization":
        t, w = tables.tasks, tables.project_intake_work
        return (
            select(
                w.c.id,
                t.c.id.label("target_id"),
                t.c.title,
                t.c.status,
                t.c.updated_at,
                w.c.input_digest,
            )
            .select_from(
                w.join(
                    t,
                    (t.c.tenant_id == w.c.tenant_id)
                    & (t.c.project_id == w.c.project_id)
                    & (t.c.id == w.c.task_id),
                ),
            )
            .where(
                w.c.tenant_id == tenant,
                w.c.project_id == project,
                w.c.work_snapshot["source"]["kind"].astext == "risk",
                w.c.work_snapshot["source"]["id"].astext == str(risk),
            )
        )
    if kind == "meeting":
        t, m = tables.meeting_agenda_items, tables.meetings
        return (
            select(
                t.c.id,
                m.c.id.label("target_id"),
                t.c.title,
                t.c.resolution_status.label("status"),
                t.c.detail,
                t.c.source_digest,
                t.c.owner_user_id,
                m.c.updated_at,
            )
            .select_from(t.join(m, (m.c.tenant_id == t.c.tenant_id) & (m.c.id == t.c.meeting_id)))
            .where(
                t.c.tenant_id == tenant,
                m.c.project_id == project,
                t.c.source_kind == "risk",
                t.c.source_entity_id == risk,
            )
        )
    if kind == "gate":
        t, g = tables.gate_signoff_rounds, tables.gates
        return (
            select(
                t.c.id,
                g.c.id.label("target_id"),
                g.c.name.label("title"),
                literal("completed").label("status"),
                t.c.completed_at,
            )
            .select_from(t.join(g, (g.c.tenant_id == t.c.tenant_id) & (g.c.id == t.c.gate_id)))
            .where(
                t.c.tenant_id == tenant,
                g.c.project_id == project,
                t.c.status == "completed",
                cast(t.c.readiness_snapshot, JSONB)["blocker_keys"].contains([f"risk:{risk}"]),
            )
        )
    if kind == "handoff":
        h, t = tables.task_takeover_packets, tables.tasks
        return (
            select(
                h.c.id,
                t.c.id.label("target_id"),
                t.c.title,
                h.c.action.label("status"),
                h.c.revision,
                h.c.created_at,
            )
            .select_from(
                h.join(
                    t,
                    (t.c.tenant_id == h.c.tenant_id)
                    & (t.c.project_id == h.c.project_id)
                    & (t.c.id == h.c.task_id),
                )
            )
            .where(
                h.c.tenant_id == tenant,
                h.c.project_id == project,
                h.c.action == "submitted",
                cast(h.c.payload, JSONB)["residual_sources"].contains(
                    [{"kind": "risk", "id": str(risk)}]
                ),
            )
        )
    raise ValueError("Unknown risk reference kind")


def require_unreferenced(c: Connection, tenant: UUID, project: UUID, risk: UUID) -> None:
    # The caller holds the same project write lock used by task, meeting,
    # initialization and Gate writes. A new consumer cannot interleave the undo.
    for kind in KINDS:
        if c.execute(query(kind, tenant, project, risk).limit(1)).first() is not None:
            raise RiskReferencedError


def page(
    c: Connection,
    tenant: UUID,
    project: UUID,
    risk: UUID,
    allowed: set[str],
    kind: str,
    offset: int,
) -> dict[str, Any]:
    groups = []
    for key, (label, _) in KINDS.items():
        count = c.execute(
            select(func.count()).select_from(query(key, tenant, project, risk).subquery())
        ).scalar_one()
        groups.append(
            {
                "kind": key,
                "label": label,
                "count": count if key in allowed else None,
                "readable": key in allowed,
                "has_references": count > 0,
            }
        )
    items = []
    more = False
    if kind in allowed:
        statement = query(kind, tenant, project, risk)
        rows = (
            c.execute(statement.order_by(statement.selected_columns.id).offset(offset).limit(51))
            .mappings()
            .all()
        )
        more = len(rows) > 50
        for row in rows[:50]:
            base = f"/projects?project={project}"
            href = (
                f"{base}&tab=decisions&meeting={row['target_id']}"
                if kind == "meeting"
                else f"{base}&tab=gates"
                if kind == "gate"
                else f"{base}&tab=work-items&entity_id={row['target_id']}"
            )
            items.append(
                {
                    "id": str(row["id"]),
                    "target_id": str(row["target_id"]),
                    "title": row["title"],
                    "status": row["status"],
                    "href": href,
                }
            )
    return {
        "groups": groups,
        "kind": kind,
        "offset": offset,
        "next_offset": offset + 50 if more else None,
        "items": items,
        "blocks_undo": any(group["has_references"] for group in groups),
    }
