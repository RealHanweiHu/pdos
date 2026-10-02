"""Forecast errors tied to the precise business observation that revealed Actual."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select

from app.db.schema import tables


def forecast_node(forecast: Any, node_id: UUID) -> dict[str, Any] | None:
    """Read an immutable result, resolving legacy keys only from its own basis."""
    mapping: dict[str, UUID | None] = {}
    identity: UUID | None
    for state in (forecast.get("inputs") or {}).get("basis", {}).get("tasks", []):
        key = state.get("node_key")
        if not isinstance(key, str):
            continue
        try:
            identity = UUID(str(state.get("node_id")))
        except ValueError:
            identity = None
        mapping[key] = identity if key not in mapping else None
    matches: list[dict[str, Any]] = []
    for node in forecast["result"]["nodes"]:
        stored_id = node.get("node_id")
        if stored_id is not None:
            try:
                identity = UUID(str(stored_id))
            except ValueError:
                continue
            if node.get("node_key") in mapping and mapping[node["node_key"]] != identity:
                continue
        else:
            identity = mapping.get(node.get("node_key"))
        if identity == node_id:
            matches.append(node)
    # Missing or ambiguous provenance cannot create an attributed error.
    return dict(matches[0]) if len(matches) == 1 else None


def correction_error_views(
    connection: Connection, tenant_id: UUID, project_id: UUID, forecasts: list[Any]
) -> list[dict[str, Any]]:
    """Derive revisions from immutable correction and prediction snapshots."""
    table = tables.schedule_source_corrections
    rows = connection.execute(
        select(table)
        .where(table.c.tenant_id == tenant_id, table.c.project_id == project_id)
        .order_by(table.c.version.desc(), table.c.id)
        .limit(500)
    ).mappings()
    result = []
    for correction in rows:
        original = correction["original_snapshot"]
        cutoff = datetime.fromisoformat(original["observed_at"])
        for forecast in forecasts:
            node = forecast_node(forecast, correction["node_id"])
            as_of = datetime.fromisoformat(forecast["result"]["as_of"])
            if node is None or as_of >= cutoff:
                continue
            for point, field in (("start", "started_at"), ("finish", "finished_at")):
                if not node.get(point) or node.get("actual_" + point):
                    continue
                actual = correction[field]
                qualified = actual_point({**original, field: actual}, point)
                eligible = qualified is not None and as_of < actual
                predicted = datetime.fromisoformat(node[point])
                delta = actual - predicted if actual else None
                seconds = (
                    Decimal(delta.days * 86400 + delta.seconds)
                    + Decimal(delta.microseconds) / 1000000
                    if delta is not None
                    else None
                )
                result.append(
                    {
                        "correction_id": str(correction["id"]),
                        "version": correction["version"],
                        "forecast_record_id": str(forecast["record_id"]),
                        "node_id": str(correction["node_id"]),
                        "point": point,
                        "predicted_at": predicted.isoformat(),
                        "observed_at": actual.isoformat() if actual else None,
                        "error_seconds": str(seconds) if seconds is not None else None,
                        "eligible": eligible,
                        "event_row_id": correction["event_row_id"],
                        "algorithm_version": "source_actual_error_revision.v1",
                    }
                )
    return result


def actual_point(observation: Any, point: str) -> datetime | None:
    if observation is None:
        return None
    if point == "finish" and (
        observation["source_status"] in ("cancelled", "skipped", "aborted")
        or (
            observation["node_kind"] == "certification"
            and observation["source_status"] in ("expired", "revoked")
        )
        or (
            observation["node_kind"] in {"gate", "tooling"}
            and observation["successful"] is not True
        )
    ):
        return None
    value = observation["started_at" if point == "start" else "finished_at"]
    if value is not None and not isinstance(value, datetime):
        raise ValueError("Actual observation timestamp must be a datetime")
    return value


def record_source_errors(connection: Connection, observation: Any, previous: Any | None) -> None:
    tenant_id, project_id, node_id = (
        observation["tenant_id"],
        observation["project_id"],
        observation["node_id"],
    )
    times, records, runs = (
        tables.schedule_time_nodes,
        tables.schedule_time_records,
        tables.schedule_forecast_runs,
    )
    for point, column in (("start", times.c.start), ("finish", times.c.end)):
        actual = actual_point(observation, point)
        if actual is None or actual == actual_point(previous, point):
            continue
        rows = connection.execute(
            select(
                times.c.record_id,
                column.label("predicted_at"),
                records.c.contract,
                runs.c.result,
                runs.c.inputs,
            )
            .join(
                records,
                (records.c.tenant_id == times.c.tenant_id)
                & (records.c.project_id == times.c.project_id)
                & (records.c.id == times.c.record_id),
            )
            .join(
                runs,
                (runs.c.tenant_id == records.c.tenant_id)
                & (runs.c.project_id == records.c.project_id)
                & (runs.c.record_id == records.c.id),
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
            as_of = datetime.fromisoformat(row["contract"]["as_of"])
            if as_of >= min(actual, observation["observed_at"]):
                continue
            result = forecast_node(row, node_id)
            if result is None or result.get(
                "actual_start" if point == "start" else "actual_finish"
            ):
                # Historical Actual carried through a forecast is not a prediction.
                continue
            delta = actual - row["predicted_at"]
            seconds = (
                Decimal(delta.days * 86400 + delta.seconds) + Decimal(delta.microseconds) / 1000000
            )
            connection.execute(
                tables.schedule_source_forecast_errors.insert().values(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    observation_id=observation["id"],
                    forecast_record_id=row["record_id"],
                    point=point,
                    node_id=node_id,
                    predicted_at=row["predicted_at"],
                    observed_at=actual,
                    error_seconds=seconds,
                )
            )
