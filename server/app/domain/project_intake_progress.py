"""Read-only initialization coverage and current Task execution, across versions."""

from collections import Counter
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, func, select

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.issue_intake_compensations import task_view
from app.domain.product_workspace import _plain
from app.domain.task_dependency_graph import active_dependencies
from app.domain.tasks import TERMINAL_TASK_STATUSES


def earlier_work(
    c: Connection,
    ctx: AuthContext,
    project: UUID,
    proposal: Any,
    before_id: UUID | None = None,
) -> dict[str, Any]:
    """Caller authorizes this project. Omitted bindings remain real business work."""
    b, p, t = tables.project_intake_work, tables.project_intake_proposals, tables.tasks
    keys = [UUID(item["key"]) for item in proposal["draft"]["work"]]
    scope = (
        b.c.tenant_id == ctx.tenant.id,
        b.c.project_id == project,
        b.c.work_key.not_in(keys),
    )
    count = c.execute(select(func.count()).select_from(b).where(*scope)).scalar_one()
    query = (
        select(b, p.c.revision.label("origin_revision"))
        .join(p, (p.c.tenant_id == b.c.tenant_id) & (p.c.id == b.c.proposal_id))
        .where(*scope)
    )
    if before_id:
        query = query.where(b.c.id < before_id)
    rows = list(c.execute(query.order_by(b.c.id.desc()).limit(21)).mappings())
    task_ids = {row["task_id"] for row in rows[:20]}
    tasks = (
        {
            row["id"]: task_view(row)
            for row in c.execute(
                select(t).where(
                    t.c.tenant_id == ctx.tenant.id,
                    t.c.project_id == project,
                    t.c.id.in_(task_ids),
                )
            ).mappings()
        }
        if task_ids
        else {}
    )
    return {
        "total": count,
        "items": [
            {
                "id": str(row["id"]),
                "work_key": str(row["work_key"]),
                "title": row["work_snapshot"]["title"],
                "proposal_id": str(row["proposal_id"]),
                "origin_revision": row["origin_revision"],
                "created_at": _plain(row)["created_at"],
                "task": tasks.get(row["task_id"]),
            }
            for row in rows[:20]
        ],
        "next_id": str(rows[19]["id"]) if len(rows) > 20 else None,
    }


def progress(
    c: Connection,
    ctx: AuthContext,
    project: UUID,
    proposal: Any,
    bindings: list[dict[str, Any]],
    source_states: list[dict[str, Any]],
    context_states: dict[str, Any],
    project_current: bool,
) -> dict[str, Any]:
    p = tables.project_intake_proposals
    latest = c.execute(
        select(func.max(p.c.revision)).where(
            p.c.tenant_id == ctx.tenant.id, p.c.project_id == project
        )
    ).scalar_one()
    by_key = {item["work_key"]: item for item in bindings}
    work = proposal["draft"]["work"]
    current_sources = {item["key"]: item["current"] for item in source_states}
    # One query for all active same-project Task predecessors; no per-row network work.
    d, t = tables.task_dependencies, tables.tasks
    task_ids = [UUID(item["task_id"]) for item in bindings]
    predecessors: dict[str, list[dict[str, Any]]] = {}
    if task_ids:
        edges = c.execute(
            select(d.c.task_id, t.c.id, t.c.title, t.c.status)
            .join(
                t,
                (t.c.tenant_id == d.c.tenant_id)
                & (t.c.project_id == d.c.project_id)
                & (t.c.id == d.c.depends_on_task_id),
            )
            .where(
                d.c.tenant_id == ctx.tenant.id,
                d.c.project_id == project,
                d.c.task_id.in_(task_ids),
                active_dependencies(ctx.tenant.id, project),
            )
            .distinct()
            .order_by(d.c.task_id, t.c.id)
        ).mappings()
        for edge in edges:
            if edge["status"] not in TERMINAL_TASK_STATUSES:
                predecessors.setdefault(str(edge["task_id"]), []).append(
                    {
                        "id": str(edge["id"]),
                        "title": edge["title"],
                        "status": edge["status"],
                        "href": (
                            f"/projects?project={project}&tab=work-items&entity_id={edge['id']}"
                        ),
                    }
                )
    entries = []
    for item in work:
        key = item["key"]
        binding = by_key.get(key)
        task = binding.get("current_task") if binding else None
        reasons = []
        if latest != proposal["revision"]:
            reasons.append("本版已不是最新现状版本")
        if not project_current:
            reasons.append("当前项目与原核对版本不同")
        if not all(current_sources.values()):
            reasons.append("本版原文来源已有变化，办理前需重新核对")
        if not context_states.get(key, {}).get("current", False):
            reasons.append("所选实际来源或前置任务已有变化")
        if binding and not binding["matches_proposal"]:
            reasons.append("本条目与已办理内容不同，请在原任务继续修正")
        missing = proposal["gaps"].get(key, [])
        waiting = [
            predecessor
            for predecessor in item.get("predecessor_work_keys", [])
            if not by_key.get(predecessor, {}).get("matches_proposal")
        ]
        unresolved = predecessors.get(binding["task_id"], []) if binding else []
        if binding:
            if not task:
                state = "task_unavailable"
            elif task["status"] in ("done", "skipped", "blocked", "pending_approval"):
                state = task["status"]
            elif unresolved:
                state = "waiting_task"
            else:
                state = "in_execution"
        elif reasons:
            state = "recheck"
        elif missing:
            state = "missing_mapping"
        elif waiting:
            state = "waiting_work"
        else:
            state = "ready"
        entries.append(
            {
                "key": key,
                "title": item["title"],
                "state": state,
                "recheck_reasons": reasons,
                "missing": missing,
                "waiting_work_keys": waiting,
                "unresolved_predecessors": unresolved,
                "task": task,
                "applied": binding is not None,
            }
        )
    gaps = []
    for source in proposal["sources"]:
        if source["kind"] != "gap":
            continue
        referenced = [item["key"] for item in work if source["key"] in item["observation_keys"]]
        applied = [key for key in referenced if by_key.get(key, {}).get("matches_proposal")]
        gaps.append(
            {
                "key": source["key"],
                "quote": source["quote"],
                "locator": source["locator"],
                "document_href": source["document_href"],
                "work_keys": referenced,
                "applied_work_keys": applied,
                "source_current": current_sources.get(source["key"], False),
            }
        )
    return {
        "read_at": datetime.now(UTC).isoformat(),
        "latest_revision": latest,
        "counts": dict(Counter(item["state"] for item in entries)),
        "total": len(entries),
        "applied": sum(item["applied"] for item in entries),
        "needs_recheck": sum(bool(item["recheck_reasons"]) for item in entries),
        "entries": entries,
        "gap_observations": gaps,
        "earlier_work": earlier_work(c, ctx, project, proposal),
    }
