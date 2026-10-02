"""Read current reservation truth into Forecast; never rewrite approved plan dates."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select

from app.db.schema import tables
from app.domain.product_workspace import _plain
from app.domain.resource_priorities import PREFIX


def reservation_conditions(
    reservations: list[dict[str, Any]],
    resources: dict[str, dict[str, Any]],
    capacities: dict[str, dict[str, Any]],
    policies: dict[str, dict[str, Any]],
    *,
    node_id: str,
) -> list[dict[str, Any]]:
    own = [row for row in reservations if row["node_id"] == node_id]
    active = [row for row in own if row["state"] == "reserved"]
    result = []
    for row in active:
        resource = resources.get(row["resource_id"])
        capacity = capacities.get(row["resource_id"])
        policy = policies.get(row["resource_id"])
        blockers = []
        if resource is None or not resource.get("person_active", True):
            blockers.append("资源或资源人员已失效")
        if capacity is None or capacity["id"] != row["capacity_version_id"]:
            blockers.append("预约容量版本已变化")
        if policy is None or row["contract"]["priority_policy_version"] != PREFIX + policy["id"]:
            blockers.append("预约优先级政策已变化")
        elif not policy.get("current", True):
            blockers.append("预约优先级已暂停或过期")
        result.append(
            {
                "reservation_id": row["id"],
                "resource_id": row["resource_id"],
                "resource_name": resource["name"] if resource else "共享资源",
                "capacity_version_id": row["capacity_version_id"],
                "reservation_version": row["version"],
                "window_start": row["window_start"],
                "window_end": row["window_end"],
                "policy_status": policy["status"] if policy else None,
                "policy_valid_from": policy["valid_from"] if policy else None,
                "policy_valid_until": policy["valid_until"] if policy else None,
                "blockers": blockers,
            }
        )
    if not active and any(row["state"] in ("released", "cancelled") for row in own):
        result.append({"blockers": ["原正式预约已释放或取消，当前剩余资源窗口未知"]})
    return result


def capture_resources(
    connection: Connection, tenant_id: UUID, project_id: UUID, node_ids: list[UUID]
) -> dict[str, Any]:
    now = datetime.now(UTC)
    reservations = [
        {**_plain(row), "window_open": row["window_end"] > now}
        for row in connection.execute(
            select(tables.resource_reservations)
            .where(
                tables.resource_reservations.c.tenant_id == tenant_id,
                tables.resource_reservations.c.project_id == project_id,
                tables.resource_reservations.c.node_id.in_(node_ids),
            )
            .order_by(tables.resource_reservations.c.id)
        ).mappings()
    ]
    ids = {UUID(row["resource_id"]) for row in reservations}
    resources = {
        str(row["id"]): _plain(row)
        for row in connection.execute(
            select(tables.planning_resources)
            .where(
                tables.planning_resources.c.tenant_id == tenant_id,
                tables.planning_resources.c.id.in_(ids),
            )
            .order_by(tables.planning_resources.c.id)
        ).mappings()
    }
    people = set(
        connection.execute(
            select(tables.users.c.id).where(
                tables.users.c.tenant_id == tenant_id,
                tables.users.c.is_active.is_(True),
                tables.users.c.id.in_(
                    [UUID(row["user_id"]) for row in resources.values() if row["user_id"]]
                ),
            )
        ).scalars()
    )
    for resource in resources.values():
        resource["person_active"] = not resource["user_id"] or UUID(resource["user_id"]) in people
    current = []
    for table in (tables.resource_capacity_versions, tables.resource_priority_versions):
        latest: dict[str, dict[str, Any]] = {}
        for row in connection.execute(
            select(table)
            .where(
                table.c.tenant_id == tenant_id,
                table.c.resource_id.in_(ids),
            )
            .order_by(table.c.resource_id, table.c.version.desc())
        ).mappings():
            # Forecast readers need current version/validity, not tenant-wide
            # priority rankings, other project evidence or administrative reasons.
            fields = ("id", "resource_id", "version") + (
                ("status", "valid_from", "valid_until")
                if table is tables.resource_priority_versions
                else ()
            )
            latest.setdefault(str(row["resource_id"]), _plain({key: row[key] for key in fields}))
        current.append(latest)
    for policy in current[1].values():
        policy["current"] = policy["status"] == "active" and (
            datetime.fromisoformat(policy["valid_from"])
            <= now
            < datetime.fromisoformat(policy["valid_until"])
        )
    # Join through project membership in the adjustment, and expose only this
    # project's reservation receipts; other project details never enter the basis.
    applications, parts = (
        tables.resource_reallocation_applications,
        tables.resource_reallocation_projects,
    )
    applied = []
    for row in connection.execute(
        select(applications)
        .join(
            parts,
            (parts.c.tenant_id == applications.c.tenant_id)
            & (parts.c.allocation_id == applications.c.allocation_id),
        )
        .where(
            applications.c.tenant_id == tenant_id,
            parts.c.project_id == project_id,
        )
        .order_by(applications.c.created_at, applications.c.id)
    ).mappings():
        applied.append(
            {
                "application_id": str(row["id"]),
                "allocation_id": str(row["allocation_id"]),
                "payload_digest": row["payload_digest"],
                "created_at": row["created_at"].isoformat(),
                "items": [
                    item
                    for item in row["receipt"]["items"]
                    if item["project_id"] == str(project_id)
                ],
            }
        )
    return {
        "reservations": reservations,
        "resources": resources,
        "capacities": current[0],
        "policies": current[1],
        "applications": applied,
    }


def refresh_after_reallocation(
    connection: Connection,
    tenant_id: UUID,
    project_ids: list[UUID],
    actor_user_id: UUID,
) -> None:
    from app.domain.formal_schedule import current_plan
    from app.domain.schedule_forecasts import automatic_forecast

    for project_id in project_ids:
        if current_plan(connection, tenant_id, project_id) is not None:
            automatic_forecast(
                connection,
                tenant_id,
                project_id,
                actor_user_id,
                "具名资源调整应用后的预约与预测反馈，容量需按新预测重核",
                datetime.now(UTC),
            )
