"""Notification projections from real source events, never arbitrary message text."""

from typing import Any

from sqlalchemy import select, union_all

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.ai_issue_silent_events import is_silent_ai_issue_event
from app.domain.customer_report_packages import approved, customer
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.quality_operations import authorize

WORK_EVENTS = {
    "TASK_CREATED",
    "TASK_UPDATED",
    "TASK_STATUS_CHANGED",
    "ISSUE_CREATED",
    "ISSUE_UPDATED",
    "ISSUE_STATUS_CHANGED",
}
SOURCE_EVENTS = WORK_EVENTS | {"CUSTOMER_REPORT_RECORDED"}


class SilentAICompletion(ProductWorkError):
    """A successful AI creation has no automatic notification side effect."""


def has_explicit_send(c: Any, delivery: Any) -> bool:
    """Preserve original named sends and later explicit retries, never infer consent.

    The immutable queued audit distinguishes automatic endpoint dispatch from a
    human send. A persisted retry is a separate, authorized human action. The
    mutable delivery reason/status is not evidence of either.
    """
    a, e, actions = tables.audit_log, tables.events, tables.webhook_delivery_actions
    queued = (
        select(a.c.actor_user_id)
        .select_from(
            a.join(
                e,
                (e.c.tenant_id == a.c.tenant_id)
                & (e.c.project_id == a.c.project_id)
                & (e.c.event_id == a.c.event_id)
                & (e.c.entity_id == a.c.entity_id)
                & (e.c.timestamp == a.c.timestamp),
            )
        )
        .where(
            a.c.tenant_id == delivery["tenant_id"],
            a.c.project_id == delivery["project_id"],
            a.c.entity_id == delivery["id"],
            a.c.action == "webhook.queued",
            a.c.actor_user_id.is_not(None),
            a.c.after_snapshot["automated"].as_boolean().is_(False),
            e.c.event_type == "WEBHOOK_RECORDED",
            e.c.source == "webhook_service",
            e.c.entity == a.c.entity,
            e.c.payload["action"].as_string() == "queued",
        )
    )
    retry = select(actions.c.actor_user_id).where(
        actions.c.tenant_id == delivery["tenant_id"],
        actions.c.project_id == delivery["project_id"],
        actions.c.delivery_id == delivery["id"],
        actions.c.action == "retry",
        actions.c.actor_user_id.is_not(None),
    )
    return c.execute(union_all(queued, retry).limit(1)).scalar_one_or_none() is not None


def notification(
    c: Any, context: AuthContext, endpoint: Any, event_id: int, *, automated: bool = False
) -> dict[str, Any]:
    project = endpoint["project_id"]
    authorize(c, context, project, Action.INTEGRATION_PROJECT_SEND)
    t = tables.events
    event = (
        c.execute(
            select(t).where(
                t.c.tenant_id == context.tenant.id, t.c.project_id == project, t.c.id == event_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if event is None or event["event_type"] not in SOURCE_EVENTS:
        raise ProductWorkError("该事件不在Webhook通知范围")
    if automated and is_silent_ai_issue_event(c, event):
        raise SilentAICompletion("AI建单成功保持静默；具名外发须另行明确办理。")
    refs: dict[str, Any] = {}
    if event["event_type"] in WORK_EVENTS:
        if endpoint["audience"] != "internal":
            raise ProductWorkError("客户端点不可接内部工程事件")
        authorize(c, context, project, Action.WORK_ITEM_VIEW)
        is_task = event["event_type"].startswith("TASK_")
        t = tables.tasks if is_task else tables.issues
        fields = (
            ("id", "title", "status", "assignee_user_id", "due_date", "updated_at")
            if is_task
            else ("id", "title", "status", "severity", "owner_user_id", "updated_at")
        )
        row = (
            c.execute(
                select(*(t.c[k] for k in fields)).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.project_id == project,
                    t.c.id == event["entity_id"],
                    *(() if is_task else (t.c.withdrawn_at.is_(None),)),
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ProductWorkError("原工作项不可读取")
        topic = "work.updated"
        data = {
            "kind": "task" if is_task else "issue",
            "current_record": _plain(row),
            "interpretation": "按原事件触发、取本次登记时当前值；不冒充原事件发生时完整快照。",
        }
    else:
        if endpoint["audience"] != "customer":
            raise ProductWorkError("该端点未授权客户资料")
        authorize(c, context, project, Action.CHANGE_VIEW)
        customer(c, context, project, endpoint["customer_id"])
        action = event["payload"].get("action")
        if action in {"approved", "withdrawn"}:
            t = tables.customer_report_decisions
            decision = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.project_id == project,
                        t.c.id == event["entity_id"],
                        t.c.action == action,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if decision is None:
                raise ProductWorkError("原客户披露裁决不可用")
            package_id = decision["package_id"]
            file = None
        elif action in {"file_created", "customer_audit_zip_created"}:
            t = tables.customer_report_files
            file = (
                c.execute(
                    select(*(v for v in t.c if v.name != "content")).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.project_id == project,
                        t.c.id == event["entity_id"],
                    )
                )
                .mappings()
                .one_or_none()
            )
            if file is None:
                raise ProductWorkError("原客户文件不可用")
            package_id = file["package_id"]
            decision = None
        else:
            raise ProductWorkError("此客户记录事件不产生对外通知")
        p = tables.customer_report_packages
        package = (
            c.execute(
                select(p).where(
                    p.c.tenant_id == context.tenant.id,
                    p.c.project_id == project,
                    p.c.id == package_id,
                    p.c.customer_id == endpoint["customer_id"],
                )
            )
            .mappings()
            .one_or_none()
        )
        if package is None:
            raise ProductWorkError("原报告不属于端点指定客户")
        if action == "withdrawn":
            topic, data = (
                "customer_report.withdrawn",
                {
                    "report_id": str(package_id),
                    "interpretation": "原客户报告披露批准已撤回，请停止使用对应报告及文件。",
                },
            )
        else:
            decision_id = file["decision_id"] if file else decision["id"]
            current, approval = approved(c, context, project, package_id, decision_id)
            refs = {
                "package_id": str(package_id),
                "decision_id": str(approval["id"]),
                "source_digest": current["source_digest"],
            }
            if file:
                topic = "customer_file.ready"
                data = {
                    "report_id": str(package_id),
                    "file": _plain(
                        {
                            k: file[k]
                            for k in ("id", "format", "filename", "byte_size", "content_digest")
                        }
                    ),
                }
            else:
                topic = "customer_report.ready"
                data = {
                    "report_id": str(package_id),
                    "title": current["snapshot"]["projection"]["title"],
                    "template_version": current["snapshot"]["projection"]["template_version"],
                    "approved_at": approval["created_at"].isoformat(),
                }
    if topic not in endpoint["topics"]:
        raise ProductWorkError("该通知类别未获端点授权")
    body = {
        "topic": topic,
        "source_event_id": event["id"],
        "source_event_reference": event["event_id"],
        "source_event_at": event["timestamp"].isoformat(),
        "data": data,
        "basis": refs,
    }
    return {**body, "digest": digest(body)}
