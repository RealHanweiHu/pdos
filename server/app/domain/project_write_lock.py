"""Shared project-row lock ordering for deterministic Gate readiness writes."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Connection, select

from app.db.schema import tables


def lock_project_write_scope(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
) -> bool:
    """Serialize readiness-changing writes with Gate decisions for one Project."""
    return (
        connection.execute(
            select(tables.projects.c.id)
            .where(
                tables.projects.c.tenant_id == tenant_id,
                tables.projects.c.id == project_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        is not None
    )
