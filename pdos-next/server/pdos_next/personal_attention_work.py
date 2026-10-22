"""Current assigned tasks and independently reviewable promises, without writes."""

from sqlalchemy import String, and_, case, cast, func, literal, or_, select
from sqlalchemy.orm import aliased

from pdos_next import models as registered_models  # noqa: F401 -- registry before domain children
from pdos_next.domain.work_fulfillment.models import WorkCommitmentReviewCurrent
from pdos_next.domain.work_management.models import (
    BINDING,
    WorkCommitmentCurrent,
    WorkCommitmentVersion,
    WorkTaskCurrent,
    WorkTaskVersion,
)
from pdos_next.models import Grant
from pdos_next.personal_attention_common import columns


def _same(left, right, keys):
    return and_(*(getattr(left, key) == getattr(right, key) for key in keys))


def _grant(query, source, ctx):
    return query.outerjoin(
        Grant,
        and_(
            Grant.tenant_id == source.tenant_id,
            Grant.category_id == source.category_id,
            Grant.principal_id == ctx.requester_id,
            or_(Grant.expires_at.is_(None), Grant.expires_at > func.transaction_timestamp()),
        ),
    )


def _blocked():
    return {
        "blocked_code": case((Grant.can_write.is_(True), None), else_="READ_ONLY"),
        "blocked_message": case(
            (Grant.can_write.is_(True), None), else_="当前只有读取权限；请在原项目核对办理权限。"
        ),
        "valid_until": Grant.expires_at,
    }


def queries(ctx, queue=None):
    task, current = WorkTaskVersion, WorkTaskCurrent
    base = and_(
        _same(task, current, (*BINDING, "task_id", "revision", "state")),
        task.id == current.version_id,
    )
    queries = []
    for task_queue, state, person, reason in (
        ("receive", "assigned", "assignee_id", "你是这项任务当前指定的承接人。"),
        ("verify", "submitted", "recipient_id", "你是当前已提交成果的接收人。"),
    ):
        if queue is not None and queue != task_queue:
            continue
        query = (
            select(
                *columns(
                    key=literal("task:") + cast(task.task_id, String),
                    kind="task",
                    queue=task_queue,
                    tenant_id=task.tenant_id,
                    source_id=task.task_id,
                    version_id=task.id,
                    revision=task.revision,
                    category_id=task.category_id,
                    product_id=task.product_id,
                    project_id=task.project_id,
                    owner_id=task.owner_id,
                    visibility=task.visibility,
                    recorded_at=task.created_at,
                    title=task.body["title"].astext,
                    reason=reason,
                    state=task.state,
                    responsible_id=ctx.requester_id,
                    responsibility="named_assignee"
                    if task_queue == "receive"
                    else "named_recipient",
                    target="project",
                    **_blocked(),
                )
            )
            .select_from(current)
            .join(task, base)
            .where(
                task.tenant_id == ctx.tenant_id,
                task.state == state,
                task.body[person].astext == str(ctx.requester_id),
            )
        )
        queries.append(_grant(query, task, ctx))

    if queue is not None and queue != "verify":
        return tuple(queries)

    promise, pointer = WorkCommitmentVersion, WorkCommitmentCurrent
    submitted = aliased(WorkTaskVersion, name="attention_submission")
    newer = aliased(WorkTaskVersion, name="attention_newer_submission")
    query = (
        select(
            *columns(
                key=literal("promise_review:") + cast(promise.series_id, String),
                kind="promise_review",
                queue="verify",
                tenant_id=promise.tenant_id,
                source_id=promise.series_id,
                version_id=promise.id,
                revision=promise.revision,
                category_id=promise.category_id,
                product_id=promise.product_id,
                project_id=promise.project_id,
                owner_id=promise.owner_id,
                visibility=promise.visibility,
                recorded_at=submitted.created_at,
                title=task.body["title"].astext,
                reason="你是这条独立承诺的接收人；承诺人已有实际提交，履行尚未核对完成。",
                state="open",
                responsible_id=ctx.requester_id,
                responsibility="promise_recipient",
                target="project",
                due_at=promise.promised_at,
                details=func.jsonb_build_object(
                    "task_id",
                    task.task_id,
                    "task_revision",
                    task.revision,
                    "submission_id",
                    submitted.id,
                    "submission_revision",
                    submitted.revision,
                    "promisor_id",
                    promise.promisor_id,
                    "original_timezone",
                    promise.original_timezone,
                    "calendar_id",
                    promise.calendar_id,
                ),
                **_blocked(),
            )
        )
        .select_from(pointer)
        .join(
            promise,
            and_(
                _same(
                    promise,
                    pointer,
                    (*BINDING, "task_id", "promisor_id", "recipient_id", "series_id", "revision"),
                ),
                promise.id == pointer.version_id,
            ),
        )
        .join(current, _same(current, promise, (*BINDING, "task_id")))
        .join(task, base)
        .join(
            submitted,
            and_(
                _same(submitted, task, (*BINDING, "task_id")),
                submitted.action == "submit",
                submitted.body["submission"] == task.body["submission"],
                submitted.actor_id == promise.promisor_id,
            ),
        )
        .where(
            promise.tenant_id == ctx.tenant_id,
            promise.recipient_id == ctx.requester_id,
            task.body["assignee_id"].astext == cast(promise.promisor_id, String),
            ~select(newer.id)
            .where(
                _same(newer, task, (*BINDING, "task_id")),
                newer.action == "submit",
                newer.body["submission"] == task.body["submission"],
                newer.revision > submitted.revision,
            )
            .exists(),
            ~select(WorkCommitmentReviewCurrent.id)
            .where(
                _same(WorkCommitmentReviewCurrent, promise, BINDING),
                WorkCommitmentReviewCurrent.commitment_id == promise.id,
                WorkCommitmentReviewCurrent.state == "fulfilled",
            )
            .exists(),
        )
    )
    queries.append(_grant(query, promise, ctx))
    return tuple(queries)
