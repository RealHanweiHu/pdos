"""Prediction identity regressions using captured snapshots, without a database."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Select

from app.domain.product_workspace import ProductWorkError
from app.domain.schedule_forecasts import identify_forecast_nodes
from app.domain.schedule_source_errors import correction_error_views, record_source_errors

AS_OF = datetime(2026, 10, 1, tzinfo=UTC)


class SnapshotRows:
    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows

    def mappings(self) -> list[dict[str, Any]]:
        return self.rows


class SnapshotConnection:
    def __init__(self, rows: list[dict[str, Any]], required_columns: set[str] | None = None):
        self.rows = rows
        self.required_columns = required_columns or set()
        self.inserts: list[dict[str, Any]] = []

    def execute(self, statement: Any) -> SnapshotRows:
        if isinstance(statement, Select):
            assert self.required_columns <= set(statement.selected_columns.keys())
            return SnapshotRows(self.rows)
        self.inserts.append(dict(statement.compile().params))
        return SnapshotRows([])


def forecast_snapshot(node_id: UUID, *, legacy: bool) -> dict[str, Any]:
    result = {
        "as_of": AS_OF.isoformat(),
        "nodes": [
            {
                "node_key": "T",
                "start": None,
                "finish": (AS_OF + timedelta(days=7)).isoformat(),
                "actual_start": None,
                "actual_finish": None,
            }
        ],
    }
    states = [{"node_key": "T", "node_id": str(node_id)}]
    return {
        "record_id": uuid4(),
        "contract": {"as_of": AS_OF.isoformat()},
        "predicted_at": AS_OF + timedelta(days=7),
        "inputs": {"basis": {"tasks": states}},
        "result": result if legacy else identify_forecast_nodes(result, states),
    }


def observation(node_id: UUID) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "project_id": uuid4(),
        "node_id": node_id,
        "node_kind": "test_run",
        "source_status": "passed",
        "started_at": None,
        "finished_at": AS_OF + timedelta(days=8),
        "observed_at": AS_OF + timedelta(days=8, hours=1),
    }


def correction(observed: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "node_id": observed["node_id"],
        "version": 1,
        "started_at": None,
        "finished_at": AS_OF + timedelta(days=9),
        "event_row_id": 12,
        "original_snapshot": {
            **observed,
            "observed_at": observed["observed_at"].isoformat(),
        },
    }


@pytest.mark.parametrize("legacy", [False, True])
def test_business_completion_and_correction_attribute_new_and_legacy_forecasts(
    legacy: bool,
) -> None:
    node_id = uuid4()
    forecast = forecast_snapshot(node_id, legacy=legacy)
    saved = deepcopy(forecast)
    observed = observation(node_id)
    connection = SnapshotConnection([forecast], {"inputs", "result"})
    record_source_errors(cast(Connection, connection), observed, None)
    assert len(connection.inserts) == 1
    error = connection.inserts[0]
    assert error["node_id"] == node_id and error["point"] == "finish"
    assert error["forecast_record_id"] == forecast["record_id"]
    assert error["error_seconds"] == Decimal(86400)
    revised = correction(observed)
    revisions = correction_error_views(
        cast(Connection, SnapshotConnection([revised])),
        observed["tenant_id"],
        observed["project_id"],
        [forecast],
    )
    assert len(revisions) == 1
    assert revisions[0]["eligible"] is True
    assert revisions[0]["error_seconds"] == "172800"
    assert revisions[0]["forecast_record_id"] == str(forecast["record_id"])
    assert forecast == saved


@pytest.mark.parametrize("problem", ["missing", "different", "invalid", "ambiguous", "conflict"])
def test_missing_or_ambiguous_identity_never_crashes_or_invents_an_error(problem: str) -> None:
    node_id = uuid4()
    forecast = forecast_snapshot(node_id, legacy=True)
    states = forecast["inputs"]["basis"]["tasks"]
    if problem == "missing":
        forecast.pop("inputs")
    elif problem == "different":
        states[0]["node_id"] = str(uuid4())
    elif problem == "invalid":
        states[0]["node_id"] = "unrecorded"
    elif problem == "ambiguous":
        states.append({"node_key": "T", "node_id": str(node_id)})
    else:
        forecast["result"]["nodes"][0]["node_id"] = str(uuid4())
    saved = deepcopy(forecast)
    observed = observation(node_id)
    connection = SnapshotConnection([forecast])
    record_source_errors(cast(Connection, connection), observed, None)
    assert connection.inserts == []
    assert (
        correction_error_views(
            cast(Connection, SnapshotConnection([correction(observed)])),
            observed["tenant_id"],
            observed["project_id"],
            [forecast],
        )
        == []
    )
    assert forecast == saved


@pytest.mark.parametrize("excluded", ["actual", "after_actual", "after_observation", "unchanged"])
def test_identity_resolution_preserves_actual_and_error_cutoffs(excluded: str) -> None:
    node_id = uuid4()
    forecast = forecast_snapshot(node_id, legacy=True)
    observed = observation(node_id)
    previous = None
    if excluded == "actual":
        forecast["result"]["nodes"][0]["actual_finish"] = forecast["result"]["nodes"][0]["finish"]
    elif excluded == "after_actual":
        forecast["contract"]["as_of"] = observed["finished_at"].isoformat()
    elif excluded == "after_observation":
        observed["observed_at"] = AS_OF
    else:
        previous = observed
    connection = SnapshotConnection([forecast])
    record_source_errors(cast(Connection, connection), observed, previous)
    assert connection.inserts == []


def test_new_prediction_identity_comes_from_captured_keys_without_mutating_inputs() -> None:
    first, second = uuid4(), uuid4()
    result = {"nodes": [{"node_key": "B"}, {"node_key": "A", "node_id": str(uuid4())}]}
    states = [{"node_key": "A", "node_id": str(first)}, {"node_key": "B", "node_id": str(second)}]
    saved = deepcopy((result, states))
    identified = identify_forecast_nodes(result, states)
    assert [node["node_id"] for node in identified["nodes"]] == [str(second), str(first)]
    assert (result, states) == saved
    with pytest.raises(ProductWorkError, match="身份映射不完整"):
        identify_forecast_nodes(result, states[:1])
    with pytest.raises(ProductWorkError, match="身份映射不完整"):
        identify_forecast_nodes(result, [*states, states[0]])
