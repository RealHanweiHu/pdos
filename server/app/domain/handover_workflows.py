"""Outstanding named workflow obligations and immutable personnel transfer receipts."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, Select, Text, case, cast, exists, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB

from app.auth.roles import Role
from app.db.schema import tables
from app.domain.change_execution_inbox import inbox_statement as execution_inbox
from app.domain.product_workspace import _plain, digest


def task_packets(tenant: UUID, user: UUID) -> Select[Any]:
    h, t, p = tables.task_takeover_packets, tables.tasks, tables.projects
    newer, original = h.alias("handover_newer_packet"), h.alias("handover_original_packet")
    sender = case((h.c.action == "submitted", h.c.actor_user_id), else_=original.c.actor_user_id)
    return (
        select(
            h.c.id,
            h.c.task_id,
            h.c.project_id,
            t.c.title,
            h.c.revision,
            h.c.action,
            h.c.receiver_user_id,
            sender.label("sender_user_id"),
            t.c.assignee_user_id,
            h.c.request_digest,
            h.c.basis,
            t.c.updated_at,
        )
        .select_from(
            h.join(
                t,
                (t.c.tenant_id == h.c.tenant_id)
                & (t.c.project_id == h.c.project_id)
                & (t.c.id == h.c.task_id),
            )
            .join(p, (p.c.tenant_id == h.c.tenant_id) & (p.c.id == h.c.project_id))
            .outerjoin(
                original,
                (original.c.tenant_id == h.c.tenant_id) & (original.c.id == h.c.submission_id),
            )
        )
        .where(
            h.c.tenant_id == tenant,
            t.c.status.not_in(("done", "skipped")),
            p.c.status.not_in(("completed", "archived")),
            ~exists(
                select(newer.c.id).where(
                    newer.c.tenant_id == h.c.tenant_id,
                    newer.c.task_id == h.c.task_id,
                    newer.c.revision > h.c.revision,
                )
            ),
            or_(
                (sender == user)
                & or_(
                    h.c.action.in_(("submitted", "returned")),
                    h.c.receiver_user_id.is_distinct_from(t.c.assignee_user_id),
                ),
                (h.c.action == "submitted")
                & (h.c.receiver_user_id == user)
                & (t.c.assignee_user_id == user),
            ),
        )
    )


def risk_results(tenant: UUID, user: UUID) -> Select[Any]:
    h, t = tables.risk_followup_results, tables.tasks
    newer = h.alias("handover_newer_risk_result")
    return (
        select(
            h.c.id,
            h.c.project_id,
            h.c.task_id,
            h.c.risk_id,
            h.c.revision,
            h.c.action,
            h.c.receiver_user_id,
            t.c.title,
        )
        .select_from(
            h.join(
                t,
                (t.c.tenant_id == h.c.tenant_id)
                & (t.c.project_id == h.c.project_id)
                & (t.c.id == h.c.task_id),
            )
        )
        .where(
            h.c.tenant_id == tenant,
            h.c.receiver_user_id == user,
            h.c.action == "submitted",
            ~exists(
                select(newer.c.id).where(
                    newer.c.tenant_id == h.c.tenant_id,
                    newer.c.task_id == h.c.task_id,
                    newer.c.revision > h.c.revision,
                )
            ),
        )
    )


def execution_requests(tenant: UUID, user: UUID) -> Select[Any]:
    r, policy, p = (
        tables.project_execution_requests,
        tables.project_execution_policies,
        tables.projects,
    )
    newer = r.alias("handover_newer_execution_request")
    return (
        select(
            r.c.id,
            r.c.project_id,
            p.c.name.label("title"),
            r.c.round_no,
            r.c.state,
            r.c.policy_id,
            r.c.version,
            r.c.basis_digest,
            policy.c.approver_user_id,
        )
        .select_from(
            r.join(
                policy, (policy.c.tenant_id == r.c.tenant_id) & (policy.c.id == r.c.policy_id)
            ).join(p, (p.c.tenant_id == r.c.tenant_id) & (p.c.id == r.c.project_id))
        )
        .where(
            r.c.tenant_id == tenant,
            policy.c.approver_user_id == user,
            r.c.state == "pending_approval",
            p.c.status.not_in(("completed", "archived")),
            ~exists(
                select(newer.c.id).where(
                    newer.c.tenant_id == r.c.tenant_id,
                    newer.c.project_id == r.c.project_id,
                    newer.c.round_no > r.c.round_no,
                )
            ),
        )
    )


def baseline_requests(tenant: UUID, user: UUID) -> Select[Any]:
    r, policy, p, d = (
        tables.baseline_change_requests,
        tables.baseline_change_policies,
        tables.projects,
        tables.baseline_change_decisions,
    )
    return (
        select(
            r.c.id,
            r.c.project_id,
            p.c.name.label("title"),
            r.c.policy_id,
            r.c.base_baseline_id,
            r.c.payload_digest,
            r.c.created_by_user_id,
            policy.c.approver_user_id,
        )
        .select_from(
            r.join(
                policy, (policy.c.tenant_id == r.c.tenant_id) & (policy.c.id == r.c.policy_id)
            ).join(p, (p.c.tenant_id == r.c.tenant_id) & (p.c.id == r.c.project_id))
        )
        .where(
            r.c.tenant_id == tenant,
            p.c.status.not_in(("completed", "archived")),
            or_(r.c.created_by_user_id == user, policy.c.approver_user_id == user),
            ~exists(select(d.c.id).where(d.c.tenant_id == r.c.tenant_id, d.c.change_id == r.c.id)),
        )
    )


def personnel_reservations(tenant: UUID, user: UUID) -> Select[Any]:
    r, resource, node, project = (
        tables.resource_reservations,
        tables.planning_resources,
        tables.schedule_nodes,
        tables.projects,
    )
    return (
        select(
            r,
            resource.c.name.label("title"),
            resource.c.user_id,
            node.c.title.label("node_title"),
        )
        .join(
            resource, (resource.c.tenant_id == r.c.tenant_id) & (resource.c.id == r.c.resource_id)
        )
        .join(
            node,
            (node.c.tenant_id == r.c.tenant_id)
            & (node.c.project_id == r.c.project_id)
            & (node.c.id == r.c.node_id),
        )
        .join(project, (project.c.tenant_id == r.c.tenant_id) & (project.c.id == r.c.project_id))
        .where(
            r.c.tenant_id == tenant,
            resource.c.user_id == user,
            resource.c.kind == "person",
            r.c.state.in_(("proposed", "reserved")),
            r.c.window_end > func.now(),
            project.c.status.not_in(("completed", "archived")),
        )
    )


def meeting_roster(tenant: UUID, user: UUID) -> Select[Any]:
    m, participant, p = tables.meetings, tables.meeting_participants, tables.projects
    return (
        select(
            participant.c.id,
            participant.c.meeting_id,
            participant.c.participation,
            participant.c.attendance,
            m.c.project_id,
            m.c.title,
            m.c.status,
            m.c.organizer_user_id,
            m.c.updated_at,
            m.c.scheduled_start_at,
            m.c.scheduled_end_at,
        )
        .join(m, (m.c.tenant_id == participant.c.tenant_id) & (m.c.id == participant.c.meeting_id))
        .join(p, (p.c.tenant_id == m.c.tenant_id) & (p.c.id == m.c.project_id))
        .where(
            participant.c.tenant_id == tenant,
            participant.c.user_id == user,
            or_(m.c.organizer_user_id == user, participant.c.participation == "required"),
            m.c.status.in_(("scheduled", "in_progress")),
            m.c.archived_at.is_(None),
            m.c.deleted_at.is_(None),
            p.c.status.not_in(("completed", "archived")),
        )
    )


def groups(c: Connection, tenant: UUID, source: UUID) -> list[dict[str, Any]]:
    result = []
    execution_query = execution_inbox(tenant, source, Role.ADMIN)
    recurrence, project = tables.meeting_recurrences, tables.projects
    periodic = (
        select(recurrence)
        .join(
            project,
            (project.c.tenant_id == recurrence.c.tenant_id)
            & (project.c.id == recurrence.c.project_id),
        )
        .where(
            recurrence.c.tenant_id == tenant,
            recurrence.c.status == "active",
            project.c.status.not_in(("completed", "archived")),
            or_(
                recurrence.c.default_participants.cast(JSONB).contains([{"user_id": str(source)}]),
                recurrence.c.agenda_template.cast(JSONB).contains([{"owner_user_id": str(source)}]),
            ),
        )
    )
    automatic = tables.meeting_generation_policies
    automatic_query = (
        select(recurrence)
        .join(
            automatic,
            (automatic.c.tenant_id == recurrence.c.tenant_id)
            & (automatic.c.recurrence_id == recurrence.c.id),
        )
        .join(
            project,
            (project.c.tenant_id == recurrence.c.tenant_id)
            & (project.c.id == recurrence.c.project_id),
        )
        .where(
            automatic.c.tenant_id == tenant,
            automatic.c.organizer_user_id == source,
            automatic.c.status == "enabled",
            project.c.status.not_in(("completed", "archived")),
        )
    )
    conference, meeting = tables.meeting_conference_requests, tables.meetings
    conference_query = (
        select(conference, meeting.c.title)
        .join(
            meeting,
            (meeting.c.tenant_id == conference.c.tenant_id)
            & (meeting.c.project_id == conference.c.project_id)
            & (meeting.c.id == conference.c.meeting_id),
        )
        .where(
            conference.c.tenant_id == tenant,
            conference.c.actor_user_id == source,
            conference.c.status.in_(("pending", "sending", "uncertain")),
        )
    )
    queries = [
        (
            "meeting_conference_requests",
            "待办或结果不明的外部会议请求",
            conference_query,
            "原发起人须先撤回未派发请求，或在原会议核对实际外部结果；外部账号及原回执不能批量改写为接手人",
        ),
        (
            "meeting_generation_authority",
            "周期会议自动生成的具名组织责任",
            automatic_query,
            "明确暂停自动生成，或由接手人在原周期核对期限和配置后以本人身份重新启用；已生成会议另行移交",
        ),
        (
            "meeting_recurrence_roster",
            "周期会议默认参会与议题责任",
            periodic,
            "调整后续会议默认名单/议题负责人或明确暂停；已生成会议仍须分别办理，恢复时重新核对有效成员",
        ),
        (
            "meeting_roster_obligations",
            "未结束会议组织与必需参会责任",
            meeting_roster(tenant, source),
            "在原会议会前准备中调整组织者及必需参会名单；议题负责人和实际行动任务分别办理，已结束会议保留原名单",
        ),
        (
            "personnel_resource_reservations",
            "本人作为共享人员资源的待办预约",
            personnel_reservations(tenant, source),
            "预约占用此人员的实际时段；资源管理员须在原预约替换人员资源或释放/取消，修改预约负责人不会改变被占用人员",
        ),
        (
            "pending_baseline_approvals",
            "尚待裁决的基线变更提交与批准责任",
            baseline_requests(tenant, source),
            "原提交人可按新政策撤回并续提，或在原记录撤回；批准人按当前有效政策裁决，正式基线应用另行办理",
        ),
        (
            "pending_execution_approvals",
            "尚待办理的项目执行批准",
            execution_requests(tenant, source),
            "在项目执行申请中办理原申请，或发布新批准政策后按当前政策续提；旧批准人不自动获得新授权",
        ),
        (
            "task_takeover_obligations",
            "任务交接交付与接收责任",
            task_packets(tenant, source),
            "先在原任务完成具名接收，或由其他交付人更新交接包并交给当前负责人；批量移交不改写原交接签名",
        ),
        (
            "risk_result_receivers",
            "风险处理结果具名接收",
            risk_results(tenant, source),
            "由当前任务负责人在原结果中更换独立接收人，或由原接收人接收/退回后继续办理；原结果和签名保留",
        ),
    ]
    if execution_query is not None:
        queries.append(
            (
                "change_execution_reviewers",
                "工程变更执行结果独立确认",
                execution_query,
                "在原变更结果中更换独立确认人，或由本人完成确认/退回；原执行范围与签名保留",
            )
        )
    for key, label, query, reason in queries:
        items = []
        for row in c.execute(query.order_by(query.selected_columns.id)).mappings():
            target_id = row.get("risk_id") or row.get("task_id")
            href = (
                f"/projects?project={row['project_id']}&tab=decisions&meeting_recurrence={row['id']}"
                if key in ("meeting_recurrence_roster", "meeting_generation_authority")
                else f"/projects?project={row['project_id']}&tab=decisions"
                f"&meeting={row['meeting_id']}"
                if key == "meeting_conference_requests"
                else f"/projects?project={row['project_id']}&tab=decisions"
                f"&meeting={row['meeting_id']}&meeting_roster_user={source}"
                if key == "meeting_roster_obligations"
                else (
                    f"/projects?project={row['project_id']}&tab=overview"
                    f"&resource_reservation_id={row['id']}"
                )
                if key == "personnel_resource_reservations"
                else f"/projects?project={row['project_id']}&tab=engineering"
                f"&change_ecr_id={row['ecr_id']}&change_task_id={row['task_id']}"
                if key == "change_execution_reviewers"
                else (
                    f"/projects?project={row['project_id']}&tab=overview&approval_request_kind="
                    + ("execution" if key == "pending_execution_approvals" else "baseline")
                    + f"&approval_request_id={row['id']}"
                )
                if key in ("pending_execution_approvals", "pending_baseline_approvals")
                else f"/projects?project={row['project_id']}&tab=work-items&entity_id={target_id}"
            )
            items.append(
                {
                    "id": str(row["id"]),
                    "title": row["title"],
                    "project_id": str(row["project_id"]),
                    "href": href,
                    "basis": digest(_plain(row)),
                }
            )
        if items:
            result.append(
                {
                    "key": key,
                    "label": label,
                    "count": len(items),
                    "can_transfer": False,
                    "reasons": [reason],
                    "items": items,
                }
            )
    return result


def history_statement(
    tenant: UUID,
    source: UUID | None,
    target: UUID | None,
    before_id: int | None,
) -> Select[Any]:
    a, u = tables.audit_log, tables.users
    actor = u.alias("handover_actor")
    old_user, new_user = u.alias("handover_from"), u.alias("handover_to")
    q = (
        select(
            a.c.id,
            a.c.entity_id.label("from_user_id"),
            a.c.actor_user_id,
            a.c.timestamp.label("created_at"),
            a.c.before_snapshot,
            a.c.after_snapshot,
            actor.c.display_name.label("actor_name"),
            old_user.c.display_name.label("from_name"),
            new_user.c.display_name.label("to_name"),
        )
        .select_from(
            a.outerjoin(
                actor, (actor.c.tenant_id == a.c.tenant_id) & (actor.c.id == a.c.actor_user_id)
            )
            .outerjoin(
                old_user, (old_user.c.tenant_id == a.c.tenant_id) & (old_user.c.id == a.c.entity_id)
            )
            .outerjoin(
                new_user,
                (new_user.c.tenant_id == a.c.tenant_id)
                & (cast(new_user.c.id, Text) == a.c.after_snapshot["to_user_id"].as_string()),
            )
        )
        .where(a.c.tenant_id == tenant, a.c.action == "user.responsibility_handover")
    )
    if source:
        q = q.where(a.c.entity_id == source)
    if target:
        q = q.where(a.c.after_snapshot["to_user_id"].as_string() == str(target))
    if before_id:
        q = q.where(a.c.id < before_id)
    return q.order_by(a.c.id.desc()).limit(21)


def history(
    engine: Engine,
    tenant: UUID,
    source: UUID | None,
    target: UUID | None,
    before_id: int | None,
) -> dict[str, Any]:
    with engine.connect() as c:
        rows = c.execute(history_statement(tenant, source, target, before_id)).mappings().all()
        return {
            "items": [_plain(row) for row in rows[:20]],
            "next_before_id": rows[19]["id"] if len(rows) > 20 else None,
        }
