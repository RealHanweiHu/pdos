"""Adopt a controlled Build resource calendar without reserving that resource."""

# ruff: noqa: F811 -- pytest fixture imports are explicitly collected here.

from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID

from build_operational_facts.fixtures import (  # noqa: F401 -- actual controlled fixtures
    configuration,
    definition,
    imported,
    known_configuration,
    operational_work,
    project,
)
from build_operational_facts.test_transactions import fact, successor
from sqlalchemy import select

from pdos_next.domain.build_operational_facts.models import BuildOperationalFact, ResourceOccupancy
from pdos_next.domain.external_wait.models import ExternalWaitVersion
from pdos_next.models import Artifact, now

from . import test_workflow as waits


def test_actual_resource_calendar_keeps_fixed_clock_and_blocks_after_resource_withdrawal(
    operational_work,
):
    operational = operational_work
    with waits.flow.scoped(SimpleNamespace(setup=operational.setup)) as session:
        source = session.get(Artifact, UUID(operational.config["source"]))
        assert source is not None and source.original_id is None
        first_line = source.content.splitlines()[0]
        source_id, source_revision = source.id, source.revision
    work = SimpleNamespace(
        setup=operational.setup,
        project_id=UUID(operational.config["project"]),
        source={
            "id": str(source_id),
            "revision": source_revision,
            "kind": "artifact",
            "position": "line:1;quote_sha256:" + sha256(first_line.encode()).hexdigest(),
        },
    )
    first = fact(operational, imported(operational))
    selected = next(
        item["ref"]
        for item in waits.workspace(work)["available_calendars"]
        if item["ref"]["kind"] == "build_resource"
        and item["ref"]["id"] == str(first.id)
        and item["ref"]["resource_id"] == str(operational.resource_id)
    )
    assert selected["calendar_version"] == "1"
    original, receipt = waits.execute(
        work,
        {
            **waits.create_record(),
            "calendar": selected,
            "build": {"id": operational.build_id, "revision": 1},
        },
    )
    waiting_id = receipt["result"]["wait_id"]
    row = waits.waiting(work, waiting_id)
    assert row["clock"]["status"] == "delivery_unknown"
    delivered_at = now() - timedelta(minutes=2)
    _, delivered = waits.execute(
        work,
        {
            "action": "delivery",
            "status": "effective",
            "at": delivered_at.isoformat(),
            "text": "Synthetic verified delivery using the explicitly adopted resource calendar",
            "original_timezone": "UTC",
        },
        wait=waits.reference(row),
    )
    row = waits.waiting(work, waiting_id)
    assert row["clock"]["status"] == "running" and row["clock"]["working_minutes"] >= 2
    with waits.flow.scoped(work) as session:
        saved = session.get(ExternalWaitVersion, UUID(delivered["subject_id"]))
        original_basis = saved.source_basis["calendar"]
        assert original_basis["ref"] == selected
        assert original_basis["source_calendar"] == first.data["resources"][0]["calendar"]
        assert original_basis["material"]["fact_sha256"] == first.fact_sha256
        assert all(
            value in saved.source_basis["artifacts"]
            for value in original_basis["material"]["source_basis"]["artifacts"]
        )

    def change_calendar(value):
        value["resources"][0]["resource"]["revision"] = 2
        value["resources"][0]["calendar"]["version"] = "2"
        value["requirements"][0]["uses"][0]["resource"]["revision"] = 2

    second = fact(
        operational, imported(operational, successor(operational, first, change_calendar))
    )
    available = waits.workspace(work)["available_calendars"]
    assert any(item["ref"]["id"] == str(second.id) for item in available)
    row = waits.waiting(work, waiting_id)
    assert row["calendar"] == selected and row["clock"]["status"] == "running"
    _, changed = waits.execute(work, waits.details_record(row), wait=waits.reference(row))
    with waits.flow.scoped(work) as session:
        saved = session.get(ExternalWaitVersion, UUID(changed["subject_id"]))
        assert saved.source_basis["calendar"]["ref"] == selected
        assert (
            saved.source_basis["calendar"]["source_calendar"] == original_basis["source_calendar"]
        )
        assert saved.source_basis["calendar"]["current"]["fact_id"] == str(second.id)
        assert not session.scalars(select(ResourceOccupancy)).all()

    def withdraw_resource(value):
        change_calendar(value)
        value["resources"][0]["resource"]["revision"] = 3
        value["requirements"][0]["uses"][0]["resource"]["revision"] = 3
        value["resources"][0]["lifecycle"] = "withdrawn"

    third = fact(
        operational, imported(operational, successor(operational, second, withdraw_resource))
    )
    assert third.revision == 3 and third.state == "active"
    row = waits.waiting(work, waiting_id)
    assert row["calendar"] == selected and row["clock"]["status"] == "calendar_unavailable"
    assert row["clock"]["working_minutes"] is None
    assert all(
        item["ref"]["kind"] != "build_resource"
        for item in waits.workspace(work)["available_calendars"]
    )
    before = waits.snapshots(work)
    rejected = waits.inputs(
        work, waits.details_record(row), wait=waits.reference(row), expected=409
    )
    assert rejected.json()["code"] in {"SOURCE_STALE", "SOURCE_UNAVAILABLE"}
    replay = waits.flow.send(work, original)
    assert replay.status_code == 200 and replay.json() == receipt
    assert waits.snapshots(work) == before
    with waits.flow.scoped(work) as session:
        assert (
            session.get(BuildOperationalFact, first.id).data["resources"][0]["calendar"]["version"]
            == "1"
        )
        assert not session.scalars(select(ResourceOccupancy)).all()
