"""Unanswered and not-progressed escalation for the project owner (D71 + D190, P77).

A deterministic system rule, never a model: the project owner is its rule owner and
recipient (as P57 item 2 does for the G0 plan rule; DC-12 escalates to the project
owner first). It is a read-only attention projection (v1.1 AttentionItem): nothing is
stored, it appears once the time has passed and disappears as soon as the work moves.

Two separate clocks (DC-12 Q10/Q14):
- 未回复: assigned and still not accepted one working day after the assignment.
- 未推进: accepted (“收到”) and still not started one working day after acceptance.
  Accepting answers the assignment but is not progress.

Working days are the Monday-to-Friday estimate (P41-10); every item says so. The
owner reads under their own access, so a project they can no longer see yields
nothing (P57). Escalating to oneself is skipped: the owner's own assignments are
already in their own queues.
"""

from sqlalchemy import DateTime, String, and_, case, cast, func, literal, or_, select

from pdos_next.core import models as registered_models  # noqa: F401 -- registry first
from pdos_next.core.models import Grant
from pdos_next.domain.my_work.attention_common import columns

from . import business_days
from .models import BINDING, WorkTaskCurrent, WorkTaskVersion

WORKDAYS = 1
QUEUE = "decide"
RULES = {
    "followup_unanswered": {
        "state": "assigned",
        "action": "assign",
        "label": "分派未回复",
        "reason": (
            "分派后超过 1 个工作日仍未承接（按周一至周五估算，未扣节假日与停线）。"
            "确定性跟进规则，未经模型；可催办或改派。"
        ),
    },
    "followup_not_progressed": {
        "state": "accepted",
        "action": "accept",
        "label": "承接未推进",
        "reason": (
            "承接后超过 1 个工作日仍未开始；“收到”不算推进（按周一至周五估算，"
            "未扣节假日与停线）。确定性跟进规则，未经模型；可询问进展或协助排除阻塞。"
        ),
    },
}


def weekday_add(instant, days, zone):
    """The SQL twin of `business_days.add_weekdays` (migration s0_0905)."""
    return func.public.work_weekday_add(instant, days, zone, type_=DateTime(timezone=True))


def grant_join(query, source, ctx):
    return query.outerjoin(
        Grant,
        and_(
            Grant.tenant_id == source.tenant_id,
            Grant.category_id == source.category_id,
            Grant.principal_id == ctx.requester_id,
            or_(Grant.expires_at.is_(None), Grant.expires_at > func.transaction_timestamp()),
        ),
    )


def blocked():
    return {
        "blocked_code": case((Grant.can_write.is_(True), None), else_="READ_ONLY"),
        "blocked_message": case(
            (Grant.can_write.is_(True), None),
            else_="当前只有读取权限；请在原项目核对办理权限。",
        ),
        "valid_until": Grant.expires_at,
    }


def queries(ctx, queue=None):
    """Return this caller's escalations as project owner; empty outside `decide`."""
    if queue is not None and queue != QUEUE:
        return ()
    task, current = WorkTaskVersion, WorkTaskCurrent
    zone = business_days.DEFAULT_TIMEZONE
    result = []
    for kind, rule in RULES.items():
        escalated = weekday_add(task.created_at, WORKDAYS, zone)
        query = (
            select(
                *columns(
                    key=literal(kind + ":") + cast(task.task_id, String),
                    kind=kind,
                    queue=QUEUE,
                    tenant_id=task.tenant_id,
                    source_id=task.task_id,
                    version_id=task.id,
                    revision=task.revision,
                    category_id=task.category_id,
                    product_id=task.product_id,
                    project_id=task.project_id,
                    owner_id=task.owner_id,
                    visibility=task.visibility,
                    recorded_at=escalated,
                    title=task.body["title"].astext,
                    reason=rule["reason"],
                    state=task.state,
                    responsible_id=ctx.requester_id,
                    responsibility="project_owner_followup",
                    target="project",
                    details=func.jsonb_build_object(
                        "view",
                        "tasks",
                        "rule",
                        kind,
                        "rule_label",
                        rule["label"],
                        "assignee_id",
                        task.body["assignee_id"].astext,
                        "since_at",
                        task.created_at,
                        "escalated_at",
                        escalated,
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
                task,
                and_(
                    *(
                        getattr(task, key) == getattr(current, key)
                        for key in (*BINDING, "task_id", "revision", "state")
                    ),
                    task.id == current.version_id,
                ),
            )
            .where(
                task.tenant_id == ctx.tenant_id,
                task.owner_id == ctx.requester_id,
                task.state == rule["state"],
                task.action == rule["action"],
                task.body["assignee_id"].astext != cast(task.owner_id, String),
                escalated <= func.transaction_timestamp(),
            )
        )
        result.append(grant_join(query, task, ctx))
    return tuple(result)
