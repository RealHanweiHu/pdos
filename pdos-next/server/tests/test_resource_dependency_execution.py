"""One real-clock versioned Start and recovery flow on Root's independent marked PG."""

# ruff: noqa: F811 - imported fixtures register their transitive dependencies.

import json
import os
import sys
import time
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import insert, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_project_first_plan import accepted
from test_retained_execution import _effects, _proof, _result_authority, _run_row
from test_retained_registry_compatibility import add_unrelated_scope
from verification_handoff import fixtures as handoff_fixtures
from verification_launch import fixtures as launch_fixtures
from verification_launch.fixtures import (  # noqa: F401
    known_configuration,
    operational_work,
    ready_work,
)

from pdos_next.database import engine_for, tenant_session
from pdos_next.domain.test_resources import retained
from pdos_next.domain.test_resources import service as resources
from pdos_next.domain.test_resources.models import TestResourceReservation as ResourceReservation
from pdos_next.domain.verification_front import service as front
from pdos_next.domain.verification_handoff import service as physical
from pdos_next.safety import verify_test_target
from pdos_next.service import digest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from current_read_profiler import CurrentReadProfiler, OwnerTarget


@pytest.fixture
def engines():
    values = [
        engine_for(os.environ[name])
        for name in ("TEST_DATABASE_URL", "DATABASE_URL", "AUTH_DATABASE_URL")
    ]
    for engine in values[:2]:
        verify_test_target(engine)
    auth = make_url(os.environ["AUTH_DATABASE_URL"])
    tested = make_url(os.environ["TEST_DATABASE_URL"])
    assert (auth.host, auth.port, auth.database) == (tested.host, tested.port, tested.database)
    assert auth.username == "pdos_next_auth"
    dispatch = engine_for(os.environ["DISPATCH_DATABASE_URL"])
    verify_test_target(dispatch)
    values[1]._pdos_dispatch_engine = dispatch
    yield tuple(values)
    for engine in (*values, dispatch):
        engine.dispose()


@pytest.fixture
def launch_work(ready_work, monkeypatch, request):
    ordinary_start = handoff_fixtures.start

    def start_with_results(work):
        work.retained_result_authority = _result_authority(work, suffix="before-versioned-start")
        return ordinary_start(work)

    monkeypatch.setattr(handoff_fixtures, "start", start_with_results)
    acceptance = launch_fixtures.accepted_work.__wrapped__(ready_work, monkeypatch)
    work = next(acceptance)
    # Freeze only preparation; actual Start uses real UTC and the real PG guard.
    preparation = launch_fixtures.launch_work.__wrapped__(
        work, request=request, monkeypatch=monkeypatch
    )
    try:
        yield next(preparation)
    finally:
        preparation.close()
        acceptance.close()


@pytest.fixture
def actual_read_profile(launch_work):
    targets = [
        OwnerTarget(physical, "_basis", "physical._basis"),
        OwnerTarget(physical, "_inspect", "physical._inspect"),
        OwnerTarget(front, "_recheck", "front._recheck"),
        OwnerTarget(resources, "_load", "resources._load"),
        OwnerTarget(retained, "inspect_retained_execution", "retained.inspect"),
    ]
    profile = CurrentReadProfiler(
        launch_work.setup.engine,
        targets,
        case_label="wave27_real_flow",
        include_worker_threads=True,
    )
    try:
        with profile:
            yield profile
    finally:
        path = os.environ.get("PDOS_ROOT_READ_PROFILE_REPORT")
        if path:
            with Path(path).open("x") as stream:
                json.dump(profile.report(), stream, indent=2)
                stream.write("\n")


@pytest.mark.parametrize("launch_work", [{"window_minutes": 45, "fact_minutes": 60}], indirect=True)
def test_full_saved_v2_actual_start_unrelated_scope_and_original_request_recovery(
    launch_work, monkeypatch, actual_read_profile
):
    work = launch_work
    assert len(work.setup.engine._pdos_test_resource_issuer_epochs) == 1
    add_unrelated_scope(work)
    started = time.monotonic()
    with actual_read_profile.section("plan_promise"):
        launch_fixtures.promised(work)
    with actual_read_profile.section("future_window_wait"):
        launch_fixtures.advance_clock(work, monkeypatch)
    with actual_read_profile.section("actual_start"):
        value = launch_fixtures.command(work, "test.run.start")
        receipt, confirmed = accepted(work.quality, value)
        work.start_command = value
    start_seconds = time.monotonic() - started
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as s:
        row = _run_row(s, work)
        saved = s.scalar(
            select(ResourceReservation).where(
                ResourceReservation.tenant_id == work.setup.tenant,
                ResourceReservation.run_id == row.run_id,
            )
        )
        proof = deepcopy(saved.dependency_proof)
        assert saved.fingerprint_version == resources._FINGERPRINT_V2
        assert row.input_snapshot["resource_fingerprint_version"] == saved.fingerprint_version
        assert row.input_snapshot["resource_dependency_proof"] == proof
        assert resources._verify_stored_fingerprint_v2(proof) == proof
        assert len(proof["material"]) == 12
        assert len(proof["material"]["issuer_epochs"]) == 1
        assert row.input_snapshot["resource_facts_revision"] == saved.facts_revision
        assert row.input_snapshot["reservation"]["facts_revision"] == saved.facts_revision
        assert proof["facts_revision"] == saved.facts_revision
        retained = _proof(s, work, row)
        assert retained["current"] is True, retained["reason_codes"]
        before = _effects(s, work)
        raw = {
            column.name: deepcopy(getattr(saved, column.name))
            for column in ResourceReservation.__table__.columns
            if column.name != "audience_dependencies"
        }
    add_unrelated_scope(work)
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as s:
        after = _proof(s, work)
        assert after["current"] is True, after["reason_codes"]
        assert after["facts_revision"] == retained["facts_revision"]
        assert after["reservation"] == retained["reservation"]
        assert after["occupancy"] == retained["occupancy"]
        assert after["sample_usage"] == retained["sample_usage"]
        assert _effects(s, work) == before
    recovered = work.quality.client.post(
        f"/v1/categories/{work.setup.category}/commands",
        json=confirmed,
        headers=work.quality.headers,
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["id"] == receipt["id"]
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as s:
        assert _effects(s, work) == before
    # Actual CHECK precedes duplicate owner/FK rules; the exact named failure
    # demonstrates a malformed proof cannot enter the actual business table.
    malformed = {**raw, "id": uuid4(), "dependency_proof": {**proof, "material": {}}}
    with Session(work.setup.admin) as s, s.begin():
        with pytest.raises(DBAPIError) as error, s.begin_nested():
            s.execute(insert(ResourceReservation).values(**malformed))
        assert error.value.orig.diag.constraint_name == "test_resource_dependency_version_complete"
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as s:
        assert _effects(s, work) == before
    path = os.environ.get("PDOS_ROOT_VERSIONED_FLOW_REPORT")
    if path:
        summary = {
            "status": "PASS_ACTUAL_V2_START_RETAINED_ORIGINAL_REQUEST_RECOVERY",
            "synthetic_only": True,
            "start_and_wait_seconds": round(start_seconds, 3),
            "full_material_keys": 12,
            "saved_issuer_dependency_keys": 1,
            "actual_registry_keys_at_start": 2,
            "actual_registry_keys_after_start": 3,
            "three_saved_fingerprints_identical": True,
            "common_original_receipt_recovered": True,
            "recovery_additional_effects": 0,
            "malformed_proof_actual_SQL_rejected": True,
            "saved_full_proof_sha256": digest(proof),
            "real_professional_qualification": False,
        }
        with Path(path).open("x") as stream:
            json.dump(summary, stream, indent=2)
            stream.write("\n")
