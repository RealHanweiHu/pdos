"""Current baseline projections and manually maintained Task prerequisites."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, or_, select, text
from sqlalchemy.sql import ColumnElement
from sqlalchemy.sql.selectable import ScalarSelect

from app.db.schema import tables


def current_baseline_id(tenant_id: UUID, project_id: UUID) -> ScalarSelect[Any]:
    return (
        select(tables.schedule_time_records.c.id)
        .where(
            tables.schedule_time_records.c.tenant_id == tenant_id,
            tables.schedule_time_records.c.project_id == project_id,
            tables.schedule_time_records.c.time_kind == "baseline",
        )
        .order_by(tables.schedule_time_records.c.version.desc())
        .limit(1)
        .scalar_subquery()
    )


def active_dependencies(tenant_id: UUID, project_id: UUID) -> ColumnElement[bool]:
    return or_(
        tables.task_dependencies.c.baseline_id.is_(None),
        tables.task_dependencies.c.baseline_id == current_baseline_id(tenant_id, project_id),
    )


def projected_dependencies(
    connection: Connection, *, tenant_id: UUID, project_id: UUID, task_id: UUID
) -> set[UUID]:
    return set(
        connection.execute(
            select(tables.task_dependencies.c.depends_on_task_id).where(
                tables.task_dependencies.c.tenant_id == tenant_id,
                tables.task_dependencies.c.project_id == project_id,
                tables.task_dependencies.c.task_id == task_id,
                tables.task_dependencies.c.baseline_id
                == current_baseline_id(tenant_id, project_id),
            )
        ).scalars()
    )


def dependency_graph_has_cycle(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    replacement_task_id: UUID | None = None,
    replacement_dependencies: tuple[UUID, ...] = (),
    formal_edges: tuple[tuple[UUID, UUID], ...] | None = None,
    formal_projects: dict[UUID, tuple[tuple[UUID, UUID], ...]] | None = None,
    cross_edge: tuple[UUID, UUID] | None = None,
    exclude_cross_application_id: UUID | None = None,
) -> bool:
    """Check all relation kinds, including paths through non-Task nodes.

    Formal edges are (successor, predecessor) node IDs, supplied only by the
    server when checking a proposed baseline. Otherwise use the current baseline.
    """
    # All graph writers acquire this after their project locks and before mutation.
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"schedule-graph:{tenant_id}"},
    )
    node_by_task = dict(
        connection.execute(
            select(tables.schedule_nodes.c.task_id, tables.schedule_nodes.c.id).where(
                tables.schedule_nodes.c.tenant_id == tenant_id,
                tables.schedule_nodes.c.task_id.is_not(None),
            )
        )
        .tuples()
        .all()
    )

    def task_vertex(task_id: UUID) -> tuple[str, UUID]:
        node_id = node_by_task.get(task_id)
        return ("node", node_id) if node_id else ("task", task_id)

    edges: dict[tuple[str, UUID], set[tuple[str, UUID]]] = {}
    manual = connection.execute(
        select(
            tables.task_dependencies.c.task_id, tables.task_dependencies.c.depends_on_task_id
        ).where(
            tables.task_dependencies.c.tenant_id == tenant_id,
            tables.task_dependencies.c.baseline_id.is_(None),
        )
    ).all()
    for child, predecessor in manual:
        if child != replacement_task_id:
            edges.setdefault(task_vertex(child), set()).add(task_vertex(predecessor))
    if replacement_task_id is not None:
        edges.setdefault(task_vertex(replacement_task_id), set()).update(
            task_vertex(predecessor) for predecessor in replacement_dependencies
        )
    records = tables.schedule_time_records
    current_baselines = (
        select(records.c.project_id, records.c.id)
        .where(records.c.tenant_id == tenant_id, records.c.time_kind == "baseline")
        .distinct(records.c.project_id)
        .order_by(records.c.project_id, records.c.version.desc())
        .subquery()
    )
    dependencies = tables.schedule_plan_dependencies
    stored_edges = connection.execute(
        select(
            dependencies.c.project_id,
            dependencies.c.successor_node_id,
            dependencies.c.predecessor_node_id,
        )
        .join(
            current_baselines,
            (current_baselines.c.project_id == dependencies.c.project_id)
            & (current_baselines.c.id == dependencies.c.baseline_id),
        )
        .where(dependencies.c.tenant_id == tenant_id)
    ).all()
    overrides = dict(formal_projects or {})
    if formal_edges is not None:
        overrides[project_id] = formal_edges
    for pid, child, predecessor in stored_edges:
        if pid not in overrides:
            edges.setdefault(("node", child), set()).add(("node", predecessor))
    for values in overrides.values():
        for child, predecessor in values:
            edges.setdefault(("node", child), set()).add(("node", predecessor))
    from app.domain.cross_project_schedule_runtime import active_applications

    for application in active_applications(connection, tenant_id):
        if application["id"] == exclude_cross_application_id:
            continue
        edges.setdefault(("node", application["successor_node_id"]), set()).add(
            ("node", application["predecessor_node_id"])
        )
    if cross_edge:
        child, predecessor = cross_edge
        edges.setdefault(("node", child), set()).add(("node", predecessor))
    # Iterative traversal avoids recursion limits for large project graphs.
    visited: set[tuple[str, UUID]] = set()
    visiting: set[tuple[str, UUID]] = set()
    for vertex in edges:
        stack = [(vertex, False)]
        while stack:
            current, leaving = stack.pop()
            if leaving:
                visiting.remove(current)
                visited.add(current)
            elif current in visiting:
                return True
            elif current not in visited:
                visiting.add(current)
                stack.append((current, True))
                stack.extend((parent, False) for parent in edges.get(current, ()))
    return False
