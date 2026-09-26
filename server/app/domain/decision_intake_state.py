"""Current and historical Decision/Issue source associations; original rows never change."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, case, func, or_, select, union

from app.db.schema import tables
from app.domain.product_workspace import _plain


def effective_sources(tenant: UUID, project: UUID | None = None) -> Any:
    r, h = tables.decision_intake_rows, tables.decision_intake_corrections
    latest = (
        select(h)
        .where(h.c.tenant_id == tenant)
        .distinct(h.c.source_row_id)
        .order_by(h.c.source_row_id, h.c.revision.desc())
        .subquery()
    )
    query = (
        select(
            r.c.id,
            r.c.project_id,
            case(
                (latest.c.id.is_not(None), latest.c.target_decision_id), else_=r.c.decision_id
            ).label("decision_id"),
            case(
                (latest.c.id.is_not(None), latest.c.target_issue_id), else_=r.c.related_issue_id
            ).label("issue_id"),
            func.coalesce(latest.c.revision, 0).label("revision"),
            latest.c.reason,
            latest.c.impact_note,
            latest.c.after_snapshot,
        )
        .select_from(r.outerjoin(latest, latest.c.source_row_id == r.c.id))
        .where(r.c.tenant_id == tenant)
    )
    if project is not None:
        query = query.where(r.c.project_id == project)
    return query.subquery()


def source_states(c: Connection, tenant: UUID, sources: list[Any]) -> dict[UUID, dict[str, Any]]:
    if not sources:
        return {}
    q = effective_sources(tenant)
    rows = c.execute(select(q).where(q.c.id.in_([source["id"] for source in sources]))).mappings()
    result = {}
    for row in rows:
        value = _plain(row)
        result[row["id"]] = {
            "source_row_id": value["id"],
            "revision": value["revision"],
            "state": "active" if row["decision_id"] else "withdrawn",
            "current_decision_id": value["decision_id"],
            "current_issue_id": value["issue_id"],
            "reason": value["reason"],
            "impact_note": value["impact_note"],
            "association_snapshot": value["after_snapshot"],
            "current_decision_href": (
                f"/projects?project={row['project_id']}&tab=decisions#decision-{row['decision_id']}"
            )
            if row["decision_id"]
            else None,
            "current_issue_href": (
                f"/projects?project={row['project_id']}&tab=work-items&entity_id={row['issue_id']}"
            )
            if row["issue_id"]
            else None,
        }
    return result


def historical_sources(
    tenant: UUID, project: UUID, *, decision: UUID | None = None, issue: UUID | None = None
) -> Any:
    """Source IDs that ever belonged to this target, including withdrawn associations."""
    r, h = tables.decision_intake_rows, tables.decision_intake_corrections
    first = select(r.c.id).where(
        r.c.tenant_id == tenant,
        r.c.project_id == project,
        r.c.decision_id == decision if decision else r.c.related_issue_id == issue,
    )
    later = select(h.c.source_row_id).where(
        h.c.tenant_id == tenant,
        h.c.project_id == project,
        or_(h.c.previous_decision_id == decision, h.c.target_decision_id == decision)
        if decision
        else or_(h.c.previous_issue_id == issue, h.c.target_issue_id == issue),
    )
    return union(first, later)


def reference_edges(tenant: UUID, project: UUID) -> Any:
    """Distinct actual Decision/Issue pairs; never cross-product unrelated historical targets."""
    r, h = tables.decision_intake_rows, tables.decision_intake_corrections
    first = select(
        r.c.id.label("source_id"), r.c.decision_id, r.c.related_issue_id.label("issue_id")
    ).where(r.c.tenant_id == tenant, r.c.project_id == project, r.c.related_issue_id.is_not(None))
    values = []
    for prefix in ("previous", "target"):
        d, i = h.c[f"{prefix}_decision_id"], h.c[f"{prefix}_issue_id"]
        values.append(
            select(h.c.source_row_id, d, i).where(
                h.c.tenant_id == tenant, h.c.project_id == project, d.is_not(None), i.is_not(None)
            )
        )
    return union(first, *values).subquery()
