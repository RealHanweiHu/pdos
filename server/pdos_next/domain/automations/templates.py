"""Minimal automation rule templates (D75, with D71 + D190), server-owned and fixed.

Deterministic templates are always on for every project: their rule owner is the
project owner (the P57 item 2 pattern), their scope is that project as the owner can
see it now (P57 item 1), and their result is the owner's attention in “要我决定”.
They never call a model, store a run or send anything. Parameters are fixed in this
minimal version (one working day, Monday-to-Friday estimate, P41-10).

The status-update template is the one rule a person instantiates: the project owner
sets a cadence (P34-6) and, on each slot, 小Pai drafts a status update through the one
registered graph (Temporal → LangGraph) as a one-confirmation candidate for the owner,
who publishes it under their own name (P65, P18). It never publishes by itself.
"""

from uuid import UUID

from sqlalchemy import select

from pdos_next.domain.projects.work import business_days
from pdos_next.domain.projects.work.status_cadence import GRACE_WORKDAYS
from pdos_next.errors import DomainError

STATUS_UPDATE = "status_update_draft"
STATUS_UPDATE_SKILL = "work_management"
STATUS_UPDATE_OPERATION = "work.status_update.create"

_DETERMINISTIC = {
    "mode": "deterministic",
    "model_calls": False,
    "always_on": True,
    "instantiable": False,
    "rule_owner": "project_owner",
    "recipient": "project_owner",
    "queue": "decide",
    "scope": "本项目 ∩ 项目负责人当前可见范围，每次读取重新核对（P57）",
    "workdays": 1,
    "basis": business_days.BASIS,
    "basis_label": business_days.BASIS_LABEL,
}

TEMPLATES = (
    {
        **_DETERMINISTIC,
        "key": "followup_unanswered",
        "name": "分派未回复升级",
        "debt": "D71",
        "decision": "P77",
        "summary": "任务分派后 1 个工作日仍未承接，给项目负责人一条注意项。",
    },
    {
        **_DETERMINISTIC,
        "key": "followup_not_progressed",
        "name": "承接未推进升级",
        "debt": "D190",
        "decision": "P77",
        "summary": "承接（“收到”）后 1 个工作日仍未开始，单独计时，给项目负责人一条注意项。",
    },
    {
        **_DETERMINISTIC,
        "key": "commitment_due",
        "name": "承诺到期提醒",
        "debt": "D75",
        "decision": "P77",
        "summary": "承诺 1 个工作日内到期或已过期且成果未提交，给项目负责人一条注意项。",
    },
    {
        **_DETERMINISTIC,
        "key": "external_wait_overdue",
        "name": "外部等待升级",
        "debt": "D75",
        "decision": "P77",
        "summary": (
            "外部等待过内部检查点 1 个工作日仍未登记回复，给项目负责人一条注意项；"
            "跟进责任人自己的“等外部回复”不变。"
        ),
    },
    {
        "key": STATUS_UPDATE,
        "name": "状态更新起草",
        "debt": "D75",
        "decision": "P65",
        "mode": "model",
        "model_calls": True,
        "always_on": False,
        "instantiable": True,
        "rule_owner": "project_owner",
        "recipient": "project_owner",
        "queue": "decide",
        "scope": "本项目；规则负责人须为当前项目负责人（P57、P65）",
        "tier": "T1",
        "skill": STATUS_UPDATE_SKILL,
        "operation": STATUS_UPDATE_OPERATION,
        "grace_workdays": GRACE_WORKDAYS,
        "basis": business_days.BASIS,
        "basis_label": business_days.BASIS_LABEL,
        "summary": (
            "按项目负责人设定的周期，小Pai 起草状态更新，作为一次确认候选交负责人发布；"
            "到期后 1 个工作日仍未发布显示“状态更新缺失”。不自动发布，不改任何状态。"
        ),
        "defaults": {
            "name": "项目状态更新起草",
            "goal": (
                "按本项目当前事实起草一条状态更新：事实摘要、下一步和引用的任务（固定版本）。"
                "只准备一次确认候选，交项目负责人确认后具名发布；不发布，不改任务、计划、"
                "预测、承诺或任何状态，不新建任务。"
            ),
            "purpose": "按周期为项目负责人准备状态更新草稿（P34 第 6 项、P65）。",
            "stop_condition": "本次候选已准备，或项目已不在负责人当前范围内。",
            "interval_seconds": 7 * 86400,
            "original_timezone": business_days.DEFAULT_TIMEZONE,
            "cooldown_seconds": 3600,
        },
    },
)


def catalog():
    return {"version": "automation-templates/v1", "templates": [dict(t) for t in TEMPLATES]}


def check_status_update(s, ctx, spec, *, enabled, rule_id=None):
    """P57-2 / P65: the cadence belongs to the current project owner; one per project."""
    from pdos_next.domain.projects.models import Project

    from .models import AutomationRuleCurrent as Current
    from .models import AutomationRuleVersion as Version

    project_id = UUID(str(spec.trigger_config["project_id"]))
    project = s.scalar(
        select(Project).where(
            Project.tenant_id == ctx.tenant_id,
            Project.category_id == ctx.category_id,
            Project.product_id == spec.product_id,
            Project.id == project_id,
        )
    )
    if project is None:
        raise DomainError("FORBIDDEN_SCOPE", "状态更新周期须绑定当前可见的实际项目。", 403)
    if project.owner_id != ctx.requester_id:
        raise DomainError(
            "FORBIDDEN_SCOPE", "状态更新周期由项目负责人设定，候选也只交项目负责人。", 403
        )
    if not enabled:
        return
    others = s.execute(
        select(Current.rule_id, Version.spec)
        .join(Version, Version.id == Current.published_version_id)
        .where(
            Current.tenant_id == ctx.tenant_id,
            Current.category_id == ctx.category_id,
            Current.owner_id == ctx.requester_id,
            Current.state == "active",
        )
    ).all()
    for other, saved in others:
        if (
            other != rule_id
            and saved.get("template") == STATUS_UPDATE
            and str((saved.get("trigger_config") or {}).get("project_id")) == str(project_id)
        ):
            raise DomainError(
                "VERSION_CONFLICT",
                "本项目已有启用的状态更新周期，请先暂停原规则或修改原规则。",
                detail={"rule_id": str(other)},
            )
