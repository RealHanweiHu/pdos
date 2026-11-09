"""Notifications, automatic follows and handover settlement after a work fact (§8, P56).

Runs inside the command's own transaction after its receipt is bound, so a
notification exists exactly when the fact does. What reaches whom is decided in
SQL (`notification_emit`): the operator never hears about their own action,
小Pai's own writes notify only an assignee (P53), and mute/level apply.
"""

from uuid import UUID

from sqlalchemy import select

from pdos_next.domain.my_work.notifications import service as notifications
from pdos_next.domain.projects.team import handover

from .constants import ACCEPT, ASSIGN, COMMIT, CREATE, REVIEW, START, STATUS, SUBMIT

TASK_REASONS = {
    ASSIGN: "task.assigned",
    ACCEPT: "task.accepted",
    START: "task.started",
    SUBMIT: "task.submitted",
    REVIEW: "task.reviewed",
}


def open_lane(s, ctx, payload):
    """A removed member may still act on their own open task (P56-1), nothing else."""
    task = getattr(payload, "task", None)
    if task is not None:
        handover.open_lane(s, ctx, payload.project_id, "work_task", task.id)


def after_task(s, ctx, operation, row):
    project_id, task_id = row.project_id, row.task_id
    body = row.body or {}
    assignee = UUID(body["assignee_id"]) if body.get("assignee_id") else None
    recipient = UUID(body["recipient_id"]) if body.get("recipient_id") else None
    latest = {"task_revision": row.revision, "state": row.state}
    human = not ctx.agent_run_id and not ctx.run_id
    if operation == CREATE:
        if human:
            notifications.follow(s, ctx, ctx.actor_id, "work_task", task_id, project_id, "created")
        return
    exclude = [ctx.actor_id]
    if operation == ASSIGN and assignee:
        notifications.follow(s, ctx, assignee, "work_task", task_id, project_id, "assigned")
        notifications.emit(
            s, ctx, assignee, "assigned", "task.assigned", project_id=project_id,
            kind="work_task", subject_id=task_id, latest=latest,
        )
        exclude.append(assignee)
    if operation == SUBMIT and recipient:
        notifications.follow(s, ctx, recipient, "work_task", task_id, project_id, "assigned")
        notifications.emit(
            s, ctx, recipient, "decide", "task.submitted", project_id=project_id,
            kind="work_task", subject_id=task_id, latest=latest,
        )
        exclude.append(recipient)
    if human:
        notifications.follow(s, ctx, ctx.actor_id, "work_task", task_id, project_id, "commented")
    notifications.emit_followers(
        s, ctx, [("work_task", task_id)], TASK_REASONS[operation], project_id=project_id,
        kind="work_task", subject_id=task_id, latest=latest, important=True, exclude=exclude,
    )
    if operation in {ASSIGN, REVIEW}:
        handover.settle(s, ctx, project_id)


def after_commitment(s, ctx, row):
    notifications.emit(
        s, ctx, row.recipient_id, "follow", "commitment.accepted", project_id=row.project_id,
        kind="work_task", subject_id=row.task_id,
        latest={"promised_at": row.promised_at.isoformat() if row.promised_at else None},
    )


def after_status(s, ctx, row):
    """Members follow a project's status updates by default (§8)."""
    from pdos_next.domain.projects.team.models import ProjectMember

    members = s.scalars(
        select(ProjectMember.principal_id).where(
            ProjectMember.tenant_id == ctx.tenant_id,
            ProjectMember.project_id == row.project_id,
            ProjectMember.left_at.is_(None),
        )
    )
    for person in sorted(set(members), key=str):
        notifications.emit(
            s, ctx, person, "follow", "project.status_updated", project_id=row.project_id,
            kind="project", subject_id=row.project_id, latest={"update_id": str(row.id)},
        )


def after(s, ctx, operation, row):
    if operation == COMMIT:
        after_commitment(s, ctx, row)
    elif operation == STATUS:
        after_status(s, ctx, row)
    else:
        after_task(s, ctx, operation, row)
