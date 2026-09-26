"""Actual Task event anchors and execution guards for applied schedule dependencies."""

from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.contracts.common_objects import NodeTime, ScopeRef, SourceRef, TimeRecord, TimeWindow
from app.db.schema import tables
from app.domain.resource_reservations import _project
from app.domain.schedule_actual_corrections import effective_observations
from app.domain.working_time import CalendarDefinition, WorkingTime, ceil_minute, minute_quantity
from app.events.writer import WrittenEventAudit


class ScheduleExecutionBlocked(ValueError):
    def __init__(self, blockers: list[dict[str, Any]]):
        self.blockers = blockers
        super().__init__("；".join(item["reason"] for item in blockers[:8]))


def schedule_state(
    connection: Connection, tenant_id: UUID, project_id: UUID, now: datetime
) -> dict[str, Any]:
    from app.domain.formal_schedule import current_plan, current_states

    formal = current_plan(connection, tenant_id, project_id)
    if formal is None:
        return {"items": [], "actual_version": None, "as_of": now.isoformat()}
    states, titles = current_states(connection, tenant_id, project_id, formal)
    by_key = {state["node_key"]: state for state in states}
    rows = [
        {
            **node,
            "calendar_version_id": UUID(
                formal["allocations"][node["node_key"]]["calendar_version_id"]
            ),
            "status": by_key[node["node_key"]]["status"],
            "title": titles[node["node_key"]],
        }
        for node in formal["nodes"]
    ]
    by_node = {row["schedule_node_id"]: row for row in rows}
    points = {}
    for state in states:
        for point, field in (("start", "actual_start"), ("finish", "actual_finish")):
            if state[field]:
                points[(UUID(state["node_id"]), point)] = {
                    "observed_at": datetime.fromisoformat(state[field]),
                    "event_row_id": state.get(field + "_event"),
                    "observation_id": state.get("actual_observation", {}).get("id"),
                }
    calendars = {
        row["id"]: WorkingTime(CalendarDefinition.model_validate(row["definition"]))
        for row in connection.execute(
            select(tables.work_calendar_versions).where(
                tables.work_calendar_versions.c.tenant_id == tenant_id,
                tables.work_calendar_versions.c.id.in_(
                    {row["calendar_version_id"] for row in rows}
                ),
            )
        ).mappings()
    }
    edges = list(
        connection.execute(
            select(tables.schedule_plan_dependencies)
            .where(
                tables.schedule_plan_dependencies.c.tenant_id == tenant_id,
                tables.schedule_plan_dependencies.c.project_id == project_id,
                tables.schedule_plan_dependencies.c.baseline_id == formal["baseline_id"],
            )
            .order_by(tables.schedule_plan_dependencies.c.id)
        ).mappings()
    )
    incoming: dict[UUID, list[Any]] = {node: [] for node in by_node}
    for edge in edges:
        incoming[edge["successor_node_id"]].append(edge)
    from app.domain.schedule_forecasts import current_forecast_points

    forecast = (
        current_forecast_points(connection, tenant_id, project_id)
        if any(Decimal(edge["lag"]) < 0 for edge in edges)
        else None
    )
    from app.domain.cross_project_schedule_runtime import execution_constraints, incoming_sources

    external = incoming_sources(connection, tenant_id, project_id)
    from app.domain.id_handoff_runtime import acceptance_conditions, execution_conditions

    handoffs = acceptance_conditions(connection, tenant_id, project_id, formal)
    from app.domain.tooling_schedule import conditions as tooling_conditions
    from app.domain.tooling_schedule import execution_conditions as tooling_execution

    tooling = tooling_conditions(connection, tenant_id, project_id)

    items = []
    for node_id, row in by_node.items():
        constraints = []
        for edge in incoming[node_id]:
            predecessor = by_node[edge["predecessor_node_id"]]
            source_point = "start" if edge["relation"][0] == "s" else "finish"
            target_point = "start" if edge["relation"][1] == "s" else "finish"
            observation = points.get((edge["predecessor_node_id"], source_point))
            bound = None
            lag = Decimal(edge["lag"])
            anchor = observation["observed_at"] if observation else None
            forecast_ref = None
            if anchor is None and lag < 0 and forecast:
                predicted = forecast["nodes"].get(predecessor["node_key"], {}).get(source_point)
                if predicted and datetime.fromisoformat(predicted) >= now:
                    anchor = datetime.fromisoformat(predicted)
                    forecast_ref = {
                        "record_id": forecast["record_id"],
                        "version": forecast["version"],
                    }
            if anchor is not None:
                if edge["lag_unit"] == "calendar_days":
                    minutes = int((abs(lag) * 1440).to_integral_value(rounding=ROUND_CEILING))
                    bound = ceil_minute(anchor) + timedelta(
                        minutes=minutes if lag >= 0 else -minutes
                    )
                else:
                    bound = calendars[row["calendar_version_id"]].advance(
                        anchor, minute_quantity(lag) * (1 if lag >= 0 else -1)
                    )
            satisfied = bound is not None and now >= bound
            label = f"{predecessor['title']} {edge['relation'].upper()}"
            reason = (
                None
                if satisfied
                else (
                    f"{label}：实际前置时间未知，提前量需当前有效预测"
                    if lag < 0
                    else f"{label}：尚无实际{'开始' if source_point == 'start' else '完成'}记录"
                )
                if bound is None
                else f"{label}：等待至{bound.isoformat()}"
            )
            constraints.append(
                {
                    "predecessor_task_id": str(predecessor["task_id"])
                    if predecessor["task_id"]
                    else None,
                    "predecessor_node_id": str(predecessor["id"]),
                    "predecessor_node_key": predecessor["node_key"],
                    "relation": edge["relation"],
                    "lag": str(edge["lag"]),
                    "lag_unit": edge["lag_unit"],
                    "target_point": target_point,
                    "source_point": source_point,
                    "source_event_row_id": observation["event_row_id"] if observation else None,
                    "source_observation_id": observation.get("observation_id")
                    if observation
                    else None,
                    "forecast_ref": forecast_ref,
                    "not_before": bound.isoformat() if bound else None,
                    "satisfied": satisfied,
                    "reason": reason,
                }
            )
        constraints.extend(
            execution_constraints(external, node_id, calendars[row["calendar_version_id"]], now)
        )
        constraints.extend(execution_conditions(handoffs.get(node_id, []), now))
        constraints.extend(tooling_execution(tooling.get(node_id, []), now))
        start = points.get((node_id, "start"))
        finish = points.get((node_id, "finish"))
        items.append(
            {
                "task_id": str(row["task_id"]) if row["task_id"] else None,
                "node_id": str(node_id),
                "node_kind": row["node_kind"],
                "node_key": row["node_key"],
                "title": row["title"],
                "status": row["status"],
                "actual_start": start["observed_at"].isoformat() if start else None,
                "actual_finish": finish["observed_at"].isoformat() if finish else None,
                "constraints": constraints,
                "start_blockers": [
                    item
                    for item in constraints
                    if item["target_point"] == "start" and not item["satisfied"]
                ],
                "finish_blockers": [
                    item
                    for item in constraints
                    if item["target_point"] == "finish" and not item["satisfied"]
                ],
            }
        )
    version = connection.execute(
        select(func.max(tables.schedule_time_records.c.version)).where(
            tables.schedule_time_records.c.tenant_id == tenant_id,
            tables.schedule_time_records.c.project_id == project_id,
            tables.schedule_time_records.c.time_kind == "actual",
        )
    ).scalar_one()
    return {
        "items": sorted(items, key=lambda item: item["node_key"]),
        "actual_version": version,
        "as_of": now.isoformat(),
        "baseline_id": str(formal["baseline_id"]),
    }


def guard_task_transition(
    connection: Connection,
    tenant_id: UUID,
    project_id: UUID,
    task_id: UUID,
    to_status: str,
    now: datetime,
) -> None:
    if to_status not in ("in_progress", "done", "skipped"):
        return
    from app.domain.formal_schedule import current_plan

    formal = current_plan(connection, tenant_id, project_id)
    binding = (
        next((node for node in formal["nodes"] if node["task_id"] == task_id), None)
        if formal
        else None
    )
    if binding is None or to_status == "skipped":
        if to_status in ("done", "skipped"):
            from app.domain.id_handoff_runtime import acceptance_conditions, execution_conditions

            node_ids = set(
                connection.execute(
                    select(tables.schedule_nodes.c.id).where(
                        tables.schedule_nodes.c.tenant_id == tenant_id,
                        tables.schedule_nodes.c.project_id == project_id,
                        tables.schedule_nodes.c.task_id == task_id,
                    )
                ).scalars()
            )
            conditions = acceptance_conditions(connection, tenant_id, project_id, formal)
            if to_status == "skipped" and any(
                entry.get("kind") == "id_freeze_checkpoint"
                for node_id in node_ids
                for entry in conditions.get(node_id, [])
            ):
                raise ScheduleExecutionBlocked(
                    [{"reason": "ID冻结检查点须办理实际完成，不能以跳过代替批准冻结"}]
                )
            blockers = [
                entry
                for node_id in node_ids
                for entry in execution_conditions(conditions.get(node_id, []), now)
                if not entry["satisfied"]
            ]
            if blockers:
                raise ScheduleExecutionBlocked(blockers)
        return
    if (
        to_status == "in_progress"
        and connection.execute(
            select(tables.projects.c.status).where(
                tables.projects.c.tenant_id == tenant_id, tables.projects.c.id == project_id
            )
        ).scalar_one()
        != "active"
    ):
        raise ScheduleExecutionBlocked([{"reason": "请先激活已应用计划的项目，再开始正式任务"}])
    try:
        state = schedule_state(connection, tenant_id, project_id, now)
    except ValueError as error:
        raise ScheduleExecutionBlocked(
            [{"reason": f"排程日历暂不能计算执行条件：{error}"}]
        ) from error
    task = next(item for item in state["items"] if item["task_id"] == str(task_id))
    blockers = task["start_blockers" if to_status == "in_progress" else "finish_blockers"]
    if to_status == "done" and task["actual_start"] is None:
        blockers = [*blockers, {"reason": "缺少实际开工记录，请先办理开始任务"}]
    if blockers:
        raise ScheduleExecutionBlocked(blockers)


def guard_source_execution(
    connection: Connection,
    tenant_id: UUID,
    project_id: UUID,
    node_id: UUID,
    action: str,
    values: dict[str, Any],
    previous: Any | None,
) -> None:
    """Guard new execution/positive completion in the source transaction.

    Cancellation, failed results and adverse Gate decisions remain recordable.
    Replaying historical evidence is handled separately without this guard.
    """
    from app.domain.formal_schedule import current_plan

    formal = current_plan(connection, tenant_id, project_id)
    if not formal or not any(node["id"] == node_id for node in formal["nodes"]):
        if values.get("finished_at") is not None and values.get("successful") is True:
            from app.domain.id_handoff_runtime import acceptance_conditions, execution_conditions

            conditions = acceptance_conditions(connection, tenant_id, project_id, formal)
            blockers = [
                entry
                for entry in execution_conditions(
                    conditions.get(node_id, []), values["finished_at"]
                )
                if not entry["satisfied"]
            ]
            if blockers:
                raise ScheduleExecutionBlocked(blockers)
        return
    if values["successful"] is False:
        return
    start = values["started_at"]
    finish = values["finished_at"]
    new_start = start is not None and (
        previous is None or previous["started_at"] is None or action == "gate.round.open"
    )
    new_finish = (
        finish is not None
        and values["successful"] is True
        and (
            previous is None
            or previous["finished_at"] != finish
            or previous["successful"] is not True
        )
    )
    if not new_start and not new_finish:
        return
    if (
        new_start
        and connection.execute(
            select(tables.projects.c.status).where(
                tables.projects.c.tenant_id == tenant_id,
                tables.projects.c.id == project_id,
            )
        ).scalar_one()
        != "active"
    ):
        raise ScheduleExecutionBlocked([{"reason": "请先激活项目，再开始正式业务节点"}])
    blockers = []
    for point, timestamp, changed in (("start", start, new_start), ("finish", finish, new_finish)):
        if not changed:
            continue
        try:
            state = schedule_state(connection, tenant_id, project_id, timestamp)
        except ValueError as error:
            raise ScheduleExecutionBlocked(
                [{"reason": f"排程暂不能计算执行条件：{error}"}]
            ) from error
        node = next(item for item in state["items"] if item["node_id"] == str(node_id))
        blockers.extend(node[f"{point}_blockers"])
        if point == "finish" and start is None:
            blockers.append({"reason": "缺少本次实际开始记录，不能确认正式节点完成"})
    if blockers:
        raise ScheduleExecutionBlocked(blockers)


def guard_source_action(
    connection: Connection,
    tenant_id: UUID,
    project_id: UUID,
    source_id: UUID,
    kind: str,
    action: str,
    after_snapshot: dict[str, Any],
    occurred_at: datetime,
) -> None:
    """Called before changing source rows, preserving valid forecast comparison."""
    from app.domain.schedule_source_actuals import KINDS, projection

    source_column = KINDS[kind]
    if source_column is None:
        if kind != "milestone":
            raise ValueError("Unsupported source kind")
        source_column = "id"
    node_id = connection.execute(
        select(tables.schedule_nodes.c.id).where(
            tables.schedule_nodes.c.tenant_id == tenant_id,
            tables.schedule_nodes.c.project_id == project_id,
            tables.schedule_nodes.c.node_kind == kind,
            (
                tables.schedule_nodes.c.id
                if kind == "milestone"
                else tables.schedule_nodes.c[source_column]
            )
            == source_id,
        )
    ).scalar_one_or_none()
    if node_id is None:
        return
    previous = (
        connection.execute(
            select(tables.schedule_source_observations)
            .where(
                tables.schedule_source_observations.c.tenant_id == tenant_id,
                tables.schedule_source_observations.c.project_id == project_id,
                tables.schedule_source_observations.c.node_id == node_id,
            )
            .order_by(tables.schedule_source_observations.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    values = projection(
        kind,
        {"action": action, "after_snapshot": after_snapshot, "timestamp": occurred_at},
        previous,
    )
    guard_source_execution(connection, tenant_id, project_id, node_id, action, values, previous)


def record_task_actual(
    connection: Connection,
    tenant_id: UUID,
    project_id: UUID,
    task_id: UUID,
    to_status: str,
    actor_user_id: UUID,
    now: datetime,
    written: WrittenEventAudit,
) -> None:
    from app.domain.formal_schedule import current_plan

    formal = current_plan(connection, tenant_id, project_id)
    binding = (
        next((node for node in formal["nodes"] if node["task_id"] == task_id), None)
        if formal
        else None
    )
    if binding is None:
        return
    from app.domain.schedule_forecasts import automatic_forecast, record_forecast_errors

    if to_status not in ("in_progress", "done"):
        automatic_forecast(
            connection, tenant_id, project_id, actor_user_id, "任务状态变化后的预测更新", now
        )
        return
    point = "start" if to_status == "in_progress" else "finish"
    table = tables.scheduled_task_observations
    if connection.execute(
        select(table.c.id).where(
            table.c.tenant_id == tenant_id,
            table.c.node_id == binding["schedule_node_id"],
            table.c.point == point,
        )
    ).first():
        automatic_forecast(
            connection, tenant_id, project_id, actor_user_id, "任务恢复后的预测更新", now
        )
        return
    connection.execute(
        table.insert().values(
            id=uuid4(),
            tenant_id=tenant_id,
            project_id=project_id,
            node_id=binding["schedule_node_id"],
            task_id=task_id,
            point=point,
            observed_at=now,
            event_row_id=written.event_row_id,
            audit_row_id=written.audit_row_id,
        )
    )
    persist_actual_snapshot(connection, tenant_id, project_id, actor_user_id, now)

    record_forecast_errors(
        connection,
        tenant_id,
        project_id,
        binding["schedule_node_id"],
        point,
        now,
        written.event_row_id,
    )
    automatic_forecast(
        connection, tenant_id, project_id, actor_user_id, "实际时间更新后的预测传播", now
    )


def persist_actual_snapshot(
    connection: Connection, tenant_id: UUID, project_id: UUID, actor_user_id: UUID, now: datetime
) -> None:
    observations = effective_observations(connection, tenant_id, project_id)
    from app.domain.schedule_source_actuals import latest_observations, observation_sources

    source_observations = latest_observations(connection, tenant_id, project_id)
    windows: dict[UUID, dict[str, Any]] = {}
    for observation in observations:
        windows.setdefault(observation["node_id"], {"start": None, "end": None})[
            "start" if observation["point"] == "start" else "end"
        ] = observation["observed_at"]
    for observation in source_observations:
        windows[observation["node_id"]] = {
            "start": observation["started_at"],
            "end": observation["finished_at"],
        }
    if not windows:
        return
    records = tables.schedule_time_records
    version = (
        connection.execute(
            select(func.max(records.c.version)).where(
                records.c.tenant_id == tenant_id,
                records.c.project_id == project_id,
                records.c.time_kind == "actual",
            )
        ).scalar_one()
        or 0
    ) + 1
    record_id = uuid4()
    contract = TimeRecord(
        id=record_id,
        tenant_id=tenant_id,
        scope=ScopeRef(kind="project", ref_id=project_id),
        version=version,
        owner_user_id=actor_user_id,
        sources=tuple(
            SourceRef(
                tenant_id=tenant_id,
                project_id=project_id,
                kind="event",
                ref_id=item["event_row_id"],
                version=1,
            )
            for item in observations
        )
        + tuple(
            SourceRef(**source)
            for item in source_observations
            for source in observation_sources(item)
        ),
        time_kind="actual",
        node_times=tuple(
            NodeTime(node_id=node_id, window=TimeWindow(**window))
            for node_id, window in sorted(windows.items(), key=lambda item: str(item[0]))
        ),
        fact_kind="observed",
        as_of=now,
    )
    connection.execute(
        records.insert().values(
            id=record_id,
            tenant_id=tenant_id,
            project_id=project_id,
            time_kind="actual",
            version=version,
            contract=contract.model_dump(mode="json"),
        )
    )
    connection.execute(
        tables.schedule_time_nodes.insert(),
        [
            {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "record_id": record_id,
                "node_id": node.node_id,
                "start": node.window.start,
                "end": node.window.end,
            }
            for node in contract.node_times
        ],
    )


class ScheduleExecutionService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(self, context: AuthContext, project_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as connection:
            _project(connection, context, project_id)
            return schedule_state(connection, context.tenant.id, project_id, datetime.now(UTC))
