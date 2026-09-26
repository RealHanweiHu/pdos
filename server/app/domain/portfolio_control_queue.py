"""Globally ordered, permission-scoped management work from actual domain records."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import Field
from sqlalchemy import (
    Connection,
    Date,
    DateTime,
    Engine,
    String,
    Uuid,
    case,
    cast,
    func,
    literal,
    or_,
    select,
    union_all,
)

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.contracts.common_objects import Contract
from app.db.schema import tables
from app.domain.my_work import _page_summary
from app.domain.organization import active_delegated_principals
from app.domain.product_workspace import ProductWorkError, _plain, _role, digest

LABELS = {
    "gate_signoff": "待专业签核",
    "gate_decision": "待Gate裁决",
    "gate_condition": "未闭Gate条件",
    "execution_approval": "首版计划待批准",
    "execution_application": "首版计划待应用",
    "baseline_approval": "基线变更待批准",
    "baseline_application": "基线变更待应用",
    "discussion_brief": "本人讨论摘要待核对",
    "decision_followup": "已决待落实",
    "blocked_task": "任务阻塞",
    "severe_issue": "高严重问题",
    "risk": "当前确认风险",
    "ecr_approval": "工程变更待批准",
    "ecn_effectivity": "ECN生效待裁决",
    "cost_approval": "成本冻结待批准",
    "cost_gap": "成本差额观察待核对",
    "id_freeze_product": "设计冻结·产品确认",
    "id_freeze_me": "设计冻结·结构确认",
    "id_freeze_hw": "设计冻结·硬件确认",
    "id_freeze_application": "设计确认齐备待冻结",
    "cross_predecessor_approval": "跨项目排程·前序项目确认",
    "cross_successor_approval": "跨项目排程·后序项目确认",
}
Kind = Literal[
    "gate_signoff",
    "gate_decision",
    "gate_condition",
    "execution_approval",
    "execution_application",
    "baseline_approval",
    "baseline_application",
    "discussion_brief",
    "decision_followup",
    "blocked_task",
    "severe_issue",
    "risk",
    "ecr_approval",
    "ecn_effectivity",
    "cost_approval",
    "cost_gap",
    "id_freeze_product",
    "id_freeze_me",
    "id_freeze_hw",
    "id_freeze_application",
    "cross_predecessor_approval",
    "cross_successor_approval",
]


class ControlQueueRead(Contract):
    project_id: UUID | None = None
    kind: Kind | None = None
    search: str = Field(default="", max_length=200)
    mine: bool = False
    overdue_only: bool = False
    order: Literal["urgency", "waiting", "risk"] = "urgency"
    offset: int = Field(default=0, ge=0)
    revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


def queries(
    context: AuthContext, now: datetime, *, visible_projects: Any
) -> tuple[list[Any], list[str]]:
    tenant = context.tenant.id
    statements = []
    unavailable: list[str] = []
    today = now.astimezone(ZoneInfo("Asia/Shanghai")).date()

    def emit(
        kind: str,
        table: Any,
        *,
        title: Any,
        status: Any,
        since: Any = None,
        due: Any = None,
        overdue: Any = None,
        owner: Any = None,
        relation: Any = None,
        note: Any = None,
        priority: Any = None,
        condition: Any = None,
        source: Any = None,
    ) -> None:
        columns = [
            literal(kind).label("kind"),
            table.c.id.label("id"),
            table.c.project_id.label("project_id"),
            title.label("title"),
            status.label("status"),
            cast(since, DateTime(timezone=True)).label("waiting_since"),
            cast(due, Date).label("due_date"),
            func.coalesce(overdue, False).label("overdue"),
            cast(owner, Uuid).label("owner_user_id"),
            cast(relation, Uuid).label("relation_id"),
            cast(note, String).label("note"),
            (priority if priority is not None else literal(0)).label("priority"),
        ]
        q = (
            select(*columns)
            .select_from(source if source is not None else table)
            .where(table.c.tenant_id == tenant)
        )
        if condition is not None:
            q = q.where(condition)
        statements.append(q)

    # Existing Gate rules decide actual readiness. This queue only exposes original pending work.
    if is_allowed(context.user.role, Action.GATE_VIEW):
        s, r, g = tables.gate_signoffs, tables.gate_signoff_rounds, tables.gates
        join = s.join(
            r,
            (r.c.tenant_id == s.c.tenant_id)
            & (r.c.project_id == s.c.project_id)
            & (r.c.id == s.c.round_id),
        ).join(
            g,
            (g.c.tenant_id == s.c.tenant_id)
            & (g.c.project_id == s.c.project_id)
            & (g.c.id == s.c.gate_id),
        )
        # Read the actual named signer in the original routing snapshot.
        # Missing assignments remain unknown.
        assigned = r.c.routing_snapshot["assignment"]["signers"][s.c.slot]["user_id"].as_string()
        emit(
            "gate_signoff",
            s,
            title=g.c.name,
            status=s.c.status,
            since=s.c.created_at,
            due=func.timezone("Asia/Shanghai", g.c.review_due_at),
            overdue=g.c.review_due_at < now,
            owner=cast(assigned, Uuid),
            relation=g.c.id,
            note=s.c.slot,
            priority=literal(80),
            source=join,
            condition=(s.c.status == "pending")
            & (s.c.requirement != "not_applicable")
            & (r.c.status == "open"),
        )
        emit(
            "gate_decision",
            g,
            title=g.c.name,
            status=g.c.status,
            since=r.c.opened_at,
            due=func.timezone("Asia/Shanghai", g.c.review_due_at),
            overdue=g.c.review_due_at < now,
            relation=r.c.id,
            note=literal("专业签核齐备性与当前事实仍在原Gate页复核"),
            priority=literal(80),
            source=g.join(
                r,
                (r.c.tenant_id == g.c.tenant_id)
                & (r.c.project_id == g.c.project_id)
                & (r.c.gate_id == g.c.id),
            ),
            condition=(g.c.status == "reviewing")
            & (r.c.status == "open")
            & ~select(s.c.id)
            .where(s.c.tenant_id == tenant, s.c.round_id == r.c.id, s.c.status == "pending")
            .correlate(r)
            .exists(),
        )
    else:
        unavailable.extend(("gate_signoff", "gate_decision", "gate_condition"))
    t = tables.tasks
    if is_allowed(context.user.role, Action.GATE_VIEW):
        emit(
            "gate_condition",
            t,
            title=t.c.title,
            status=t.c.status,
            since=t.c.created_at,
            due=t.c.due_date,
            overdue=t.c.due_date < today,
            owner=t.c.assignee_user_id,
            relation=t.c.source_entity_id,
            note=t.c.expected_output,
            priority=literal(75),
            condition=(t.c.kind == "gate_action")
            & (t.c.source_entity == "gate")
            & (t.c.status != "done"),
        )
    events = tables.events
    transition = (
        select(events.c.timestamp, events.c.payload)
        .where(
            events.c.tenant_id == tenant,
            events.c.project_id == t.c.project_id,
            events.c.entity_id == t.c.id,
            events.c.event_type == "TASK_STATUS_CHANGED",
        )
        .order_by(events.c.timestamp.desc(), events.c.id.desc())
        .limit(1)
        .lateral("blocked_transition")
    )
    emit(
        "blocked_task",
        t,
        title=t.c.title,
        status=t.c.status,
        since=case(
            (transition.c.payload["to_status"].as_string() == "blocked", transition.c.timestamp),
            else_=None,
        ),
        due=t.c.due_date,
        overdue=t.c.due_date < today,
        owner=t.c.assignee_user_id,
        note=t.c.blocked_reason,
        priority=literal(70),
        source=t.outerjoin(transition, literal(True)),
        condition=(t.c.status == "blocked") & (t.c.kind != "gate_action"),
    )
    i = tables.issues
    emit(
        "severe_issue",
        i,
        title=i.c.title,
        status=i.c.status,
        since=i.c.created_at,
        due=i.c.target_date,
        overdue=i.c.target_date < today,
        owner=i.c.owner_user_id,
        note=i.c.severity,
        priority=case((i.c.severity == "critical", 100), else_=90),
        condition=(i.c.status != "closed") & i.c.severity.in_(("high", "critical")),
    )
    risks = tables.risks
    emit(
        "risk",
        risks,
        title=risks.c.title,
        status=risks.c.status,
        since=risks.c.created_at,
        due=risks.c.target_date,
        overdue=risks.c.target_date < today,
        owner=risks.c.owner_user_id,
        note=risks.c.mitigation_plan,
        priority=risks.c.likelihood * risks.c.impact,
        condition=(risks.c.status != "closed")
        & (risks.c.draft_state == "confirmed")
        & risks.c.dismissed_at.is_(None),
    )
    d = tables.decisions
    emit(
        "decision_followup",
        d,
        title=d.c.title,
        status=d.c.follow_up_state,
        since=d.c.decided_at,
        owner=d.c.owner_user_id,
        relation=d.c.follow_up_task_id,
        note=d.c.follow_up_note,
        priority=literal(60),
        condition=d.c.follow_up_state == "pending",
    )
    b, p, a = (
        tables.baseline_change_requests,
        tables.baseline_change_policies,
        tables.baseline_change_applications,
    )
    decisions = tables.baseline_change_decisions
    joined = b.join(
        p,
        (p.c.tenant_id == b.c.tenant_id)
        & (p.c.project_id == b.c.project_id)
        & (p.c.id == b.c.policy_id),
    )
    newer_policy = p.alias("current_queue_baseline_policy")
    current_policy = (
        select(newer_policy.c.id)
        .where(newer_policy.c.tenant_id == tenant, newer_policy.c.project_id == b.c.project_id)
        .order_by(newer_policy.c.version.desc())
        .limit(1)
        .correlate(b)
        .scalar_subquery()
    )

    def original_status(value: str) -> Any:
        return case((b.c.policy_id != current_policy, "policy_changed"), else_=value)

    no_application = (
        ~select(a.c.id)
        .where(a.c.tenant_id == tenant, a.c.change_id == b.c.id)
        .correlate(b)
        .exists()
    )
    emit(
        "baseline_approval",
        b,
        title=literal("正式基线变更"),
        status=original_status("pending"),
        since=b.c.created_at,
        owner=p.c.approver_user_id,
        relation=b.c.policy_id,
        note=b.c.reason,
        priority=literal(80),
        source=joined,
        condition=~select(decisions.c.id)
        .where(decisions.c.tenant_id == tenant, decisions.c.change_id == b.c.id)
        .correlate(b)
        .exists()
        & no_application,
    )
    stopped = decisions.alias("queue_stopped")
    emit(
        "baseline_application",
        b,
        title=literal("获批基线独立应用"),
        status=original_status("approved"),
        since=decisions.c.created_at,
        relation=b.c.policy_id,
        note=b.c.reason,
        priority=literal(65),
        source=joined.join(
            decisions,
            (decisions.c.tenant_id == b.c.tenant_id)
            & (decisions.c.change_id == b.c.id)
            & (decisions.c.action == "approve"),
        ),
        condition=no_application
        & ~select(stopped.c.id)
        .where(
            stopped.c.tenant_id == tenant,
            stopped.c.change_id == b.c.id,
            stopped.c.action != "approve",
        )
        .correlate(b)
        .exists(),
    )
    ex, ep, ea = (
        tables.project_execution_requests,
        tables.project_execution_policies,
        tables.initial_plan_applications,
    )
    exjoin = ex.join(
        ep,
        (ep.c.tenant_id == ex.c.tenant_id)
        & (ep.c.project_id == ex.c.project_id)
        & (ep.c.id == ex.c.policy_id),
    )
    for state, kind in (
        ("pending_approval", "execution_approval"),
        ("approved", "execution_application"),
    ):
        emit(
            kind,
            ex,
            title=literal("首版正式计划"),
            status=ex.c.state,
            since=ex.c.created_at
            if state == "pending_approval"
            else cast(ex.c.approval["approved_at"].as_string(), DateTime(timezone=True)),
            owner=ep.c.approver_user_id if state == "pending_approval" else None,
            relation=ex.c.policy_id,
            note=ex.c.request_reason,
            priority=literal(80 if state == "pending_approval" else 65),
            source=exjoin,
            condition=(ex.c.state == state)
            & ~select(ea.c.id)
            .where(ea.c.tenant_id == tenant, ea.c.execution_request_id == ex.c.id)
            .correlate(ex)
            .exists(),
        )
    if is_allowed(context.user.role, Action.CHANGE_VIEW):
        ecr, ecn = tables.engineering_change_requests, tables.engineering_change_notices
        emit(
            "ecr_approval",
            ecr,
            title=ecr.c.code + " · " + ecr.c.title,
            status=ecr.c.status,
            since=ecr.c.analyzed_at,
            priority=literal(80),
            note=literal("等待本轮影响分析批准；原双人规则、范围与当前事实仍在原变更入口核对"),
            condition=ecr.c.status == "approval",
        )
        event = tables.events
        submitted = (
            select(func.max(event.c.timestamp))
            .where(
                event.c.tenant_id == tenant,
                event.c.project_id == ecn.c.project_id,
                event.c.entity_id == ecn.c.id,
                event.c.event_type == "CHANGE_RECORD_CHANGED",
                event.c.payload["record_type"].as_string() == "ecn",
                event.c.payload["action"].as_string() == "effectivity_submitted",
            )
            .correlate(ecn)
            .scalar_subquery()
        )
        emit(
            "ecn_effectivity",
            ecn,
            title=ecn.c.code + " · " + ecn.c.title,
            status=ecn.c.status,
            since=submitted,
            relation=ecn.c.ecr_id,
            priority=literal(80),
            note=literal("等待ECN生效裁决；等待起点取原提交事件，缺失时保留未知"),
            condition=ecn.c.status == "effectivity_decision",
        )
    else:
        unavailable.extend(("ecr_approval", "ecn_effectivity"))
    if is_allowed(context.user.role, Action.PRODUCT_ENGINEERING_VIEW):
        request, decision, calculation = (
            tables.cost_freeze_requests,
            tables.cost_freeze_decisions,
            tables.cost_rollups,
        )
        emit(
            "cost_approval",
            request,
            title=calculation.c.title,
            status=literal("pending_approval"),
            since=request.c.created_at,
            owner=request.c.approver_user_id,
            relation=request.c.rollup_id,
            priority=literal(80),
            note=literal("原成本计算待具名批准；来源、范围、金额与批准资格在原入口重核"),
            source=request.join(
                calculation,
                (calculation.c.tenant_id == request.c.tenant_id)
                & (calculation.c.project_id == request.c.project_id)
                & (calculation.c.id == request.c.rollup_id),
            ),
            condition=~select(decision.c.id)
            .where(
                decision.c.tenant_id == tenant,
                decision.c.project_id == request.c.project_id,
                decision.c.freeze_request_id == request.c.id,
            )
            .correlate(request)
            .exists(),
        )
        case_row, observation, issue = (
            tables.cost_gap_cases,
            tables.cost_gap_observations,
            tables.issues,
        )
        newer = observation.alias("newer_control_gap")
        emit(
            "cost_gap",
            observation,
            title=literal("Cost Gap · ") + case_row.c.subsystem + " · " + case_row.c.basis,
            status=observation.c.state,
            since=observation.c.created_at,
            owner=issue.c.owner_user_id,
            relation=case_row.c.issue_id,
            due=issue.c.target_date,
            overdue=issue.c.target_date < today,
            priority=literal(70),
            note=literal("最新保存观察；期限沿关联问题。实际办理前重核原计算和来源；问题状态：")
            + issue.c.status,
            source=observation.join(
                case_row,
                (case_row.c.tenant_id == observation.c.tenant_id)
                & (case_row.c.project_id == observation.c.project_id)
                & (case_row.c.id == observation.c.case_id),
            ).join(
                issue,
                (issue.c.tenant_id == case_row.c.tenant_id)
                & (issue.c.project_id == case_row.c.project_id)
                & (issue.c.id == case_row.c.issue_id),
            ),
            condition=observation.c.state.in_(("exceeded", "needs_review"))
            & ~select(newer.c.id)
            .where(
                newer.c.tenant_id == tenant,
                newer.c.project_id == observation.c.project_id,
                newer.c.case_id == observation.c.case_id,
                newer.c.version > observation.c.version,
            )
            .correlate(observation)
            .exists(),
        )
    else:
        unavailable.extend(("cost_approval", "cost_gap"))
    if is_allowed(context.user.role, Action.PRODUCT_ENGINEERING_VIEW):
        request, decision, frozen, revision, variant = (
            tables.id_design_freeze_requests,
            tables.id_design_freeze_decisions,
            tables.id_design_freezes,
            tables.id_design_revisions,
            tables.id_design_variants,
        )
        successor = request.alias("control_id_successor")
        newer = revision.alias("control_id_newer_revision")
        changed = (
            select(newer.c.id)
            .where(
                newer.c.tenant_id == tenant,
                newer.c.project_id == revision.c.project_id,
                newer.c.variant_id == revision.c.variant_id,
                newer.c.version > revision.c.version,
            )
            .correlate(revision)
            .exists()
        )
        source = request.join(
            revision,
            (revision.c.tenant_id == request.c.tenant_id)
            & (revision.c.project_id == request.c.project_id)
            & (revision.c.id == request.c.revision_id),
        ).join(
            variant,
            (variant.c.tenant_id == revision.c.tenant_id)
            & (variant.c.project_id == revision.c.project_id)
            & (variant.c.id == revision.c.variant_id),
        )
        pending = (
            ~select(successor.c.id)
            .where(
                successor.c.tenant_id == tenant,
                successor.c.project_id == request.c.project_id,
                successor.c.previous_request_id == request.c.id,
            )
            .correlate(request)
            .exists()
        )
        pending = (
            pending
            & ~select(decision.c.id)
            .where(
                decision.c.tenant_id == tenant,
                decision.c.project_id == request.c.project_id,
                decision.c.freeze_request_id == request.c.id,
                decision.c.action == "reject",
            )
            .correlate(request)
            .exists()
        )
        pending = (
            pending
            & ~select(frozen.c.id)
            .where(
                frozen.c.tenant_id == tenant,
                frozen.c.project_id == revision.c.project_id,
                frozen.c.variant_id == revision.c.variant_id,
            )
            .correlate(revision)
            .exists()
        )
        for slot in ("product", "me", "hw"):
            emit(
                f"id_freeze_{slot}",
                request,
                title=variant.c.title,
                status=case((changed, "source_changed"), else_="pending"),
                since=request.c.created_at,
                owner=case((changed, None), else_=request.c[f"{slot}_user_id"]),
                relation=request.c.revision_id,
                priority=literal(80),
                source=source,
                note=literal(
                    "原设计冻结分席确认；已替代申请不重复列出，当前版本与固定证据在原入口复核"
                ),
                condition=pending
                & ~select(decision.c.id)
                .where(
                    decision.c.tenant_id == tenant,
                    decision.c.project_id == request.c.project_id,
                    decision.c.freeze_request_id == request.c.id,
                    decision.c.slot == slot,
                )
                .correlate(request)
                .exists(),
            )
        approvals = (
            select(func.count())
            .select_from(decision)
            .where(
                decision.c.tenant_id == tenant,
                decision.c.project_id == request.c.project_id,
                decision.c.freeze_request_id == request.c.id,
                decision.c.action == "approve",
            )
            .correlate(request)
            .scalar_subquery()
        )
        approved_at = (
            select(func.max(decision.c.created_at))
            .where(
                decision.c.tenant_id == tenant,
                decision.c.project_id == request.c.project_id,
                decision.c.freeze_request_id == request.c.id,
                decision.c.action == "approve",
            )
            .correlate(request)
            .scalar_subquery()
        )
        emit(
            "id_freeze_application",
            request,
            title=variant.c.title,
            status=case((changed, "source_changed"), else_="approved"),
            since=approved_at,
            relation=request.c.revision_id,
            priority=literal(65),
            source=source,
            note=literal("三席已确认，等待原独立冻结办理；确认并不等同已冻结"),
            condition=pending & (approvals == 3),
        )
    else:
        unavailable.extend(
            ("id_freeze_product", "id_freeze_me", "id_freeze_hw", "id_freeze_application")
        )
    # A cross-project proposal is readable only through both project scopes or its
    # exact original named sharing audience. Do not expose partner records here.
    proposals, policies, decisions = (
        tables.cross_project_schedule_proposals,
        tables.baseline_change_policies,
        tables.cross_project_schedule_decisions,
    )
    applications = tables.cross_project_schedule_applications
    for side in ("predecessor", "successor"):
        proposal = select(
            proposals, proposals.c[f"{side}_project_id"].label("project_id")
        ).subquery(f"control_cross_{side}")
        named_member = (
            literal(context.user.role in (Role.OWNER, Role.ADMIN))
            | select(tables.project_members.c.id)
            .where(
                tables.project_members.c.tenant_id == tenant,
                tables.project_members.c.project_id == proposal.c.project_id,
                tables.project_members.c.user_id == context.user.id,
            )
            .correlate(proposal)
            .exists()
        )
        shared = (
            (proposal.c.snapshot["sharing"]["version"].as_string() == "cross_schedule_approval.v1")
            & (
                proposal.c.snapshot[side]["policy"]["approver_user_id"].as_string()
                == str(context.user.id)
            )
            & proposal.c.snapshot["sharing"]["audience"].bool_op("@>")(
                func.jsonb_build_array(
                    func.jsonb_build_object(
                        "project_id",
                        cast(proposal.c.project_id, String),
                        "approver_user_id",
                        str(context.user.id),
                    )
                )
            )
            & named_member
        )
        allowed = (
            proposal.c.predecessor_project_id.in_(visible_projects)
            & proposal.c.successor_project_id.in_(visible_projects)
        ) | shared
        newer_policy = policies.alias(f"control_cross_{side}_newer_policy")
        changed_policy = (
            select(newer_policy.c.id)
            .where(
                newer_policy.c.tenant_id == tenant,
                newer_policy.c.project_id == policies.c.project_id,
                newer_policy.c.version > policies.c.version,
            )
            .correlate(policies)
            .exists()
        )
        emit(
            f"cross_{side}_approval",
            proposal,
            title=func.coalesce(
                proposal.c.snapshot[side]["node"]["title"].as_string(), "原跨项目节点"
            ),
            status=case((changed_policy, "policy_changed"), else_="pending"),
            since=proposal.c.created_at,
            owner=case((changed_policy, None), else_=policies.c.approver_user_id),
            relation=proposal.c[f"{side}_policy_id"],
            priority=literal(80),
            note=literal(
                "本项目一侧的跨项目排程确认；仅展示本侧节点，原分享范围、双方来源和双人规则在原入口复核"
            ),
            source=proposal.join(
                policies,
                (policies.c.tenant_id == proposal.c.tenant_id)
                & (policies.c.project_id == proposal.c.project_id)
                & (policies.c.id == proposal.c[f"{side}_policy_id"]),
            ),
            condition=allowed
            & ~select(decisions.c.id)
            .where(
                decisions.c.tenant_id == tenant,
                decisions.c.proposal_id == proposal.c.id,
                (decisions.c.project_id == proposal.c.project_id)
                | (decisions.c.action != "approve"),
            )
            .correlate(proposal)
            .exists()
            & ~select(applications.c.id)
            .where(applications.c.tenant_id == tenant, applications.c.proposal_id == proposal.c.id)
            .correlate(proposal)
            .exists(),
        )
    if is_allowed(context.user.role, Action.CHANGE_VIEW) and is_allowed(
        context.user.role, Action.QUALITY_VIEW
    ):
        run, review = tables.agent_runs, tables.debate_brief_reviews
        binding = tables.debate_run_bindings
        turns = tables.debate_turn_receipts
        emit(
            "discussion_brief",
            run,
            title=literal("本人已完成讨论的摘要待核对"),
            status=run.c.status,
            since=run.c.completed_at,
            owner=run.c.requested_by_user_id,
            relation=binding.c.ecr_id,
            source=run.join(
                binding,
                (binding.c.tenant_id == run.c.tenant_id)
                & (binding.c.project_id == run.c.project_id)
                & (binding.c.run_id == run.c.id),
            ),
            note=literal("仅表示暂无具名核对回执；原资料和分歧须在原讨论中重新核对"),
            priority=literal(55),
            condition=(run.c.context_version == "change-discussion-request-v1")
            & (run.c.status == "succeeded")
            & (run.c.requested_by_user_id == context.user.id)
            & ~select(review.c.id)
            .where(review.c.tenant_id == tenant, review.c.run_id == run.c.id)
            .correlate(run)
            .exists()
            & select(turns.c.id)
            .where(turns.c.tenant_id == tenant, turns.c.run_id == run.c.id)
            .correlate(run)
            .exists(),
        )
    else:
        unavailable.append("discussion_brief")
    return statements, unavailable


def link(row: dict[str, Any]) -> str:
    base = f"/projects?project={row['project_id']}"
    kind = row["kind"]
    identity = row["id"]
    if kind.startswith("id_freeze_"):
        return f"{base}&tab=overview&id_freeze_request={identity}&id_revision={row['relation_id']}"
    if kind.startswith("cross_"):
        return f"{base}&tab=overview&cross_proposal={identity}#cross-proposal-landing"
    if kind == "ecr_approval":
        return f"{base}&tab=engineering&change_ecr_id={identity}#ecr-{identity}"
    if kind == "ecn_effectivity":
        return f"{base}&tab=engineering&change_ecr_id={row['relation_id']}#ecn-{identity}"
    if kind == "cost_approval":
        return f"{base}&tab=materials&cost_freeze_request={identity}#cost-freeze-landing"
    if kind == "cost_gap":
        return f"{base}&tab=work-items&entity_id={row['relation_id']}#issue-{row['relation_id']}"
    if kind == "gate_signoff":
        return f"{base}&tab=gates&gate={row['relation_id']}"
    if kind == "gate_decision":
        return f"{base}&tab=gates&gate={identity}"
    if kind.startswith("baseline_"):
        return f"{base}&tab=overview&approval_request_kind=baseline&approval_request_id={identity}"
    if kind.startswith("execution_"):
        return f"{base}&tab=overview&approval_request_kind=execution&approval_request_id={identity}"
    if kind == "discussion_brief":
        return f"{base}&tab=decisions&discussion_run_id={identity}" + (
            f"&discussion_ecr_id={row['relation_id']}" if row["relation_id"] else ""
        )
    if kind == "decision_followup":
        return f"{base}&tab=decisions&decision_id={identity}#decision-{identity}"
    tab = "issues" if kind == "severe_issue" else "risks" if kind == "risk" else "tasks"
    return f"{base}&tab={tab}&entity_id={identity}"


def queue_query(
    c: Connection, context: AuthContext, now: datetime
) -> tuple[Any, Any, Any, Any, list[str]]:
    _role(context, Action.WORK_ITEM_VIEW)
    p = tables.projects
    visible = select(p.c.id).where(p.c.tenant_id == context.tenant.id)
    if context.user.role not in (Role.OWNER, Role.ADMIN):
        principals = active_delegated_principals(
            c, tenant_id=context.tenant.id, delegate_user_id=context.user.id, moment=now
        )
        visible = visible.where(
            p.c.id.in_(
                select(tables.project_members.c.project_id).where(
                    tables.project_members.c.tenant_id == context.tenant.id,
                    tables.project_members.c.user_id.in_((context.user.id, *principals)),
                )
            )
        )
    statements, unavailable = queries(context, now, visible_projects=visible)
    q = union_all(*statements).subquery("management_queue")
    u = tables.users
    source = q.join(p, (p.c.tenant_id == context.tenant.id) & (p.c.id == q.c.project_id)).outerjoin(
        u, (u.c.tenant_id == context.tenant.id) & (u.c.id == q.c.owner_user_id)
    )
    query = (
        select(
            q,
            p.c.code.label("project_code"),
            p.c.name.label("project_name"),
            p.c.status.label("project_status"),
            u.c.display_name.label("owner_name"),
        )
        .select_from(source)
        .where(q.c.project_id.in_(visible))
    )
    return query, q, source, visible, unavailable


class PortfolioControlQueue:
    def __init__(self, engine: Engine):
        self.engine = engine

    def read(self, context: AuthContext, command: ControlQueueRead) -> dict[str, Any]:
        _role(context, Action.WORK_ITEM_VIEW)
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            query, q, source, visible, unavailable = queue_query(c, context, now)
            p = tables.projects
            if command.project_id:
                query = query.where(q.c.project_id == command.project_id)
            if command.kind:
                query = query.where(q.c.kind == command.kind)
            if command.mine:
                query = query.where(q.c.owner_user_id == context.user.id)
            if command.overdue_only:
                query = query.where(q.c.overdue.is_(True))
            if command.search:
                query = query.where(
                    or_(
                        q.c.title.icontains(command.search, autoescape=True),
                        p.c.code.icontains(command.search, autoescape=True),
                        p.c.name.icontains(command.search, autoescape=True),
                    )
                )
            order: tuple[Any, ...] = (
                q.c.overdue.desc(),
                q.c.priority.desc(),
                q.c.waiting_since.asc().nullslast(),
                q.c.kind,
                q.c.id,
            )
            if command.order == "waiting":
                order = (q.c.waiting_since.asc().nullslast(), q.c.priority.desc(), q.c.kind, q.c.id)
            if command.order == "risk":
                order = (
                    q.c.priority.desc(),
                    q.c.overdue.desc(),
                    q.c.waiting_since.asc().nullslast(),
                    q.c.kind,
                    q.c.id,
                )
            count, revision = c.execute(_page_summary(query, order)).one()
            if command.offset and (not command.revision or revision != command.revision):
                raise ProductWorkError("队列内容或权限已有变化，请从第一页重新读取")
            found = (
                c.execute(query.order_by(*order).offset(command.offset).limit(31)).mappings().all()
            )
            items = []
            for r in found[:30]:
                item = _plain(r)
                since = r["waiting_since"]
                item.update(
                    source_digest=digest(_plain(r)),
                    label=LABELS[r["kind"]],
                    href=link(item),
                    waiting_days=str(
                        max(Decimal(0), Decimal(str((now - since).total_seconds())) / 86400)
                    )
                    if since
                    else None,
                    timing_basis="actual_status_transition"
                    if r["kind"] == "blocked_task"
                    else "issue_registered"
                    if r["kind"] == "severe_issue"
                    else "cost_observation_registered"
                    if r["kind"] == "cost_gap"
                    else "risk_registered"
                    if r["kind"] == "risk"
                    else "original_request_or_assignment",
                )
                items.append(item)
            counts = c.execute(
                select(q.c.kind, func.count())
                .select_from(source)
                .where(q.c.project_id.in_(visible))
                .group_by(q.c.kind)
            ).all()
            return {
                "items": items,
                "can_escalate": is_allowed(context.user.role, Action.WORK_ITEM_EDIT),
                "total": count,
                "revision": revision,
                "next_offset": command.offset + 30 if len(found) > 30 else None,
                "as_of": now.isoformat(),
                "business_date": now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat(),
                "counts": {k: n for k, n in counts},
                "unavailable": unavailable,
                "labels": LABELS,
                "scope": "all_currently_visible_projects; private_briefs_actor_only",
                "ordering": "过期优先；再按业务类型优先级/严重度及原等待时间；未配置自动升级",
            }
