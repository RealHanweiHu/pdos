"""Minimal approved cross-project scheduling projections, without partner content."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, exists, or_, select

from app.db.schema import tables


def application_heads(connection: Connection, tenant_id: UUID) -> list[Any]:
    apps = tables.cross_project_schedule_applications
    newer = apps.alias("newer_cross_application")
    return list(
        connection.execute(
            select(apps)
            .where(
                apps.c.tenant_id == tenant_id,
                ~exists(
                    select(newer.c.id).where(
                        newer.c.tenant_id == apps.c.tenant_id,
                        or_(
                            newer.c.replaces_application_id == apps.c.id,
                            newer.c.displaces_application_id == apps.c.id,
                        ),
                    )
                ),
            )
            .order_by(apps.c.id)
        ).mappings()
    )


def active_applications(connection: Connection, tenant_id: UUID) -> list[Any]:
    return [row for row in application_heads(connection, tenant_id) if row["operation"] != "remove"]


def incoming_sources(
    connection: Connection, tenant_id: UUID, project_id: UUID
) -> list[dict[str, Any]]:
    from app.domain.schedule_forecasts import capture_basis

    return list(capture_basis(connection, tenant_id, project_id)["basis"]["external_dependencies"])


def execution_constraints(
    sources: list[dict[str, Any]], node_id: UUID, calendar: Any, now: datetime
) -> list[dict[str, Any]]:
    from datetime import timedelta
    from decimal import ROUND_CEILING, Decimal

    from app.domain.working_time import ceil_minute, minute_quantity

    constraints = []
    for source in sources:
        if source["successor_node_id"] != str(node_id):
            continue
        lag = Decimal(source["lag"])
        anchor = datetime.fromisoformat(source["anchor"]) if source["anchor"] else None
        # Positive lag always waits for Actual. Lead may use a fresh future forecast.
        if source["anchor_kind"] == "forecast" and (lag >= 0 or anchor is None or anchor < now):
            anchor = None
        bound = None
        if anchor is not None:
            if source["lag_unit"] == "calendar_days":
                minutes = int((abs(lag) * 1440).to_integral_value(rounding=ROUND_CEILING))
                bound = ceil_minute(anchor) + timedelta(minutes=minutes if lag >= 0 else -minutes)
            else:
                bound = calendar.advance(anchor, minute_quantity(lag) * (1 if lag >= 0 else -1))
        satisfied = bound is not None and now >= bound
        constraints.append(
            {
                **source,
                "predecessor_task_id": None,
                "predecessor_node_key": None,
                "not_before": bound.isoformat() if bound else None,
                "satisfied": satisfied,
                "reason": None
                if satisfied
                else source["unknown_reason"]
                or (
                    f"跨项目{source['relation'].upper()}依赖：等待至{bound.isoformat()}"
                    if bound
                    else "跨项目依赖尚无可满足执行条件的前置实际时间或有效提前量预测"
                ),
            }
        )
    return constraints
