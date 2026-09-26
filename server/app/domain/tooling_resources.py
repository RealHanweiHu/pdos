"""Actual tooling identity links and scoped views of the existing reservation ledger."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.plan_scenarios import _calendar_access
from app.domain.product_workspace import ProductWorkError, _plain

KINDS = {
    "mold": {"mold"},
    "fixture": {"fixture"},
    "tooling": {"mold", "fixture", "equipment", "bench"},
}


def source(c: Connection, tenant: UUID, identity: UUID, tooling_kind: str) -> dict[str, Any]:
    table = tables.planning_resources
    row = (
        c.execute(select(table).where(table.c.tenant_id == tenant, table.c.id == identity))
        .mappings()
        .one_or_none()
    )
    if row is None or row["kind"] not in KINDS[tooling_kind]:
        raise ProductWorkError("请选择本租户内与实际工装类型相符的模具、治具或设备资源")
    return _plain(dict(row))


def choices(c: Connection, context: AuthContext) -> list[dict[str, Any]]:
    _calendar_access(context)
    table = tables.planning_resources
    return [
        _plain(dict(row))
        for row in c.execute(
            select(table.c.id, table.c.name, table.c.kind)
            .where(table.c.tenant_id == context.tenant.id, table.c.kind.in_(KINDS["tooling"]))
            .order_by(table.c.name, table.c.id)
        ).mappings()
    ]


def readout(c: Connection, context: AuthContext, project: UUID, row: Any) -> dict[str, Any]:
    _calendar_access(context)
    identity = row["payload"].get("planning_resource_id")
    if not identity:
        return {"state": "unlinked", "capacity": None, "reservations": [], "nodes": []}
    resource = source(c, context.tenant.id, UUID(identity), row["tooling_kind"])
    caps = tables.resource_capacity_versions
    capacity = (
        c.execute(
            select(caps)
            .where(caps.c.tenant_id == context.tenant.id, caps.c.resource_id == UUID(identity))
            .order_by(caps.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    nodes = tables.schedule_nodes
    related = list(
        c.execute(
            select(nodes)
            .where(
                nodes.c.tenant_id == context.tenant.id,
                nodes.c.project_id == project,
                (nodes.c.tooling_id == UUID(str(row["id"])))
                | nodes.c.id.in_([UUID(value) for value in row["payload"]["need_node_ids"]]),
            )
            .order_by(nodes.c.id)
        ).mappings()
    )
    booking = tables.resource_reservations
    bookings = list(
        c.execute(
            select(booking)
            .where(
                booking.c.tenant_id == context.tenant.id,
                booking.c.project_id == project,
                booking.c.resource_id == UUID(identity),
                booking.c.node_id.in_([node["id"] for node in related]),
            )
            .order_by(booking.c.updated_at.desc(), booking.c.id)
            .limit(21)
        ).mappings()
    )
    # Capacity is a published declaration. Real conflicts and legacy allocations are
    # checked by the established reservation service at independent confirmation.
    return _plain(
        {
            "state": "linked",
            "resource": resource,
            "capacity": dict(capacity) if capacity else None,
            "nodes": [
                {
                    "id": node["id"],
                    "kind": node["node_kind"],
                    "is_round": node["tooling_id"] == UUID(str(row["id"])),
                    "title": node["title"],
                }
                for node in related
            ],
            "reservations": [
                {
                    "id": value["id"],
                    "node_id": value["node_id"],
                    "state": value["state"],
                    "version": value["version"],
                    "capacity_version_id": value["capacity_version_id"],
                    "window_start": value["window_start"],
                    "window_end": value["window_end"],
                    "parallel_units": value["parallel_units"],
                    "occupancy_policy": value["occupancy_policy"],
                    "uses_latest_capacity": bool(
                        capacity and value["capacity_version_id"] == capacity["id"]
                    ),
                }
                for value in bookings[:20]
            ],
            "has_more_reservations": len(bookings) > 20,
        }
    )
