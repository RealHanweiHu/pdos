"""Single-project overview: one read-only projection in the reader's own scope (P34-6, §5.1).

Everything here is read through the reader's category session, so row-level security
and each domain's own readers decide what appears; nothing is copied from a wider
scope. The overview never writes, never decides, and never derives a value from a
model. Sections that cannot be read say so instead of looking empty.
"""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, or_, select

from pdos_next.core.models import Principal
from pdos_next.core.service import require_access
from pdos_next.domain.categories.preproject.access import human
from pdos_next.errors import DomainError

from . import rules

READ_ERRORS = {
    "SOURCE_UNAVAILABLE",
    "SOURCE_STALE",
    "VERSION_CONFLICT",
    "FORBIDDEN_SCOPE",
    "INTEGRITY_MISMATCH",
    "RECHECK_REQUIRED",
    "INTEGRATION_REQUIRED",
    "NAMED_DECISION_REQUIRED",
}
OPEN_TASK_STATES = {"assigned", "accepted", "in_progress", "submitted"}
CLOSED_G0_STATES = {"done", "closed", "cancelled"}


def _section(read):
    """Run one section reader; a read failure becomes an explicit unavailable section."""
    try:
        return read()
    except DomainError as error:
        if error.code not in READ_ERRORS and error.reason not in READ_ERRORS:
            raise
        return {"available": False, "reason": error.message}


class _People:
    def __init__(self, s, ctx):
        self.s, self.ctx, self.cache = s, ctx, {}

    def __call__(self, identity):
        if identity is None:
            return None
        key = UUID(str(identity))
        if key not in self.cache:
            row = self.s.scalar(
                select(Principal).where(
                    Principal.tenant_id == self.ctx.tenant_id, Principal.id == key
                )
            )
            self.cache[key] = row.name if row else None
        return {"id": str(key), "name": self.cache[key]}


def _action(kind, kind_of, title, reason, responsible, *, due_at=None, view, panel=None, source):
    return {
        "kind": kind,
        "kind_label": rules.ACTION_KINDS[kind],
        "type": kind_of,
        "title": title,
        "reason": reason,
        "responsible": responsible,
        "due_at": due_at,
        "target": {"view": view, "panel": panel},
        "source": source,
    }


def _governance(s, ctx, product_id, project_id):
    from pdos_next.domain.projects.governance.service import view

    return view(s, ctx, product_id, project_id)


def _stage(gov):
    stages = [
        {"key": stage["key"], "name": stage["name"], "status": stage["status"]}
        for stage in gov["stages"]
    ]
    return {
        "available": bool(stages),
        "template": gov["template"],
        "stages": stages,
        "current": {"key": gov["current_stage"]["key"], "name": gov["current_stage"]["name"]}
        if gov["current_stage"]
        else None,
        "completed": gov["completed"],
        "reason": None if stages else "尚未采用阶段模板",
    }


def _health(gov, at):
    health = dict(gov["health"])
    checks = gov["gate"]["checks"]
    basis = [
        {"key": check["key"], "label": check["label"], "state": check["state"]}
        for check in checks
        if check["state"] != "READY"
    ]
    overdue = [
        c["id"]
        for c in gov["commitments"]
        if not c["fulfilled"] and rules.overdue(at, c["promised_at"])
    ]
    health["basis"] = {
        "gate_state": gov["gate"]["state"],
        "conditions": basis,
        "overdue_commitments": overdue,
        "review_pending": bool(gov["gate"].get("review_current")),
        "stage_adopted": bool(gov["stages"]),
    }
    return health


def _next_node(gov, people):
    timeline = gov["timeline"] if gov["stages"] else None
    commitments = []
    for c in (timeline or {}).get("commitments", []):
        commitments.append(
            {
                "id": c["id"],
                "promised_at": c["promised_at"],
                "fulfilled": c["fulfilled"],
                "promisor": people(c["promisor_id"]),
                "recipient": people(c["recipient_id"]),
            }
        )
    current = gov["current_stage"]
    return {
        "name": f"{current['name']}出口" if current else None,
        "times": {
            "task_key": (timeline or {}).get("task_key"),
            "baseline": ((timeline or {}).get("baseline") or {}).get("latest_finish"),
            "forecast": {
                "earliest": ((timeline or {}).get("forecast") or {}).get("earliest_finish"),
                "latest": ((timeline or {}).get("forecast") or {}).get("latest_finish"),
            }
            if (timeline or {}).get("forecast")
            else None,
            "commitments": commitments,
            "actual": (timeline or {}).get("actual"),
        },
        "slip": rules.slip(timeline),
        "exit_conditions": rules.exit_conditions(gov["gate"]["checks"]),
        "exit_outcomes": {
            "available": False,
            "label": rules.STAGE_NODES_MISSING,
            "reason": rules.STAGE_NODES_REASON,
        },
    }


def _quality(s, ctx, product_id, project_id, people):
    from pdos_next.domain.quality.execution.models import QualityIssueCurrent, QualityIssueVersion

    rows = s.execute(
        select(QualityIssueVersion)
        .join(
            QualityIssueCurrent,
            (QualityIssueCurrent.tenant_id == QualityIssueVersion.tenant_id)
            & (QualityIssueCurrent.product_id == QualityIssueVersion.product_id)
            & (QualityIssueCurrent.issue_version_id == QualityIssueVersion.id),
        )
        .where(
            QualityIssueVersion.tenant_id == ctx.tenant_id,
            QualityIssueVersion.product_id == product_id,
            QualityIssueVersion.project_id == project_id,
            # Private issues stay with their owner, as in the quality reader itself.
            or_(
                QualityIssueVersion.visibility != "private",
                QualityIssueVersion.owner_id == ctx.requester_id,
            ),
        )
    ).scalars()
    issues = []
    for row in rows:
        snapshot = row.issue_snapshot or {}
        if snapshot.get("merged_into") or snapshot.get("status") == "closed":
            continue
        issues.append(
            {
                "id": str(row.issue_id),
                "revision": row.revision,
                "title": snapshot.get("title") or "未命名问题",
                "status": row.status,
                "risk": snapshot.get("risk"),
                "risk_label": rules.ISSUE_RISK_NAMES.get(snapshot.get("risk"), "未分级"),
                "owner": people(row.owner_id),
                "recorded_at": row.created_at.isoformat(),
            }
        )
    return sorted(issues, key=rules.issue_key)


def _next_build(s, ctx, product_id, project_id):
    from pdos_next.domain.builds.service import list_builds
    from pdos_next.domain.builds.start.models import BuildStart

    listing = list_builds(s, ctx, product_id, project_id=project_id)
    started = set(
        s.scalars(
            select(BuildStart.build_id).where(
                BuildStart.tenant_id == ctx.tenant_id,
                BuildStart.product_id == product_id,
                BuildStart.project_id == project_id,
            )
        )
    )
    waiting = [item for item in listing["items"] if UUID(item["id"]) not in started]
    # The next Build is the earliest planned start among Builds not yet started;
    # undated ones follow, newest first (list order), so an unknown date is never guessed.
    waiting.sort(key=lambda item: (item["planned_start"] is None, item["planned_start"] or ""))
    build = waiting[0] if waiting else None
    return {
        "available": True,
        "build": {
            key: build[key]
            for key in (
                "id",
                "revision",
                "name",
                "type",
                "purpose",
                "planned_quantity",
                "unit",
                "planned_start",
                "planned_end",
                "verification_objectives",
                "source_status",
            )
        }
        | {
            "engineering_configuration": {
                "name": build["engineering_configuration"]["name"],
                "revision": build["engineering_configuration"]["revision"],
            },
            "manufacturing_configuration": {
                "name": build["manufacturing_configuration"]["name"],
                "revision": build["manufacturing_configuration"]["revision"],
            },
        }
        if build
        else None,
        "not_started": len(waiting),
        "unavailable_count": listing["unavailable_count"],
    }


def _duty(s, ctx, product_id, project_id, at):
    from pdos_next.core.models import Receipt
    from pdos_next.domain.projects.activity import activity_records
    from pdos_next.domain.projects.activity_catalog import OPERATION_LABELS, SOURCES

    since = at - timedelta(days=rules.DUTY_DAYS)
    agent_receipts = (
        Receipt.agent_run_id.is_not(None),
        Receipt.product_id == product_id,
        Receipt.created_at >= since,
        Receipt.created_at <= at,
    )
    # Which operations 小Pai actually wrote here recently (a small indexed read); the
    # activity sources for those operations then decide project and reader binding.
    written = set(
        s.scalars(
            select(Receipt.operation)
            .where(
                Receipt.tenant_id == ctx.tenant_id,
                Receipt.category_id == ctx.category_id,
                *agent_receipts,
            )
            .distinct()
        )
    )
    known = {operation for source in SOURCES for operation in source.operations}
    result = {
        "available": True,
        "window_days": rules.DUTY_DAYS,
        "since": since.isoformat(),
        "items": [],
        "total": 0,
        # Run revert (core/run_revert) does not cover these writes yet; cancelling
        # 小Pai's own unaccepted tasks arrives with W6 ③ (P48).
        "revocable": False,
        "revocation_note": "当前这些写入不能按运行撤回；取消小Pai 自建未承接的任务随 W6 ③（P48）。",
        "counts_as_todo": False,
    }
    if not written & known:
        return result
    records = activity_records(
        ctx,
        product_id,
        project_id,
        receipt_filter=agent_receipts,
        operations=written & known,
        include_runs=False,
    )
    rows = s.execute(
        select(
            records.c.operation,
            func.count().label("count"),
            func.count(func.distinct(records.c.run_id)).label("runs"),
        )
        .where(
            records.c.record_kind == "domain_receipt",
            records.c.actor_kind == "agent",
            records.c.recorded_at >= since,
            records.c.recorded_at <= at,
        )
        .group_by(records.c.operation)
        .order_by(records.c.operation)
    ).all()
    result["items"] = [
        {
            "operation": row.operation,
            "label": OPERATION_LABELS.get(row.operation, row.operation),
            "count": row.count,
            "runs": row.runs,
        }
        for row in rows
    ]
    result["total"] = sum(row.count for row in rows)
    return result


def overview(s, ctx, product_id, project_id):
    from pdos_next.domain.projects.external_wait.views import workspace as wait_workspace
    from pdos_next.domain.projects.governance.service import promise_facts
    from pdos_next.domain.projects.team.service import view as team_view
    from pdos_next.domain.projects.work import owner as work_owner
    from pdos_next.domain.projects.work.views import workspace as work_workspace

    human(s, ctx)
    product = require_access(s, ctx, product_id)
    project = work_owner.project(s, ctx, product_id, project_id)
    at = s.scalar(select(func.transaction_timestamp()))
    people = _People(s, ctx)
    owner = people(project.owner_id)

    gov = _section(lambda: _governance(s, ctx, product_id, project_id))
    if gov.get("available") is False:
        stage = {"available": False, "reason": gov["reason"], "stages": []}
        health = {"available": False, "reason": gov["reason"]}
        next_node = {"available": False, "reason": gov["reason"]}
        review_pending = False
        gate_checks = []
    else:
        stage = _stage(gov)
        health = _health(gov, at)
        next_node = _next_node(gov, people)
        review_pending = bool(gov["gate"].get("review_current"))
        gate_checks = gov["gate"]["checks"]

    work = _section(lambda: work_workspace(s, ctx, product_id, project_id))
    # The governance view already carries the same promise facts; read them once.
    promises = (
        gov["commitments"]
        if gov.get("available") is not False
        else _section(lambda: promise_facts(s, ctx, product_id, project_id))
    )
    waits = _section(lambda: wait_workspace(s, ctx, product_id, project_id))
    team = _section(lambda: team_view(s, ctx, product_id, project_id))

    tasks = work.get("tasks", []) if work.get("available") is not False else []
    task_by_id = {task["task_id"]: task for task in tasks}
    wait_rows = waits.get("waits", []) if waits.get("available") is not False else []
    promise_rows = promises if isinstance(promises, list) else []

    # 需要办理 (B11): blocked, to receive, to decide — each with its named owner.
    actions = []
    for check in gate_checks:
        if check["state"] == "BLOCKED":
            actions.append(
                _action(
                    "blocked",
                    "gate_condition",
                    f"出口条件阻塞：{check['label']}",
                    check.get("detail") or "当前出口条件为硬阻塞",
                    owner,
                    view="gates",
                    source={"type": "gate_check", "id": check["key"], "revision": None},
                )
            )
    for wait in wait_rows:
        if wait["state"] != "open":
            continue
        if wait["blocking"]:
            actions.append(
                _action(
                    "blocked",
                    "external_wait",
                    f"阻塞型外部等待：{wait['title']}",
                    f"等待对象：{wait['target']}",
                    people(wait["responsible_id"]),
                    due_at=wait.get("next_check_at"),
                    view="plan",
                    panel="commitments",
                    source={
                        "type": "external_wait",
                        "id": wait["id"],
                        "revision": wait["revision"],
                    },
                )
            )
        if wait.get("transfer"):
            actions.append(
                _action(
                    "receive",
                    "external_wait_transfer",
                    f"外部等待转交待接受：{wait['title']}",
                    "接受后责任才转给接收人，原负责人此前不卸责。",
                    people(wait["transfer"]["to_id"]),
                    view="plan",
                    panel="commitments",
                    source={
                        "type": "external_wait",
                        "id": wait["id"],
                        "revision": wait["revision"],
                    },
                )
            )
    if review_pending:
        stage_name = stage["current"]["name"] if stage.get("current") else "当前阶段"
        actions.append(
            _action(
                "decide",
                "stage_review",
                f"阶段评审待具名决定：{stage_name}",
                "评审已提交且出口依据未变；阶段决定只由项目负责人具名办理。",
                owner,
                view="gates",
                source={"type": "stage_review", "id": None, "revision": None},
            )
        )
    for task in tasks:
        source = {"type": "task", "id": task["task_id"], "revision": task["revision"]}
        if task["state"] == "assigned":
            actions.append(
                _action(
                    "receive",
                    "task_assigned",
                    task["title"],
                    "任务已分派，等待承接人承接。",
                    people(task["assignee_id"]),
                    view="tasks",
                    source=source,
                )
            )
        elif task["state"] == "submitted":
            actions.append(
                _action(
                    "decide",
                    "task_review",
                    task["title"],
                    "成果已提交，等待接收人验收。",
                    people(task["recipient_id"]),
                    view="tasks",
                    source=source,
                )
            )
        elif task["state"] == "proposed":
            actions.append(
                _action(
                    "decide",
                    "task_unassigned",
                    task["title"],
                    "任务尚未分派。",
                    people(task["owner_id"]),
                    view="tasks",
                    source=source,
                )
            )
    for promise in promise_rows:
        task = task_by_id.get(promise["task_id"])
        if (
            promise["fulfilled"]
            or not task
            or not task.get("submission")
            or task.get("assignee_id") != promise["promisor_id"]
        ):
            continue
        actions.append(
            _action(
                "decide",
                "promise_review",
                f"承诺待核对履行：{task['title']}",
                "承诺人已有实际提交，接收人尚未核对履行。",
                people(promise["recipient_id"]),
                due_at=promise["promised_at"],
                view="plan",
                panel="commitments",
                source={"type": "commitment", "id": promise["id"], "revision": None},
            )
        )

    # Key commitments: the gate milestone's first, then every open one by date.
    gate_ids = {c["id"] for c in (next_node.get("times") or {}).get("commitments", [])}
    open_promises = [p for p in promise_rows if not p["fulfilled"]]
    open_promises.sort(
        key=lambda p: (p["id"] not in gate_ids, p["promised_at"] is None, p["promised_at"] or "")
    )
    key_commitments = [
        {
            "id": p["id"],
            "title": task_by_id[p["task_id"]]["title"]
            if p["task_id"] in task_by_id
            else "任务暂不可读",
            "promisor": people(p["promisor_id"]),
            "recipient": people(p["recipient_id"]),
            "promised_at": p["promised_at"],
            "for_gate": p["id"] in gate_ids,
            "overdue": rules.overdue(at, p["promised_at"]),
        }
        for p in open_promises[:5]
    ]

    # Risks, problems, overdue waits and what falls due within seven days.
    g0_items = work.get("g0_open_items", []) if work.get("available") is not False else []
    risks = [
        {
            "id": item["id"],
            "title": item["title"],
            "responsible": people(item["owner_id"]),
            "due_date": item.get("due_date"),
            "state": (item.get("risk_followup") or {}).get("state", "open"),
        }
        for item in g0_items
        if item["kind"] == "risk"
        and (item.get("risk_followup") or {}).get("state", "open") != "closed"
    ]
    overdue_waits = [
        {
            "id": wait["id"],
            "title": wait["title"],
            "target": wait["target"],
            "responsible": people(wait["responsible_id"]),
            "escalation": wait["clock"]["escalation"],
            "reason": (wait["clock"].get("reasons") or [None])[-1],
            "blocking": wait["blocking"],
        }
        for wait in wait_rows
        if wait["state"] == "open" and rules.wait_overdue(wait.get("clock"))
    ]
    due = []
    for p in open_promises:
        if rules.due_soon(at, p["promised_at"]):
            due.append(
                {
                    "kind": "commitment",
                    "id": p["id"],
                    "title": task_by_id[p["task_id"]]["title"]
                    if p["task_id"] in task_by_id
                    else "任务暂不可读",
                    "responsible": people(p["promisor_id"]),
                    "due_at": p["promised_at"],
                }
            )
    for item in g0_items:
        if item["kind"] == "task" and item.get("status") not in CLOSED_G0_STATES:
            if rules.due_soon(at, item.get("due_date")):
                due.append(
                    {
                        "kind": "g0_task",
                        "id": item["id"],
                        "title": item["title"],
                        "responsible": people(item["owner_id"]),
                        "due_at": item["due_date"],
                    }
                )
    due.sort(key=lambda value: str(value["due_at"]))

    issues = _section(lambda: _quality(s, ctx, product_id, project_id, people))

    # Team, vacant roles and a simple load hint (open tasks here; hours are not summed).
    if team.get("available") is False:
        team_view_data = team
    else:
        names = {role["key"]: role["name"] for role in team["catalog"]["roles"]}
        load = {}
        for task in tasks:
            if task["state"] in OPEN_TASK_STATES and task.get("assignee_id"):
                load[task["assignee_id"]] = load.get(task["assignee_id"], 0) + 1
        team_view_data = {
            "available": True,
            "members": [
                {
                    "principal_id": member["principal_id"],
                    "name": member["name"],
                    "is_owner": member["is_owner"],
                    "roles": [role["name"] for role in member["roles"]],
                    "lead_roles": [role["name"] for role in member["roles"] if role.get("lead")],
                    "open_tasks": load.get(member["principal_id"], 0),
                }
                for member in team["members"]
            ],
            "vacant_roles": [names.get(key, key) for key in team["vacant_roles"]],
            "roles_without_lead": [names.get(key, key) for key in team["roles_without_lead"]],
            "load_note": "负载按本项目中承接人未完成的任务计数；工时未知，不合计。",
        }

    updates = work.get("updates", []) if work.get("available") is not False else []
    latest = updates[0] if updates else None

    return {
        "version": "project-overview/v1",
        "as_of": at.isoformat(),
        "rules": list(rules.RULES),
        "project": {
            "id": str(project.id),
            "revision": project.revision,
            "name": project.name,
            "status": project.status,
            "visibility": project.visibility,
            "owner": owner,
            "product": {"id": str(product.id), "name": product.name},
        },
        "stage": stage,
        "health": health,
        "next_node": next_node,
        "actions": {
            "available": all(
                section.get("available") is not False if isinstance(section, dict) else True
                for section in (work, waits)
            ),
            "items": rules.sort_actions(actions),
            "partial_reasons": [
                section["reason"]
                for section in (gov, work, waits, promises)
                if isinstance(section, dict) and section.get("available") is False
            ],
        },
        "next_build": _section(lambda: _next_build(s, ctx, product_id, project_id)),
        "key_commitments": key_commitments,
        "risks": {
            "risks": risks,
            "issues": issues,
            "overdue_waits": overdue_waits,
            "due_soon": due,
            "window_days": rules.DUE_SOON_DAYS,
        },
        "team": team_view_data,
        "status_update": {
            "latest": {
                "id": latest["id"],
                "revision": latest["revision"],
                "actor": people(latest["actor_id"]),
                "fact_summary": latest["fact_summary"],
                "next_steps": latest["next_steps"],
                "created_at": latest["created_at"],
                "receipt_id": latest["receipt_id"],
            }
            if latest
            else None,
            "cycle": {
                "available": False,
                "reason": "状态更新周期尚未接入（由自动化规则提供）；暂不判定“状态更新缺失”。",
            },
        },
        "agent_duty": _section(lambda: _duty(s, ctx, product_id, project_id, at)),
    }
