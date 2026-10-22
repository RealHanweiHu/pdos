"""One actual fresh Start: SQL atom rejection, whole rollback and lost response."""

# ruff: noqa: F811 - imported fixtures register their transitive dependencies.

import json
import os
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from resource_dependency_faults.faults import (
    FAULT_CODE,
    fail_after_final_common_flush,
    snapshot,
)
from resource_dependency_faults.helpers import (
    _baseline,
    _unchanged,
    deferred_negatives_before_retry,
)
from sqlalchemy import insert, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_resource_dependency_execution import (  # noqa: F401
    actual_read_profile,
    engines,
    known_configuration,
    launch_work,
    operational_work,
    ready_work,
)
from test_retained_execution import _proof
from test_retained_registry_compatibility import add_unrelated_scope
from verification_launch import fixtures as launch_fixtures

from pdos_next.database import tenant_session
from pdos_next.domain.test_resources import service as resources
from pdos_next.domain.test_resources.models import TestResourceReservation as ResourceReservation
from pdos_next.service import digest


@pytest.mark.parametrize("launch_work", [{"window_minutes": 45, "fact_minutes": 60}], indirect=True)
def test_actual_v2_atom_rollback_and_lost_response_recovery(
    launch_work, monkeypatch, actual_read_profile
):
    work = launch_work
    assert len(work.setup.engine._pdos_test_resource_issuer_epochs) == 1
    add_unrelated_scope(work)
    with actual_read_profile.section("plan_promise"):
        launch_fixtures.promised(work)
    with actual_read_profile.section("future_window_wait"):
        launch_fixtures.advance_clock(work, monkeypatch)
    value = launch_fixtures.command(work, "test.run.start")
    with actual_read_profile.section("actual_start_preview"):
        preview = work.quality.client.post(
            f"/v1/categories/{work.setup.category}/commands/preview",
            json=value,
            headers=work.quality.headers,
        )
    assert preview.status_code == 200, preview.text
    prepared = preview.json()["command"]
    command, baseline = _baseline(work, prepared)
    with actual_read_profile.section("deferred_sql_negatives"):
        negatives = deferred_negatives_before_retry(work, prepared, monkeypatch)

    with (
        fail_after_final_common_flush(monkeypatch, command) as fault,
        actual_read_profile.section("api_precommit_fault"),
    ):
        failed = work.quality.client.post(
            f"/v1/categories/{work.setup.category}/commands",
            json=deepcopy(prepared),
            headers=work.quality.headers,
        )
    assert failed.status_code == 409, failed.text
    assert failed.json()["detail"]["reason"] == FAULT_CODE
    assert fault == {"attached": True, "armed": True, "fired": True, "flushed_common_rows": 4}
    _unchanged(work, baseline)

    actual_post = work.quality.client.post
    dropped = {}

    def lose_actual_committed_response(*args, **kwargs):
        response = actual_post(*args, **kwargs)
        assert response.status_code == 200, response.text
        dropped["receipt_id"] = response.json()["id"]
        raise httpx.ReadError(
            "Synthetic client response loss after actual commit", request=response.request
        )

    with (
        monkeypatch.context() as patch,
        actual_read_profile.section("actual_start_response_loss"),
    ):
        patch.setattr(work.quality.client, "post", lose_actual_committed_response)
        with pytest.raises(httpx.ReadError, match="after actual commit"):
            work.quality.client.post(
                f"/v1/categories/{work.setup.category}/commands",
                json=deepcopy(prepared),
                headers=work.quality.headers,
            )
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        committed = snapshot(session, work.setup.tenant)
        assert committed != baseline
        history = _proof(session, work)
        assert history["current"] is True, history["reason_codes"]
        saved = session.scalar(
            select(ResourceReservation).where(
                ResourceReservation.tenant_id == work.setup.tenant,
                ResourceReservation.run_id == command.payload["run_id"],
            )
        )
        proof = deepcopy(saved.dependency_proof)
        assert saved.fingerprint_version == resources._FINGERPRINT_V2
        assert resources._verify_stored_fingerprint_v2(proof) == proof
        assert len(proof["material"]) == 12
        assert len(proof["material"]["issuer_epochs"]) == 1
        assert proof["facts_revision"] == saved.facts_revision == history["facts_revision"]
        raw = {
            column.name: deepcopy(getattr(saved, column.name))
            for column in ResourceReservation.__table__.columns
            if column.name != "audience_dependencies"
        }
        assert snapshot(session, work.setup.tenant) == committed
    add_unrelated_scope(work)
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        reread = _proof(session, work)
        assert reread["current"] is True, reread["reason_codes"]
        for key in ("facts_revision", "reservation", "occupancy", "sample_usage"):
            assert reread[key] == history[key]
        assert snapshot(session, work.setup.tenant) == committed
    with actual_read_profile.section("original_request_recovery"):
        recovered = actual_post(
            f"/v1/categories/{work.setup.category}/commands",
            json=deepcopy(prepared),
            headers=work.quality.headers,
        )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["id"] == dropped["receipt_id"]
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        assert snapshot(session, work.setup.tenant) == committed

    malformed = {**raw, "id": uuid4(), "dependency_proof": {**proof, "material": {}}}
    with Session(work.setup.admin) as session, session.begin():
        with pytest.raises(DBAPIError) as error, session.begin_nested():
            session.execute(insert(ResourceReservation).values(**malformed))
        assert error.value.orig.diag.constraint_name == "test_resource_dependency_version_complete"
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        assert snapshot(session, work.setup.tenant) == committed

    report = os.environ.get("PDOS_ROOT_VERSIONED_ATOM_REPORT")
    if report:
        with Path(report).open("x") as stream:
            json.dump(
                {
                    "status": "PASS_ACTUAL_V2_SQL_ATOM_ROLLBACK_AND_COMMITTED_RESPONSE_LOSS",
                    "synthetic_only": True,
                    **negatives,
                    "whole_17_table_row_hashes_equal_after_each_failure": True,
                    "api_precommit_fault": fault,
                    "same_confirmation_and_request_lawful_retry": True,
                    "actual_commit_then_client_response_loss": True,
                    "original_receipt_recovered_without_additional_effects": True,
                    "full_material_keys": 12,
                    "saved_issuer_dependency_keys": 1,
                    "actual_registry_keys_at_start": 2,
                    "actual_registry_keys_after_start": 3,
                    "saved_full_proof_sha256": digest(proof),
                    "malformed_proof_actual_SQL_rejected": True,
                    "real_professional_qualification": False,
                },
                stream,
                indent=2,
            )
            stream.write("\n")
