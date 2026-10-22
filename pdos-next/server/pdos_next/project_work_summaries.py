"""Bounded latest named updates for already-readable project heads."""

from sqlalchemy import and_, func, select, tuple_

from pdos_next.domain.work_management.models import ProjectStatusUpdate
from pdos_next.models import Principal


def latest(session, ctx, projects):
    if not projects:
        return {}
    fact = ProjectStatusUpdate
    scopes = [(row.category_id, row.product_id, row.id) for row in projects]
    ranked = (
        select(
            fact.id,
            fact.project_id,
            fact.revision,
            fact.actor_id,
            fact.fact_summary,
            fact.next_steps,
            fact.task_refs,
            fact.created_at,
            fact.receipt_id,
            func.row_number()
            .over(partition_by=fact.project_id, order_by=(fact.created_at.desc(), fact.id.desc()))
            .label("position"),
        )
        .where(
            fact.tenant_id == ctx.tenant_id,
            tuple_(fact.category_id, fact.product_id, fact.project_id).in_(scopes),
        )
        .subquery()
    )
    rows = session.execute(
        select(ranked, Principal.name.label("actor_name"))
        .outerjoin(
            Principal,
            and_(Principal.tenant_id == ctx.tenant_id, Principal.id == ranked.c.actor_id),
        )
        .where(ranked.c.position == 1)
    ).mappings()
    return {
        row["project_id"]: {
            "id": str(row["id"]),
            "revision": row["revision"],
            "actor": {"id": str(row["actor_id"]), "name": row["actor_name"]},
            "fact_summary": row["fact_summary"],
            "next_steps": row["next_steps"],
            "task_refs": row["task_refs"],
            "created_at": row["created_at"].isoformat(),
            "receipt_id": str(row["receipt_id"]),
        }
        for row in rows
    }
