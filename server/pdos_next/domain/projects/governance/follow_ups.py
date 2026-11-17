"""Carry named approval follow-ups into the next stage's exit checks."""

from sqlalchemy import select

from pdos_next.core.models import Principal
from pdos_next.domain.categories.preproject.access import member
from pdos_next.domain.projects.work import owner
from pdos_next.domain.projects.work.models import WorkTaskCurrent, WorkTaskVersion
from pdos_next.domain.projects.work.rules import require
from pdos_next.errors import DomainError


def _open_tasks(s, project):
    return s.scalars(
        select(WorkTaskVersion)
        .join(
            WorkTaskCurrent,
            (WorkTaskCurrent.tenant_id == WorkTaskVersion.tenant_id)
            & (WorkTaskCurrent.version_id == WorkTaskVersion.id),
        )
        .where(
            WorkTaskVersion.tenant_id == project.tenant_id,
            WorkTaskVersion.project_id == project.id,
            WorkTaskCurrent.state.in_(("assigned", "accepted", "in_progress", "submitted")),
        )
        .order_by(WorkTaskVersion.created_at.desc(), WorkTaskVersion.id)
    )


def available(s, project):
    from uuid import UUID

    rows = list(_open_tasks(s, project))
    names = dict(
        s.execute(
            select(Principal.id, Principal.name).where(
                Principal.tenant_id == project.tenant_id,
                Principal.active.is_(True),
                Principal.id.in_({UUID(row.body["assignee_id"]) for row in rows}),
            )
        ).all()
    )
    return [
        {
            "task": {"id": str(row.task_id), "revision": row.revision},
            "owner_id": row.body["assignee_id"],
            "owner_name": names[UUID(row.body["assignee_id"])],
            "title": row.body["title"],
        }
        for row in rows
        if UUID(row.body["assignee_id"]) in names
    ]


def fixed(s, ctx, pid, project, items, next_stage):
    if not items:
        return []
    require(next_stage, "项目需要后续阶段，才能将待办纳入其出口检查。", "VALIDATION_FAILED", 422)
    result = []
    for item in items:
        row, task, _ = owner.task(s, ctx, pid, item.task.id, revision=item.task.revision)
        require(
            row.project_id == project.id
            and task.assignee_id == item.owner_id
            and row.state in {"assigned", "accepted", "in_progress", "submitted"},
            "请固定本项目已有分派且尚待完成的任务及其执行人。",
            "VERSION_CONFLICT",
        )
        grant = member(s, ctx, item.owner_id)
        require(grant.can_write, "待办负责人已失去品类写入权限。", "FORBIDDEN_SCOPE", 403)
        owner.sources_current(s, ctx, pid, row.source_basis)
        result.append(
            {
                **item.model_dump(mode="json"),
                "title": task.title,
                "next_stage_id": next_stage["id"],
            }
        )
    return result


def checks(s, ctx, pid, project, entries):
    result = []
    for item in entries:
        pointer = s.scalar(
            select(WorkTaskCurrent).where(
                WorkTaskCurrent.tenant_id == ctx.tenant_id,
                WorkTaskCurrent.project_id == project.id,
                WorkTaskCurrent.task_id == item["task"]["id"],
            )
        )
        row = s.get(WorkTaskVersion, pointer.version_id) if pointer else None
        accepted = False
        if row and row.state == "completed" and row.body["assignee_id"] == item["owner_id"]:
            try:
                owner.retained(s, ctx, pid, row)
                owner.sources_current(s, ctx, pid, row.source_basis)
                accepted = True
            except DomainError as error:
                if error.code not in {
                    "SOURCE_UNAVAILABLE",
                    "SOURCE_STALE",
                    "FORBIDDEN_SCOPE",
                    "VERSION_CONFLICT",
                    "RECHECK_REQUIRED",
                }:
                    raise
        result.append(
            {
                "key": "follow_up:" + item["task"]["id"],
                "label": item["title"],
                "state": "READY" if accepted else "UNKNOWN",
                "detail": "已有实际验收" if accepted else "尚缺具名待办的有效验收",
                "ref": item | {"completion_receipt_id": str(row.receipt_id) if accepted else None},
            }
        )
    return result
