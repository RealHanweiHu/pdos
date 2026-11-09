"""Manager cockpit: every project the reader may see, compared by exit outcome (§5.2, D76).

Rows come from the same personal project read as the project list (B2 same source),
so stage, gate and health agree across list, board, timeline and cockpit. A row
compares projects by their current stage's exit conditions — rule results, one per
condition — never by tasks, task counts or completion ratios (P61-3). The cockpit
only drills down; it offers no rescheduling or reallocation (B4).
"""

from uuid import UUID

from sqlalchemy import and_, func, select

from pdos_next.domain.categories.preproject.access import human
from pdos_next.errors import DomainError

from . import rules

PAGE = 200


def _projects(s, ctx):
    from pdos_next.domain.my_work.views import projects

    entries, unavailable, cursor, seen = [], 0, None, set()
    while True:
        page = projects(s, ctx, cursor=cursor, page_size=PAGE)
        entries.extend(page["items"])
        unavailable += page["unavailable_count"]
        cursor = page["next_cursor"]
        if not cursor:
            return entries, unavailable
        if cursor in seen:
            raise DomainError("VERSION_CONFLICT", "项目分页位置未推进，请刷新重试。")
        seen.add(cursor)


def _open_risks(s, ctx, project_ids):
    from pdos_next.domain.categories.preproject.models import ProjectOpenItem
    from pdos_next.domain.projects.risk.models import ProjectRiskFollowupCurrent

    if not project_ids:
        return {}
    closed = (
        select(ProjectRiskFollowupCurrent.id)
        .where(
            ProjectRiskFollowupCurrent.tenant_id == ProjectOpenItem.tenant_id,
            ProjectRiskFollowupCurrent.risk_id == ProjectOpenItem.id,
            ProjectRiskFollowupCurrent.state == "closed",
        )
        .exists()
    )
    return dict(
        s.execute(
            select(ProjectOpenItem.project_id, func.count(ProjectOpenItem.id))
            .where(
                ProjectOpenItem.tenant_id == ctx.tenant_id,
                ProjectOpenItem.project_id.in_(project_ids),
                ProjectOpenItem.kind == "risk",
                ~closed,
            )
            .group_by(ProjectOpenItem.project_id)
        ).all()
    )


def _sets(s, ctx, project_ids):
    from pdos_next.domain.projects.sets.models import ProjectSet, ProjectSetLink

    if not project_ids:
        return {}
    latest = (
        select(ProjectSetLink.project_id, ProjectSetLink.set_id)
        .where(
            ProjectSetLink.tenant_id == ctx.tenant_id,
            ProjectSetLink.project_id.in_(project_ids),
        )
        .distinct(ProjectSetLink.project_id)
        .order_by(ProjectSetLink.project_id, ProjectSetLink.revision.desc())
        .subquery()
    )
    names = (
        select(ProjectSet.set_id, ProjectSet.name)
        .where(ProjectSet.tenant_id == ctx.tenant_id)
        .distinct(ProjectSet.set_id)
        .order_by(ProjectSet.set_id, ProjectSet.revision.desc())
        .subquery()
    )
    rows = s.execute(
        select(latest.c.project_id, latest.c.set_id, names.c.name).outerjoin(
            names, and_(names.c.set_id == latest.c.set_id)
        )
    ).all()
    return {
        row.project_id: {"id": str(row.set_id), "name": row.name}
        for row in rows
        if row.set_id is not None
    }


def _row(entry, *, risk_count, project_set, principal_id):
    project, governance = entry["project"], entry["project"]["governance"]
    timeline = governance["timeline"] if governance["stages"] else None
    update = project.get("latest_status_update")
    return {
        "project": {
            "id": project["id"],
            "name": project["name"],
            "status": project["status"],
            "visibility": project["visibility"],
            "owner": {"id": project["owner_id"], "name": project.get("owner_name")},
            "category": {"id": entry["category"]["id"], "name": entry["category"]["name"]},
            "product": {"id": entry["product"]["id"], "name": entry["product"]["name"]},
            "set": project_set,
        },
        "stage": {
            "adopted": bool(governance["stages"]),
            "stages": [
                {"name": stage["name"], "status": stage["status"]} for stage in governance["stages"]
            ],
            "current": governance["current_stage"]["name"] if governance["current_stage"] else None,
            "completed": governance["completed"],
        },
        "health": governance["health"],
        "next_node": {
            "name": governance["next_gate_name"],
            "times": {
                "baseline": ((timeline or {}).get("baseline") or {}).get("latest_finish"),
                "forecast": ((timeline or {}).get("forecast") or {}).get("latest_finish"),
                "commitments": [
                    {"promised_at": c["promised_at"], "fulfilled": c["fulfilled"]}
                    for c in (timeline or {}).get("commitments", [])
                ],
                "actual": (timeline or {}).get("actual"),
            },
            "slip": rules.slip(timeline),
        },
        "exit_conditions": rules.exit_conditions(governance.get("exit_conditions", [])),
        "exit_outcomes": {"available": False, "label": rules.STAGE_NODES_MISSING},
        "latest_update": {
            "first_sentence": rules.first_sentence(update["fact_summary"]),
            "actor": update["actor"],
            "created_at": update["created_at"],
        }
        if update
        else None,
        "risk_count": risk_count,
        "review_pending": bool(governance.get("review_pending")),
        "my_decision": bool(governance.get("review_pending"))
        and project["owner_id"] == str(principal_id),
    }


def cockpit(s, ctx):
    human(s, ctx)
    entries, unavailable = _projects(s, ctx)
    keys = [UUID(entry["project"]["id"]) for entry in entries]
    risks = _open_risks(s, ctx, keys)
    sets = _sets(s, ctx, keys)
    rows = [
        _row(
            entry,
            risk_count=risks.get(UUID(entry["project"]["id"]), 0),
            project_set=sets.get(UUID(entry["project"]["id"])),
            principal_id=ctx.requester_id,
        )
        for entry in entries
    ]
    order = {rule["state"]: index for index, rule in enumerate(rules.HEALTH_RULES)}
    rows.sort(key=lambda row: (order.get(row["health"]["state"], 99), row["project"]["name"]))
    return {
        "version": "project-cockpit/v1",
        "as_of": s.scalar(select(func.transaction_timestamp())).isoformat(),
        "rules": list(rules.RULES),
        "summary": rules.summary(rows, principal_id=ctx.requester_id)
        | {
            "resource_conflicts": {
                "available": False,
                "reason": "跨项目资源冲突读集尚未接入；冲突在各项目计划候选比较中查看。",
            },
            "status_updates_missing": {
                "available": False,
                "reason": "状态更新周期尚未接入（由自动化规则提供），暂不判定缺失。",
            },
            "agent_exceptions": {
                "available": False,
                "reason": "小Pai 自动化例外尚未接入（由自动化规则提供）。",
            },
        },
        "items": rows,
        "unavailable_count": unavailable,
    }
