"""Capacity checks for immutable remaining-work forecasts without changing reservations."""

from datetime import datetime
from decimal import Decimal, localcontext
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, case, literal_column, select

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError, _plain, digest
from app.domain.resource_capacity import CapacityCheckDraft, evaluate_capacity
from app.domain.resource_reservations import _project
from app.domain.schedule_forecasts import capture_basis
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


def _forecast(
    connection: Connection, context: AuthContext, project_id: UUID, record_id: UUID
) -> Any:
    runs = tables.schedule_forecast_runs
    row = (
        connection.execute(
            select(runs).where(
                runs.c.tenant_id == context.tenant.id,
                runs.c.project_id == project_id,
                runs.c.record_id == record_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkAccessError("预测版本不存在或不属于当前项目")
    return row


def reservation_differences(
    connection: Connection,
    tenant_id: UUID,
    project_id: UUID,
    result: dict[str, Any],
    as_of: datetime,
    unknown_nodes: set[str],
    *,
    node_keys: dict[UUID, str] | None = None,
) -> list[dict[str, Any]]:
    booking = tables.resource_reservations
    intervals = tables.resource_reservation_intervals
    resource = tables.planning_resources
    if node_keys is None:
        from app.domain.formal_schedule import current_plan

        formal = current_plan(connection, tenant_id, project_id)
        node_keys = {node["id"]: node["node_key"] for node in formal["nodes"]} if formal else {}
    node_key = (
        case(node_keys, value=booking.c.node_id, else_=None)
        if node_keys
        else literal_column("NULL")
    ).label("node_key")
    reserved = list(
        connection.execute(
            select(
                booking.c.id,
                booking.c.resource_id,
                booking.c.parallel_units,
                node_key,
                intervals.c.start,
                intervals.c.end,
                resource.c.name,
            )
            .join(
                intervals,
                (intervals.c.tenant_id == booking.c.tenant_id)
                & (intervals.c.reservation_id == booking.c.id),
            )
            .join(
                resource,
                (resource.c.tenant_id == booking.c.tenant_id)
                & (resource.c.id == booking.c.resource_id),
            )
            .where(
                booking.c.tenant_id == tenant_id,
                booking.c.project_id == project_id,
                booking.c.state == "reserved",
                booking.c.node_id.in_(node_keys),
            )
        ).mappings()
    )
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    names = {profile["resource_id"]: profile["resource_name"] for profile in result["profiles"]}

    def include(
        resource_id: str,
        node_key: str,
        start: datetime,
        end: datetime,
        units: Decimal,
        kind: str,
        receipt_id: str | None = None,
    ) -> None:
        start = max(start, as_of)
        if end <= start:
            return
        group = groups.setdefault((resource_id, node_key), {"points": {}, "ids": set()})
        group["points"].setdefault(start, []).append((kind, units))
        group["points"].setdefault(end, []).append((kind, -units))
        if receipt_id:
            group["ids"].add(receipt_id)

    for row in result["demand_intervals"]:
        include(
            row["resource_id"],
            row["node_key"],
            datetime.fromisoformat(row["start"]),
            datetime.fromisoformat(row["end"]),
            Decimal(row["units"]),
            "desired",
        )
    for row in reserved:
        names[str(row["resource_id"])] = row["name"]
        include(
            str(row["resource_id"]),
            row["node_key"],
            row["start"],
            row["end"],
            row["parallel_units"],
            "reserved",
            str(row["id"]),
        )
    differences = []
    with localcontext() as calculation:
        calculation.prec = 48
        for (resource_id, key), group in sorted(groups.items()):
            demand = Decimal(0)
            booked = Decimal(0)
            points = sorted(group["points"])
            for index, left in enumerate(points[:-1]):
                for kind, units in group["points"][left]:
                    if kind == "desired":
                        demand += units
                    else:
                        booked += units
                if demand == booked:
                    continue
                differences.append(
                    {
                        "resource_id": resource_id,
                        "resource_name": names.get(resource_id, "共享资源"),
                        "node_key": key,
                        "start": left.isoformat(),
                        "end": points[index + 1].isoformat(),
                        "forecast_units": None if key in unknown_nodes else str(demand),
                        "reserved_units": str(booked),
                        "difference_units": None if key in unknown_nodes else str(demand - booked),
                        "disposition": "requirement_unknown"
                        if key in unknown_nodes
                        else "additional_capacity_needed"
                        if demand > booked
                        else "excess_reserved",
                        "reservation_ids": sorted(group["ids"]),
                    }
                )
                if len(differences) > 10000:
                    raise ProductWorkError("预约差异过多，请缩小预测范围后处理")
    return differences


def evaluate_current_forecast_capacity(
    connection: Connection,
    context: AuthContext,
    project_id: UUID,
    forecast: Any,
    draft: CapacityCheckDraft,
) -> dict[str, Any]:
    record_id = forecast["record_id"]
    capture = capture_basis(connection, context.tenant.id, project_id)
    if forecast["basis_digest"] != capture["basis_digest"]:
        raise ProductWorkError("预测依据已变化，请先重算预测")
    latest = connection.execute(
        select(tables.schedule_time_records.c.id)
        .where(
            tables.schedule_time_records.c.tenant_id == context.tenant.id,
            tables.schedule_time_records.c.project_id == project_id,
            tables.schedule_time_records.c.time_kind == "forecast",
        )
        .order_by(tables.schedule_time_records.c.version.desc())
        .limit(1)
    ).scalar_one()
    if latest != record_id:
        raise ProductWorkError("已有新的预测版本，请检查最新一轮")
    nodes = [item for item in forecast["result"]["nodes"] if not item.get("actual_finish")]
    if any("remaining_work_minutes" not in item for item in nodes):
        raise ProductWorkError("此预测未固定剩余资源时段，请重新计算预测")
    projection = {
        **forecast["result"],
        "nodes": [
            {
                **item,
                "start": item["remaining_work_start"],
                "work_minutes": item["remaining_work_minutes"],
            }
            for item in nodes
        ],
    }
    result = evaluate_capacity(
        connection,
        context,
        {"id": record_id, "result": projection, "result_digest": digest(projection)},
        draft,
        covered_project_id=project_id,
    )
    result["forecast_record_id"] = result.pop("scenario_id")
    result["forecast_projection_digest"] = result.pop("scenario_digest")
    result["reservation_match_policy"] = "same_project_node_resource_union"
    uncertain_keys = {key for issue in result["unknown"] for key in issue["node_key"].split(", ")}
    result["reservation_differences"] = reservation_differences(
        connection,
        context.tenant.id,
        project_id,
        result,
        datetime.fromisoformat(forecast["result"]["as_of"]),
        {
            item["node_key"]
            for item in nodes
            if item["node_key"] in uncertain_keys
            or item.get("remaining_work_start") is None
            or item.get("remaining_work_minutes") is None
            or (
                not draft.demands.get(item["node_key"])
                and item["node_key"] not in draft.no_resource_reasons
            )
        },
    )
    return result


class ForecastCapacityService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def list(self, context: AuthContext, project_id: UUID, record_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as connection:
            _project(connection, context, project_id)
            forecast = _forecast(connection, context, project_id, record_id)
            table = tables.forecast_capacity_checks
            rows = list(
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.project_id == project_id,
                        table.c.forecast_record_id == record_id,
                    )
                    .order_by(table.c.created_at.desc(), table.c.id.desc())
                    .limit(51)
                ).mappings()
            )
            from app.domain.formal_schedule import current_plan

            formal = current_plan(connection, context.tenant.id, project_id)
            if formal is None:
                raise ProductWorkError("缺少当前正式计划")
            initial = formal["capacity_inputs"]
            remaining = {
                row["node_key"]
                for row in forecast["result"]["nodes"]
                if not row.get("actual_finish")
            }
            return {
                "items": [_plain(row) for row in rows[:50]],
                "has_more": len(rows) > 50,
                "initial_demands": {
                    key: value for key, value in initial["demands"].items() if key in remaining
                },
                "initial_no_resource_reasons": {
                    key: value
                    for key, value in initial.get("no_resource_reasons", {}).items()
                    if key in remaining
                },
            }

    def check(
        self, context: AuthContext, project_id: UUID, record_id: UUID, draft: CapacityCheckDraft
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            _project(connection, context, project_id, write=True)
            forecast = _forecast(connection, context, project_id, record_id)
            table = tables.forecast_capacity_checks
            fingerprint = digest(
                {
                    "project_id": str(project_id),
                    "forecast_record_id": str(record_id),
                    **draft.model_dump(mode="json"),
                }
            )
            prior = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.created_by_user_id == context.user.id,
                        table.c.request_id == draft.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != fingerprint:
                    raise ProductWorkError("请求编号已用于另一项预测容量检查")
                return _plain(prior)
            result = evaluate_current_forecast_capacity(
                connection, context, project_id, forecast, draft
            )
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        forecast_record_id=record_id,
                        inputs=draft.model_dump(mode="json"),
                        result=result,
                        result_digest=digest(result),
                        forecast_basis_digest=forecast["basis_digest"],
                        created_by_user_id=context.user.id,
                        request_id=draft.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            for capacity_id in sorted(
                {
                    value.capacity_version_id
                    for values in draft.demands.values()
                    for value in values
                },
                key=str,
            ):
                connection.execute(
                    tables.forecast_capacity_check_versions.insert().values(
                        tenant_id=context.tenant.id,
                        check_id=row["id"],
                        capacity_version_id=capacity_id,
                    )
                )
            EventAuditWriter(
                connection,
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"forecast-capacity:{row['id']}",
                    event_type="FORECAST_CAPACITY_CHECKED",
                    source="planning_service",
                    entity_id=row["id"],
                    payload={"record_id": str(row["id"])},
                ),
                AuditDraft(
                    action="forecast.capacity_check",
                    after_snapshot={
                        "id": str(row["id"]),
                        "forecast_record_id": str(record_id),
                        "status": result["status"],
                        "result_digest": row["result_digest"],
                    },
                ),
            )
            return _plain(row)
