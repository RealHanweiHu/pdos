"""Resolve certificate retirement only through applied baseline replacements."""

from uuid import UUID

from sqlalchemy import Connection, select

from app.db.schema import tables


def retired_certification_ids(
    connection: Connection, tenant_id: UUID, project_id: UUID
) -> set[UUID]:
    from app.domain.formal_schedule import current_plan

    formal = current_plan(connection, tenant_id, project_id)
    if formal is None:
        return set()
    active = {node["id"] for node in formal["nodes"] if node["node_kind"] == "certification"}
    applications, requests = tables.baseline_change_applications, tables.baseline_change_requests
    snapshots = connection.execute(
        select(requests.c.snapshot)
        .join(
            applications,
            (applications.c.tenant_id == requests.c.tenant_id)
            & (applications.c.project_id == requests.c.project_id)
            & (applications.c.change_id == requests.c.id),
        )
        .join(
            tables.schedule_time_records,
            (tables.schedule_time_records.c.tenant_id == applications.c.tenant_id)
            & (tables.schedule_time_records.c.project_id == applications.c.project_id)
            & (tables.schedule_time_records.c.id == applications.c.baseline_id),
        )
        .where(
            applications.c.tenant_id == tenant_id,
            applications.c.project_id == project_id,
        )
        .order_by(tables.schedule_time_records.c.version)
    ).scalars()
    replacements = {}
    for snapshot in snapshots:
        for replacement in snapshot["result"]["changes"].get("certification_replacements", ()):
            replacements[UUID(replacement["previous_node_id"])] = UUID(
                replacement["replacement_node_id"]
            )
    retired = set()
    for old in replacements:
        if old in active:
            continue
        seen, current = set(), old
        while current in replacements and current not in seen and current not in active:
            seen.add(current)
            current = replacements[current]
        if current in active:
            retired.add(old)
    if not retired:
        return set()
    return set(
        connection.execute(
            select(tables.schedule_nodes.c.certification_id).where(
                tables.schedule_nodes.c.tenant_id == tenant_id,
                tables.schedule_nodes.c.project_id == project_id,
                tables.schedule_nodes.c.node_kind == "certification",
                tables.schedule_nodes.c.id.in_(retired),
            )
        ).scalars()
    )
