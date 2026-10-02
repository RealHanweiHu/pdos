"""Removed formal nodes retain explicit material impacts; no database access."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection

from app.domain import material_schedule as bridge


class Entries:
    def __init__(self, values: list[dict[str, Any]]):
        self.values = values

    def mappings(self) -> list[dict[str, Any]]:
        return self.values


class Reader:
    def __init__(self, values: list[dict[str, Any]]):
        self.values = values

    def execute(self, statement: Any) -> Entries:
        return Entries(self.values)


def setup(
    monkeypatch: pytest.MonkeyPatch,
    *,
    removed: bool = False,
    restored: bool = False,
    mode: str = "waiting",
    formal_missing: bool = False,
) -> tuple[Connection, UUID, UUID, UUID, UUID, dict[str, Any]]:
    tenant, project, identity, issue, node, current_node = (uuid4() for _ in range(6))
    previous_baseline, current_baseline = uuid4(), uuid4()
    row = {
        "id": uuid4(),
        "exception_id": identity,
        "mode": mode,
        "version": 2,
        "source_digest": "a" * 64,
        "target_point": "start",
        "ready_at": datetime.now(UTC) + timedelta(days=2) if mode == "estimate" else None,
        "node_ids": [str(node), str(current_node)],
        "snapshot": {"source": {"revision_id": "same"}, "baseline_id": str(previous_baseline)},
    }
    formal = (
        None
        if formal_missing
        else {
            "baseline_id": current_baseline,
            "nodes": [{"id": current_node}] if removed else [{"id": node}, {"id": current_node}],
        }
    )
    state = {
        "core": {"revision_id": "same"},
        "source_digest": "a" * 64,
        "supply_ready": restored,
        "latest_review": {"id": str(uuid4())},
    }
    monkeypatch.setattr(bridge, "latest_bindings", lambda *args: [row])
    monkeypatch.setattr(bridge, "current_plan", lambda *args: formal)
    monkeypatch.setattr(bridge, "observations", lambda *args: {identity: state})
    c = cast(Connection, Reader([{"id": identity, "issue_id": issue}]))
    return c, tenant, project, node, current_node, row


@pytest.mark.parametrize("mode", ["waiting", "estimate"])
@pytest.mark.parametrize("restored", [False, True])
def test_removed_node_stays_unmapped_even_after_supply_recovers(
    monkeypatch: pytest.MonkeyPatch, mode: str, restored: bool
) -> None:
    c, tenant, project, original, retained, row = setup(
        monkeypatch, removed=True, restored=restored, mode=mode
    )
    values = bridge.conditions(c, tenant, project)
    missing = values[original][0]
    assert set(values) == {original, retained}
    assert missing["status"] == "rebind_required" and missing["ready_at"] is None
    assert "重新绑定或解除" in missing["reason"]
    assert missing["bound_baseline_id"] == row["snapshot"]["baseline_id"]
    assert missing["current_baseline_id"] != missing["bound_baseline_id"]
    assert missing["binding_id"] == str(row["id"])
    assert values[retained][0]["status"] == ("ready" if restored else mode)


@pytest.mark.parametrize("mode", ["waiting", "estimate"])
@pytest.mark.parametrize("restored", [False, True])
def test_new_baseline_preserving_original_nodes_keeps_existing_behavior(
    monkeypatch: pytest.MonkeyPatch, mode: str, restored: bool
) -> None:
    c, tenant, project, original, retained, _ = setup(
        monkeypatch, restored=restored, mode=mode
    )
    values = bridge.conditions(c, tenant, project)
    assert {v[0]["status"] for v in values.values()} == {"ready" if restored else mode}
    assert set(values) == {original, retained}


def test_no_current_formal_plan_requires_explicit_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, tenant, project, original, retained, _ = setup(
        monkeypatch, restored=True, formal_missing=True
    )
    values = bridge.conditions(c, tenant, project)
    assert set(values) == {original, retained}
    assert all(value[0]["status"] == "rebind_required" for value in values.values())
    assert "当前没有正式计划" in values[original][0]["reason"]


def test_explicit_release_removes_conditions_and_keeps_release_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, tenant, project, _, _, row = setup(monkeypatch)
    row.update(mode="released", node_ids=[])
    assert bridge.conditions(c, tenant, project) == {}
    assert bridge.binding_scope(row, None)["status"] == "released"
    assert bridge.binding_scope(row, None)["missing_node_ids"] == []


def test_original_supply_change_still_invalidates_a_retained_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, tenant, project, original, _, _ = setup(monkeypatch)
    original_observations = bridge.observations

    def changed(*args: Any) -> dict[UUID, dict[str, Any]]:
        values = original_observations(*args)
        for value in values.values():
            value["source_digest"] = "b" * 64
        return values

    monkeypatch.setattr(bridge, "observations", changed)
    assert bridge.conditions(c, tenant, project)[original][0]["status"] == "source_changed"
