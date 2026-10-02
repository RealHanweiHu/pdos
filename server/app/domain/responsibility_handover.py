"""Current responsibility inventory shared by handover preview and application."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Connection, Table, exists, or_, select

from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables
from app.domain.product_workspace import _plain, digest


class HandoverConflictError(ValueError):
    pass


@dataclass(frozen=True)
class Responsibility:
    key: str
    label: str
    table: Table
    column: str
    current: ColumnElement[bool]
    action: Action | None = None
    manual: bool = False


def _quality_kind(name: str) -> str:
    return {
        "complaints": "complaint",
        "nonconformance_reports": "ncr",
        "capa_actions": "capa",
        "certifications": "certification",
    }[name]


def _handoff_label(key: str) -> str:
    from app.domain.project_completion import HANDOFF_ITEMS

    return HANDOFF_ITEMS.get(key, key)


def responsibilities() -> tuple[Responsibility, ...]:
    t = tables
    formal_tasks = exists(
        select(t.schedule_nodes.c.task_id).where(
            t.schedule_nodes.c.tenant_id == t.tasks.c.tenant_id,
            t.schedule_nodes.c.task_id == t.tasks.c.id,
        )
    )
    specs = [
        Responsibility(
            "issue_owner",
            "问题负责人",
            t.issues,
            "owner_user_id",
            (t.issues.c.status != "closed") & t.issues.c.withdrawn_at.is_(None),
            Action.ISSUE_EXECUTE,
        ),
        Responsibility(
            "issue_verifier",
            "问题验证人",
            t.issues,
            "verifier_user_id",
            (t.issues.c.status != "closed") & t.issues.c.withdrawn_at.is_(None),
            Action.ISSUE_VERIFY,
        ),
        Responsibility(
            "task_assignee",
            "任务负责人",
            t.tasks,
            "assignee_user_id",
            t.tasks.c.status.not_in(("done", "skipped")) & ~formal_tasks,
            Action.WORK_ITEM_EDIT,
        ),
        Responsibility(
            "risk_owner",
            "风险负责人",
            t.risks,
            "owner_user_id",
            t.risks.c.status != "closed",
            Action.WORK_ITEM_EDIT,
        ),
        Responsibility(
            "project_owner",
            "项目负责人",
            t.projects,
            "owner_user_id",
            t.projects.c.status.not_in(("completed", "archived")),
            Action.PROJECT_EDIT,
        ),
        Responsibility(
            "direct_reports", "直接下属", t.users, "manager_user_id", t.users.c.is_active.is_(True)
        ),
        Responsibility(
            "formal_task_owner",
            "已登记排程的任务负责人",
            t.tasks,
            "assignee_user_id",
            t.tasks.c.status.not_in(("done", "skipped")) & formal_tasks,
            manual=True,
        ),
    ]
    # These records use their own version, review or acceptance workflows.
    # Keep their original owners and give administrators the actual objects to resolve.
    for name, label, column, current in (
        (
            "research_tasks",
            "研究任务负责人",
            "owner_user_id",
            t.research_tasks.c.state.not_in(("completed", "cancelled")),
        ),
        (
            "scoped_work_items",
            "立项前工作负责人",
            "owner_user_id",
            t.scoped_work_items.c.state.not_in(("completed", "cancelled")),
        ),
        (
            "scoped_work_items",
            "立项前工作接收人",
            "receiver_user_id",
            t.scoped_work_items.c.state.not_in(("completed", "cancelled")),
        ),
        ("complaints", "客诉负责人", "owner_user_id", t.complaints.c.status != "closed"),
        (
            "nonconformance_reports",
            "不符合项负责人",
            "owner_user_id",
            t.nonconformance_reports.c.status != "closed",
        ),
        ("capa_actions", "CAPA行动负责人", "owner_user_id", t.capa_actions.c.status != "completed"),
        (
            "project_handoff_items",
            "项目结束交接接收人",
            "receiver_user_id",
            t.project_handoff_items.c.status != "accepted",
        ),
        ("certifications", "在办认证负责人", "owner_user_id", t.certifications.c.status == "draft"),
        (
            "decisions",
            "待执行决定负责人",
            "owner_user_id",
            t.decisions.c.follow_up_state.in_(("pending", "completed")),
        ),
        (
            "initial_plan_reviews",
            "初始计划审核人",
            "reviewer_user_id",
            t.initial_plan_reviews.c.state == "pending_review",
        ),
        (
            "resource_reservations",
            "资源预约负责人",
            "owner_user_id",
            t.resource_reservations.c.state.in_(("proposed", "reserved")),
        ),
        (
            "resources",
            "未释放的旧资源分配",
            "assigned_user_id",
            t.resources.c.status.in_(("planned", "active")),
        ),
        (
            "product_definitions",
            "未发布产品定义负责人",
            "owner_user_id",
            t.product_definitions.c.state != "published",
        ),
        (
            "definition_requirement_packages",
            "需求候选包负责人",
            "owner_user_id",
            t.definition_requirement_packages.c.state.in_(("pending_review", "accepted")),
        ),
        (
            "application_input_waits",
            "运行待补充信息",
            "owner_user_id",
            t.application_input_waits.c.resolved_at.is_(None),
        ),
    ):
        specs.append(
            Responsibility(
                f"{name}.{column}", label, getattr(t, name), column, current, manual=True
            )
        )
    for name, label, current in (
        ("market_spaces", "市场空间负责人", t.market_spaces.c.lifecycle != "archived"),
        ("product_nodes", "产品层级负责人", t.product_nodes.c.lifecycle != "retired"),
        ("research_sources", "有效研究来源负责人", t.research_sources.c.status == "active"),
        (
            "research_subscriptions",
            "研究订阅负责人",
            t.research_subscriptions.c.status.in_(("active", "paused", "quarantined")),
        ),
        ("opportunities", "在办机会负责人", t.opportunities.c.state != "closed"),
        ("experiments", "在办实验负责人", t.experiments.c.state.not_in(("concluded", "cancelled"))),
        ("product_strategies", "未发布策略负责人", t.product_strategies.c.state != "published"),
        (
            "meeting_agenda_items",
            "未决会议议题负责人",
            t.meeting_agenda_items.c.resolution_status == "open",
        ),
    ):
        specs.append(
            Responsibility(
                f"{name}.owner_user_id",
                label,
                getattr(t, name),
                "owner_user_id",
                current,
                manual=True,
            )
        )
    for name, label in (
        ("project_execution_policies", "项目执行批准人"),
        ("baseline_change_policies", "基线变更批准人"),
        ("schedule_commitment_policies", "承诺批准人"),
    ):
        table = getattr(t, name)
        newer = table.alias(f"newer_{name}_handover")
        current = ~exists(
            select(newer.c.id).where(
                newer.c.tenant_id == table.c.tenant_id,
                newer.c.project_id == table.c.project_id,
                newer.c.version > table.c.version,
            )
        )
        specs.append(Responsibility(name, label, table, "approver_user_id", current, manual=True))
    revision, newer = (
        t.id_design_revisions,
        t.id_design_revisions.alias("newer_id_handover_revision"),
    )
    current = ~exists(
        select(newer.c.id).where(
            newer.c.tenant_id == revision.c.tenant_id,
            newer.c.variant_id == revision.c.variant_id,
            newer.c.version > revision.c.version,
        )
    ) & ~exists(
        select(t.id_design_freezes.c.id).where(
            t.id_design_freezes.c.tenant_id == revision.c.tenant_id,
            t.id_design_freezes.c.variant_id == revision.c.variant_id,
        )
    )
    specs.append(
        Responsibility(
            "id_design_owner", "未冻结设计负责人", revision, "owner_user_id", current, manual=True
        )
    )
    specification = t.specifications
    later = specification.alias("handover_newer_specification")
    specs.append(
        Responsibility(
            "specification_owner",
            "当前规格负责人",
            specification,
            "owner_user_id",
            ~exists(
                select(later.c.id).where(
                    later.c.tenant_id == specification.c.tenant_id,
                    later.c.project_id == specification.c.project_id,
                    later.c.code == specification.c.code,
                    later.c.version > specification.c.version,
                )
            ),
            manual=True,
        )
    )
    return tuple(specs)


def inventory(
    connection: Connection, tenant_id: UUID, source_id: UUID, target_id: UUID, now: datetime
) -> dict[str, Any]:
    users = {
        row["id"]: row
        for row in connection.execute(
            select(tables.users).where(
                tables.users.c.tenant_id == tenant_id,
                tables.users.c.id.in_((source_id, target_id)),
            )
        ).mappings()
    }
    if source_id == target_id or set(users) != {source_id, target_id}:
        raise HandoverConflictError("请选择本组织中两位不同成员")
    if not users[target_id]["is_active"] or users[target_id]["role"] in ("supplier", "customer"):
        raise HandoverConflictError("接手人须为有效内部成员")
    target_role = Role(users[target_id]["role"])
    groups: list[dict[str, Any]] = []
    affected_projects: set[UUID] = set()
    for spec in responsibilities():
        table = spec.table
        statement = select(table).where(
            table.c.tenant_id == tenant_id, table.c[spec.column] == source_id, spec.current
        )
        if "supersedes_id" in table.c:
            newer_row = table.alias(f"newer_{spec.key.replace('.', '_')}")
            statement = statement.where(
                ~exists(
                    select(newer_row.c.id).where(
                        newer_row.c.tenant_id == tenant_id, newer_row.c.supersedes_id == table.c.id
                    )
                )
            )
        if spec.table is tables.initial_plan_reviews:
            newer_review = table.alias("handover_newer_plan_review")
            next_candidate = tables.initial_plan_candidates.alias("handover_newer_plan_candidate")
            statement = statement.where(
                ~exists(
                    select(newer_review.c.id).where(
                        newer_review.c.tenant_id == table.c.tenant_id,
                        newer_review.c.candidate_id == table.c.candidate_id,
                        newer_review.c.round_no > table.c.round_no,
                    )
                ),
                ~exists(
                    select(next_candidate.c.id).where(
                        next_candidate.c.tenant_id == table.c.tenant_id,
                        next_candidate.c.supersedes_id == table.c.candidate_id,
                    )
                ),
            )
        if spec.key == "direct_reports":
            statement = statement.where(table.c.id != target_id)
        if "project_id" in table.c:
            statement = statement.where(
                exists(
                    select(tables.projects.c.id).where(
                        tables.projects.c.tenant_id == tenant_id,
                        tables.projects.c.id == table.c.project_id,
                        tables.projects.c.status.not_in(("completed", "archived")),
                    )
                )
            )
        if table is tables.id_design_revisions:
            statement = statement.add_columns(
                select(tables.id_design_variants.c.title)
                .where(
                    tables.id_design_variants.c.tenant_id == tenant_id,
                    tables.id_design_variants.c.id == table.c.variant_id,
                )
                .scalar_subquery()
                .label("title")
            )
        if table is tables.application_input_waits:
            run = tables.agent_runs
            statement = (
                statement.join(
                    run, (run.c.tenant_id == table.c.tenant_id) & (run.c.id == table.c.run_id)
                )
                .add_columns(run.c.project_id, table.c.body["goal"].as_string().label("title"))
                .where(
                    run.c.status == "waiting_input",
                    table.c.expires_at > now,
                    exists(
                        select(tables.projects.c.id).where(
                            tables.projects.c.tenant_id == tenant_id,
                            tables.projects.c.id == run.c.project_id,
                            tables.projects.c.status.not_in(("completed", "archived")),
                        )
                    ),
                )
            )
        if table is tables.meeting_agenda_items:
            meeting = tables.meetings
            statement = (
                statement.join(
                    meeting,
                    (meeting.c.tenant_id == table.c.tenant_id)
                    & (meeting.c.id == table.c.meeting_id),
                )
                .add_columns(meeting.c.project_id)
                .where(
                    meeting.c.status.in_(("scheduled", "in_progress", "completed")),
                    meeting.c.deleted_at.is_(None),
                    meeting.c.archived_at.is_(None),
                    exists(
                        select(tables.projects.c.id).where(
                            tables.projects.c.tenant_id == tenant_id,
                            tables.projects.c.id == meeting.c.project_id,
                            tables.projects.c.status.not_in(("completed", "archived")),
                        )
                    ),
                )
            )
        if table is tables.definition_requirement_packages:
            statement = statement.add_columns(
                select(tables.product_definitions.c.title)
                .where(
                    tables.product_definitions.c.tenant_id == tenant_id,
                    tables.product_definitions.c.id == table.c.definition_id,
                )
                .scalar_subquery()
                .label("title")
            )
        rows = list(connection.execute(statement.order_by(table.c.id)).mappings())
        if spec.table is tables.decisions:
            from app.domain.decision_responsibilities import current as decision_current

            rows = [
                row
                for row in rows
                if decision_current(connection, tenant_id, row["project_id"], row["id"])[
                    "effective_follow_up_state"
                ]
                == "pending"
            ]
        if not rows:
            continue
        reasons = []
        if spec.manual:
            reasons.append(
                "由资源管理员核对并释放原分配，保留原人员与盘点历史；接手人的新占用另行预约"
                if table is tables.resources
                else "请在原业务入口按当前版本重新指定责任或完成办理"
            )
        if spec.action and not is_allowed(target_role, spec.action):
            reasons.append("接手人当前角色不能办理这类工作；移交不会借用离职成员的角色")
        if spec.key in ("issue_owner", "issue_verifier"):
            opposite = "verifier_user_id" if spec.key == "issue_owner" else "owner_user_id"
            if any(row[opposite] in (source_id, target_id) for row in rows):
                reasons.append("接手人已承担同一问题的另一职责，请分别指定负责人和验证人")
        if spec.key == "direct_reports":
            from app.domain.organization import escalation_chain

            ancestors = escalation_chain(connection, tenant_id=tenant_id, user_id=target_id)
            if any(row["id"] in ancestors for row in rows):
                reasons.append("本次移交会形成汇报关系环，请先调整组织关系")
        entries = []
        for row in rows:
            project_id = row.get("project_id") or (
                row["id"] if spec.key == "project_owner" else None
            )
            if project_id and not reasons:
                affected_projects.add(project_id)
            entries.append(
                {
                    "id": str(row["id"]),
                    "title": str(
                        _handoff_label(row["item_key"])
                        if spec.table is tables.project_handoff_items
                        else row.get("title")
                        or row.get("certificate_type")
                        or row.get("nonconformity")
                        or row.get("description")
                        or row.get("name")
                        or row.get("question")
                        or row.get("hypothesis")
                        or row.get("url")
                        or row.get("display_name")
                        or row["id"]
                    ),
                    "project_id": str(project_id) if project_id else None,
                    "href": (
                        f"/projects?project={project_id}&tab=overview&approval_policy_kind="
                        + {
                            "project_execution_policies": "execution",
                            "baseline_change_policies": "baseline",
                            "schedule_commitment_policies": "commitment",
                        }[table.name]
                        + f"&approval_policy_id={row['id']}"
                    )
                    if table
                    in (
                        tables.project_execution_policies,
                        tables.baseline_change_policies,
                        tables.schedule_commitment_policies,
                    )
                    else (
                        f"/projects?project={project_id}&tab=overview&id_owner_revision={row['id']}"
                    )
                    if table is tables.id_design_revisions
                    else (
                        f"/projects?project={project_id}&tab=overview"
                        f"&specification_owner_id={row['id']}"
                    )
                    if table is tables.specifications
                    else (
                        f"/projects?project={project_id}&tab=overview"
                        f"&resource_allocation_id={row['id']}"
                    )
                    if table is tables.resources
                    else f"/projects?project={project_id}&tab=overview&input_wait_id={row['id']}"
                    if table is tables.application_input_waits
                    else (
                        f"/projects?project={project_id}&tab=decisions"
                        f"&meeting={row['meeting_id']}&agenda_owner_id={row['id']}"
                    )
                    if table is tables.meeting_agenda_items
                    else f"/knowledge?source_owner_id={row['id']}"
                    if table is tables.research_sources
                    else (
                        "/product-work?space="
                        + str(
                            row["id"] if table is tables.market_spaces else row["market_space_id"]
                        )
                        + (
                            "&responsibility_kind=space"
                            if table is tables.market_spaces
                            else "&responsibility_kind=node"
                        )
                        + f"&responsibility_id={row['id']}"
                    )
                    if table in (tables.market_spaces, tables.product_nodes)
                    else (
                        f"/projects?project={project_id}&tab=decisions"
                        f"&decision_owner_id={row['id']}"
                    )
                    if project_id and table is tables.decisions
                    else (
                        f"/product-work?space={row['market_space_id']}"
                        "&responsibility_kind="
                        + {
                            "research_tasks": "research",
                            "scoped_work_items": "work",
                            "product_definitions": "definition",
                            "definition_requirement_packages": "package",
                            "product_strategies": "strategy",
                            "experiments": "experiment",
                            "opportunities": "opportunity",
                            "research_subscriptions": "subscription",
                        }[table.name]
                        + f"&responsibility_id={row['id']}"
                    )
                    if table
                    in (
                        tables.research_tasks,
                        tables.scoped_work_items,
                        tables.product_definitions,
                        tables.definition_requirement_packages,
                        tables.product_strategies,
                        tables.experiments,
                        tables.opportunities,
                        tables.research_subscriptions,
                    )
                    else (
                        f"/projects?project={project_id}&tab=overview"
                        f"&reservation_owner_id={row['id']}"
                    )
                    if project_id and table is tables.resource_reservations
                    else (
                        f"/projects?project={project_id}&tab=quality"
                        f"&quality_owner_kind={_quality_kind(table.name)}&quality_owner_id={row['id']}"
                    )
                    if project_id
                    and table
                    in (
                        tables.complaints,
                        tables.nonconformance_reports,
                        tables.capa_actions,
                        tables.certifications,
                    )
                    else (
                        f"/projects?project={project_id}&tab=overview"
                        f"&completion_item={row['item_key']}"
                    )
                    if project_id and spec.table is tables.project_handoff_items
                    else f"/projects?project={project_id}&tab=work-items&entity_id={row['id']}"
                    if project_id and spec.table in (tables.tasks, tables.issues, tables.risks)
                    else f"/projects?project={project_id}"
                    if project_id
                    else f"/initial-plans/{row['candidate_id']}"
                    if spec.table is tables.initial_plan_reviews
                    else "/product-work"
                    if "market_space_id" in table.c
                    else "/governance/organization",
                    "basis": digest(_plain(row)),
                }
            )
        groups.append(
            {
                "key": spec.key,
                "label": spec.label,
                "count": len(entries),
                "can_transfer": not reasons,
                "reasons": reasons,
                "items": entries,
            }
        )
    # Reuse the live named-confirmation/acceptance query, including supersession and closed rounds.
    from app.domain.id_design_inbox import inbox_statement

    id_statement = inbox_statement(tenant_id, source_id, Role.ADMIN)
    if id_statement is not None:
        entries = [
            {
                "id": str(row["id"]),
                "title": row["title"],
                "project_id": str(row["project_id"]),
                "href": (
                    f"/projects?project={row['project_id']}&tab=overview"
                    f"&id_freeze_request={row['id']}&id_revision={row['revision_id']}"
                )
                if row["kind"] == "freeze"
                else (
                    f"/projects?project={row['project_id']}&tab=overview"
                    f"&id_handoff={row['id']}&id_freeze={row['freeze_id']}"
                ),
                "basis": digest(_plain(row)),
            }
            for row in connection.execute(id_statement.order_by("id")).mappings()
        ]
        if entries:
            groups.append(
                {
                    "key": "id_design_actions",
                    "label": "设计确认与交接接收",
                    "count": len(entries),
                    "can_transfer": False,
                    "reasons": ["固定版本中的具名确认不能代签，请重新准备冻结申请或交接轮次"],
                    "items": entries,
                }
            )
    from app.domain.handover_workflows import groups as workflow_groups

    groups.extend(workflow_groups(connection, tenant_id, source_id))
    from app.domain.case_review_responsibilities import groups as case_review_groups

    groups.extend(case_review_groups(connection, tenant_id, source_id))
    from app.domain.gate_responsibilities import groups as gate_groups

    groups.extend(gate_groups(connection, tenant_id, source_id))
    from app.domain.preproject_responsibilities import definition_obligations

    groups.extend(definition_obligations(connection, tenant_id, source_id))
    pending_plan_entries = []
    candidates = tables.initial_plan_candidates
    newer_candidate = candidates.alias("newer_handover_plan")
    for candidate in connection.execute(
        select(candidates)
        .where(
            candidates.c.tenant_id == tenant_id,
            ~exists(
                select(newer_candidate.c.id).where(
                    newer_candidate.c.tenant_id == tenant_id,
                    newer_candidate.c.supersedes_id == candidates.c.id,
                )
            ),
            ~exists(
                select(tables.initial_plan_applications.c.id).where(
                    tables.initial_plan_applications.c.tenant_id == tenant_id,
                    tables.initial_plan_applications.c.candidate_id == candidates.c.id,
                )
            ),
        )
        .order_by(candidates.c.id)
    ).mappings():
        for node in candidate["plan"]["nodes"]:
            if str(source_id) in (node.get("owner_user_id"), node.get("receiver_user_id")):
                pending_plan_entries.append(
                    {
                        "id": f"{candidate['id']}:{node['node_key']}",
                        "title": node["title"],
                        "project_id": None,
                        "href": f"/initial-plans/{candidate['id']}?node={node['node_key']}",
                        "basis": digest({"candidate_id": str(candidate["id"]), "node": node}),
                    }
                )
    if pending_plan_entries:
        groups.append(
            {
                "key": "initial_plan_responsibility",
                "label": "未应用计划中的负责人和接收人",
                "count": len(pending_plan_entries),
                "can_transfer": False,
                "reasons": ["请修订计划中的具名责任并重新确认，原审核依据保留"],
                "items": pending_plan_entries,
            }
        )
    # Formal receiver roles live in the current baseline, including later baseline changes.
    from app.domain.formal_schedule import current_plan, current_states

    receiver_entries = []
    for project in connection.execute(
        select(tables.projects.c.id).where(
            tables.projects.c.tenant_id == tenant_id,
            tables.projects.c.status.not_in(("completed", "archived")),
        )
    ).scalars():
        formal = current_plan(connection, tenant_id, project)
        if formal is None:
            continue
        states, _ = current_states(connection, tenant_id, project, formal)
        done = {
            state["node_key"]
            for state in states
            if state.get("actual_finish") or state.get("status") in ("done", "skipped", "completed")
        }
        node_ids = {node["node_key"]: node["id"] for node in formal["nodes"]}
        for node in formal["plan"]["nodes"]:
            if node["node_key"] not in done and str(source_id) in (
                node.get("owner_user_id"),
                node.get("receiver_user_id"),
            ):
                receiver_entries.append(
                    {
                        "id": f"{project}:{node['node_key']}",
                        "title": node["title"],
                        "project_id": str(project),
                        "href": f"/projects?project={project}&tab=overview"
                        f"&schedule_responsibility_node={node_ids[node['node_key']]}",
                        "basis": digest({"node": node, "baseline": str(formal["baseline_id"])}),
                    }
                )
    if receiver_entries:
        groups.append(
            {
                "key": "formal_plan_responsibility",
                "label": "正式计划中的负责人和接收人",
                "count": len(receiver_entries),
                "can_transfer": False,
                "reasons": ["责任属于获批计划，请在项目排程中提交责任变更并应用新基线"],
                "items": receiver_entries,
            }
        )
    delegations = [
        _plain(row)
        for row in connection.execute(
            select(tables.user_delegations)
            .where(
                tables.user_delegations.c.tenant_id == tenant_id,
                tables.user_delegations.c.revoked_at.is_(None),
                tables.user_delegations.c.ends_at > now,
                or_(
                    tables.user_delegations.c.principal_user_id == source_id,
                    tables.user_delegations.c.delegate_user_id == source_id,
                ),
            )
            .order_by(tables.user_delegations.c.id)
        ).mappings()
    ]
    if users[target_id]["manager_user_id"] == source_id:
        groups.append(
            {
                "key": "successor_reporting_line",
                "label": "接手人的汇报关系",
                "count": 1,
                "can_transfer": True,
                "reasons": [],
                "items": [
                    {
                        "id": str(target_id),
                        "title": users[target_id]["display_name"],
                        "project_id": None,
                        "href": "/governance/organization",
                        "basis": digest(_plain(users[target_id])),
                    }
                ],
            }
        )
    existing_memberships = set(
        connection.execute(
            select(tables.project_members.c.project_id).where(
                tables.project_members.c.tenant_id == tenant_id,
                tables.project_members.c.user_id == target_id,
                tables.project_members.c.project_id.in_(affected_projects),
            )
        ).scalars()
    )
    membership_additions = affected_projects - existing_memberships
    result = {
        "project_access_count": len(membership_additions),
        "successor_manager_id": str(users[source_id]["manager_user_id"])
        if users[source_id]["manager_user_id"]
        else None,
        "from_name": users[source_id]["display_name"],
        "to_name": users[target_id]["display_name"],
        "from_user_id": str(source_id),
        "to_user_id": str(target_id),
        "groups": groups,
        "delegations_to_revoke": len(delegations),
        "project_ids": sorted(str(p) for p in membership_additions),
        "transfer_count": sum(g["count"] for g in groups if g["can_transfer"]),
        "manual_count": sum(g["count"] for g in groups if not g["can_transfer"]),
    }
    result["basis_digest"] = digest(
        {
            **result,
            "users": [
                {
                    field: str(users[key][field])
                    for field in ("id", "role", "is_active", "manager_user_id")
                }
                for key in (source_id, target_id)
            ],
            "delegations": delegations,
        }
    )
    return result
