"""P56 handover lane: what a removed member may still see and do, decided in SQL.

Removal ends the person's project audience at once. While their own tasks,
commitments or external waits are open, the server may open a lane for exactly
one of those items in the current transaction (`open_handover_lane`); every
other project read keeps denying them. When nothing is left, the removal settles
by itself (`settle_project_handover`), whoever closed the last item.
"""

from uuid import UUID

from sqlalchemy import text

from pdos_next.errors import DomainError

KINDS = {"work_task", "external_wait"}
LABELS = {"work_task": "任务", "work_commitment": "承诺", "external_wait": "外部等待"}


def open_lane(s, ctx, project_id, kind, subject_id):
    """Open the lane for one own open item; False when the person is not in handover.

    SQL decides whether the lane may open; the transaction-local setting is only
    the intent, and the projects policy re-checks the person and item on every row.
    """
    if kind is not None and kind not in KINDS:
        raise DomainError("VALIDATION_FAILED", "交接事项类型不受支持。", 422)
    allowed = s.scalar(
        text("SELECT open_handover_lane(:t, :project, :kind, :subject)"),
        {"t": ctx.tenant_id, "project": project_id, "kind": kind, "subject": subject_id},
    )
    if not allowed:
        return False
    current = s.scalar(text("SELECT current_setting('pdos.handover_lane', true)")) or ""
    lanes = {value for value in current.split(",") if value}
    if str(project_id) not in lanes:
        s.execute(
            text("SELECT set_config('pdos.handover_lane', :value, true)"),
            {"value": ",".join(sorted(lanes | {str(project_id)}))},
        )
    return True


def items(s, ctx, project_id, person):
    """Open items of one person: the owner or the person themself may ask."""
    rows = s.execute(
        text(
            "SELECT kind, subject_id, task_id, label, state "
            "FROM project_handover_items(:t, :project, :person) ORDER BY kind, label, subject_id"
        ),
        {"t": ctx.tenant_id, "project": project_id, "person": person},
    ).all()
    return [
        {
            "kind": row.kind,
            "kind_label": LABELS[row.kind],
            "subject_id": str(row.subject_id),
            "task_id": str(row.task_id) if row.task_id else None,
            "label": row.label or LABELS[row.kind],
            "state": row.state,
        }
        for row in rows
    ]


def counts(values):
    result = {"tasks": 0, "commitments": 0, "external_waits": 0}
    key = {
        "work_task": "tasks",
        "work_commitment": "commitments",
        "external_wait": "external_waits",
    }
    for value in values:
        result[key[value["kind"]]] += 1
    return result


def settle(s, ctx, project_id):
    """Complete every removal on this project whose handover is now empty (P56-2)."""
    s.flush()
    return s.scalar(
        text("SELECT settle_project_handover(:t, :project)"),
        {"t": ctx.tenant_id, "project": project_id},
    )


def mine(s, ctx):
    """Projects where the requester is in handover, each with only their own open items."""
    from pdos_next.domain.projects.work.models import WorkTaskCurrent, WorkTaskVersion
    from pdos_next.domain.projects.work.views import task_view

    projects = s.execute(
        text(
            "SELECT project_id, category_id, product_id, project_name, owner_id, left_at "
            "FROM my_handover_projects(:t) ORDER BY left_at DESC, project_id"
        ),
        {"t": ctx.tenant_id},
    ).all()
    result = []
    for project in projects:
        open_lane(s, ctx, project.project_id, None, None)
        own = items(s, ctx, project.project_id, ctx.requester_id)
        tasks = {}
        for item in own:
            if item["task_id"] is None or item["task_id"] in tasks:
                continue
            pointer = (
                s.query(WorkTaskCurrent)
                .filter(
                    WorkTaskCurrent.tenant_id == ctx.tenant_id,
                    WorkTaskCurrent.project_id == project.project_id,
                    WorkTaskCurrent.task_id == UUID(item["task_id"]),
                )
                .one_or_none()
            )
            if pointer is None:
                continue
            version = s.get(WorkTaskVersion, pointer.version_id)
            view = task_view(version, [])
            tasks[item["task_id"]] = {
                key: view[key]
                for key in (
                    "id",
                    "task_id",
                    "version_id",
                    "revision",
                    "owner_id",
                    "sources",
                    "state",
                    "title",
                    "goal",
                    "outcomes",
                    "g0_open_item",
                    "assignee_id",
                    "recipient_id",
                    "actual_start",
                    "submission",
                    "review",
                )
                if key in view
            }
        owner = s.execute(
            text("SELECT name FROM principals WHERE tenant_id=:t AND id=:id"),
            {"t": ctx.tenant_id, "id": project.owner_id},
        ).scalar()
        # The model revision the person's own task commands are checked against.
        revision = s.execute(
            text("SELECT revision FROM products WHERE tenant_id=:t AND id=:id"),
            {"t": ctx.tenant_id, "id": project.product_id},
        ).scalar()
        result.append(
            {
                "project": {
                    "id": str(project.project_id),
                    "category_id": str(project.category_id),
                    "product_id": str(project.product_id),
                    "name": project.project_name,
                    "owner_id": str(project.owner_id),
                    "owner_name": owner or "项目负责人",
                    "left_at": project.left_at.isoformat() if project.left_at else None,
                    "product_revision": revision,
                },
                "items": own,
                "counts": counts(own),
                "tasks": list(tasks.values()),
            }
        )
    return {
        "items": result,
        # P56: only these own items stay visible; the rest of each project does not.
        "scope_note": "交接期只保留本人未交接事项的查看与办理；项目讨论与其他内容已不可见。",
    }
