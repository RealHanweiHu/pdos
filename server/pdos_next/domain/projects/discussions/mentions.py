"""@ mentions in a discussion message (P34-3, design §7.1–7.2).

The composer writes tokens such as ``@[许晴](person:<uuid>)``; the server alone
decides who they reach. A mention only notifies and makes the person follow
that thread: it never grants access and is never an assignment.

- ``person``: must be able to see the thread's subject now, otherwise refused;
- ``role``: current project members holding that role who can see the subject;
- ``all``: only the project owner; every current member who can see it;
- ``task``: a reference to a task of the same project (no notification);
- ``agent``: @小Pai in a shared thread is W6 ⑥ (P34-4, P52, P54) and is refused here.
"""

import re
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select, text

from pdos_next.core.models import Principal
from pdos_next.domain.categories.preproject.access import fail

TOKEN = re.compile(
    r"@\[(?P<label>[^\]\n]{1,80})\]\((?P<kind>person|role|all|task|agent)(?::(?P<ref>[A-Za-z0-9_\-]{1,64}))?\)"
)
MAX_PEOPLE = 20


@dataclass
class Resolved:
    stored: list = field(default_factory=list)
    recipients: set = field(default_factory=set)
    people: set = field(default_factory=set)


def tokens(body):
    return [match.groupdict() for match in TOKEN.finditer(body)]


def _uuid(value):
    try:
        return UUID(value)
    except (TypeError, ValueError):
        fail("VALIDATION_FAILED", "mention_invalid", "提及格式无效，请重新选择。", 422)


def can_see(s, ctx, thread, person):
    return bool(
        s.scalar(
            text("SELECT discussion_person_open(:t, :c, :product, :project, :kind, :subject, :p)"),
            {
                "t": ctx.tenant_id,
                "c": thread.category_id,
                "product": thread.product_id,
                "project": thread.project_id,
                "kind": thread.subject_type,
                "subject": thread.subject_id,
                "p": person,
            },
        )
    )


def _current_members(s, ctx, project_id):
    from pdos_next.domain.projects.team.models import MemberRole, ProjectMember

    rows = s.execute(
        select(ProjectMember.id, ProjectMember.principal_id).where(
            ProjectMember.tenant_id == ctx.tenant_id,
            ProjectMember.project_id == project_id,
            ProjectMember.left_at.is_(None),
        )
    ).all()
    roles = {}
    for member_id, key in s.execute(
        select(MemberRole.member_id, MemberRole.role_key).where(
            MemberRole.tenant_id == ctx.tenant_id, MemberRole.project_id == project_id
        )
    ).all():
        roles.setdefault(member_id, set()).add(key)
    return {principal: roles.get(member_id, set()) for member_id, principal in rows}


def resolve(s, ctx, thread, project, body):
    """Validate every token against current access; return what to store and whom to notify."""
    from pdos_next.domain.projects.team import roles as catalog

    found = tokens(body)
    result = Resolved()
    if not found:
        return result
    if any(item["kind"] == "agent" for item in found):
        fail(
            "VALIDATION_FAILED",
            "agent_mention_pending",
            "在讨论中 @小Pai 还未开放，请在小Pai 对话中办理。",
            422,
        )
    members = None
    blocked = []
    seen = set()
    for item in found:
        kind, ref = item["kind"], item["ref"]
        key = (kind, ref)
        if key in seen:
            continue
        seen.add(key)
        if kind == "person":
            person = _uuid(ref)
            row = s.get(Principal, person)
            if row is None or row.tenant_id != ctx.tenant_id or row.kind != "human":
                fail("VALIDATION_FAILED", "mention_unknown", "被提及的人不在当前组织。", 422)
            if not can_see(s, ctx, thread, person):
                blocked.append({"principal_id": str(person), "name": row.name})
                continue
            result.people.add(person)
            result.recipients.add(person)
            result.stored.append({"kind": "person", "id": str(person)})
        elif kind in {"role", "all"}:
            if members is None:
                members = _current_members(s, ctx, project.id)
            if kind == "all":
                if ctx.requester_id != project.owner_id:
                    fail(
                        "FORBIDDEN_SCOPE",
                        "mention_all_owner_only",
                        "@全体 只有项目负责人可用。",
                        403,
                    )
                chosen = set(members)
            else:
                names = catalog.names(s, ctx.tenant_id)
                if ref is None or ref not in names:
                    fail(
                        "VALIDATION_FAILED",
                        "mention_role_unknown",
                        "该角色不在当前角色目录中。",
                        422,
                    )
                chosen = {person for person, held in members.items() if ref in held}
                if not chosen:
                    fail(
                        "VALIDATION_FAILED",
                        "mention_role_empty",
                        f"本项目暂无“{names[ref]}”角色的成员。",
                        422,
                    )
            reach = {person for person in chosen if can_see(s, ctx, thread, person)}
            result.recipients |= reach
            entry = {"kind": kind, "member_ids": sorted(str(value) for value in reach)}
            if kind == "role":
                entry["key"] = ref
            result.stored.append(entry)
        else:  # task reference: same project, visible to the writer
            from pdos_next.domain.projects.work.models import WorkTaskCurrent

            task_id = _uuid(ref)
            exists = s.scalar(
                select(WorkTaskCurrent.task_id).where(
                    WorkTaskCurrent.tenant_id == ctx.tenant_id,
                    WorkTaskCurrent.project_id == project.id,
                    WorkTaskCurrent.task_id == task_id,
                )
            )
            if exists is None:
                fail("VALIDATION_FAILED", "mention_task_unknown", "引用的任务不在本项目中。", 422)
            result.stored.append({"kind": "task", "id": str(task_id)})
    if blocked:
        fail(
            "VALIDATION_FAILED",
            "mention_not_visible",
            "不在本项目受众中："
            + "、".join(item["name"] for item in blocked)
            + "。提及不授予访问权，请先由负责人邀请加入团队。",
            422,
            blocked=blocked,
        )
    if len(result.recipients) > MAX_PEOPLE * 3 or len(result.people) > MAX_PEOPLE:
        fail("VALIDATION_FAILED", "mention_too_many", "一条消息提及的人过多，请缩小范围。", 422)
    return result
