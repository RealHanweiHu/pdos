"""Explicit answer-to-task continuation over the existing work_management skill."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from pdos_next.agent_kernel.models import AgentRun
from pdos_next.agent_kernel.requested_skills import RequestedSkill, validate
from pdos_next.agent_kernel.skills import SkillCatalog
from pdos_next.domain.preproject.access import member
from pdos_next.domain.work_management.owner import project
from pdos_next.errors import DomainError
from pdos_next.schema_base import StrictModel

from .action_sources import capture_work, recheck_work

OPERATION = "work.task.create"
SKILL = "work_management"
KEY = "work_followup_action"


class Assignment(StrictModel):
    assignee_id: UUID
    recipient_id: UUID


class WorkFollowupAction(StrictModel):
    kind: Literal["prepare_work_followup"] = "prepare_work_followup"
    project_id: UUID
    citation_ids: tuple[UUID, ...] = Field(min_length=1, max_length=20)
    assignment: Assignment | None = None


def _assignment(session, ctx, run, value):
    if value is None:
        return
    chosen = Assignment.model_validate(value)
    target = project(session, ctx, run.product_id, run.project_id)
    if target.owner_id != ctx.requester_id:
        raise DomainError("FORBIDDEN_SCOPE", "任务分派仍须由当前项目负责人确认。", 403)
    for identity in {chosen.assignee_id, chosen.recipient_id}:
        if not member(session, ctx, identity).can_write:
            raise DomainError("FORBIDDEN_SCOPE", "办理人须有当前品类写入权限。", 403)


def prepare_start(session, ctx, effective, parent, requested):
    if requested is None:
        return effective, None, tuple(effective.requested_skills)
    if (
        parent is None
        or parent.product_id is None
        or parent.project_id is None
        or parent.category_id != ctx.category_id
        or effective.product_id != parent.product_id
        or effective.project_id != parent.project_id
        or requested.project_id != parent.project_id
    ):
        raise DomainError("FORBIDDEN_SCOPE", "请从本项目的引用回答准备资料跟进任务。", 403)
    _assignment(session, ctx, parent, requested.assignment)
    proof = capture_work(session, ctx, parent, requested.citation_ids)
    from .action_taint import inherit

    inherit(parent, proof["taint"])
    catalog = SkillCatalog()
    skill = catalog.configuration(SKILL)
    if skill is None:
        raise DomainError("SOURCE_UNAVAILABLE", "项目工作技能尚未配置。")
    fixed = RequestedSkill(key=skill.key, version=skill.version, digest=skill.digest)
    skills = tuple(effective.requested_skills)
    if not any(value.key == SKILL for value in skills):
        skills += (fixed,)
    validate(session, ctx, skills, catalog=catalog)
    action = {
        "version": 1,
        "kind": requested.kind,
        "source_run_id": str(parent.id),
        "citation_ids": sorted({str(value) for value in requested.citation_ids}),
        "assignment": (
            requested.assignment.model_dump(mode="json") if requested.assignment else None
        ),
        "source_proof": proof,
    }
    # The Human's actual source choices remain effective.sources. Selecting a
    # discussion citation never silently binds it as a task original.
    return effective, action, skills


def check_action(session, ctx, run, action):
    if (
        not isinstance(action, dict)
        or action.get("version") != 1
        or action.get("kind") != "prepare_work_followup"
    ):
        raise DomainError("SOURCE_STALE", "资料跟进入口资料已变化。")
    parent = session.get(AgentRun, UUID(action["source_run_id"]))
    if (
        parent is None
        or parent.id != run.continued_from_id
        or parent.tenant_id != run.tenant_id
        or parent.session_id != run.session_id
        or parent.requester_id != ctx.requester_id
        or parent.category_id != ctx.category_id
        or parent.product_id != run.product_id
        or parent.project_id != run.project_id
    ):
        raise DomainError("FORBIDDEN_SCOPE", "资料跟进须沿用真实直接父讨论与本人项目。", 403)
    # Assignment remains a Human selection. Its native T1 owner rechecks current
    # members when a real task exists; readonly action checks must not lock Grants.
    proof = recheck_work(session, ctx, parent, action["source_proof"])
    if sorted(action["citation_ids"]) != sorted(
        row["citation_id"] for row in proof["discussion_sources"]
    ):
        raise DomainError("SOURCE_STALE", "固定讨论依据已变化。")
    return proof


def context_value(action):
    return {
        "kind": "prepare_work_followup",
        "project_id": action["source_proof"]["target"]["project_id"],
        "citation_ids": list(action["citation_ids"]),
        "draft_rules": [
            "只准备work.task.create候选，由本人核对后创建；此入口不自动执行T0。",
            "根据原讨论起草标题、目标和成果要求；方法、判据缺乏依据时保留待确认。",
            "sources只能引用本人选择且本次实际读取的原件与逐字定位，聊天不是原件。",
            "缺少原件、目标或成果要求时向本人询问；不默认生成G0事项、计划或日期承诺。",
            "负责人由本人在独立work.task.assign的T1确认中办理，不冒充承接或承诺。",
        ],
    }


CONTEXT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "kind": {"const": "prepare_work_followup"},
        "project_id": {"type": "string", "format": "uuid"},
        "citation_ids": {"type": "array", "items": {"type": "string", "format": "uuid"}},
        "draft_rules": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["kind", "project_id", "citation_ids", "draft_rules"],
}
