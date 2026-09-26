"""Immutable forecast inputs/results and errors measured against later actual events."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field
from sqlalchemy import Connection, Engine, func, select, true

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import (
    Contract,
    Digest,
    NodeTime,
    PlanCandidate,
    Quantity,
    ScopeRef,
    SourceRef,
    Text,
    TimeRecord,
    TimeWindow,
)
from app.db.schema import tables
from app.domain.plan_scheduling import NodeAllocation
from app.domain.product_workspace import ProductWorkError, _plain, _role, digest
from app.domain.resource_reservations import _project
from app.domain.schedule_forecast_engine import (
    ALGORITHM_VERSION,
    MATERIAL_ALGORITHM_VERSION,
    TOOLING_ALGORITHM_VERSION,
    calculate_forecast,
)
from app.domain.schedule_source_errors import correction_error_views
from app.domain.working_time import CalendarDefinition
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class RemainingEstimate(Contract):
    remaining_hours: Quantity | None = Field(ge=0)
    remaining_waiting_days: int | None = Field(ge=0, le=36600)
    not_before: AwareDatetime | None = None
    basis: Text


class ForecastDraft(Contract):
    request_id: UUID
    expected_basis_digest: Digest
    estimates: dict[str, RemainingEstimate] = Field(default_factory=dict, max_length=2000)
    reason: Text


def capture_local_basis(
    connection: Connection, tenant_id: UUID, project_id: UUID
) -> dict[str, Any]:
    from app.domain.formal_schedule import current_plan, current_states

    formal = current_plan(connection, tenant_id, project_id)
    if formal is None:
        raise ProductWorkError("请先应用正式初始计划")
    states, titles = current_states(connection, tenant_id, project_id, formal)
    from app.domain.id_handoff_runtime import acceptance_conditions

    handoffs = acceptance_conditions(connection, tenant_id, project_id, formal)
    for state in states:
        conditions = handoffs.get(UUID(state["node_id"]), [])
        if conditions:
            state["id_handoff_conditions"] = conditions
            reasons = [
                entry["reason"]
                for entry in conditions
                if not entry["accepted"] and entry.get("kind") != "id_freeze_checkpoint"
            ]
            checkpoint_warnings = [
                f"ID冻结待办理：{entry['reason']}；预测不表示检查点已通过"
                for entry in conditions
                if entry.get("kind") == "id_freeze_checkpoint" and not entry["accepted"]
            ]
            state["input_warnings"] = [*state.get("input_warnings", []), *checkpoint_warnings]
            if state.get("actual_finish"):
                state["input_warnings"] = [*state.get("input_warnings", []), *reasons]
            else:
                state["input_unknown"] = [*state.get("input_unknown", []), *reasons]
    from app.domain.material_schedule import conditions as material_conditions

    material = material_conditions(connection, tenant_id, project_id)
    for state in states:
        if material.get(UUID(state["node_id"])):
            state["material_conditions"] = material[UUID(state["node_id"])]
    from app.domain.tooling_schedule import conditions as tooling_conditions

    tooling = tooling_conditions(connection, tenant_id, project_id)
    for state in states:
        if tooling.get(UUID(state["node_id"])):
            state["tooling_conditions"] = tooling[UUID(state["node_id"])]
    allocations = formal["allocations"]
    calendars = {
        str(row["id"]): row["definition"]
        for row in connection.execute(
            select(tables.work_calendar_versions).where(
                tables.work_calendar_versions.c.tenant_id == tenant_id,
                tables.work_calendar_versions.c.id.in_(
                    {UUID(item["calendar_version_id"]) for item in allocations.values()}
                ),
            )
        ).mappings()
    }
    basis = {
        "baseline_id": str(formal["baseline_id"]),
        "baseline_version": formal["baseline_version"],
        "plan": formal["plan"],
        "allocations": allocations,
        "calendars": calendars,
        "tasks": states,
    }
    return {"basis": basis, "basis_digest": digest(basis), "titles": titles}


def capture_basis(connection: Connection, tenant_id: UUID, project_id: UUID) -> dict[str, Any]:
    from app.domain.schedule_network import capture_network, latest_human_estimates, project_sources

    capture = capture_local_basis(connection, tenant_id, project_id)
    local = capture["basis"]
    network = capture_network(connection, tenant_id, project_id, local)
    basis = {**local, "external_dependencies": []}
    if network:
        basis["external_input_digest"] = digest(network)
        basis["external_dependencies"] = project_sources(
            network,
            local,
            datetime.now(UTC),
            latest_human_estimates(connection, tenant_id, project_id, local),
        )
    return {
        **capture,
        "basis": basis,
        "network": network,
        "basis_digest": digest(
            {key: value for key, value in basis.items() if key != "external_dependencies"}
        ),
    }


def persist_forecast(
    connection: Connection,
    tenant_id: UUID,
    project_id: UUID,
    actor_user_id: UUID | None,
    command: ForecastDraft,
    capture: dict[str, Any],
    *,
    as_of: datetime | None = None,
    trigger: str = "human",
) -> dict[str, Any]:
    if trigger not in ("human", "automatic", "propagation") or (
        (actor_user_id is None) != (trigger == "propagation")
    ):
        raise ProductWorkError("预测必须区分人工办理与确定性服务传播")
    table = tables.schedule_forecast_runs
    fingerprint = digest({"project_id": str(project_id), **command.model_dump(mode="json")})
    prior = (
        connection.execute(
            select(table).where(
                table.c.tenant_id == tenant_id,
                table.c.created_by_user_id == actor_user_id,
                table.c.request_id == command.request_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if prior:
        if prior["request_digest"] != fingerprint:
            raise ProductWorkError("请求编号已用于不同的预测输入")
        from app.domain.schedule_network import public_forecast

        return public_forecast(prior)
    if command.expected_basis_digest != capture["basis_digest"]:
        raise ProductWorkError("实际进展或排程依据已变化，请刷新剩余工作估计")
    basis = dict(capture["basis"])
    now = as_of or datetime.now(UTC)
    if capture.get("network"):
        from app.domain.schedule_network import project_sources

        basis["external_dependencies"] = project_sources(
            capture["network"],
            basis,
            now,
            {key: value.model_dump(mode="json") for key, value in command.estimates.items()},
        )
    allocations = {
        key: NodeAllocation(
            calendar_key=value["calendar_version_id"],
            parallel_units=value["parallel_units"],
            allocation_basis=value["allocation_basis"],
            not_before=value.get("not_before"),
        )
        for key, value in basis["allocations"].items()
    }
    try:
        result = calculate_forecast(
            PlanCandidate.model_validate(basis["plan"]),
            now,
            {
                key: CalendarDefinition.model_validate(value)
                for key, value in basis["calendars"].items()
            },
            allocations,
            {item["node_key"]: item for item in basis["tasks"]},
            {key: value.model_dump(mode="json") for key, value in command.estimates.items()},
            basis.get("external_dependencies", []),
        )
    except ValueError as error:
        result = {
            "algorithm_version": TOOLING_ALGORITHM_VERSION
            if any(item.get("tooling_conditions") for item in basis["tasks"])
            else MATERIAL_ALGORITHM_VERSION
            if any(item.get("material_conditions") for item in basis["tasks"])
            else ALGORITHM_VERSION,
            "as_of": now.isoformat(),
            "complete": False,
            "project_finish": None,
            "capacity_status": "not_rechecked",
            "calendars": basis["calendars"],
            "nodes": [
                {
                    "node_key": item["node_key"],
                    "start": item["actual_start"],
                    "finish": item["actual_finish"],
                    "actual_start": item["actual_start"],
                    "actual_finish": item["actual_finish"],
                    "status": item["status"],
                    "origin": "actual" if item["actual_finish"] else "unknown",
                    "unknown_reasons": []
                    if item["actual_finish"]
                    else [f"预测计算未完成：{error}"],
                    "warnings": [],
                    "estimate": None,
                }
                for item in basis["tasks"]
            ],
        }

    records = tables.schedule_time_records
    version = (
        connection.execute(
            select(func.max(records.c.version)).where(
                records.c.tenant_id == tenant_id,
                records.c.project_id == project_id,
                records.c.time_kind == "forecast",
            )
        ).scalar_one()
        or 0
    ) + 1
    record_id = uuid4()
    node_ids = {row["node_key"]: UUID(row["node_id"]) for row in basis["tasks"]}
    sources = [
        SourceRef(
            tenant_id=tenant_id,
            project_id=project_id,
            kind="schedule_time_record",
            ref_id=UUID(basis["baseline_id"]),
            version=basis.get("baseline_version", 1),
        )
    ]
    sources.extend(
        SourceRef(
            tenant_id=tenant_id,
            project_id=project_id,
            kind="cross_project_schedule_application",
            ref_id=UUID(edge["application_id"]),
            version=1,
        )
        for edge in basis.get("external_dependencies", [])
    )
    for item in basis["tasks"]:
        for field in ("actual_start_event", "actual_finish_event"):
            if item[field]:
                sources.append(
                    SourceRef(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        kind="event",
                        ref_id=item[field],
                        version=1,
                    )
                )
    for item in basis["tasks"]:
        if item.get("actual_observation"):
            observed = item["actual_observation"]
            sources.append(
                SourceRef(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    kind="schedule_source_observation",
                    ref_id=UUID(observed["id"]),
                    version=observed["version"],
                )
            )
        if item.get("actual_correction"):
            correction = item["actual_correction"]
            sources.append(
                SourceRef(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    kind="schedule_source_correction",
                    ref_id=UUID(correction["id"]),
                    version=correction["version"],
                )
            )
    contract = TimeRecord(
        id=record_id,
        tenant_id=tenant_id,
        scope=ScopeRef(kind="project", ref_id=project_id),
        version=version,
        owner_user_id=actor_user_id,
        sources=tuple(sources),
        time_kind="forecast",
        node_times=tuple(
            NodeTime(
                node_id=node_ids[item["node_key"]],
                window=TimeWindow(start=item["start"], end=item["finish"]),
            )
            for item in result["nodes"]
        ),
        fact_kind="derived",
        algorithm_version=result["algorithm_version"],
        as_of=now,
    )
    connection.execute(
        records.insert().values(
            id=record_id,
            tenant_id=tenant_id,
            project_id=project_id,
            time_kind="forecast",
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
                "node_id": item.node_id,
                "start": item.window.start,
                "end": item.window.end,
            }
            for item in contract.node_times
        ],
    )
    row = (
        connection.execute(
            table.insert()
            .values(
                tenant_id=tenant_id,
                project_id=project_id,
                record_id=record_id,
                baseline_id=UUID(basis["baseline_id"]),
                inputs={
                    "basis": basis,
                    "network": capture.get("network"),
                    "trigger": trigger,
                    "estimates": {
                        key: value.model_dump(mode="json")
                        for key, value in command.estimates.items()
                    },
                    "as_of": now.isoformat(),
                },
                result=result,
                basis_digest=capture["basis_digest"],
                reason=command.reason,
                created_by_user_id=actor_user_id,
                request_id=command.request_id,
                request_digest=fingerprint,
            )
            .returning(table)
        )
        .mappings()
        .one()
    )
    EventAuditWriter(
        connection, tenant_id=tenant_id, actor_user_id=actor_user_id, project_id=project_id
    ).record(
        EventDraft(
            event_id=f"schedule-forecast:{record_id}",
            event_type="SCHEDULE_FORECAST_RECALCULATED",
            source="planning_service",
            entity_id=record_id,
            payload={
                "record_id": str(record_id),
                "version": version,
                "complete": result["complete"],
            },
            occurred_at=now,
        ),
        AuditDraft(
            action="schedule.forecast",
            after_snapshot={
                "record_id": str(record_id),
                "version": version,
                "basis_digest": capture["basis_digest"],
                "project_finish": result["project_finish"],
            },
            context={"reason": command.reason},
        ),
    )
    from app.domain.schedule_network import public_forecast

    return {**public_forecast(row), "version": version}


def automatic_forecast(
    connection: Connection,
    tenant_id: UUID,
    project_id: UUID,
    actor_user_id: UUID,
    reason: str,
    now: datetime,
) -> None:
    capture = capture_basis(connection, tenant_id, project_id)
    persist_forecast(
        connection,
        tenant_id,
        project_id,
        actor_user_id,
        ForecastDraft(
            request_id=uuid4(), expected_basis_digest=capture["basis_digest"], reason=reason
        ),
        capture,
        as_of=now,
        trigger="automatic",
    )


def record_forecast_errors(
    connection: Connection,
    tenant_id: UUID,
    project_id: UUID,
    node_id: UUID,
    point: str,
    observed_at: datetime,
    event_row_id: int,
) -> None:
    times = tables.schedule_time_nodes
    records = tables.schedule_time_records
    column = times.c.start if point == "start" else times.c.end
    rows = connection.execute(
        select(times.c.record_id, column.label("predicted_at"), records.c.contract)
        .join(
            records,
            (records.c.tenant_id == times.c.tenant_id)
            & (records.c.project_id == times.c.project_id)
            & (records.c.id == times.c.record_id),
        )
        .where(
            times.c.tenant_id == tenant_id,
            times.c.project_id == project_id,
            times.c.node_id == node_id,
            records.c.time_kind == "forecast",
            column.is_not(None),
        )
    ).mappings()
    for row in rows:
        if datetime.fromisoformat(row["contract"]["as_of"]) >= observed_at:
            continue
        delta = observed_at - row["predicted_at"]
        seconds = (
            Decimal(delta.days * 86400 + delta.seconds) + Decimal(delta.microseconds) / 1000000
        )
        connection.execute(
            tables.schedule_forecast_errors.insert().values(
                tenant_id=tenant_id,
                project_id=project_id,
                forecast_record_id=row["record_id"],
                node_id=node_id,
                point=point,
                event_row_id=event_row_id,
                predicted_at=row["predicted_at"],
                observed_at=observed_at,
                error_seconds=seconds,
            )
        )


def forecast_changes(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    previous = {item["node_key"]: item for item in before["nodes"]}
    changed = []
    for item in after["nodes"]:
        prior = previous.get(item["node_key"])
        if prior is None or any(
            prior.get(point) != item.get(point) for point in ("start", "finish")
        ):
            differences = {}
            for point in ("start", "finish"):
                old = prior.get(point) if prior else None
                new = item.get(point)
                differences[point] = {
                    "before": old,
                    "after": new,
                    "delta_minutes": (
                        datetime.fromisoformat(new) - datetime.fromisoformat(old)
                    ).total_seconds()
                    / 60
                    if old and new
                    else None,
                }
            changed.append({"node_key": item["node_key"], **differences})
    return changed


class ScheduleForecastService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(
        self, context: AuthContext, project_id: UUID, *, record_id: UUID | None = None
    ) -> dict[str, Any]:
        with self.engine.connect() as connection:
            _project(connection, context, project_id)
            capture = capture_basis(connection, context.tenant.id, project_id)
            records = tables.schedule_time_records
            runs = tables.schedule_forecast_runs
            history = list(
                connection.execute(
                    select(runs, records.c.version)
                    .join(
                        records,
                        (records.c.tenant_id == runs.c.tenant_id)
                        & (records.c.id == runs.c.record_id),
                    )
                    .where(
                        runs.c.tenant_id == context.tenant.id,
                        runs.c.project_id == project_id,
                        runs.c.record_id == record_id if record_id else true(),
                    )
                    .order_by(records.c.version.desc())
                    .limit(51)
                ).mappings()
            )
            if record_id is not None and not history:
                raise ProductWorkError("所选预测版本不存在于当前可访问项目中")
            errors = list(
                connection.execute(
                    select(tables.schedule_forecast_errors)
                    .where(
                        tables.schedule_forecast_errors.c.tenant_id == context.tenant.id,
                        tables.schedule_forecast_errors.c.project_id == project_id,
                        tables.schedule_forecast_errors.c.forecast_record_id.in_(
                            [row["record_id"] for row in history[:50]]
                        ),
                    )
                    .order_by(tables.schedule_forecast_errors.c.observed_at.desc())
                ).mappings()
            )
            source_errors = tables.schedule_source_forecast_errors
            source_observations = tables.schedule_source_observations
            business_errors = list(
                connection.execute(
                    select(
                        source_errors,
                        source_observations.c.node_kind,
                        source_observations.c.version.label("observation_version"),
                        source_observations.c.source_status,
                        source_observations.c.event_row_id,
                        source_observations.c.audit_row_id,
                    )
                    .join(
                        source_observations,
                        (source_observations.c.tenant_id == source_errors.c.tenant_id)
                        & (source_observations.c.project_id == source_errors.c.project_id)
                        & (source_observations.c.id == source_errors.c.observation_id),
                    )
                    .where(
                        source_errors.c.tenant_id == context.tenant.id,
                        source_errors.c.project_id == project_id,
                        source_errors.c.forecast_record_id.in_(
                            [row["record_id"] for row in history[:50]]
                        ),
                    )
                    .order_by(
                        source_observations.c.observed_at.desc(),
                        source_observations.c.version.desc(),
                    )
                ).mappings()
            )
            corrections = tables.schedule_actual_corrections
            revised = tables.schedule_forecast_error_corrections
            revisions = list(
                connection.execute(
                    select(
                        revised,
                        corrections.c.node_id,
                        corrections.c.point,
                        corrections.c.version,
                        corrections.c.observed_at,
                        corrections.c.event_row_id,
                        corrections.c.created_at,
                    )
                    .join(
                        corrections,
                        (corrections.c.tenant_id == revised.c.tenant_id)
                        & (corrections.c.project_id == revised.c.project_id)
                        & (corrections.c.id == revised.c.correction_id),
                    )
                    .where(
                        revised.c.tenant_id == context.tenant.id,
                        revised.c.project_id == project_id,
                        revised.c.forecast_record_id.in_(
                            [row["record_id"] for row in history[:50]]
                        ),
                    )
                    .order_by(corrections.c.version.desc())
                ).mappings()
            )
            from app.domain.schedule_network import public_forecast

            return {
                "basis_digest": capture["basis_digest"],
                "external_dependencies": capture["basis"].get("external_dependencies", []),
                "tasks": [
                    {**item, "title": capture["titles"][item["node_key"]]}
                    for item in capture["basis"]["tasks"]
                ],
                "items": [
                    {
                        **public_forecast(row),
                        "basis_is_current": row["basis_digest"] == capture["basis_digest"],
                        "changes": forecast_changes(history[index + 1]["result"], row["result"])
                        if index + 1 < len(history)
                        else None,
                    }
                    for index, row in enumerate(history[:50])
                ],
                "has_more": len(history) > 50,
                "errors": [_plain(row) for row in errors],
                "source_errors": [_plain(row) for row in business_errors],
                "source_error_corrections": correction_error_views(
                    connection, context.tenant.id, project_id, history[:50]
                ),
                "error_corrections": [_plain(row) for row in revisions],
                "can_recalculate": record_id is None
                and is_allowed(context.user.role, Action.PROJECT_EDIT),
            }

    def recalculate(
        self, context: AuthContext, project_id: UUID, command: ForecastDraft
    ) -> dict[str, Any]:
        _role(context, Action.PROJECT_EDIT)
        with self.engine.begin() as connection:
            _project(connection, context, project_id, write=True)
            capture = capture_basis(connection, context.tenant.id, project_id)
            return persist_forecast(
                connection, context.tenant.id, project_id, context.user.id, command, capture
            )


def current_forecast_points(
    connection: Connection, tenant_id: UUID, project_id: UUID, *, trail: tuple[UUID, ...] = ()
) -> dict[str, Any] | None:
    if project_id in trail or len(trail) >= 32:
        return None
    runs = tables.schedule_forecast_runs
    records = tables.schedule_time_records
    latest = (
        connection.execute(
            select(runs, records.c.version)
            .join(
                records,
                (records.c.tenant_id == runs.c.tenant_id) & (records.c.id == runs.c.record_id),
            )
            .where(runs.c.tenant_id == tenant_id, runs.c.project_id == project_id)
            .order_by(records.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    if latest is None:
        return None
    capture = capture_basis(connection, tenant_id, project_id)
    if latest["basis_digest"] != capture["basis_digest"]:
        return None
    return {
        "record_id": str(latest["record_id"]),
        "version": latest["version"],
        "nodes": {item["node_key"]: item for item in latest["result"]["nodes"]},
    }
