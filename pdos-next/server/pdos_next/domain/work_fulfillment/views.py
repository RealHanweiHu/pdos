"""Actual promise and review heads under the caller's ordinary project scope."""

from sqlalchemy import select

from pdos_next.domain.work_management import owner
from pdos_next.domain.work_management.models import (
    WorkCommitmentCurrent,
    WorkCommitmentVersion,
    WorkTaskVersion,
)
from pdos_next.domain.work_management.schemas import TaskSnapshot
from pdos_next.domain.work_management.views import commitment_view
from pdos_next.models import Grant, now
from pdos_next.service import require_access

from .models import WorkCommitmentReview, WorkCommitmentReviewCurrent
from .service import retained


def review_view(row):
    return {
        "id": str(row.id),
        "revision": row.revision,
        "decision": row.decision,
        "state": row.state,
        "checks": row.body["checks"],
        "actor_id": str(row.actor_id),
        "recorded_at": row.body["time"]["recorded_at"],
        "receipt_id": str(row.receipt_id),
    }


def fulfillment(s, ctx, pid, promise_id):
    pointer = s.scalar(
        select(WorkCommitmentReviewCurrent).where(
            WorkCommitmentReviewCurrent.tenant_id == ctx.tenant_id,
            WorkCommitmentReviewCurrent.product_id == pid,
            WorkCommitmentReviewCurrent.commitment_id == promise_id,
        )
    )
    history = [
        retained(s, ctx, pid, row)
        for row in s.scalars(
            select(WorkCommitmentReview)
            .where(
                WorkCommitmentReview.tenant_id == ctx.tenant_id,
                WorkCommitmentReview.product_id == pid,
                WorkCommitmentReview.commitment_id == promise_id,
            )
            .order_by(WorkCommitmentReview.revision)
        )
    ]
    current = next((row for row in history if pointer and row.id == pointer.version_id), None)
    return {
        "state": current.state if current else "open",
        "revision": current.revision if current else 0,
        "review": review_view(current) if current else None,
        "history": [review_view(row) for row in history],
    }


def workspace(s, ctx, pid, project_id):
    product = require_access(s, ctx, pid)
    project = owner.project(s, ctx, pid, project_id)
    current_ids = set(
        s.scalars(
            select(WorkCommitmentCurrent.version_id).where(
                WorkCommitmentCurrent.tenant_id == ctx.tenant_id,
                WorkCommitmentCurrent.product_id == pid,
                WorkCommitmentCurrent.project_id == project_id,
            )
        )
    )
    grant = s.scalar(
        select(Grant).where(
            Grant.tenant_id == ctx.tenant_id,
            Grant.category_id == ctx.category_id,
            Grant.principal_id == ctx.requester_id,
        )
    )
    writable = bool(
        grant
        and grant.can_write
        and (grant.expires_at is None or grant.expires_at > now())
        and ctx.actor_id == ctx.requester_id
        and not ctx.agent_run_id
        and not ctx.run_id
    )
    rows = []
    for promise in s.scalars(
        select(WorkCommitmentVersion)
        .where(
            WorkCommitmentVersion.tenant_id == ctx.tenant_id,
            WorkCommitmentVersion.product_id == pid,
            WorkCommitmentVersion.project_id == project_id,
        )
        .order_by(WorkCommitmentVersion.created_at, WorkCommitmentVersion.id)
    ):
        owner.retained(s, ctx, pid, promise)
        task, snapshot, _ = owner.task(s, ctx, pid, promise.task_id)
        submission = None
        if snapshot.submission:
            submitted = s.scalar(
                select(WorkTaskVersion)
                .where(
                    WorkTaskVersion.tenant_id == ctx.tenant_id,
                    WorkTaskVersion.product_id == pid,
                    WorkTaskVersion.task_id == promise.task_id,
                    WorkTaskVersion.action == "submit",
                    WorkTaskVersion.body["submission"] == task.body["submission"],
                )
                .order_by(WorkTaskVersion.revision.desc())
                .limit(1)
            )
            if submitted:
                owner.retained(s, ctx, pid, submitted)
                fixed = TaskSnapshot.model_validate(submitted.body).submission
                submission = {
                    "id": str(submitted.id),
                    "revision": submitted.revision,
                    "actor_id": str(submitted.actor_id),
                    "results": [result.model_dump(mode="json") for result in fixed.results],
                    "time": fixed.time.model_dump(mode="json"),
                }
        state = fulfillment(s, ctx, pid, promise.id)
        rows.append(
            {
                **commitment_view(promise, promise.id in current_ids),
                "series_id": str(promise.series_id),
                "sources": promise.sources,
                "task": {
                    "id": str(task.task_id),
                    "version_id": str(task.id),
                    "revision": task.revision,
                    "title": snapshot.title,
                    "state": task.state,
                },
                "submission": submission,
                "fulfillment": state,
                "can_review": bool(
                    writable
                    and promise.id in current_ids
                    and promise.recipient_id == ctx.requester_id
                    and snapshot.assignee_id == promise.promisor_id
                    and submission
                    and submission["actor_id"] == str(promise.promisor_id)
                    and state["state"] == "open"
                ),
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
        "commitments": rows,
        "as_of": now().isoformat(),
    }
