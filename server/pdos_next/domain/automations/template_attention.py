"""Deterministic rule templates as the project owner's attention (D75, P77, P57).

Two of the three minimal templates need no model and no stored run:
- 承诺到期提醒 (`commitment_due`): a promise in the owner's project is due within one
  working day or already past due, and its outcome is not yet submitted.
- 外部等待升级 (`external_wait_overdue`): an open external wait passed its internal check
  one working day ago and no reply has been recorded since that check. This sits on
  the existing wait clock (check point, recorded reply); the responsible person's own
  item in “等外部回复” is unchanged, and this is the escalation to the owner.

The rule owner is the project owner (P57 item 2 pattern), and each read is under the
owner's own access, so the scope is always “owner's current scope ∩ that project”
(P57 item 1). Escalating to oneself is skipped. Nothing is written; an item goes away
when the promise is submitted, the wait gets a reply or a new check, or it closes.
Working days are the Monday-to-Friday estimate (P41-10).
"""

from sqlalchemy import DateTime, String, and_, case, cast, func, literal, select

from pdos_next.core import models as registered_models  # noqa: F401 -- registry first
from pdos_next.domain.my_work.attention_common import columns
from pdos_next.domain.projects.external_wait.models import ExternalWaitCurrent, ExternalWaitVersion
from pdos_next.domain.projects.work import business_days
from pdos_next.domain.projects.work.followup import QUEUE, blocked, grant_join, weekday_add
from pdos_next.domain.projects.work.models import (
    BINDING,
    WorkCommitmentCurrent,
    WorkCommitmentVersion,
    WorkTaskCurrent,
    WorkTaskVersion,
)

WORKDAYS = 1
COMMITMENT_REASON = (
    "承诺将在 1 个工作日内到期或已过期，成果尚未提交（按周一至周五估算，未扣节假日与停线）。"
    "承诺到期提醒规则，未经模型；可询问进展、协助或与接收人商定新日期。"
)
WAIT_REASON = (
    "外部等待过内部检查点 1 个工作日仍未登记回复（按周一至周五估算，未扣节假日与停线）。"
    "外部等待升级规则，未经模型；这不是对方违约判定，可跟进或调整检查点。"
)


def _same(left, right, keys):
    return and_(*(getattr(left, key) == getattr(right, key) for key in keys))


def _commitments(ctx):
    promise, pointer = WorkCommitmentVersion, WorkCommitmentCurrent
    task, current = WorkTaskVersion, WorkTaskCurrent
    now = func.transaction_timestamp()
    soon = weekday_add(now, WORKDAYS, promise.original_timezone)
    query = (
        select(
            *columns(
                key=literal("commitment_due:") + cast(promise.series_id, String),
                kind="commitment_due",
                queue=QUEUE,
                tenant_id=promise.tenant_id,
                source_id=promise.series_id,
                version_id=promise.id,
                revision=promise.revision,
                category_id=promise.category_id,
                product_id=promise.product_id,
                project_id=promise.project_id,
                owner_id=promise.owner_id,
                visibility=promise.visibility,
                recorded_at=promise.promised_at,
                title=task.body["title"].astext,
                reason=COMMITMENT_REASON,
                state=task.state,
                responsible_id=ctx.requester_id,
                responsibility="project_owner_followup",
                target="project",
                due_at=promise.promised_at,
                details=func.jsonb_build_object(
                    "view",
                    "tasks",
                    "rule",
                    "commitment_due",
                    "rule_label",
                    "承诺到期提醒",
                    "phase",
                    case((promise.promised_at <= now, "overdue"), else_="due_soon"),
                    "promisor_id",
                    promise.promisor_id,
                    "recipient_id",
                    promise.recipient_id,
                    "work_task_id",
                    promise.task_id,
                    "workdays",
                    WORKDAYS,
                    "basis",
                    business_days.BASIS,
                    "basis_label",
                    business_days.BASIS_LABEL,
                    "timezone",
                    promise.original_timezone,
                    "model_calls",
                    False,
                ),
                **blocked(),
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
        .join(
            task,
            and_(
                _same(task, current, (*BINDING, "task_id", "revision", "state")),
                task.id == current.version_id,
            ),
        )
        .where(
            promise.tenant_id == ctx.tenant_id,
            promise.owner_id == ctx.requester_id,
            promise.promisor_id != promise.owner_id,
            promise.promised_at.is_not(None),
            promise.promised_at <= soon,
            task.state.in_(("accepted", "in_progress")),
            task.body["assignee_id"].astext == cast(promise.promisor_id, String),
        )
    )
    return grant_join(query, promise, ctx)


def _waits(ctx):
    current, row = ExternalWaitCurrent, ExternalWaitVersion
    check = cast(row.body["next_check_at"].astext, DateTime(timezone=True))
    replied = cast(row.body["reply"]["recorded_at"].astext, DateTime(timezone=True))
    zone = row.body["original_timezone"].astext
    escalated = weekday_add(check, WORKDAYS, zone)
    query = (
        select(
            *columns(
                key=literal("external_wait_overdue:") + cast(row.wait_id, String),
                kind="external_wait_overdue",
                queue=QUEUE,
                tenant_id=row.tenant_id,
                source_id=row.wait_id,
                version_id=row.id,
                revision=row.revision,
                category_id=row.category_id,
                product_id=row.product_id,
                project_id=row.project_id,
                owner_id=row.owner_id,
                visibility=row.visibility,
                recorded_at=escalated,
                title=row.body["title"].astext,
                reason=WAIT_REASON,
                state=row.state,
                responsible_id=ctx.requester_id,
                responsibility="project_owner_followup",
                target="project",
                details=func.jsonb_build_object(
                    "view",
                    "work",
                    "rule",
                    "external_wait_overdue",
                    "rule_label",
                    "外部等待升级",
                    "wait_responsible_id",
                    row.body["responsible_id"].astext,
                    "next_check_at",
                    row.body["next_check_at"].astext,
                    "next_check_is_internal",
                    True,
                    "escalated_at",
                    escalated,
                    "blocking",
                    row.body["blocking"].as_boolean(),
                    "workdays",
                    WORKDAYS,
                    "basis",
                    business_days.BASIS,
                    "basis_label",
                    business_days.BASIS_LABEL,
                    "timezone",
                    zone,
                    "model_calls",
                    False,
                ),
                **blocked(),
            )
        )
        .select_from(current)
        .join(
            row,
            and_(
                _same(current, row, (*BINDING, "wait_id", "revision", "state")),
                current.version_id == row.id,
            ),
        )
        .where(
            row.tenant_id == ctx.tenant_id,
            row.owner_id == ctx.requester_id,
            row.state == "open",
            row.body["responsible_id"].astext != cast(row.owner_id, String),
            row.body["next_check_at"].astext.is_not(None),
            escalated <= func.transaction_timestamp(),
            func.coalesce(replied, literal("-infinity").cast(DateTime(timezone=True))) < check,
        )
    )
    return grant_join(query, row, ctx)


def queries(ctx, queue=None):
    """Deterministic template attention for the project owner, in “要我决定”."""
    if queue is not None and queue != QUEUE:
        return ()
    return (_commitments(ctx), _waits(ctx))
