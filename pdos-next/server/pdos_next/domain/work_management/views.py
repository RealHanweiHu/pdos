"""Current project work and fixed historical facts, without historical source bodies."""

from uuid import UUID

from sqlalchemy import select

from pdos_next.models import Grant, Principal, now
from pdos_next.service import require_access

from . import owner
from .models import (
    ProjectStatusUpdate,
    WorkCommitmentCurrent,
    WorkCommitmentVersion,
    WorkTaskCurrent,
    WorkTaskVersion,
)
from .schemas import CommitmentSnapshot, TaskSnapshot


def _time(value):
    return (
        None
        if value is None
        else {
            "at": value.actual_at.isoformat(),
            "original_timezone": value.original_timezone,
            "calendar_id": str(value.calendar_id) if value.calendar_id else None,
            "actor_id": str(value.actor_id),
            "recorded_at": value.recorded_at.isoformat(),
        }
    )


def task_view(row, history):
    snapshot = TaskSnapshot.model_validate(row.body)
    return {
        "id": str(row.task_id),
        "task_id": str(row.task_id),
        "version_id": str(row.id),
        "revision": row.revision,
        "state": row.state,
        "status": row.state,
        "title": snapshot.title,
        "goal": snapshot.goal,
        "outcomes": [value.model_dump(mode="json") for value in snapshot.outcomes],
        "owner_id": str(row.owner_id),
        "assignee_id": str(snapshot.assignee_id) if snapshot.assignee_id else None,
        "recipient_id": str(snapshot.recipient_id) if snapshot.recipient_id else None,
        "plan_task": snapshot.plan_task.model_dump(mode="json") if snapshot.plan_task else None,
        "npi_template": snapshot.npi_template.model_dump(mode="json")
        if snapshot.npi_template
        else None,
        "g0_open_item": snapshot.g0_open_item.model_dump(mode="json")
        if snapshot.g0_open_item
        else None,
        "sources": row.sources,
        "actual_start": _time(snapshot.actual_start),
        "submission": None
        if snapshot.submission is None
        else {
            **_time(snapshot.submission.time),
            "results": [value.model_dump(mode="json") for value in snapshot.submission.results],
        },
        "review": None
        if snapshot.review is None
        else {
            **_time(snapshot.review.time),
            "decision": snapshot.review.decision,
            "checks": [value.model_dump(mode="json") for value in snapshot.review.checks],
        },
        "history": [
            {
                "id": str(value.id),
                "revision": value.revision,
                "action": value.action,
                "state": value.state,
                "actor_id": str(value.actor_id),
                "created_at": value.created_at.isoformat(),
                "receipt_id": str(value.receipt_id),
            }
            for value in history
        ],
    }


def commitment_view(row, current=True):
    value = CommitmentSnapshot.model_validate(row.body)
    return {
        **value.model_dump(mode="json"),
        "id": str(row.id),
        "status": "current" if current else "superseded",
        "created_at": row.created_at.isoformat(),
    }


def update_view(row):
    return {
        "id": str(row.id),
        "revision": row.revision,
        "actor_id": str(row.actor_id),
        "fact_summary": row.fact_summary,
        "next_steps": row.next_steps,
        "task_refs": row.task_refs,
        "sources": row.sources,
        "created_at": row.created_at.isoformat(),
        "receipt_id": str(row.receipt_id),
    }


def workspace(s, ctx, pid, project_id):
    from .g0_sources import workspace_items

    product = require_access(s, ctx, pid)
    project = owner.project(s, ctx, pid, project_id)
    scope = (
        WorkTaskVersion.tenant_id == ctx.tenant_id,
        WorkTaskVersion.product_id == pid,
        WorkTaskVersion.project_id == project_id,
    )
    pointers = list(
        s.scalars(
            select(WorkTaskCurrent)
            .where(
                WorkTaskCurrent.tenant_id == ctx.tenant_id,
                WorkTaskCurrent.product_id == pid,
                WorkTaskCurrent.project_id == project_id,
            )
            .order_by(WorkTaskCurrent.created_at, WorkTaskCurrent.id)
        )
    )
    tasks = []
    for pointer in pointers:
        row = owner.retained(s, ctx, pid, s.get(WorkTaskVersion, pointer.version_id))
        history = list(
            s.scalars(
                select(WorkTaskVersion)
                .where(
                    *scope,
                    WorkTaskVersion.task_id == row.task_id,
                )
                .order_by(WorkTaskVersion.revision)
            )
        )
        tasks.append(task_view(row, history))
    currents = {
        row.version_id
        for row in s.scalars(
            select(WorkCommitmentCurrent).where(
                WorkCommitmentCurrent.tenant_id == ctx.tenant_id,
                WorkCommitmentCurrent.product_id == pid,
                WorkCommitmentCurrent.project_id == project_id,
            )
        )
    }
    commitments = []
    for row in s.scalars(
        select(WorkCommitmentVersion)
        .where(
            WorkCommitmentVersion.tenant_id == ctx.tenant_id,
            WorkCommitmentVersion.product_id == pid,
            WorkCommitmentVersion.project_id == project_id,
        )
        .order_by(WorkCommitmentVersion.created_at, WorkCommitmentVersion.id)
    ):
        owner.retained(s, ctx, pid, row)
        commitments.append(commitment_view(row, row.id in currents))
    updates = []
    for row in s.scalars(
        select(ProjectStatusUpdate)
        .where(
            ProjectStatusUpdate.tenant_id == ctx.tenant_id,
            ProjectStatusUpdate.product_id == pid,
            ProjectStatusUpdate.project_id == project_id,
        )
        .order_by(ProjectStatusUpdate.created_at.desc(), ProjectStatusUpdate.id.desc())
    ):
        owner.retained(s, ctx, pid, row)
        updates.append(update_view(row))
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
    from pdos_next.domain.project_risk.views import projection as risk_projection

    native_items = workspace_items(s, ctx, pid, project_id)
    for item in native_items:
        if item["kind"] == "risk":
            item["risk_followup"] = risk_projection(
                s, ctx, pid, project, UUID(item["id"]), UUID(item["decision_id"])
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
        "tasks": tasks,
        "g0_open_items": native_items,
        "commitments": commitments,
        "updates": updates,
        "as_of": now().isoformat(),
    }
