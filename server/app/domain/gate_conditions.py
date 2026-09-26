"""Original conditional decisions alongside their current, scoped execution tasks."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select

from app.db.schema import tables
from app.domain.gates import GateNotFoundError
from app.domain.product_workspace import _plain

FIELDS = {
    "title": ("title", "条件内容"),
    "owner_user_id": ("assignee_user_id", "负责人"),
    "due_date": ("due_date", "截止日期"),
    "closure_evidence": ("expected_output", "关闭依据要求"),
}


def history(
    c: Connection, tenant: UUID, project: UUID, gate: UUID, before: int | None
) -> dict[str, Any]:
    g, a, t, u, r = (
        tables.gates,
        tables.audit_log,
        tables.tasks,
        tables.users,
        tables.gate_signoff_rounds,
    )
    if (
        c.scalar(
            select(g.c.id).where(g.c.tenant_id == tenant, g.c.project_id == project, g.c.id == gate)
        )
        is None
    ):
        raise GateNotFoundError
    query = select(a.c.id, a.c.actor_user_id, a.c.timestamp, a.c.context).where(
        a.c.tenant_id == tenant,
        a.c.project_id == project,
        a.c.entity == "gate",
        a.c.entity_id == gate,
        a.c.action == "gate.conditional",
    )
    if before is not None:
        query = query.where(a.c.id < before)
    audit_rows = [
        _plain(row) for row in c.execute(query.order_by(a.c.id.desc()).limit(21)).mappings()
    ]
    ids = {UUID(v) for row in audit_rows[:20] for v in row["context"].get("condition_task_ids", [])}
    task_rows = c.execute(
        select(
            t.c.id,
            t.c.title,
            t.c.assignee_user_id,
            t.c.status,
            t.c.due_date,
            t.c.expected_output,
            t.c.completion_evidence_ref,
            t.c.completed_at,
            t.c.updated_at,
        ).where(
            t.c.tenant_id == tenant,
            t.c.project_id == project,
            t.c.id.in_(ids),
            t.c.kind == "gate_action",
            t.c.source_entity == "gate",
            t.c.source_entity_id == gate,
        )
    ).mappings()
    tasks = {str(row["id"]): _plain(row) for row in task_rows}
    people = {UUID(v) for task in tasks.values() for v in [task["assignee_user_id"]] if v}
    people.update(UUID(row["actor_user_id"]) for row in audit_rows[:20] if row["actor_user_id"])
    people.update(
        UUID(item["owner_user_id"])
        for row in audit_rows[:20]
        for item in row["context"].get("conditions", [])
    )
    names = {
        str(row.id): row.display_name
        for row in c.execute(
            select(u.c.id, u.c.display_name).where(u.c.tenant_id == tenant, u.c.id.in_(people))
        )
    }
    round_ids = {
        UUID(row["context"]["round_id"])
        for row in audit_rows[:20]
        if row["context"].get("round_id")
    }
    rounds = {
        str(row.id): row.round_number
        for row in c.execute(
            select(r.c.id, r.c.round_number).where(
                r.c.tenant_id == tenant,
                r.c.project_id == project,
                r.c.gate_id == gate,
                r.c.id.in_(round_ids),
            )
        )
    }
    items = []
    for audit in audit_rows[:20]:
        context = audit["context"]
        originals = {item["task_id"]: item for item in context.get("conditions", [])}
        conditions = []
        for identity in context.get("condition_task_ids", []):
            original, current = originals.get(identity), tasks.get(identity)
            conditions.append(
                {
                    "task_id": identity,
                    "original": {**original, "owner_name": names.get(original["owner_user_id"])}
                    if original
                    else None,
                    "current": {**current, "assignee_name": names.get(current["assignee_user_id"])}
                    if current
                    else None,
                    "changed_fields": [
                        label
                        for old, (new, label) in FIELDS.items()
                        if original and current and original[old] != current[new]
                    ],
                }
            )
        items.append(
            {
                "audit_id": audit["id"],
                "decided_at": audit["timestamp"],
                "decided_by_name": names.get(audit["actor_user_id"]),
                "decided_by_user_id": audit["actor_user_id"],
                "decision_id": context.get("decision_id"),
                "round_id": context.get("round_id"),
                "round_number": rounds.get(context.get("round_id")),
                "conditions": conditions,
            }
        )
    return {"items": items, "next_before": audit_rows[19]["id"] if len(audit_rows) > 20 else None}
